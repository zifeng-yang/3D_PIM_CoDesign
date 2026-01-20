import os
import sys
import math
import subprocess
from modules.visualizer import C_RED, C_YELLOW, C_BLUE, C_PURPLE, C_CYAN, C_END, AsyncSpinner
from modules.result_parser import TimeloopParser
from timeloopfe.v4.specification import Specification
from timeloopfe.common.backend_calls import _specification_to_yaml_string

class CoDesignEvaluator:
    def __init__(self, arch_gen, tl_wrapper, ram_wrapper, trace_gen, config):
        self.arch_gen = arch_gen
        self.tl = tl_wrapper
        self.ram = ram_wrapper
        self.trace = trace_gen
        self.cfg = config
        self.PENALTY_VAL = 1e30

    def evaluate_system(self, hw_config, software_schedule, stats_dir, comp_dir, iter_context=None):
        num_nodes = hw_config['num_nodes']
        prob_paths = software_schedule['prob_paths']
        
        iter_str = ""
        if iter_context:
            iter_str = f"It{iter_context['iter']}/{iter_context['max_iter']} " # 精简 Iter -> It

        total_layers = len(prob_paths)
        agg_cycles, agg_energy, max_area = 0, 0, 0.0
        
        for i, prob_path in enumerate(prob_paths):
            layer_name = os.path.basename(prob_path).replace('.yaml', '')
            
            # --- 构造显示信息 (精简版) ---
            # 蓝色: 步骤
            step_info = f"{C_BLUE}{iter_str}Eval{C_END}"
            
            # 紫色: 进度条 [██░░]
            bar_len = 8 # 减小进度条长度以节省空间
            filled = int(bar_len * ((i) / total_layers))
            bar_str = "█" * filled + "░" * (bar_len - filled)
            
            # 青色: 层名 (限制长度)
            layer_short = layer_name[:15] + ".." if len(layer_name) > 15 else layer_name
            layer_info = f"{C_CYAN}{i+1}/{total_layers}:{layer_short:<17}{C_END}"
            
            msg = f"{step_info}|{C_PURPLE}[{bar_str}]{C_END}|{layer_info}"

            # --- 启动异步 Spinner ---
            with AsyncSpinner(msg) as spinner:
                
                layer_dir = os.path.join(stats_dir, layer_name)
                if not os.path.exists(layer_dir): os.makedirs(layer_dir)

                input_files = [hw_config['arch_file'], prob_path, software_schedule['mapper_path'], software_schedule['constraints_path']]
                if os.path.exists(comp_dir):
                    for root, _, files in os.walk(comp_dir):
                        for file in files:
                            if file.endswith(".yaml"): input_files.append(os.path.join(root, file))

                canonical_input = os.path.join(layer_dir, "timeloop-input.yaml")
                if not self._preprocess_timeloop_input(input_files, canonical_input): 
                    return self.PENALTY_VAL, 0, 0, 0, {}

                cmd = ["timeloop-mapper", canonical_input, "-o", layer_dir]
                ret = self._run_subprocess(cmd)
                
                if not ret['success']: return self.PENALTY_VAL, 0, 0, 0, {}

                stats_file = os.path.join(layer_dir, "timeloop-mapper.stats.txt")
                if not os.path.exists(stats_file): return self.PENALTY_VAL, 0, 0, 0, {}

                try:
                    results = TimeloopParser(stats_file).parse()
                except: return self.PENALTY_VAL, 0, 0, 0, {}

                logic_cyc = results.get('cycles', 0)
                layer_energy = results.get('energy_pj', 0)
                area = results.get('area_mm2', 0)
                max_area = max(max_area, area)

            # Area Check
            if i == 0 and max_area > self.cfg['AREA_LIMIT_MM2']:
                agg_cycles += logic_cyc * total_layers * 10 
                agg_energy += layer_energy * total_layers * 10
                break

            noc_lat = 0
            noc_eng = 0
            if num_nodes > 1:
                noc_lat = 500 * math.sqrt(num_nodes) 
                noc_eng = 100 * num_nodes

            agg_cycles += logic_cyc + noc_lat 
            agg_energy += layer_energy + noc_eng

        edp = agg_cycles * agg_energy
        if max_area > self.cfg['AREA_LIMIT_MM2']:
            ratio = max_area / self.cfg['AREA_LIMIT_MM2']
            edp = (edp + 1e20) * (ratio ** 2)

        if edp == 0: edp = self.PENALTY_VAL
        return edp, agg_cycles, agg_energy, max_area, {}

    def _preprocess_timeloop_input(self, input_files, output_path):
        try:
            spec = Specification.from_yaml_files(input_files)
            with open(output_path, "w") as f: f.write(_specification_to_yaml_string(spec._process()))
            return True
        except: return False

    def _run_subprocess(self, cmd):
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            return {'success': res.returncode == 0}
        except: return {'success': False}
