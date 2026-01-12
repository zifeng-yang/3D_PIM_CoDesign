import os
import csv
import numpy as np
import logging
import math
import yaml
import shutil
import time
import datetime
from skopt import Optimizer
from skopt.space import Integer

# 导入自定义模块
from modules.arch_gen import ArchGenerator
from modules.wrapper_timeloop import TimeloopWrapper
from modules.wrapper_ramulator import RamulatorWrapper
from modules.trace_gen import TraceGenerator
from modules.result_parser import TimeloopParser

# === 全局配置 ===
DRAM_BANK_WIDTH = 256       # bits
N_CALLS = 50                # 迭代次数
OUTPUT_FILE = "dse_results_nicepim.csv"
AREA_LIMIT_MM2 = 48.0       # Area Budget (mm^2)

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

def generate_booksim_config(output_path, num_nodes):
    """
    根据节点数量动态生成 BookSim 配置文件 (Mesh拓扑)
    """
    # 动态计算拓扑维度 k (例如 4个节点 -> 2x2 Mesh)
    k = int(math.ceil(math.sqrt(num_nodes)))
    if k < 2: k = 2
    
    # 使用 f-string 生成配置内容
    # 注意：配置中的注释使用 // (BookSim语法)
    config_content = f"""
// Auto-generated BookSim Config for {num_nodes} nodes
topology = mesh;
k = {k};
n = 2;
routing_function = dim_order;

// 流量模型 (会被 Wrapper 根据真实 Trace 覆盖注入率)
traffic = uniform;
packet_size = 1;
injection_rate = 0.01; 

// 仿真控制 (会被 Wrapper 根据真实 Ramulator 周期覆盖 sim_count)
sim_type = latency;
warmup_periods = 0;
sim_count = 1000; 

// [关键修复] 关闭读写分离模式，避免 VC 分配导致的 Assertion Failed
use_read_write = 0;

// VC 配置
num_vcs = 4;
vc_buf_size = 4;
wait_for_tail_credit = 1;
"""
    
    # 写入文件
    with open(output_path, 'w') as f:
        f.write(config_content)
    
    return output_path

# DRAM 静态能耗估算
def calc_dram_background_energy(simulation_time_ns):
    p_static_mw = 11.0 
    e_static = p_static_mw * simulation_time_ns 
    return e_static

# 贝叶斯优化状态管理 (TuRBO 算法简化版)
class TuRBOState:
    def __init__(self, dim, length_min=0.5, length_max=2.0, length_init=1.0):
        self.dim = dim
        self.length = length_init
        self.length_min = length_min
        self.length_max = length_max
        self.length_init = length_init 
        self.failure_counter = 0
        self.success_counter = 0
        self.best_value = float('inf')
        self.best_x = None
        self.succ_tol = 3
        self.fail_tol = 5

    def update(self, y, x):
        if y < self.best_value:
            self.best_value = y
            self.best_x = x
            self.success_counter += 1
            self.failure_counter = 0
        else:
            self.success_counter = 0
            self.failure_counter += 1

        if self.success_counter >= self.succ_tol:
            self.length = min(self.length * 2.0, self.length_max)
            self.success_counter = 0
        elif self.failure_counter >= self.fail_tol:
            self.length /= 2.0
            self.failure_counter = 0
        
        if self.length < self.length_min:
            self.length = self.length_init

    def get_trust_region_bounds(self, space):
        if self.best_x is None: return space
        bounds = []
        for i, dim in enumerate(space):
            low, high = dim.low, dim.high
            tr_radius = self.length * (high - low) / 2.0
            center = self.best_x[i]
            x_min = max(low, int(center - tr_radius))
            x_max = min(high, int(center + tr_radius))
            if x_max < x_min: x_max = x_min
            bounds.append(Integer(x_min, x_max, name=dim.name))
        return bounds

def generate_dynamic_mapper(template_path, output_path, num_nodes, mode):
    if not os.path.exists(template_path): return False
    with open(template_path, 'r') as f: config = yaml.safe_load(f)

    if 'mapspace' not in config: config['mapspace'] = {'template': 'uber', 'version': 0.4}
    if 'constraints' not in config: config['constraints'] = {'version': 0.4, 'targets': []}
    elif 'targets' not in config['constraints']: config['constraints']['targets'] = []

    if mode == "atomic":
        spatial_constraint = {
            'target': 'PIM_Node',
            'type': 'spatial',
            'factors': f'M={num_nodes}', 
            'permutation': 'M' 
        }
        config['constraints']['targets'].append(spatial_constraint)
    
    with open(output_path, 'w') as f: yaml.dump(config, f, default_flow_style=False)
    return True

def run_turbo_dse():
    # 搜索空间定义
    full_space = [
        Integer(1, 16, name='num_nodes'),          # PIM 节点数量
        Integer(4, 32, name='pe_dim'),             # PE 阵列维度
        Integer(1048576, 33554432, name='sram_size') # SRAM 大小 (Bytes)
    ]
    
    turbo = TuRBOState(dim=len(full_space))
    cwd = os.getcwd()
    
    # 初始化各模块
    hw_gen = ArchGenerator(template_path=os.path.join(cwd, "templates/arch.yaml.jinja2"),
                           output_dir=os.path.join(cwd, "output/generated_arch"))
    tl_wrapper = TimeloopWrapper()
    
    # 初始化 RamulatorWrapper (注意：现在它负责调用本地二进制文件)
    ram_wrapper = RamulatorWrapper()
    
    trace_gen = TraceGenerator(os.path.join(cwd, "output/dram.trace"))
    
    comp_dir = os.path.join(cwd, "configs/arch/components")
    if not os.path.exists(comp_dir):
        print(f"[Error] Component dir not found: {comp_dir}")
        return

    # 初始化结果文件
    if not os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, 'w', newline='') as f:
            csv.writer(f).writerow(["Iter", "Mode", "Nodes", "PE_Dim", "SRAM", "EDP", "Latency", "Energy", "Area_mm2", "Runtime_s"])

    start_time_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"=== NicePIM Co-Design Engine (BookSim Integrated) Started at {start_time_str} ===")
    global_start = time.time()

    for i in range(N_CALLS):
        iter_start = time.time()
        
        # 1. 采样 (TuRBO)
        current_bounds = turbo.get_trust_region_bounds(full_space)
        opt = Optimizer(current_bounds, base_estimator="ET", acq_func="EI", 
                        n_initial_points=2 if i==0 else 1, random_state=42+i)
        try:
            next_point = opt.ask()
        except:
            next_point = [np.random.randint(d.low, d.high+1) for d in full_space]

        num_nodes, pe_dim, sram_sz = next_point
        # 交替运行 Baseline 和 Atomic 模式
        mode = "baseline" if i % 2 == 0 else "atomic"
        
        print(f"\n--- Iter {i+1} [{mode.upper()}] Nodes={num_nodes}, PE={pe_dim}x{pe_dim}, SRAM={sram_sz//1024}KB ---")

        stats_dir = os.path.join(cwd, f"output/step_{i}")
        if not os.path.exists(stats_dir): os.makedirs(stats_dir)

        # 2. 生成硬件配置
        sram_depth = sram_sz // 8 
        arch_file = hw_gen.generate_config({
            'NUM_NODES': num_nodes,
            'PE_DIM_X': pe_dim,
            'PE_DIM_Y': pe_dim,
            'SRAM_DEPTH': sram_depth,
            'SRAM_WIDTH': 64
        }, filename=f"arch_{i}.yaml")
        
        # 3. 生成映射约束
        base_mapper_path = os.path.join(cwd, f"configs/mapper/mapper_{mode}.yaml")
        if not os.path.exists(base_mapper_path):
            base_mapper_path = os.path.join(cwd, "configs/mapper/mapper.yaml")
        iter_mapper_path = os.path.join(stats_dir, "mapper_generated.yaml")
        generate_dynamic_mapper(base_mapper_path, iter_mapper_path, num_nodes, mode)

        # 4. 运行 Timeloop (Docker)
        t0 = time.time()
        is_success = tl_wrapper.run_mapper(
            arch_path=arch_file,
            prob_path=os.path.join(cwd, "configs/prob/cnn_layer.yaml"),
            mapper_path=iter_mapper_path,
            output_dir=stats_dir,
            component_dir=comp_dir 
        )
        t_timeloop = time.time() - t0
        
        # 初始化结果
        edp = 1e16
        latency = 0
        energy = 0
        area_mm2 = 0.0
        
        if is_success:
            # 5. 解析 Timeloop 结果
            stats_file = os.path.join(stats_dir, "timeloop-mapper.stats.txt")
            parser = TimeloopParser(stats_file)
            results = parser.parse()
            
            logic_cycle = results.get('cycles', 0)
            logic_energy = results.get('energy_pj', 0)
            area_mm2 = results.get('area_mm2', 0.0)
            dram_r = results.get('dram_reads', 0)
            sram_r = results.get('sram_reads', 0)

            print(f"  >> [Logic] Cycles: {logic_cycle:,} | Energy: {logic_energy:.2e} pJ | Area: {area_mm2:.2f} mm2")
            reuse_ratio = sram_r / dram_r if dram_r > 0 else 0
            print(f"  >> [Mem]   DRAM Acc: {dram_r:,} | SRAM Acc: {sram_r:,} | Reuse: {reuse_ratio:.1f}x")

            # 面积约束检查
            if area_mm2 > AREA_LIMIT_MM2:
                print(f"  [Constraint] Area {area_mm2:.2f} > {AREA_LIMIT_MM2}. Penalty applied.")
                edp = 1e17
            elif logic_cycle > 0:
                # 6. 生成访存 Trace
                trace_path, num_reqs = trace_gen.generate_structured_trace(
                    results, 
                    mode=mode, 
                    output_path=f"output/dram_{i}.trace",
                    stats_path=stats_file
                )
                
                # 7. 联合仿真 (Ramulator + BookSim)
                t1 = time.time()
                
                # 生成 BookSim 初始配置
                noc_cfg_path = os.path.join(stats_dir, "noc_config.cfg")
                generate_booksim_config(noc_cfg_path, num_nodes)

                # 调用 Wrapper (本地执行)
                # Wrapper 会先跑 Ramulator 得到真实周期，再用该周期驱动 BookSim
                sim_results = ram_wrapper.run_simulation(
                    config_rel_path="configs/ramulator/LPDDR4-config.cfg",
                    trace_rel_path=f"output/dram_{i}.trace",
                    output_rel_dir=stats_dir,
                    network_config_path=noc_cfg_path,
                    num_nodes=num_nodes 
                )
                t_ramulator = time.time() - t1
                
                ram_cycle = sim_results['ram_cycles']
                noc_energy = sim_results['noc_energy']
                noc_avg_lat = sim_results['avg_network_latency']

                # 8. 性能与能耗汇总 (数据驱动)
                if mode == "atomic":
                    # PIM 模式: 计算与访存/网络高度重叠
                    # 总延迟 = max(逻辑计算, 访存 + 网络开销)
                    # 粗略估算网络总开销 = 平均单包延迟 * 总包数 / 并行度
                    noc_total_latency_penalty = int(noc_avg_lat * num_reqs / num_nodes)
                    total_cycle = max(logic_cycle, ram_cycle + noc_total_latency_penalty)
                else:
                    # Baseline 模式: 串行阻塞
                    noc_total_latency_penalty = int(noc_avg_lat * num_reqs / num_nodes)
                    total_cycle = logic_cycle + ram_cycle + noc_total_latency_penalty
                
                # 计算 DRAM 动态和静态能耗
                dram_dynamic = num_reqs * DRAM_BANK_WIDTH * 1.2
                dram_static = calc_dram_background_energy(total_cycle * 1.0) 
                
                # 总能耗 = 逻辑 + DRAM(动+静) + NoC(BookSim真实值)
                total_energy = logic_energy + dram_dynamic + dram_static + noc_energy
                
                edp = total_cycle * total_energy
                latency = total_cycle
                energy = total_energy
                
                print(f"  >> [NoC]   Energy: {noc_energy:.2e} pJ | Avg Lat: {noc_avg_lat:.1f} cycles")
                print(f"  >> [Total] EDP: {edp:.2e} | Lat: {latency:.2e} | En: {energy:.2e}")
        
        # 9. 更新优化器
        if mode == "atomic":
            turbo.update(edp, next_point)
        
        iter_end = time.time()
        print(f"  >> [Timer] Iteration finished in {iter_end - iter_start:.2f}s")
        
        # 10. 记录结果
        with open(OUTPUT_FILE, 'a', newline='') as f:
            csv.writer(f).writerow([i+1, mode, num_nodes, pe_dim, sram_sz, edp, latency, energy, area_mm2, f"{iter_end - iter_start:.2f}"])

    print(f"\nBest Config found: {turbo.best_x} with EDP: {turbo.best_value:.2e}")

if __name__ == "__main__":
    run_turbo_dse()
