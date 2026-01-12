import subprocess
import os
import re
import glob

class RamulatorWrapper:
    def __init__(self):
        self.project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        
        # [配置] 请确保路径正确
        self.ramulator_bin = "/home/yangzifeng/ramulator/ramulator"
        self.booksim_bin   = "/home/yangzifeng/ramulator-pim/workspace/ramulator-pim/booksim2/src/booksim"
        
        # [自动搜索] 查找 BookSim 的 tech 文件
        self.tech_file_path = self._find_or_create_tech_file()
        if self.tech_file_path:
            print(f"[Init] Using BookSim tech file: {self.tech_file_path}")

    def _find_or_create_tech_file(self):
        """
        查找现有的 .tech 文件，如果找不到，则创建一个临时的 dummy_22nm.tech
        确保 sim_power = 1 始终可用。
        """
        if not os.path.exists(self.booksim_bin):
            return None
            
        bin_dir = os.path.dirname(self.booksim_bin)
        # 1. 尝试搜索现有文件
        search_paths = [
            os.path.join(bin_dir, "tech"),
            os.path.join(bin_dir, "../tech"),
            os.path.join(bin_dir, "examples"),
            os.path.join(bin_dir, "../../tech")
        ]
        
        for p in search_paths:
            if os.path.exists(p):
                for tech in ["22nm.tech", "45nm.tech"]:
                    target = os.path.join(p, tech)
                    if os.path.exists(target):
                        return os.path.abspath(target)
        
        # 2. 如果没找到，创建一个默认的 22nm tech 文件
        dummy_tech_path = os.path.join(self.project_root, "configs", "ramulator", "dummy_22nm.tech")
        if not os.path.exists(os.path.dirname(dummy_tech_path)):
            os.makedirs(os.path.dirname(dummy_tech_path), exist_ok=True)
            
        # 写入标准的 22nm 参数 (参考 BookSim 官方)
        tech_content = """
        vd = 0.9;
        L = 0.022;
        W = 0.022;
        IoffN = 1.6e-7;
        IoffP = 1.6e-7;
        Vdd = 0.9;
        Area = 0.0;
        """
        with open(dummy_tech_path, 'w') as f:
            f.write(tech_content)
        
        print(f"[Init] Created dummy tech file at: {dummy_tech_path}")
        return dummy_tech_path

    def _parse_ramulator1_stats(self, stats_file):
        """解析 Ramulator 1.0 生成的标准 .stats 文件"""
        cycles = 0
        if not os.path.exists(stats_file):
            print(f"[DEBUG-RAM] Stats file NOT FOUND at: {stats_file}")
            return 0
            
        try:
            with open(stats_file, 'r') as f:
                for line in f:
                    if "ramulator.dram_cycles" in line:
                        parts = line.split()
                        if len(parts) > 1:
                            try:
                                cycles = int(parts[1])
                            except ValueError:
                                pass
                            break
        except Exception as e:
            print(f"[DEBUG-RAM] Error parsing stats: {e}")
        
        print(f"[DEBUG-RAM] Parsed DRAM Cycles: {cycles}")
        return cycles

    def _parse_booksim_output(self, output_text):
        """解析 BookSim 输出，增强鲁棒性"""
        noc_power = 0.0
        avg_latency = 0.0
        
        # 1. 解析 Latency (支持多种格式)
        # Type A: "Average packet latency = 12.345"
        # Type B: "Packet latency average = 12.345"
        lat_match = re.search(r'(?:average packet latency|packet latency average|network latency)\s*=\s*([\d\.]+)', output_text, re.IGNORECASE)
        if lat_match: 
            avg_latency = float(lat_match.group(1))
        
        # 2. 解析 Power
        power_match = re.search(r'Total Power\s*=\s*([\d\.]+)', output_text, re.IGNORECASE)
        if power_match: 
            noc_power = float(power_match.group(1)) * 1000.0
            
        return noc_power, avg_latency

    def _update_booksim_config(self, cfg_path, injection_rate, packet_count):
        """更新 BookSim 配置: 强制注入 tech_file"""
        if not os.path.exists(cfg_path): return
        
        with open(cfg_path, 'r') as f: 
            lines = f.readlines()
        
        new_lines = []
        keys_found = {'injection_rate': False, 'sim_count': False, 'sim_power': False, 'tech_file': False}

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("injection_rate"):
                new_lines.append(f"injection_rate = {injection_rate:.6f};\n")
                keys_found['injection_rate'] = True
            elif stripped.startswith("sim_count"):
                new_lines.append(f"sim_count = {int(packet_count)};\n")
                keys_found['sim_count'] = True
            elif stripped.startswith("sim_power"):
                new_lines.append("sim_power = 1;\n")
                keys_found['sim_power'] = True
            elif stripped.startswith("tech_file"):
                new_lines.append(f"tech_file = {self.tech_file_path};\n")
                keys_found['tech_file'] = True
            else:
                new_lines.append(line)
        
        if not keys_found['injection_rate']: new_lines.append(f"injection_rate = {injection_rate:.6f};\n")
        if not keys_found['sim_count']: new_lines.append(f"sim_count = {int(packet_count)};\n")
        if not keys_found['sim_power']: new_lines.append("sim_power = 1;\n")
        if not keys_found['tech_file'] and self.tech_file_path: new_lines.append(f"tech_file = {self.tech_file_path};\n")

        with open(cfg_path, 'w') as f: 
            f.writelines(new_lines)

    def run_simulation(self, config_rel_path, trace_rel_path, output_rel_dir, network_config_path=None, num_nodes=1):
        print(f"\n--- [Ramulator 1.0 Wrapper] Start Simulation ---")
        
        abs_config = os.path.join(self.project_root, config_rel_path)
        base_trace_path = os.path.join(self.project_root, trace_rel_path)
        
        trace_basename = os.path.basename(base_trace_path)
        stats_filename = trace_basename + ".stats"
        abs_stats_path = os.path.join(self.project_root, output_rel_dir, stats_filename)
        booksim_log_path = os.path.join(self.project_root, output_rel_dir, "booksim.log")

        os.makedirs(os.path.dirname(abs_stats_path), exist_ok=True)

        # === 1. Run Ramulator ===
        cmd_ram = [self.ramulator_bin, abs_config, "--mode=dram", "--stats", abs_stats_path, base_trace_path]

        ram_cycles = 0
        try:
            subprocess.run(cmd_ram, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
            if os.path.exists(abs_stats_path):
                ram_cycles = self._parse_ramulator1_stats(abs_stats_path)
            else:
                print(f"[DEBUG-RAM] Warning: Stats file missing.")
        except subprocess.TimeoutExpired:
            print("[DEBUG-RAM] Error: Ramulator Timed Out!")
            return {'ram_cycles': 0, 'noc_energy': 0.0, 'avg_network_latency': 0.0}
        except subprocess.CalledProcessError as e:
            print(f"[DEBUG-RAM] CRASHED. Code: {e.returncode}")
            return {'ram_cycles': 0, 'noc_energy': 0.0, 'avg_network_latency': 0.0}

        # === 2. Run BookSim Co-Simulation ===
        noc_energy = 0.0
        avg_network_latency = 0.0

        if network_config_path and ram_cycles > 0:
            if not os.path.exists(self.booksim_bin):
                print(f"[DEBUG-BOOK] Binary not found. Skipping.")
            else:
                abs_net_cfg = os.path.join(self.project_root, network_config_path)
                
                req_count = 0
                if os.path.exists(base_trace_path):
                    try:
                        with open(base_trace_path, 'r') as f: req_count = sum(1 for _ in f)
                    except: req_count = 1000

                real_inj = float(req_count) / float(ram_cycles * max(num_nodes, 1))
                if real_inj < 0.0001: real_inj = 0.0001
                
                # 保护：注入率过高
                HARD_LIMIT_INJ = 0.25
                if real_inj > HARD_LIMIT_INJ:
                    print(f"[DEBUG-BOOK] Injection rate {real_inj:.4f} > {HARD_LIMIT_INJ}. Skipping & penalizing.")
                    return {'ram_cycles': ram_cycles, 'noc_energy': 1e10, 'avg_network_latency': 10000.0}
                
                sample_packet_count = min(req_count, 10000)
                if sample_packet_count < 1000: sample_packet_count = 1000
                
                self._update_booksim_config(abs_net_cfg, injection_rate=real_inj, packet_count=sample_packet_count)
                
                cmd_book = [self.booksim_bin, abs_net_cfg]
                
                try:
                    with open(booksim_log_path, 'w') as log_f:
                        subprocess.run(cmd_book, stdout=log_f, stderr=subprocess.STDOUT, check=True, timeout=10)
                    
                    with open(booksim_log_path, 'r') as log_f:
                        output_text = log_f.read()
                        power, lat = self._parse_booksim_output(output_text)
                        
                        # [诊断] 如果 Latency 还是 0，打印日志以便排查
                        if lat == 0.0:
                            print(f"[DEBUG-BOOK] WARNING: Latency is 0.00. Dumping log tail:")
                            print("--- BookSim Output Tail ---")
                            print(output_text[-500:]) 
                            print("-------------------------")
                        
                        noc_energy = power * ram_cycles
                        avg_network_latency = lat
                        print(f"[DEBUG-BOOK] Done. Power:{power:.2f}, AvgLat:{lat:.2f}, TotalE:{noc_energy:.2e}")
                        
                except subprocess.TimeoutExpired:
                    print(f"[DEBUG-BOOK] Timeout! Network Congested.")
                    avg_network_latency = 5000.0
                    noc_energy = 5e9
                except subprocess.CalledProcessError:
                    print(f"[DEBUG-BOOK] CRASHED/Unstable.")
                    avg_network_latency = 8000.0
                    noc_energy = 8e9

        return {
            'ram_cycles': ram_cycles,
            'noc_energy': noc_energy,
            'avg_network_latency': avg_network_latency
        }
