import subprocess
import os
import re

class RamulatorWrapper:
    def __init__(self):
        self.project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        # 请确认此路径正确
        self.ramulator_bin = "/home/yangzifeng/ramulator/ramulator"
        self.booksim_bin   = "/home/yangzifeng/ramulator-pim/workspace/ramulator-pim/booksim2/src/booksim"

    def _parse_ramulator1_stats(self, stats_file):
        """解析 Ramulator 1.0 的统计文件 (从 stdout 重定向而来)"""
        cycles = 0
        if not os.path.exists(stats_file):
            print(f"[DEBUG-RAM] Stats file not found: {stats_file}")
            return 0
            
        with open(stats_file, 'r') as f:
            for line in f:
                # 查找关键统计项
                if "ramulator.dram_cycles" in line:
                    parts = line.split()
                    if len(parts) > 1:
                        try:
                            cycles = int(parts[1])
                        except ValueError:
                            pass
                        break
        
        print(f"[DEBUG-RAM] Parsed Cycles: {cycles}")
        return cycles

    def _parse_booksim_output(self, output_text):
        noc_power = 0.0
        avg_latency = 0.0
        lat_match = re.search(r'average packet latency\s*=\s*([\d\.]+)', output_text)
        if lat_match: avg_latency = float(lat_match.group(1))
        power_match = re.search(r'Total Power\s*=\s*([\d\.]+)', output_text)
        if power_match: noc_power = float(power_match.group(1)) * 1000.0
        return noc_power, avg_latency

    def _update_booksim_config(self, cfg_path, injection_rate, sim_cycles):
        if not os.path.exists(cfg_path): return
        with open(cfg_path, 'r') as f: lines = f.readlines()
        new_lines = []
        has_inj = False
        has_sim = False
        for line in lines:
            if "injection_rate" in line:
                new_lines.append(f"injection_rate = {injection_rate:.6f};\n")
                has_inj = True
            elif "sim_count" in line:
                new_lines.append(f"sim_count = {int(sim_cycles)};\n")
                has_sim = True
            else:
                new_lines.append(line)
        if not has_inj: new_lines.append(f"injection_rate = {injection_rate:.6f};\n")
        if not has_sim: new_lines.append(f"sim_count = {int(sim_cycles)};\n")
        with open(cfg_path, 'w') as f: f.writelines(new_lines)

    def run_simulation(self, config_rel_path, trace_rel_path, output_rel_dir, network_config_path=None, num_nodes=1):
        print(f"\n--- [Ramulator 1.0 Wrapper] Start Simulation ---")
        
        abs_config = os.path.join(self.project_root, config_rel_path)
        base_trace_path = os.path.join(self.project_root, trace_rel_path)
        
        # 定义输出统计文件路径
        trace_basename = os.path.basename(base_trace_path)
        stats_filename = trace_basename + ".stats"
        abs_stats_path = os.path.join(self.project_root, output_rel_dir, stats_filename)

        # [修正] Ramulator 1.0 标准命令行格式:
        # ./ramulator <config_file> --mode=cpu <trace_file>
        cmd_ram = [
            self.ramulator_bin,
            abs_config,      # 第一个参数必须是配置文件
            "--mode=cpu",
            base_trace_path  # 最后一个参数是 Trace 文件
        ]

        ram_cycles = 0
        try:
            print(f"[DEBUG-RAM] Executing: {' '.join(cmd_ram)}")
            
            # 打开文件用于保存 stdout
            with open(abs_stats_path, 'w') as f_out:
                # 执行命令，将 stdout 重定向到文件
                subprocess.run(cmd_ram, check=True, stdout=f_out, stderr=subprocess.PIPE, text=True)
            
            # 解析刚才生成的 stats 文件
            ram_cycles = self._parse_ramulator1_stats(abs_stats_path)
            
        except subprocess.CalledProcessError as e:
            print(f"[DEBUG-RAM] CRASHED with return code {e.returncode}")
            print(f"Stderr: {e.stderr}")
            return {'ram_cycles': 0, 'noc_energy': 0.0, 'avg_network_latency': 0.0}

        # BookSim 部分 (保持不变)
        noc_energy = 0.0
        avg_network_latency = 0.0

        if network_config_path and ram_cycles > 0:
            abs_net_cfg = os.path.join(self.project_root, network_config_path)
            
            req_count = 0
            if os.path.exists(base_trace_path):
                with open(base_trace_path, 'r') as f:
                    req_count = sum(1 for line in f if line.strip())
            
            real_inj = float(req_count) / float(ram_cycles * num_nodes) if num_nodes > 0 else 0.01
            if real_inj > 0.95: real_inj = 0.95
            if real_inj < 0.0001: real_inj = 0.0001
            
            self._update_booksim_config(abs_net_cfg, injection_rate=real_inj, sim_cycles=ram_cycles)
            
            cmd_book = [self.booksim_bin, abs_net_cfg]
            try:
                result = subprocess.run(cmd_book, capture_output=True, text=True)
                if result.returncode == 0:
                    power, lat = self._parse_booksim_output(result.stdout)
                    noc_energy = power * ram_cycles
                    avg_network_latency = lat
                    print(f"[DEBUG-BOOK] Power:{power}, Lat:{lat}, Cycles:{ram_cycles}")
            except Exception as e:
                print(f"[DEBUG-BOOK] Exception: {e}")

        return {
            'ram_cycles': ram_cycles,
            'noc_energy': noc_energy,
            'avg_network_latency': avg_network_latency
        }
