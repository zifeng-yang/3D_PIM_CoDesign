# 文件路径: main_optimization.py

import os
import csv
import numpy as np
import logging
import math
from skopt import Optimizer
from skopt.space import Integer

# 导入自定义模块
from modules.arch_gen import ArchGenerator
from modules.wrapper_timeloop import TimeloopWrapper
from modules.wrapper_ramulator import RamulatorWrapper
from modules.trace_gen import TraceGenerator

# === 常量定义 ===
DRAM_ENERGY_PER_BIT = 0.88  # pJ/bit
DRAM_BANK_WIDTH = 128       # bits
N_CALLS = 50                # 增加迭代次数以体现收敛性
OUTPUT_FILE = "dse_results_turbo.csv"

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

class TuRBOState:
    """简化的信任域状态机 (Trust Region State Machine)"""
    def __init__(self, dim, length_min=0.5, length_max=2.0, length_init=1.0):
        self.dim = dim
        self.length = length_init
        self.length_min = length_min
        self.length_max = length_max
        self.failure_counter = 0
        self.success_counter = 0
        self.best_value = float('inf')
        self.best_x = None
        # TuRBO 超参数
        self.succ_tol = 3  # 连续成功3次扩大
        self.fail_tol = 5  # 连续失败5次缩小

    def update(self, y, x):
        if y < self.best_value:
            self.best_value = y
            self.best_x = x
            self.success_counter += 1
            self.failure_counter = 0
        else:
            self.success_counter = 0
            self.failure_counter += 1

        # 动态调整信任域半径 (Length)
        if self.success_counter >= self.succ_tol:
            self.length = min(self.length * 2.0, self.length_max)
            self.success_counter = 0
        elif self.failure_counter >= self.fail_tol:
            self.length /= 2.0
            self.failure_counter = 0
        
        # 重启机制：如果半径过小，通常需要重启 (这里简化为重置半径)
        if self.length < self.length_min:
            self.length = self.length_init

    def get_trust_region_bounds(self, space):
        """计算当前信任域的上下界"""
        if self.best_x is None:
            return space # 尚未找到最优解，搜索全域

        bounds = []
        for i, dim in enumerate(space):
            low, high = dim.low, dim.high
            range_ = high - low
            
            # 信任域半径 (归一化后)
            tr_radius = self.length * range_ / 2.0
            
            center = self.best_x[i]
            x_min = max(low, int(center - tr_radius))
            x_max = min(high, int(center + tr_radius))
            
            # 确保 Integer 空间有效
            if x_max < x_min: x_max = x_min
            
            bounds.append(Integer(x_min, x_max, name=dim.name))
        return bounds

def run_turbo_dse():
    # 1. 定义完整设计空间 (Table IV)
    full_space = [
        Integer(2, 16, name='pe_x'),        # Dimension X
        Integer(2, 16, name='pe_y'),        # Dimension Y
        Integer(8192, 131072, name='sram_size') # Buffer Size (Bytes)
    ]
    
    # 初始化 TuRBO 状态
    turbo = TuRBOState(dim=len(full_space))
    
    # 2. 初始化工具链
    cwd = os.getcwd()
    hw_gen = ArchGenerator(template_path=os.path.join(cwd, "templates/arch.yaml.jinja2"),
                           output_dir=os.path.join(cwd, "output/generated_arch"))
    tl_wrapper = TimeloopWrapper()
    ram_wrapper = RamulatorWrapper()
    trace_gen = TraceGenerator(os.path.join(cwd, "output/dram.trace"))

    # CSV Header
    if not os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, 'w', newline='') as f:
            csv.writer(f).writerow(["Iter", "Mode", "PE_X", "PE_Y", "SRAM", "EDP", "TR_Length", "Latency", "Energy"])

    print("=== Co-Design Started: TuRBO + Atomic Scheduling ===")

    # 使用两个优化器实例：全局(热启动用) + 局部(信任域用)
    # 这里为了代码简洁，我们每一轮动态创建受限的优化器
    
    for i in range(N_CALLS):
        # --- Step A: 确定当前的搜索空间 (Trust Region) ---
        current_bounds = turbo.get_trust_region_bounds(full_space)
        
        # 临时优化器，用于在信任域内采样
        # 注意：这里简化了逻辑，每次重新初始化以利用 bounds，
        # 实际 TuRBO 会维护一个包含所有历史数据的全局模型
        opt = Optimizer(current_bounds, base_estimator="ET", acq_func="EI", 
                        n_initial_points=2 if i==0 else 1, random_state=42+i)
        
        try:
            next_point = opt.ask()
        except:
            # 如果信任域太小导致采样失败，回退到全局采样
            next_point = [np.random.randint(d.low, d.high+1) for d in full_space]

        pe_x, pe_y, sram_sz = next_point
        
        # --- Step B: 切换调度模式 (Baseline vs Atomic) ---
        # 为了对比，我们在偶数轮跑 Baseline，奇数轮跑 Proposed
        # 实际论文数据建议分别跑两组完整的 DSE，这里为了演示合并在一起
        mode = "baseline" if i % 2 == 0 else "atomic"
        mapper_file = "mapper_baseline.yaml" if mode == "baseline" else "mapper_atomic.yaml"
        
        print(f"\n--- Iter {i+1} [{mode.upper()}] TR_Len={turbo.length:.2f} ---")
        print(f"Config: {pe_x}x{pe_y}, {sram_sz//1024}KB")

        # --- Step C: 仿真流程 ---
        # 1. 生成硬件
        arch_file = hw_gen.generate_config({'pe_dim_x': pe_x, 'pe_dim_y': pe_y, 'sram_size': sram_sz}, 
                                           filename=f"arch_{i}.yaml")
        
        # 2. Timeloop 映射 (计算延迟与能耗)
        stats_dir = os.path.join(cwd, f"output/step_{i}")
        tl_stats = tl_wrapper.run_mapper(
            arch_path=arch_file,
            prob_path=os.path.join(cwd, "configs/prob/cnn_layer.yaml"),
            mapper_path=os.path.join(cwd, f"configs/mapper/{mapper_file}"), # 动态切换 Mapper
            output_dir=stats_dir
        )
        
        # 3. 结果处理
        edp = 1e15 # 默认惩罚值
        latency = 0
        energy = 0
        
        if tl_stats:
            logic_cycle = tl_stats['cycles']
            logic_energy = tl_stats['energy_pj']
            
            # 4. 生成 Trace (基于模式)
            # 关键：atomic 模式下生成的 Trace 局部性更好
            trace_path, num_reqs = trace_gen.generate_structured_trace(
                tl_stats, mode=mode, output_path=f"output/dram_{i}.trace")
            
            # 5. Ramulator 仿真
            ram_cycle = ram_wrapper.run_simulation(
                config_rel_path="configs/ramulator/sedram.cfg",
                trace_rel_path=f"output/dram_{i}.trace.0",
                output_rel_dir=stats_dir
            )
            
            if ram_cycle:
                # 6. 计算系统指标
                total_cycle = max(logic_cycle, ram_cycle)
                dram_energy = num_reqs * DRAM_BANK_WIDTH * DRAM_ENERGY_PER_BIT
                total_energy = logic_energy + dram_energy
                edp = total_cycle * total_energy
                
                latency = total_cycle
                energy = total_energy
                print(f"  >> Success: EDP={edp:.2e} (L={logic_cycle}, M={ram_cycle})")
            else:
                print("  >> Ramulator Failed")
        else:
            print("  >> Timeloop Mapping Failed")

        # --- Step D: 更新 TuRBO 状态 ---
        # 只有 Proposed 模式的数据用于更新硬件优化器 (协同进化的逻辑)
        if mode == "atomic":
            turbo.update(edp, next_point)
        
        # 记录数据
        with open(OUTPUT_FILE, 'a', newline='') as f:
            csv.writer(f).writerow([i+1, mode, pe_x, pe_y, sram_sz, edp, turbo.length, latency, energy])

    print(f"\nBest Config (Atomic): {turbo.best_x}, EDP: {turbo.best_value:.2e}")

if __name__ == "__main__":
    run_turbo_dse()
