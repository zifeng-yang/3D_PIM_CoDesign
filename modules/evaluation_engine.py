import os
import math
import yaml
import time
import sys
import contextlib
# [关键修改] 引入新的 DualProgressBar
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
        # 静态功耗模型 (Background Power)
        return 11.0 * time_ns 

    def _generate_booksim_config(self, output_path, num_nodes):
        # [NoC 优化] 针对资源受限场景的拓扑选择
        if num_nodes <= 8:
            topology = "ring"
            k = num_nodes
            n = 1
        else:
            topology = "mesh"
            k = int(math.ceil(math.sqrt(num_nodes)))
            n = 2

        # [NoC 优化] 匹配 Hybrid Bonding 的高带宽 (256 bits = 32 Bytes)
        channel_width = 256 
        
        # [NoC 优化] 极简 Buffer 配置以降低功耗
        num_vcs = 2 
        vc_buf_size = 4 

        # [加速优化] 减少 NoC 仿真采样数
        content = f"""
topology = {topology};
k = {k};
n = {n};
routing_function = min_adapt;
traffic = uniform;
packet_size = 1;
channel_width = {channel_width}; 
num_vcs = {num_vcs};
vc_buf_size = {vc_buf_size};
wait_for_tail_credit = 1;
sim_type = latency;
warmup_periods = 100;  # 加速: 1000 -> 100
sim_count = 1000;      # 加速: 5000 -> 1000
sample_period = 1000;
use_read_write = 0;
input_speedup = 1;
output_speedup = 1;
internal_speedup = 1.0;
"""
        with open(output_path, 'w') as f: f.write(content)
        return output_path

    def _generate_mapper(self, template_path, output_path, num_nodes, mode):
        if not os.path.exists(template_path): return False
        with open(template_path, 'r') as f: config = yaml.safe_load(f)
        
        if 'mapspace' not in config: config['mapspace'] = {'template': 'uber', 'version': 0.4}
        
        # [加速优化] 注入快速搜索参数
        if 'mapper' not in config: config['mapper'] = {}
        config['mapper']['victory-condition'] = 100
        config['mapper']['timeout'] = 60  # 单层最长 60s
        config['mapper']['algorithm'] = "random-pruned"

        if 'constraints' not in config: config['constraints'] = {'version': 0.4, 'targets': []}
        elif 'targets' not in config['constraints']: config['constraints']['targets'] = []

        # Atomic 模式强制空间切分
        if mode == "atomic":
            config['constraints']['targets'].append({
                'target': 'PIM_Node', 'type': 'spatial', 'factors': f'M={num_nodes}', 'permutation': 'M' 
            })
            
        with open(output_path, 'w') as f: yaml.dump(config, f, default_flow_style=False)
        return True

    def evaluate(self, mode, num_nodes, arch_file, stats_dir, comp_dir, prob_paths=[]):
        """
        全网络评估：循环运行所有层并聚合结果
        prob_paths: YAML 文件路径列表 (由 WorkloadManager 生成)
        """
        t_start = time.time()
        
        # 兼容性处理
        if isinstance(prob_paths, str): prob_paths = [prob_paths]
        if not prob_paths: return 1e18, 0, 0, 0, {}

        # [UI 优化] 使用双层进度条
        total_layers = len(prob_paths)
        pb = DualProgressBar(mode, total_layers)
        pb.start()

        # 1. 生成 Mapper 配置文件 (所有层共用)
        cwd = os.getcwd()
        base_mapper = os.path.join(cwd, f"configs/mapper/mapper_{mode}.yaml")
        if not os.path.exists(base_mapper): base_mapper = os.path.join(cwd, "configs/mapper/mapper.yaml")
        iter_mapper = os.path.join(stats_dir, f"mapper_{mode}.yaml")
        self._generate_mapper(base_mapper, iter_mapper, num_nodes, mode)

        # 聚合变量初始化
        agg_cycles = 0
        agg_energy = 0
        agg_noc_lat = 0
        max_area = 0
        valid_layers = 0

        # === 2. 逐层仿真循环 ===
        for i, prob_path in enumerate(prob_paths):
            # 获取层名称
            layer_name = os.path.basename(prob_path).replace('.yaml', '')
            
            # [UI 优化] 更新外层进度 (层级信息)
            pb.update_layer(i+1, layer_name)

            # [关键] 为每一层创建独立子目录，防止 stats 文件被覆盖
            layer_dir = os.path.join(stats_dir, layer_name)
            if not os.path.exists(layer_dir): os.makedirs(layer_dir)

            # --- A. Timeloop Mapper ---
            pb.update_step(1, "Mapping")
            is_success = False
            with contextlib.redirect_stdout(None), contextlib.redirect_stderr(None):
                try:
                    is_success = self.tl.run_mapper(
                        arch_path=arch_file, 
                        prob_path=prob_path, 
                        mapper_path=iter_mapper, 
                        output_dir=layer_dir,      # 输出到层级目录
                        component_dir=comp_dir 
                    )
                except: is_success = False

            if not is_success:
                pb.finish()
                print(f"\n{C_RED}[Failed] Layer {layer_name} failed mapping.{C_END}")
                return 1e18, 0, 0, 0, {}

            # --- B. Result Parsing ---
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
            
            # --- C. NoC Simulation ---
            noc_lat = 0
            noc_eng = 0
            ram_cycles = 0
            
            if num_nodes > 1:
                pb.update_step(3, "NoC Sim")
                # 生成 Trace
                trace_file = os.path.join(layer_dir, f"dram_{mode}.trace")
                self.trace.generate_structured_trace(results, mode, trace_file, stats_file)
                
                # 生成 NoC Config
                noc_cfg = os.path.join(layer_dir, "noc_config.cfg")
                self._generate_booksim_config(noc_cfg, num_nodes)
                
                # 运行 Ramulator
                sim_res = self.ram.run_simulation(
                    config_rel_path="configs/ramulator/LPDDR4-config.cfg",
                    trace_rel_path=trace_file, 
                    output_rel_dir=layer_dir,  
                    network_config_path=noc_cfg, 
                    num_nodes=num_nodes
                )
                
                noc_eng = sim_res['noc_energy'] * 0.2
                noc_lat = sim_res['avg_network_latency'] * 0.5
                ram_cycles = sim_res['ram_cycles']

            # --- D. Aggregation ---
            pb.update_step(4, "Calculating")
            
            # 性能模型
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
            
            # 累加
            agg_cycles += total_layer_cyc
            
            dram_dyn_eng = dram_acc * self.cfg['DRAM_BANK_WIDTH'] * 1.2 
            dram_sta_eng = self._calc_dram_energy(total_layer_cyc)
            
            agg_energy += (layer_energy + noc_eng + dram_dyn_eng + dram_sta_eng)
            agg_noc_lat += noc_lat
            max_area = max(max_area, area)
            valid_layers += 1

        # === 3. Finish ===
        pb.finish()
        
        # 面积约束
        total_area = max_area
        penalty_factor = 1.0
        area_msg = f"{total_area:.1f}"
        if total_area > self.cfg['AREA_LIMIT_MM2']:
            ratio = (total_area - self.cfg['AREA_LIMIT_MM2']) / self.cfg['AREA_LIMIT_MM2']
            penalty_factor = 1.0 + (ratio * 10.0)
            area_msg = f"{C_YELLOW}{total_area:.1f}>{self.cfg['AREA_LIMIT_MM2']}{C_END}"

        # 最终指标
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
