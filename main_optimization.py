import os
import csv
import numpy as np
import logging
import math
import yaml
import shutil
from skopt import Optimizer
from skopt.space import Integer

# 导入自定义模块
from modules.arch_gen import ArchGenerator
from modules.wrapper_timeloop import TimeloopWrapper
from modules.wrapper_ramulator import RamulatorWrapper
from modules.trace_gen import TraceGenerator
from modules.result_parser import TimeloopParser

# === 全局配置 ===
DRAM_ENERGY_PER_BIT = 0.88  # pJ/bit (LPDDR4)
DRAM_BANK_WIDTH = 256       # bits (Wide IO for PIM)
N_CALLS = 50                # 迭代次数
OUTPUT_FILE = "dse_results_nicepim.csv"
AREA_LIMIT_MM2 = 48.0       # NicePIM Area Budget

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
    """
    根据硬件规模(Nodes)动态生成 Mapper 约束。
    论文实现关键：Software-Hardware Co-Design
    """
    if not os.path.exists(template_path):
        print(f"  [Warning] Mapper template {template_path} not found. Using defaults.")
        return False

    with open(template_path, 'r') as f:
        config = yaml.safe_load(f)

    # === [FIX] 关键修复：约束必须在顶级 constraints 键下 ===
    # 确保 mapspace 存在 (用于 template: uber)
    if 'mapspace' not in config: 
        config['mapspace'] = {'template': 'uber', 'version': 0.4}
    
    # 确保顶层 constraints 结构存在
    if 'constraints' not in config: 
        config['constraints'] = {'version': 0.4, 'targets': []}
    elif 'targets' not in config['constraints']:
        config['constraints']['targets'] = []

    # === 策略注入 ===
    if mode == "atomic":
        # 策略：将任务在 PIM_Node 层面进行空间切分 (Spatial Tiling)
        # 强制 Output (M维度) 或 Input (C维度) 分布在不同节点上
        spatial_constraint = {
            'target': 'PIM_Node',
            'type': 'spatial',
            'factors': f'M={num_nodes}', # 假设沿输出通道切分
            'permutation': 'M' 
        }
        # 将约束添加到顶层 targets 列表
        config['constraints']['targets'].append(spatial_constraint)
    
    # 写入新的 Mapper 文件
    with open(output_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False)
    
    return True

def run_turbo_dse():
    # 1. 定义 NicePIM 风格搜索空间
    # - Nodes: 1~16 (Vault级并行)
    # - PE: 4~32 (节点内阵列维度)
    # - SRAM: 64KB~1MB (节点内缓存)
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
    
    # 检查组件库
    comp_dir = os.path.join(cwd, "configs/arch/components")
    if not os.path.exists(comp_dir):
        print(f"[Error] Component dir not found: {comp_dir}")
        return

    # CSV Header
    if not os.path.exists(OUTPUT_FILE):
        with open(OUTPUT_FILE, 'w', newline='') as f:
            csv.writer(f).writerow(["Iter", "Mode", "Nodes", "PE_Dim", "SRAM", "EDP", "Latency", "Energy", "Area_mm2"])

    print("=== NicePIM Co-Design Engine Started ===")

    for i in range(N_CALLS):
        # --- Step A: TuRBO 采样 ---
        current_bounds = turbo.get_trust_region_bounds(full_space)
        opt = Optimizer(current_bounds, base_estimator="ET", acq_func="EI", 
                        n_initial_points=2 if i==0 else 1, random_state=42+i)
        try:
            next_point = opt.ask()
        except:
            next_point = [np.random.randint(d.low, d.high+1) for d in full_space]

        num_nodes, pe_dim, sram_sz = next_point
        
        # --- Step B: 模式切换 (Baseline vs Atomic) ---
        mode = "baseline" if i % 2 == 0 else "atomic"
        
        print(f"\n--- Iter {i+1} [{mode.upper()}] Nodes={num_nodes}, PE={pe_dim}x{pe_dim}, SRAM={sram_sz//1024}KB ---")

        # --- Step C: 仿真闭环 ---
        stats_dir = os.path.join(cwd, f"output/step_{i}")
        if not os.path.exists(stats_dir):
            os.makedirs(stats_dir) # [关键修复] 防止 Docker 权限锁死

        # 1. 生成硬件 (支持多节点)
        # width=64 bits -> 8 bytes per word. depth = size / 8
        sram_depth = sram_sz // 8 
        arch_file = hw_gen.generate_config({
            'NUM_NODES': num_nodes,
            'PE_DIM_X': pe_dim,
            'PE_DIM_Y': pe_dim,
            'SRAM_DEPTH': sram_depth,
            'SRAM_WIDTH': 64 # 固定字长
        }, filename=f"arch_{i}.yaml")
        
        # 2. 动态生成 Mapper
        base_mapper_path = os.path.join(cwd, f"configs/mapper/mapper_{mode}.yaml")
        # 如果特定的 mapper 不存在，回退到通用 mapper.yaml
        if not os.path.exists(base_mapper_path):
            base_mapper_path = os.path.join(cwd, "configs/mapper/mapper.yaml")
            
        iter_mapper_path = os.path.join(stats_dir, "mapper_generated.yaml")
        generate_dynamic_mapper(base_mapper_path, iter_mapper_path, num_nodes, mode)

        # 3. 运行 Timeloop
        is_success = tl_wrapper.run_mapper(
            arch_path=arch_file,
            prob_path=os.path.join(cwd, "configs/prob/cnn_layer.yaml"),
            mapper_path=iter_mapper_path, # 使用动态生成的 Mapper
            output_dir=stats_dir,
            component_dir=comp_dir 
        )
        
        # 结果初始化
        edp = 1e16 # Penalty
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
            
            print(f"  >> Sim Result: Area={area_mm2:.2f} mm2, Cycle={logic_cycle}")

            # 5. 约束检查 (NicePIM Constraint)
            if area_mm2 > AREA_LIMIT_MM2:
                print(f"  [Constraint] Area {area_mm2:.2f} > {AREA_LIMIT_MM2} mm2. Penalty Applied.")
                edp = 1e17 # Hard Constraint
            elif logic_cycle > 0:
                # 6. 生成 Trace 并运行 Ramulator
                trace_path, num_reqs = trace_gen.generate_structured_trace(
                    results, mode=mode, output_path=f"output/dram_{i}.trace")
                
                # Ramulator (Optional: 只有当 num_reqs > 0 才跑)
                if num_reqs > 0:
                    ram_cycle = ram_wrapper.run_simulation(
                        config_rel_path="configs/ramulator/sedram.cfg",
                        trace_rel_path=f"output/dram_{i}.trace", # 注意路径一致性
                        output_rel_dir=stats_dir
                    )
                else:
                    ram_cycle = 0

                # 7. 系统级性能汇总
                # 对于 PIM，延迟通常由最慢的节点或主要计算决定
                # 简单模型：Max(Logic, Memory)
                total_cycle = max(logic_cycle, ram_cycle if ram_cycle else 0)
                
                # 系统能耗 = 逻辑能耗 + DRAM 动态能耗
                dram_energy = num_reqs * DRAM_BANK_WIDTH * DRAM_ENERGY_PER_BIT
                total_energy = logic_energy + dram_energy
                
                edp = total_cycle * total_energy
                latency = total_cycle
                energy = total_energy
                
                print(f"  >> [Success] EDP={edp:.2e}")
        
        # --- Step D: 更新优化器 ---
        # 只有在 Atomic 模式下更新硬件搜索方向 (Co-Design 逻辑)
        if mode == "atomic":
            turbo.update(edp, next_point)
            
        # 记录数据
        with open(OUTPUT_FILE, 'a', newline='') as f:
            csv.writer(f).writerow([i+1, mode, num_nodes, pe_dim, sram_sz, edp, latency, energy, area_mm2])

    print(f"\nBest Config found: {turbo.best_x} with EDP: {turbo.best_value:.2e}")

if __name__ == "__main__":
    run_turbo_dse()
