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
        self.SAMPLE_SIZE = 500 

    def evaluate_system(self, hw_config, software_schedule, stats_dir, comp_dir, iter_context=None):
        num_nodes = hw_config['num_nodes']
        prob_paths = software_schedule['prob_paths']
        
        # [关键修复] 在这里定义 total_layers，确保作用域覆盖后续循环
        total_layers = len(prob_paths)
        
        iter_str = ""
        if iter_context:
            iter_str = f"It{iter_context['iter']}/{iter_context['max_iter']} "

        agg = {
            'log_E': 0.0, 'log_C': 0.0,
            'mem_E': 0.0, 'mem_C': 0.0,
            'noc_E': 0.0, 'noc_C': 0.0
        }
        max_area = 0.0
        
        for i, prob_path in enumerate(prob_paths):
            layer_name = os.path.basename(prob_path).replace('.yaml', '')
            
            bar_len = 8 
            # 这里的 total_layers 现在是安全的
            progress = i / max(1, total_layers)
            filled = int(bar_len * progress)
            bar_str = "█" * filled + "░" * (bar_len - filled)
            layer_short = layer_name[:15] + ".." if len(layer_name) > 15 else layer_name
            msg = f"{C_BLUE}{iter_str}Eval{C_END}|{C_PURPLE}[{bar_str}]{C_END}|{C_CYAN}{i+1}/{total_layers}:{layer_short:<17}{C_END}"

            with AsyncSpinner(msg) as spinner:
                
                layer_dir = os.path.join(stats_dir, layer_name)
                if not os.path.exists(layer_dir): os.makedirs(layer_dir)

                # --- 1. Run Timeloop (Logic) ---
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
                
                if not ret['success']:
                    spinner.stop()
                    print(f"\n{C_RED}[Timeloop Failed]{C_END} {layer_name}")
                    return self.PENALTY_VAL, 0, 0, 0, {}

                stats_file = os.path.join(layer_dir, "timeloop-mapper.stats.txt")
                if not os.path.exists(stats_file): return self.PENALTY_VAL, 0, 0, 0, {}

                try:
                    parser = TimeloopParser(stats_file)
                    results = parser.parse()
                except: return self.PENALTY_VAL, 0, 0, 0, {}

                logic_cyc = results.get('cycles', 0)
                logic_eng = results.get('energy_pj', 0)
                area = results.get('area_mm2', 0)
                max_area = max(max_area, area)
                
                real_dram_accesses = results.get('dram_accesses', 0)

                # --- 2. Run Ramulator-PIM & BookSim (Sampling Mode) ---
                trace_file = os.path.join(layer_dir, "dram.trace")
                
                # 生成 Burst Trace
                sampled_count = self._generate_synthetic_trace(trace_file, real_dram_accesses, self.SAMPLE_SIZE)
                
                trace_rel = os.path.relpath(trace_file, os.getcwd())
                output_rel = os.path.relpath(layer_dir, os.getcwd())
                
                # 配置 Ramulator-PIM
                config_ram = "configs/ramulator/LPDDR4-config.cfg"
                config_noc = "configs/ramulator/sedram.cfg" 

                sim_res = self.ram.run_simulation(
                    config_rel_path=config_ram, 
                    trace_rel_path=trace_rel, 
                    output_rel_dir=output_rel, 
                    network_config_path=config_noc, 
                    num_nodes=num_nodes
                )
                
                # 外推 (Extrapolation)
                scale_factor = 0.0
                if sampled_count > 0:
                    scale_factor = float(real_dram_accesses) / float(sampled_count)
                
                mem_cyc = sim_res.get('ram_cycles', 0) * scale_factor
                mem_eng = sim_res.get('ram_energy_pj', 0.0) * scale_factor
                
                noc_eng = sim_res.get('noc_energy_pj', 0.0) * scale_factor
                noc_cyc = sim_res.get('noc_cycles', 0.0) * scale_factor
                
                # 3. Accumulate
                agg['log_E'] += logic_eng
                agg['log_C'] += logic_cyc
                agg['mem_E'] += mem_eng
                agg['mem_C'] += mem_cyc
                agg['noc_E'] += noc_eng
                agg['noc_C'] += noc_cyc

            if i == 0 and max_area > self.cfg['AREA_LIMIT_MM2']:
                for k in agg: agg[k] *= 10
                break

        # Pipeline Latency Model: Max(Logic, Memory) + NoC Overhead
        total_cyc = max(agg['log_C'], agg['mem_C']) + agg['noc_C']
        total_eng = agg['log_E'] + agg['mem_E'] + agg['noc_E']
        
        edp = total_cyc * total_eng
        if max_area > self.cfg['AREA_LIMIT_MM2']:
            ratio = max_area / self.cfg['AREA_LIMIT_MM2']
            edp = (edp + 1e20) * (ratio ** 2)

        if edp == 0: edp = self.PENALTY_VAL
        
        return edp, total_cyc, total_eng, max_area, {
            'logic_E': agg['log_E'], 'logic_C': agg['log_C'],
            'dram_E': agg['mem_E'],  'dram_C': agg['mem_C'],
            'noc_E': agg['noc_E'],   'noc_C': agg['noc_C'],
            'total_C': total_cyc
        }

    def _generate_synthetic_trace(self, filepath, total_accesses, sample_limit):
        count = min(total_accesses, sample_limit)
        if count <= 0:
            with open(filepath, 'w') as f: pass
            return 0
        with open(filepath, 'w') as f:
            base_addr = 0x100000
            for i in range(count):
                rw = 'W' if i % 5 == 0 else 'R'
                addr = base_addr + (i * 32)
                f.write(f"{hex(addr)} {rw}\n")
        return count

    def _preprocess_timeloop_input(self, input_files, output_path):
        try:
            spec = Specification.from_yaml_files(input_files)
            with open(output_path, "w") as f: f.write(_specification_to_yaml_string(spec._process()))
            return True
        except: return False

    def _run_subprocess(self, cmd):
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            return {'success': res.returncode == 0, 'stdout': res.stdout, 'stderr': res.stderr}
        except Exception as e:
            return {'success': False, 'stdout': "", 'stderr': str(e)}
