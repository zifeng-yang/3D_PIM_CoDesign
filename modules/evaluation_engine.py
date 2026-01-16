import os
import math
import yaml
import time
import sys
import subprocess
from modules.visualizer import DualProgressBar, C_RED, C_YELLOW, C_BLUE, C_END
from modules.result_parser import TimeloopParser

# 引入 TimeloopFE 库函数进行格式转换
from timeloopfe.v4.specification import Specification
from timeloopfe.common.backend_calls import _specification_to_yaml_string

class CoDesignEvaluator:
    def __init__(self, arch_gen, tl_wrapper, ram_wrapper, trace_gen, config):
        self.arch_gen = arch_gen
        self.tl = tl_wrapper
        self.ram = ram_wrapper
        self.trace = trace_gen
        self.cfg = config

    def _calc_dram_energy(self, time_ns):
        return 11.0 * time_ns 

    def _generate_booksim_config(self, output_path, num_nodes):
        if num_nodes <= 8:
            topology, k, n = "ring", num_nodes, 1
        else:
            topology, k, n = "mesh", int(math.ceil(math.sqrt(num_nodes))), 2

        content = f"""
topology = {topology};
k = {k}; n = {n};
routing_function = min_adapt; traffic = uniform;
packet_size = 1; channel_width = 256; 
num_vcs = 2; vc_buf_size = 4; wait_for_tail_credit = 1;
sim_type = latency; warmup_periods = 100; sim_count = 1000; sample_period = 1000;
use_read_write = 0; input_speedup = 1; output_speedup = 1; internal_speedup = 1.0;
"""
        with open(output_path, 'w') as f: f.write(content)
        return output_path

    def _generate_mapper(self, template_path, output_path, num_nodes, mode):
        # [关键修复] 去掉多余的引号，并使用下划线格式
        algo = "random_pruned" 
        
        config = {
            'mapper': {
                'version': 0.4,
                'algorithm': algo,
                'timeout': 60,
                'optimization_metrics': ['delay', 'energy'],
                'live_status': False,
                'num_threads': 8,
                'search_size': 0,
                'diagnostics': True 
            },
            'mapspace': {
                'version': 0.4,
                'template': 'uber',
            },
            'constraints': {
                'version': 0.4,
                'targets': []
            }
        }
        
        with open(output_path, 'w') as f: 
            yaml.dump(config, f, default_flow_style=False)
        return True

    def evaluate(self, mode, num_nodes, arch_file, stats_dir, comp_dir, prob_paths=[]):
        t_start = time.time()
        if isinstance(prob_paths, str): prob_paths = [prob_paths]
        if not prob_paths: return 1e18, 0, 0, 0, {}

        total_layers = len(prob_paths)
        pb = DualProgressBar(mode, total_layers)
        pb.start()

        iter_mapper = os.path.join(stats_dir, f"mapper_{mode}.yaml")
        self._generate_mapper(None, iter_mapper, num_nodes, mode)

        agg_cycles = 0
        agg_energy = 0
        agg_noc_lat = 0
        max_area = 0
        valid_layers = 0

        for i, prob_path in enumerate(prob_paths):
            layer_name = os.path.basename(prob_path).replace('.yaml', '')
            pb.update_layer(i+1, layer_name)
            layer_dir = os.path.join(stats_dir, layer_name)
            if not os.path.exists(layer_dir): os.makedirs(layer_dir)

            pb.update_step(1, "Mapping")
            
            input_files = [arch_file, prob_path, iter_mapper]
            if os.path.exists(comp_dir):
                for root, _, files in os.walk(comp_dir):
                    for file in files:
                        if file.endswith(".yaml"):
                            input_files.append(os.path.join(root, file))
            
            # === [TimeloopFE 预处理] ===
            canonical_input_path = os.path.join(layer_dir, "timeloop-input.yaml")
            try:
                spec = Specification.from_yaml_files(input_files)
                spec = spec._process() 
                try:
                    yaml_content = _specification_to_yaml_string(spec)
                except TypeError:
                    yaml_content = _specification_to_yaml_string(spec, False)
                
                with open(canonical_input_path, "w") as f:
                    f.write(yaml_content)
                    
            except Exception as e:
                pb.finish()
                print(f"\n{C_RED}[Error] TimeloopFE Pre-processing Failed for {layer_name}{C_END}")
                print(f"Details: {e}")
                return 1e18, 0, 0, 0, {}

            # === [直接运行 C++ Backend] ===
            cmd = ["timeloop-mapper", canonical_input_path, "-o", layer_dir]

            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                is_success = (result.returncode == 0)
                
                stats_file = os.path.join(layer_dir, "timeloop-mapper.stats.txt")
                if is_success and not os.path.exists(stats_file):
                    is_success = False
                    error_msg = f"Mapper finished (RC=0) but NO VALID MAPPING found."
                    
                    diag_marker = "Stats:"
                    if diag_marker in result.stdout:
                        diag_content = result.stdout.split(diag_marker)[-1]
                        error_msg += f"\n{C_YELLOW}>>> Diagnostics:{C_END}\n{diag_content}"
                    else:
                        error_msg += f"\nLast Output:\n" + "\n".join(result.stdout.splitlines()[-20:])
                else:
                    error_msg = result.stderr if not is_success else ""
                    
            except subprocess.TimeoutExpired:
                is_success = False
                error_msg = "Timeloop Timeout (120s)"
            except Exception as e:
                is_success = False
                error_msg = str(e)

            if not is_success:
                pb.finish()
                print(f"\n{C_RED}[Failed] Layer {layer_name} failed.{C_END}")
                print(f"{C_YELLOW}=== Diagnostics / Error Log ==={C_END}")
                print(error_msg)
                print(f"{C_YELLOW}==============================={C_END}")
                return 1e18, 0, 0, 0, {}

            pb.update_step(2, "Parsing")
            try:
                parser = TimeloopParser(stats_file)
                results = parser.parse()
            except:
                pb.finish()
                print(f"{C_RED}[Error] Parse failed for {layer_name}{C_END}")
                return 1e18, 0, 0, 0, {}

            logic_cyc = results.get('cycles', 0)
            layer_energy = results.get('energy_pj', 0)
            area = results.get('area_mm2', 0.0)
            dram_acc = results.get('dram_reads', 0)
            sram_acc = results.get('sram_reads', 0)
            
            # [NoC Sim]
            if num_nodes > 1:
                pb.update_step(3, "NoC Sim")
                trace_file = os.path.join(layer_dir, f"dram_{mode}.trace")
                self.trace.generate_structured_trace(results, mode, trace_file, stats_file)
                noc_cfg = os.path.join(layer_dir, "noc_config.cfg")
                self._generate_booksim_config(noc_cfg, num_nodes)
                
                with open(os.devnull, 'w') as devnull:
                    try:
                        sim_res = self.ram.run_simulation(
                            "configs/ramulator/LPDDR4-config.cfg", trace_file, 
                            layer_dir, noc_cfg, num_nodes
                        )
                        noc_eng = sim_res['noc_energy'] * 0.2
                        noc_lat = sim_res['avg_network_latency'] * 0.5
                        ram_cycles = sim_res['ram_cycles']
                    except:
                        noc_lat = 10000 

            pb.update_step(4, "Calc")
            noc_overhead = noc_lat if num_nodes > 1 else 0
            mem_latency = ram_cycles + noc_overhead
            
            masking_alpha = 0.0
            if mode == "atomic":
                reuse_ratio = sram_acc / max(1, dram_acc)
                if reuse_ratio < 4.0: masking_alpha = 0.2
                elif reuse_ratio < 64.0: masking_alpha = 0.6
                else: masking_alpha = 0.95
            
            overlap = min(logic_cyc, mem_latency) * masking_alpha
            total_layer_cyc = logic_cyc + mem_latency - overlap
            
            agg_cycles += total_layer_cyc
            dram_dyn_eng = dram_acc * self.cfg['DRAM_BANK_WIDTH'] * 1.2 
            dram_sta_eng = self._calc_dram_energy(total_layer_cyc)
            
            agg_energy += (layer_energy + noc_eng + dram_dyn_eng + dram_sta_eng)
            agg_noc_lat += noc_lat
            max_area = max(max_area, area)
            valid_layers += 1

        pb.finish()
        
        total_area = max_area
        penalty_factor = 1.0
        area_msg = f"{max_area:.1f}"
        if max_area > self.cfg['AREA_LIMIT_MM2']:
            ratio = (max_area - self.cfg['AREA_LIMIT_MM2']) / self.cfg['AREA_LIMIT_MM2']
            penalty_factor = 1.0 + (ratio * 10.0)
            area_msg = f"{C_YELLOW}{max_area:.1f}>{self.cfg['AREA_LIMIT_MM2']}{C_END}"

        edp_raw = agg_cycles * agg_energy
        edp_final = edp_raw * penalty_factor

        t_total = time.time() - t_start
        fmt_row = "  {:<9} | {:<6} | {:<10} | {:<10} | {:<8} | {:<8} | {:<6} | {:<4}"
        log_msg = fmt_row.format(mode.upper(), f"{t_total:.1f}s", f"{agg_cycles:.2e}", 
                                 f"{valid_layers} Lyrs", f"{agg_energy:.1e}", f"{edp_raw:.1e}", area_msg, '-')
        sys.stdout.write(f"\r{log_msg}" + " "*30 + "\n")

        details = {
            'cycles': agg_cycles, 
            'layers': valid_layers,
            'avg_noc_lat': agg_noc_lat / max(1, valid_layers)
        }
        return edp_final, agg_cycles, agg_energy, max_area, details
