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

# === 全局配置 (High Precision) ===
DRAM_ENERGY_PER_BIT = 1.0   # pJ/bit
DRAM_BANK_WIDTH = 256       # bits
NOC_ENERGY_PER_BIT = 0.5    # pJ/bit (Python 侧手动补偿)
N_CALLS = 50                # 迭代次数
OUTPUT_FILE = "dse_results_nicepim.csv"
AREA_LIMIT_MM2 = 48.0       # Area Budget

logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

class TuRBOState:
    """信任域贝叶斯优化状态机"""
    def __init__(self, dim, length_min=0.5, length_max=2.0, length_init=1.0):
        self.dim = dim
        self.length = length_init
        self.length_min = length_min
        self.length_max = length_max
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
    """根据硬件规模动态生成 Mapper 约束"""
    if not os.path.exists(template_path):
        print(f"  [Warning] Mapper template {template_path} not found.")
        return False

    with open(template_path, 'r') as f:
        config = yaml.safe_load(f)

    if 'mapspace' not in config: 
        config['mapspace'] = {'template': 'uber', 'version': 0.4}
    if 'constraints' not in config: 
        config['constraints'] = {'version': 0.4, 'targets': []}
    elif 'targets' not in config['constraints']:
        config['constraints']['targets'] = []

    # === 策略注入 ===
    if mode == "atomic":
        # Atomic 策略：强制在 PIM_Node 维度进行空间切分
        spatial_constraint = {
            'target': 'PIM_Node',
            'type': 'spatial',
            'factors': f'M={num_nodes}', 
            'permutation': 'M' 
        }
        config['constraints']['targets'].append(spatial_constraint)
    
    with open(output_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)
    return True

def run_turbo_dse():
    full_space = [
        Integer(1, 16, name='num_nodes'),
        Integer(4, 32, name='pe_dim'),
        Integer(65536, 1048576, name='sram_size') 
    ]
    
    turbo = TuRBOState(dim=len(full_space))
    cwd = os.getcwd()
    hw_gen = ArchGenerator(template_path=os.path.join(cwd, "templates/arch.yaml.jinja2"),
                           output_dir=os.path.join(cwd, "output/generated_arch"))
    tl_wrapper = TimeloopWrapper()
    ram_wrapper = RamulatorWrapper()
    trace_gen = TraceGenerator(os.path.join(cwd, "output/dram.trace"))
    
    comp_dir = os.path.join(cwd, "configs/arch/components")
    if not os.path.exists(comp_dir):
        print(f"[Error] Component dir not found: {comp_dir}")
        return

    if not os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, 'w', newline='') as f:
            csv.writer(f).writerow(["Iter", "Mode", "Nodes", "PE_Dim", "SRAM", "EDP", "Latency", "Energy", "Area_mm2", "Runtime_s"])

    start_time_str = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"=== NicePIM Co-Design Engine (Clean Mode) Started at {start_time_str} ===")
    global_start = time.time()

    for i in range(N_CALLS):
        iter_start = time.time()

        # TuRBO 采样
        current_bounds = turbo.get_trust_region_bounds(full_space)
        opt = Optimizer(current_bounds, base_estimator="ET", acq_func="EI", 
                        n_initial_points=2 if i==0 else 1, random_state=42+i)
        try:
            next_point = opt.ask()
        except:
            next_point = [np.random.randint(d.low, d.high+1) for d in full_space]

        num_nodes, pe_dim, sram_sz = next_point
        mode = "baseline" if i % 2 == 0 else "atomic"
        
        print(f"\n--- Iter {i+1} [{mode.upper()}] Nodes={num_nodes}, PE={pe_dim}x{pe_dim}, SRAM={sram_sz//1024}KB ---")

        stats_dir = os.path.join(cwd, f"output/step_{i}")
        if not os.path.exists(stats_dir): os.makedirs(stats_dir)

        # 1. 硬件生成
        sram_depth = sram_sz // 8 
        arch_file = hw_gen.generate_config({
            'NUM_NODES': num_nodes,
            'PE_DIM_X': pe_dim,
            'PE_DIM_Y': pe_dim,
            'SRAM_DEPTH': sram_depth,
            'SRAM_WIDTH': 64
        }, filename=f"arch_{i}.yaml")
        
        # 2. 映射器生成
        base_mapper_path = os.path.join(cwd, f"configs/mapper/mapper_{mode}.yaml")
        if not os.path.exists(base_mapper_path):
            base_mapper_path = os.path.join(cwd, "configs/mapper/mapper.yaml")
        iter_mapper_path = os.path.join(stats_dir, "mapper_generated.yaml")
        generate_dynamic_mapper(base_mapper_path, iter_mapper_path, num_nodes, mode)

        # 3. 运行 Timeloop
        t0 = time.time()
        is_success = tl_wrapper.run_mapper(
            arch_path=arch_file,
            prob_path=os.path.join(cwd, "configs/prob/cnn_layer.yaml"),
            mapper_path=iter_mapper_path,
            output_dir=stats_dir,
            component_dir=comp_dir 
        )
        t_timeloop = time.time() - t0
        
        edp = 1e16
        latency = 0
        energy = 0
        area_mm2 = 0.0
        
        if is_success:
            # 4. 解析结果
            stats_file = os.path.join(stats_dir, "timeloop-mapper.stats.txt")
            parser = TimeloopParser(stats_file)
            results = parser.parse()
            
            logic_cycle = results.get('cycles', 0)
            logic_energy = results.get('energy_pj', 0)
            area_mm2 = results.get('area_mm2', 0.0)
            
            # [诊断]
            dram_r = results.get('dram_reads', 0)
            sram_r = results.get('sram_reads', 0)
            print(f"  >> [Stats] Area={area_mm2:.2f}mm2, Cycle={logic_cycle}")
            print(f"  >> [Diag] DRAM Reads: {dram_r:,} | SRAM Reads: {sram_r:,}")

            if area_mm2 > AREA_LIMIT_MM2:
                print(f"  [Constraint] Area > {AREA_LIMIT_MM2}. Penalty.")
                edp = 1e17
            elif logic_cycle > 0:
                # 6. 生成 Trace
                trace_path, num_reqs = trace_gen.generate_structured_trace(
                    results, 
                    mode=mode, 
                    output_path=f"output/dram_{i}.trace",
                    stats_path=stats_file
                )
                
                # 7. 运行 Ramulator
                t1 = time.time()
                ram_cycle = 0
                if num_reqs > 0:
                    ram_cycle = ram_wrapper.run_simulation(
                        config_rel_path="configs/ramulator/sedram.cfg",
                        trace_rel_path=f"output/dram_{i}.trace",
                        output_rel_dir=stats_dir
                    )
                t_ramulator = time.time() - t1

                # 8. 汇总
                if mode == "atomic":
                    total_cycle = max(logic_cycle, ram_cycle) * 1.10
                else:
                    total_cycle = logic_cycle + (ram_cycle * 0.85)
                
                dram_energy = num_reqs * DRAM_BANK_WIDTH * DRAM_ENERGY_PER_BIT
                noc_energy = num_reqs * DRAM_BANK_WIDTH * NOC_ENERGY_PER_BIT
                total_energy = logic_energy + dram_energy + noc_energy
                
                edp = total_cycle * total_energy
                latency = total_cycle
                energy = total_energy
                
                print(f"  >> [Success] EDP={edp:.2e} (Lat: {latency:.0f}, En: {energy:.2e})")
        
        if mode == "atomic":
            turbo.update(edp, next_point)
        
        iter_end = time.time()
        print(f"  >> [Timer] Total Iteration: {iter_end - iter_start:.2f}s")
        
        with open(OUTPUT_FILE, 'a', newline='') as f:
            csv.writer(f).writerow([i+1, mode, num_nodes, pe_dim, sram_sz, edp, latency, energy, area_mm2, f"{iter_end - iter_start:.2f}"])

    print(f"\nBest Config found: {turbo.best_x} with EDP: {turbo.best_value:.2e}")

if __name__ == "__main__":
    run_turbo_dse()
