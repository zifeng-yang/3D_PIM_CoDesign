import os
import sys
import time
import numpy as np
import warnings

# ==========================================
# [环境优化] 屏蔽冗余警告
# ==========================================
warnings.filterwarnings("ignore", module="skopt")
warnings.filterwarnings("ignore", category=UserWarning, message="The objective has been evaluated")
warnings.filterwarnings("ignore", module="sklearn")

# ==========================================
# [环境修复] 动态链接库路径自动注入
# ==========================================
TIMELOOP_LIB_PATH = "/home/yangzifeng/accelergy-timeloop-infrastructure/src/timeloop/lib"
if os.path.exists(TIMELOOP_LIB_PATH):
    current_ld_path = os.environ.get("LD_LIBRARY_PATH", "")
    if TIMELOOP_LIB_PATH not in current_ld_path:
        os.environ["LD_LIBRARY_PATH"] = TIMELOOP_LIB_PATH + ":" + current_ld_path

from skopt import Optimizer
from skopt.space import Integer
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import Matern, WhiteKernel

# === 模块导入 ===
from modules.arch_gen import ArchGenerator
from modules.wrapper_timeloop import TimeloopWrapper
from modules.wrapper_ramulator import RamulatorWrapper
from modules.trace_gen import TraceGenerator
from modules.visualizer import C_GREEN, C_RED, C_YELLOW, C_BLUE, C_PURPLE, C_CYAN, C_END, AsyncSpinner
from modules.data_logger import DataLogger
from modules.evaluation_engine import CoDesignEvaluator
from modules.workload_manager import WorkloadManager
from modules.software_optimizer import SoftwareOptimizer

# ==========================================
#               全局配置
# ==========================================
MAX_ITERATIONS = 15  
TURBO_BATCH_SIZE = 20 

CONFIG = {
    'AREA_LIMIT_MM2': 48.0,      
    'TSV_AREA_OVERHEAD': 0.0,    
    'DRAM_BANK_WIDTH': 256,
    'TIMEOUT_SEC': 120,
    'NOTE': 'Decoupled Co-Design: Algorithm 1 Implementation'
}

# === 快速重估模型 ===
class FastReestimator:
    def __init__(self):
        kernel = Matern(length_scale=1.0, length_scale_bounds=(1e-2, 1e5), nu=2.5) + \
                 WhiteKernel(noise_level=1e-5, noise_level_bounds=(1e-9, 1e-1))
        self.model = GaussianProcessRegressor(kernel=kernel, n_restarts_optimizer=5, normalize_y=True)
        self.X_history = []
        self.y_history = []
        self.is_fitted = False

    def update(self, hw_params, performance_metric):
        self.X_history.append(hw_params)
        self.y_history.append(performance_metric) 
        if len(self.X_history) >= 3:
            try:
                self.model.fit(np.array(self.X_history), np.array(self.y_history))
                self.is_fitted = True
            except: pass

    def predict(self, hw_params):
        if not self.is_fitted: return np.random.rand() 
        pred, std = self.model.predict(np.array([hw_params]), return_std=True)
        return pred[0] + 1.96 * std[0] 

# === 主类 ===
class DecoupledCoDesignEngine:
    def __init__(self):
        self.logger = DataLogger(CONFIG)
        self.cwd = os.getcwd()
        self._init_modules()
        self._init_space()
        
        self.best_result = {'hw': None, 'sw': None, 'edp': float('inf')}
        self.surrogate = FastReestimator()

        self.tr_length = 4.0 
        self.fail_count = 0
        self.succ_count = 0

        self.HEADER = "  {:<4} | {:<5} | {:<7} | {:<9} | {:<9} | {:<9} | {:<9} | {:<10}"
        self.DIVIDER = "-" * 85

    def _init_modules(self):
        print(f"{C_BLUE}>>> Initializing Modules...{C_END}")
        self.wm = WorkloadManager(config_dir="configs/prob/generated")
        self.prob_paths = self.wm.generate_full_model("resnet18")
        self.arch_gen = ArchGenerator(template_path="templates/arch.yaml.jinja2", output_dir="output/generated_arch")
        self.sw_opt = SoftwareOptimizer(config_dir="output/generated_configs")
        self.evaluator = CoDesignEvaluator(self.arch_gen, TimeloopWrapper(), RamulatorWrapper(), TraceGenerator("output/dram.trace"), CONFIG)

    def _init_space(self):
        self.bounds = [(1, 16), (4, 32), (18, 25)]
        self.space = [Integer(*b, name=n) for b, n in zip(self.bounds, ['nodes', 'pe', 'sram_log2'])]

    def _print_header(self):
        print(f"\n{self.DIVIDER}")
        print(self.HEADER.format("Iter", "Nodes", "PE Size", "SRAM", "Area(mm2)", "EDP", "Cycles", "Status"))
        print(f"{self.DIVIDER}")

    def _get_trust_region_space(self, center):
        new_space = []
        names = ['nodes', 'pe', 'sram_log2']
        for i, (low, high) in enumerate(self.bounds):
            L = int(self.tr_length)
            c = center[i]
            local_low = max(low, c - L)
            local_high = min(high, c + L)
            if local_low > local_high: local_high = local_low
            new_space.append(Integer(local_low, local_high, name=names[i]))
        return new_space

    def run(self):
        print(f"\n{C_GREEN}=== Algorithm 1: Decoupled Iteration Co-Design Started ==={C_END}")
        current_hw_params = [4, 16, 21] 
        self._print_header()

        for i in range(MAX_ITERATIONS):
            iter_id = i + 1
            
            # --- Step 1 ---
            msg_step1 = f"  {C_BLUE}Iter {iter_id}/{MAX_ITERATIONS} | Step 1/3 : Software Optimization{C_END}"
            with AsyncSpinner(msg_step1):
                stats_dir = os.path.join(self.cwd, f"output/iter_{iter_id}")
                if not os.path.exists(stats_dir): os.makedirs(stats_dir)
                
                sram_sz = 2 ** current_hw_params[2]
                arch_file = self.arch_gen.generate_config({
                    'NUM_NODES': current_hw_params[0], 'PE_DIM_X': current_hw_params[1], 'PE_DIM_Y': current_hw_params[1], 
                    'SRAM_DEPTH': sram_sz // 64, 'SRAM_WIDTH': 64
                }, filename=f"arch_iter_{iter_id}.yaml")
                
                hw_cfg = {'num_nodes': current_hw_params[0], 'pe': current_hw_params[1], 'sram_log2': current_hw_params[2], 'arch_file': arch_file}
                current_sw_schedule = self.sw_opt.optimize(hw_cfg, self.prob_paths, iter_id)
            
            # --- Step 2 ---
            # Evaluator 内部使用 AsyncSpinner
            edp, cycles, energy, area, details = self.evaluator.evaluate_system(
                hw_cfg, current_sw_schedule, stats_dir, "configs/arch/components", 
                iter_context={'iter': iter_id, 'max_iter': MAX_ITERATIONS}
            )
            
            # --- Result Logic ---
            status_str, color = "OK", C_END
            is_success = False
            
            if area > CONFIG['AREA_LIMIT_MM2']:
                status_str, color = "Area Vio", C_RED
            elif edp > 1e25: 
                status_str, color = "Failed", C_RED
            elif edp < self.best_result['edp']:
                status_str, color = "New Best", C_GREEN
                self.best_result = {'hw': current_hw_params, 'sw': current_sw_schedule, 'edp': edp}
                is_success = True 

            # TuRBO Logic
            if is_success:
                self.succ_count += 1
                self.fail_count = 0
                if self.succ_count >= 2: 
                    self.tr_length = min(self.tr_length * 2.0, 8.0)
                    self.succ_count = 0
            else:
                self.succ_count = 0
                self.fail_count += 1
                if self.fail_count >= 2: 
                    self.tr_length = max(self.tr_length / 2.0, 1.0)
                    self.fail_count = 0

            # Print Table Row
            sram_disp = f"{sram_sz//1024}KB" if sram_sz < 1024*1024 else f"{sram_sz//1024//1024}MB"
            row_str = self.HEADER.format(iter_id, current_hw_params[0], f"{current_hw_params[1]}x{current_hw_params[1]}", sram_disp, f"{area:.1f}", f"{edp:.1e}", f"{cycles:.1e}", status_str)
            print(f"\r{color}{row_str}{C_END}\033[K") 

            # Update Surrogate
            target_val = -np.log10(edp + 1e-9)
            self.surrogate.update(current_hw_params, target_val)
            
            # --- Step 3 ---
            msg_step3 = f"  {C_BLUE}Iter {iter_id}/{MAX_ITERATIONS} | Step 3/3 : HW Opt (TuRBO TR={self.tr_length:.1f}){C_END}"
            with AsyncSpinner(msg_step3):
                tr_space = self._get_trust_region_space(current_hw_params)
                opt = Optimizer(tr_space, base_estimator="GP", acq_func="EI", n_initial_points=5)
                best_internal_hw = current_hw_params
                best_internal_score = -float('inf')
                
                for _ in range(TURBO_BATCH_SIZE):
                    try:
                        next_point = opt.ask()
                        score = self.surrogate.predict(next_point)
                        if score > best_internal_score:
                            best_internal_score = score
                            best_internal_hw = next_point
                        opt.tell(next_point, -score)
                    except: break
            
            current_hw_params = best_internal_hw

        print(f"{self.DIVIDER}\n{C_GREEN}=== Optimization Finished ==={C_END}")
        print(f"Best Config: {self.best_result['hw']} (EDP: {self.best_result['edp']:.2e})")

if __name__ == "__main__":
    DecoupledCoDesignEngine().run()
