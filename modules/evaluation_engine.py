import os
import math
import yaml
import time
import sys
import subprocess
from modules.visualizer import DualProgressBar, C_RED, C_YELLOW, C_BLUE, C_END
from modules.result_parser import TimeloopParser

class CoDesignEvaluator:
    def __init__(self, arch_gen, tl_wrapper, ram_wrapper, trace_gen, config):
        self.arch_gen = arch_gen
        self.tl = tl_wrapper
        self.ram = ram_wrapper
        self.trace = trace_gen
        self.cfg = config

    def _calc_dram_energy(self, time_ns):
        # 静态功耗模型
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
        # 1. 基础读取 (只读取 mapspace 和 constraints 模板，忽略 mapper)
        if os.path.exists(template_path):
            with open(template_path, 'r') as f: config = yaml.safe_load(f)
        else:
            config = {}

        if 'mapspace' not in config: 
            config['mapspace'] = {'template': 'uber', 'version': 0.4}
        
        # 2. [核心修复] 极简 Mapper 配置
        # 移除了所有导致 ParseError 的别名参数，只保留最核心的
        # 注意：算法名称加了内部单引号，防止被解析为表达式
        config['mapper'] = {
            'version': 0.4,
            'algorithm': "'random-pruned'", 
            'timeout': 60
        }

        # 3. 约束配置
        if 'constraints' not in config: 
            config['constraints'] = {'version': 0.4, 'targets': []}
        elif 'targets' not in config['constraints']: 
            config['constraints']['targets'] = []

        # [核心修复] 通用 Bypass 约束
        # 1. 使用 'dataspace' 而不是 'datatype'
        # 2. 使用正确的组件名称 'RegFile' 和 'Node_SRAM'
        common_constraints = [
            # 允许 Input/Output 跳过寄存器文件 (解决 ResNet 第一层 C=3 问题)
            {'target': 'RegFile', 'type': 'dataspace', 'bypass': ['Inputs', 'Outputs'], 'keep': ['Weights']},
            # 允许 Weights 跳过节点级 SRAM (减少片上存储压力)
            {'target': 'Node_SRAM', 'type': 'dataspace', 'bypass': ['Weights'], 'keep': ['Inputs', 'Outputs']}
        ]
        
        # 将通用约束加入配置
        for c in common_constraints:
            config['constraints']['targets'].append(c)

        # 4. Atomic 模式专用约束
        if mode == "atomic":
            config['constraints']['targets'].append({
                'target': 'PIM_Node', 
                'type': 'spatial', 
                # [关键] 不指定 factors，只指定维度，让 Timeloop 自动寻找最佳切分
                'permutation': ['M'] 
            })
            
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

        # Mapper 路径准备
        cwd = os.getcwd()
        base_mapper = os.path.join(cwd, f"configs/mapper/mapper_{mode}.yaml")
        if not os.path.exists(base_mapper): base_mapper = os.path.join(cwd, "configs/mapper/mapper.yaml")
        iter_mapper = os.path.join(stats_dir, f"mapper_{mode}.yaml")
        
        # 生成干净的 Mapper 配置文件
        self._generate_mapper(base_mapper, iter_mapper, num_nodes, mode)

        agg_cycles = 0
        agg_energy = 0
        agg_noc_lat = 0
        max_area = 0
        valid_layers = 0

        # === 逐层仿真循环 ===
        for i, prob_path in enumerate(prob_paths):
            layer_name = os.path.basename(prob_path).replace('.yaml', '')
            pb.update_layer(i+1, layer_name)

            layer_dir = os.path.join(stats_dir, layer_name)
            if not os.path.exists(layer_dir): os.makedirs(layer_dir)

            # --- A. 运行 Timeloop Mapper ---
            pb.update_step(1, "Mapping")
            
            # 收集所有输入文件
            input_files = [arch_file, prob_path, iter_mapper]
            if os.path.exists(comp_dir):
                for root, _, files in os.walk(comp_dir):
                    for file in files:
                        if file.endswith(".yaml"):
                            input_files.append(os.path.join(root, file))
            
            # [关键] 确保 -o 参数在所有输入文件之后
            cmd = ["tl", "mapper"] + input_files + ["-o", layer_dir]
            
            try:
                # 捕获输出，只在失败时显示
                result = subprocess.run(cmd, capture_output=True, text=True)
                is_success = (result.returncode == 0)
                error_msg = result.stderr if not is_success else ""
            except Exception as e:
                is_success = False
                error_msg = str(e)

            if not is_success:
                pb.finish()
                print(f"\n{C_RED}[Failed] Layer {layer_name} failed mapping.{C_END}")
                # 打印错误日志用于调试
                print(f"{C_YELLOW}=== Timeloop Error Log ==={C_END}")
                print(error_msg[-2000:] if error_msg else "No error message captured.") 
                print(f"{C_YELLOW}=========================={C_END}")
                # 遇到错误立即停止，返回极大的惩罚值
                return 1e18, 0, 0, 0, {}

            # --- B. 解析结果 ---
            pb.update_step(2, "Parsing")
            try:
                stats_file = os.path.join(layer_dir, "timeloop-mapper.stats.txt")
                parser = TimeloopParser(stats_file)
                results = parser.parse()
            except:
                pb.finish()
                return 1e18, 0, 0, 0, {}

            logic_cyc = results.get('cycles', 0)
            layer_energy = results.get('energy_pj', 0)
            area = results.get('area_mm2', 0.0)
            dram_acc = results.get('dram_reads', 0)
            sram_acc = results.get('sram_reads', 0)
            
            # --- C. 运行 NoC 仿真 ---
            noc_lat = 0
            noc_eng = 0
            ram_cycles = 0
            
            if num_nodes > 1:
                pb.update_step(3, "NoC Sim")
                trace_file = os.path.join(layer_dir, f"dram_{mode}.trace")
                self.trace.generate_structured_trace(results, mode, trace_file, stats_file)
                noc_cfg = os.path.join(layer_dir, "noc_config.cfg")
                self._generate_booksim_config(noc_cfg, num_nodes)
                
                # 运行 Ramulator/BookSim
                with open(os.devnull, 'w') as devnull:
                    sim_res = self.ram.run_simulation(
                        "configs/ramulator/LPDDR4-config.cfg", trace_file, 
                        layer_dir, noc_cfg, num_nodes
                    )
                
                noc_eng = sim_res['noc_energy'] * 0.2
                noc_lat = sim_res['avg_network_latency'] * 0.5
                ram_cycles = sim_res['ram_cycles']

            # --- D. 聚合计算 ---
            pb.update_step(4, "Calc")
            noc_overhead = noc_lat if num_nodes > 1 else 0
            mem_latency = ram_cycles + noc_overhead
            
            # Atomic 模式下的 Masking 模型
            masking_alpha = 0.0
            if mode == "atomic":
                reuse_ratio = sram_acc / max(1, dram_acc)
                if reuse_ratio < 4.0: masking_alpha = 0.2
                elif reuse_ratio < 64.0: masking_alpha = 0.6
                else: masking_alpha = 0.95
            
            overlap = min(logic_cyc, mem_latency) * masking_alpha
            total_layer_cyc = logic_cyc + mem_latency - overlap
            
            agg_cycles += total_layer_cyc
            
            # 简单的 DRAM 功耗估算
            dram_dyn_eng = dram_acc * self.cfg['DRAM_BANK_WIDTH'] * 1.2 
            dram_sta_eng = self._calc_dram_energy(total_layer_cyc)
            
            agg_energy += (layer_energy + noc_eng + dram_dyn_eng + dram_sta_eng)
            agg_noc_lat += noc_lat
            max_area = max(max_area, area)
            valid_layers += 1

        # === 循环结束 ===
        pb.finish()
        
        # 面积惩罚
        total_area = max_area
        penalty_factor = 1.0
        area_msg = f"{total_area:.1f}"
        if total_area > self.cfg['AREA_LIMIT_MM2']:
            ratio = (total_area - self.cfg['AREA_LIMIT_MM2']) / self.cfg['AREA_LIMIT_MM2']
            penalty_factor = 1.0 + (ratio * 10.0)
            area_msg = f"{C_YELLOW}{total_area:.1f}>{self.cfg['AREA_LIMIT_MM2']}{C_END}"

        edp_raw = agg_cycles * agg_energy
        edp_final = edp_raw * penalty_factor

        t_total = time.time() - t_start
        fmt_row = "  {:<9} | {:<6} | {:<10} | {:<10} | {:<8} | {:<8} | {:<6} | {:<4}"
        padding = " " * 30
        sys.stdout.write(f"\r{fmt_row.format(mode.upper(), f'{t_total:.1f}s', f'{agg_cycles:.2e}', f'{valid_layers} Lyrs', f'{agg_energy:.1e}', f'{edp_raw:.1e}', area_msg, '-')}{padding}\n")

        details = {
            'cycles': agg_cycles, 
            'layers': valid_layers,
            'avg_noc_lat': agg_noc_lat / max(1, valid_layers)
        }
        return edp_final, agg_cycles, agg_energy, total_area, details
