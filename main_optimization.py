import os
import csv
import time
import datetime
import numpy as np
from skopt import Optimizer
from skopt.space import Integer
from skopt.learning import GaussianProcessRegressor
from skopt.learning.gaussian_process.kernels import Matern, WhiteKernel

# === 模块化导入 ===
from modules.arch_gen import ArchGenerator
from modules.wrapper_timeloop import TimeloopWrapper
from modules.wrapper_ramulator import RamulatorWrapper
from modules.trace_gen import TraceGenerator
# [修复] 移除了 print_progress_bar，保留颜色代码
from modules.visualizer import C_GREEN, C_RED, C_YELLOW, C_BLUE, C_END
from modules.data_logger import DataLogger
from modules.optimizer_turbo import TuRBOState
from modules.evaluation_engine import CoDesignEvaluator
from modules.workload_manager import WorkloadManager 

# ==========================================
#               全局配置 (CONFIG)
# ==========================================
N_CALLS = 50 

CONFIG = {
    # 面积约束：Logic Layer 的 Footprint (mm^2)
    # 因为采用了 Hybrid Bonding，垂直堆叠不增加 Footprint，且 TSV 面积忽略不计
    'AREA_LIMIT_MM2': 48.0,      
    'TSV_AREA_OVERHEAD': 0.0,    
    
    'DRAM_BANK_WIDTH': 256,      # bits, 用于能耗估算和 NoC 匹配
    'TIMEOUT_SEC': 120,          # 防止 Baseline 在大搜索空间下卡死
    'NOTE': 'Real Workload (ResNet18) + Ring NoC + Hybrid Bonding'
}

def run_dse():
    # ---------------------------------------------------------
    # 1. 系统初始化与负载准备
    # ---------------------------------------------------------
    logger = DataLogger(CONFIG)
    print(f"\n=== 3D PIM Co-Design Engine (Production Ready) Started ===")
    print(f"Results saved to: {logger.get_results_dir()}\n")
    
    # [关键步骤] 准备真实神经网络负载
    print(f"{C_BLUE}>>> Initializing Workload Manager...{C_END}")
    # 指定生成的 yaml 存放路径
    prob_dir = "configs/prob/generated"
    wm = WorkloadManager(config_dir=prob_dir)
    
    # 生成全网络负载 (ResNet18)
    # 这会返回一个包含多层 yaml 文件的列表 (sorted list)
    target_prob_paths = wm.generate_full_model("resnet18")
    
    if not target_prob_paths:
        print(f"{C_RED}[Error] No workloads generated!{C_END}")
        return
        
    print(f"{C_GREEN}>>> Selected Full Model: ResNet18 ({len(target_prob_paths)} layers){C_END}\n")

    # ---------------------------------------------------------
    # 2. 初始化评估引擎
    # ---------------------------------------------------------
    cwd = os.getcwd()
    comp_dir = os.path.join(cwd, "configs/arch/components")

    arch_gen = ArchGenerator(template_path=os.path.join(cwd, "templates/arch.yaml.jinja2"),
                             output_dir=os.path.join(cwd, "output/generated_arch"))
    
    evaluator = CoDesignEvaluator(
        arch_gen=arch_gen,
        tl_wrapper=TimeloopWrapper(),
        ram_wrapper=RamulatorWrapper(),
        trace_gen=TraceGenerator(os.path.join(cwd, "output/dram.trace")),
        config=CONFIG
    )

    # ---------------------------------------------------------
    # 3. 优化器配置
    # ---------------------------------------------------------
    # 搜索空间: Nodes [1,16], PE [4,32], SRAM_Log2 [20,25] (1MB~32MB)
    space = [Integer(1, 16, name='nodes'), Integer(4, 32, name='pe'), Integer(20, 25, name='sram_log2')]
    turbo = TuRBOState(dim=len(space))

    # 增强型高斯过程模型
    gp_kernel = Matern(length_scale=1.0, length_scale_bounds=(1e-1, 100.0), nu=2.5) + WhiteKernel(noise_level=1e-5)
    base_estimator = GaussianProcessRegressor(kernel=gp_kernel, alpha=1e-5, normalize_y=True, n_restarts_optimizer=2)

    # 初始化日志文件
    with open(logger.summary_file, 'w', newline='') as f:
        csv.writer(f).writerow(["Iter", "Nodes", "PE", "SRAM_KB", "EDP_Base", "Lat_Base", "En_Base", 
                                "EDP_Atom", "Lat_Atom", "En_Atom", "Area_mm2", "Runtime_s", "Improvement"])
    with open(logger.details_file, 'w', newline='') as f:
        csv.writer(f).writerow(["Iter", "Mode", "Cycles", "DRAM_Acc", "SRAM_Acc", "NoC_Lat", "NoC_Pwr"])

    HEADER_DIVIDER = "-" * 105
    HEADER_FORMAT = "  {:<9} | {:<6} | {:<10} | {:<10} | {:<8} | {:<8} | {:<6} | {:<4}"

    # ---------------------------------------------------------
    # 4. 主循环
    # ---------------------------------------------------------
    for i in range(N_CALLS):
        iter_id = i + 1
        iter_start = time.time()
        
        # [修复] 移除了 print_progress_bar 调用，界面由 Evaluation Engine 内部的 StepProgressBar 接管
        
        # --- A. 采样 ---
        bounds = turbo.get_trust_region_bounds(space)
        opt = Optimizer(bounds, base_estimator=base_estimator, acq_func="EI", n_initial_points=3 if i==0 else 1, random_state=42+i)
        try: next_point = opt.ask()
        except: next_point = [np.random.randint(d.low, d.high+1) for d in space]
        
        num_nodes = next_point[0]
        pe_dim = next_point[1]
        sram_log2 = next_point[2]
        sram_sz = 2 ** sram_log2 
        
        print(f"{HEADER_DIVIDER}")
        print(f"Iter {iter_id}/{N_CALLS} | HW Config: Nodes={num_nodes} | PE={pe_dim}x{pe_dim} | SRAM=2^{sram_log2} ({sram_sz//1024}KB)")
        print(f"{HEADER_DIVIDER}")
        print(HEADER_FORMAT.format("Mode", "Time", "Latency", "Bottleneck", "Energy", "EDP", "Area", "Mask"))
        print(f"{HEADER_DIVIDER}")

        stats_dir = os.path.join(cwd, f"output/step_{i}")
        if not os.path.exists(stats_dir): os.makedirs(stats_dir)
        
        sram_depth = sram_sz // 8 
        arch_file = arch_gen.generate_config({
            'NUM_NODES': num_nodes, 'PE_DIM_X': pe_dim, 'PE_DIM_Y': pe_dim, 'SRAM_DEPTH': sram_depth, 'SRAM_WIDTH': 64
        }, filename=f"arch_{i}.yaml")

        # --- B. 评估 (传入全网络文件列表) ---
        # 注意：这里传入的是 prob_paths 列表，Evaluation Engine 会自动循环跑完所有层
        edp_base, lat_base, en_base, area_base, det_base = evaluator.evaluate(
            "baseline", num_nodes, arch_file, stats_dir, comp_dir, prob_paths=target_prob_paths
        )
        edp_atom, lat_atom, en_atom, area_atom, det_atom = evaluator.evaluate(
            "atomic", num_nodes, arch_file, stats_dir, comp_dir, prob_paths=target_prob_paths
        )

        print(f"{HEADER_DIVIDER}")

        # --- C. 分析与更新 ---
        imp_str = "0.0%"
        base_valid = edp_base < 1e15 
        atom_valid = edp_atom < 1e15
        
        if not base_valid and atom_valid:
            print(f"  >>> Result: {C_GREEN}Atomic Enabler 🚀 (Baseline Failed){C_END}"); imp_str = "Inf"
        elif not base_valid and not atom_valid:
            print(f"  >>> Result: {C_RED}Both Failed (Bad HW){C_END}"); imp_str = "0.0%"
        elif edp_atom < edp_base:
            imp = (edp_base - edp_atom) / edp_base * 100.0
            print(f"  >>> Result: {C_GREEN}Improved by {imp:.2f}%{C_END}"); imp_str = f"{imp:.1f}%"
        else:
            print(f"  >>> Result: {C_YELLOW}No Improvement{C_END}")

        turbo.update(edp_atom, next_point)
        duration = time.time() - iter_start
        print(f"  >>> Iteration Time: {duration:.2f}s\n")

        # --- D. 记录 ---
        metrics = {'base_edp': edp_base, 'base_lat': lat_base, 'base_en': en_base, 'atom_edp': edp_atom, 'atom_lat': lat_atom, 'atom_en': en_atom, 'area': area_atom, 'base_det': det_base, 'atom_det': det_atom}
        logger.log_iteration(iter_id, next_point, metrics, duration, imp_str)
        
        # 备份第一个 workload 文件作为样本
        files_to_save = [arch_file]
        if target_prob_paths: files_to_save.append(target_prob_paths[0])
        
        if os.path.exists(os.path.join(stats_dir, "mapper_baseline.yaml")): files_to_save.append(os.path.join(stats_dir, "mapper_baseline.yaml"))
        if os.path.exists(os.path.join(stats_dir, "mapper_atomic.yaml")): files_to_save.append(os.path.join(stats_dir, "mapper_atomic.yaml"))
        logger.archive_artifacts(iter_id, files_to_save)
        
        if iter_id % 5 == 0: logger.save_checkpoint(turbo)

    # 5. 结束
    # [修复] 移除了 print_progress_bar 调用
    
    # 转换最优解格式用于显示
    best_nodes = turbo.best_x[0]
    best_pe = turbo.best_x[1]
    best_sram_kb = (2 ** turbo.best_x[2]) // 1024
    
    print(f"\n\n{C_GREEN}=== Optimization Finished ==={C_END}")
    print(f"Best Atomic Config found:")
    print(f"  Nodes: {best_nodes}")
    print(f"  PE:    {best_pe}x{best_pe}")
    print(f"  SRAM:  {best_sram_kb} KB")
    print(f"  EDP:   {turbo.best_value:.2e}")

if __name__ == "__main__":
    run_dse()
