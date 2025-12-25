import os
import csv
import numpy as np
import logging

# 使用 skopt 进行贝叶斯优化
from skopt import Optimizer
from skopt.space import Integer

# [Critical] 确保导入路径与你的 ls 结构一致
from modules.arch_gen import ArchGenerator
from modules.wrapper_timeloop import TimeloopWrapper
from modules.wrapper_ramulator import RamulatorWrapper
from modules.trace_gen import TraceGenerator

# === NicePIM 论文核心常数  ===
# Section VIII.B: "energy cost of DRAM access is 0.88 pJ/bit"
DRAM_ENERGY_PER_BIT = 0.88 
# Section VIII.B: "data width of input... is 16-bit" -> 128-bit bank width
DRAM_BANK_WIDTH = 128       

# === 全局配置 ===
N_CALLS = 15                
N_RANDOM_STARTS = 5         
OUTPUT_FILE = "dse_results_nicepim.csv" # 改名以区分旧数据

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

def run_nicepim_dse():
    # 1. 定义设计空间 (Table IV in Paper) [cite: 566]
    # PE Array: 1~256 total PEs. We optimize Dimensions X * Y.
    # SRAM: 1KB ~ 2048KB.
    space = [
        Integer(4, 16, name='pe_x'),      # Constraints: 4x4 to 16x16
        Integer(4, 16, name='pe_y'),
        Integer(8192, 131072, name='sram_size') # 8KB - 128KB (Bytes)
    ]
    
    # 初始化优化器 (使用 Extra Trees 回归器，适合离散硬件空间)
    opt = Optimizer(space, base_estimator="ET", acq_func="EI", 
                    n_initial_points=N_RANDOM_STARTS, random_state=42)
    
    # 2. 初始化工具链
    cwd = os.getcwd()
    
    # [Updated] 指向新建的 templates 目录
    hw_gen = ArchGenerator(
        template_path=os.path.join(cwd, "templates/arch.yaml.jinja2"),
        output_dir=os.path.join(cwd, "output/generated_arch")
    )
    
    tl_wrapper = TimeloopWrapper(docker_image_name="timeloopaccelergy/timeloop-accelergy-pytorch:latest-amd64")
    ram_wrapper = RamulatorWrapper(docker_image="ramulator-pim-test:latest")
    trace_gen = TraceGenerator(os.path.join(cwd, "output/dram.trace"))

    # CSV Header
    if not os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["Iteration", "PE_X", "PE_Y", "SRAM", "EDP", "Total_Energy", "Logic_Energy", "DRAM_Energy", "Cycles"])

    print("=== NicePIM Design Space Exploration Started ===")
    print(f"Constraints: 28nm, 400MHz, 0.88pJ/bit DRAM")

    for i in range(N_CALLS):
        # A. 获取参数
        next_point = opt.ask()
        pe_x, pe_y, sram_sz = next_point
        
        print(f"\n--- Iteration {i+1}/{N_CALLS} ---")
        print(f"Trying: PE={pe_x}x{pe_y}, SRAM={sram_sz} Bytes")

        # B. 生成硬件 (注入论文默认参数)
        design_params = {'pe_dim_x': pe_x, 'pe_dim_y': pe_y, 'sram_size': sram_sz}
        arch_file = hw_gen.generate_config(design_params, filename=f"opt_arch_{i+1}.yaml")
        
        # C. 运行 Timeloop (Logic Die Simulation)
        stats_dir = os.path.join(cwd, f"output/step_{i+1}")
        tl_stats = tl_wrapper.run_mapper(
            arch_path=arch_file,
            prob_path=os.path.join(cwd, "configs/prob/cnn_layer.yaml"),
            mapper_path=os.path.join(cwd, "configs/mapper/mapper.yaml"),
            output_dir=stats_dir
        )
        
        edp = 1e25 # Penalty
        logic_E = 0
        dram_E = 0
        sys_cycles = 0

        if tl_stats:
            tl_cycles = tl_stats['cycles']
            logic_E = tl_stats['energy_pj'] # Accelergy: SRAM + MAC Energy
            
            # D. 运行 Ramulator (3D Memory Simulation)
            # 1. 生成 NicePIM 风格的 Trace (Tile-based Access)
            # 采样率 5% 以平衡速度
            scale = 0.05
            trace_path, num_reqs = trace_gen.generate_from_stats(tl_stats, scaling_factor=scale)
            
            # 2. 仿真
            ram_cycles_sampled = ram_wrapper.run_simulation(
                config_rel_path="configs/ramulator/sedram.cfg",
                trace_rel_path=f"output/dram.trace.0",
                output_rel_dir=f"output/step_{i+1}"
            )
            
            if ram_cycles_sampled:
                # 3. 还原真实周期
                ram_cycles_total = int(ram_cycles_sampled * (1.0 / scale))
                
                # 4. [Core Logic] 计算真实 DRAM 能耗 (0.88 pJ/bit)
                # Total Bits = Lines * 128-bit * (1/scale)
                total_bits = num_reqs * DRAM_BANK_WIDTH * (1.0 / scale)
                dram_E = total_bits * DRAM_ENERGY_PER_BIT
                
                # 5. 系统性能汇总
                # Latency = max(Compute, Memory) (假设 PIM 流水线掩盖)
                sys_cycles = max(tl_cycles, ram_cycles_total)
                total_E = logic_E + dram_E
                edp = total_E * sys_cycles
                
                print(f"  >> [Result] Logic E: {logic_E:.2e} pJ, DRAM E: {dram_E:.2e} pJ")
                print(f"  >> [Result] Latency: {sys_cycles} (Compute: {tl_cycles}, Mem: {ram_cycles_total})")
                print(f"  >> [Result] EDP: {edp:.2e}")
            else:
                print("  >> [Fail] Ramulator simulation failed.")
        else:
            print("  >> [Fail] Timeloop mapping failed.")

        # E. 记录与反馈
        opt.tell(next_point, edp)
        
        with open(OUTPUT_FILE, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([i+1, pe_x, pe_y, sram_sz, edp, logic_E + dram_E, logic_E, dram_E, sys_cycles])

    # 结束
    best_idx = np.argmin(opt.yi)
    print(f"\n=== Best Config Found: EDP = {opt.yi[best_idx]:.2e} ===")
    print(f"Config: {opt.Xi[best_idx]}")

if __name__ == "__main__":
    run_nicepim_dse()
