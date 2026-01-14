import subprocess
import os
import re
import glob

class RamulatorWrapper:
    def __init__(self):
        self.project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.ramulator_bin = "/home/yangzifeng/ramulator/ramulator"
        self.booksim_bin   = "/home/yangzifeng/ramulator-pim/workspace/ramulator-pim/booksim2/src/booksim"
        self.tech_file_path = self._find_or_create_tech_file()

    def _find_or_create_tech_file(self):
        if not os.path.exists(self.booksim_bin): return None
        bin_dir = os.path.dirname(self.booksim_bin)
        search_paths = [
            os.path.join(bin_dir, "power"), os.path.join(bin_dir, "../power"),
            os.path.join(bin_dir, "tech"), os.path.join(bin_dir, "../tech"),
            os.path.join(bin_dir, "examples"), os.path.join(bin_dir, "../../tech")
        ]
        for p in search_paths:
            if os.path.exists(p):
                if os.path.exists(os.path.join(p, "techfile.txt")): return os.path.abspath(os.path.join(p, "techfile.txt"))
                for tech in ["22nm.tech", "32nm.tech", "45nm.tech"]:
                    target = os.path.join(p, tech)
                    if os.path.exists(target): return os.path.abspath(target)
                techs = glob.glob(os.path.join(p, "*.tech"))
                if techs: return os.path.abspath(techs[0])
        
        dummy_tech_path = os.path.join(self.project_root, "configs", "ramulator", "official_32nm.tech")
        if not os.path.exists(os.path.dirname(dummy_tech_path)):
            os.makedirs(os.path.dirname(dummy_tech_path), exist_ok=True)
        
        # 纯净版 Tech 文件 (无 Area 字段)
        tech_content = """
H_INVD2=8; W_INVD2=3; H_DFQD1=8; W_DFQD1=16; H_ND2D1=8; W_ND2D1=3; H_SRAM=8; W_SRAM=6;
Vdd=0.9; R=606.321; IoffSRAM=0.00000032; IoffP=0.00000102; IoffN=0.00000102;
Cg_pwr=0.000000000000000534; Cd_pwr=0.000000000000000267; Cgdl=0.0000000000000001068;
Cg=0.000000000000000534; Cd=0.000000000000000267; LAMBDA=0.016; MetalPitch=0.000080;
Rw=0.720044; Cw_gnd=0.000000000000267339; Cw_cpl=0.000000000000267339; wire_length=2.0;
"""
        with open(dummy_tech_path, 'w') as f: f.write(tech_content)
        return dummy_tech_path

    def _parse_ramulator1_stats(self, stats_file):
        cycles = 0
        if not os.path.exists(stats_file): return 0
        try:
            with open(stats_file, 'r') as f:
                for line in f:
                    if "ramulator.dram_cycles" in line:
                        parts = line.split()
                        if len(parts) > 1:
                            try: cycles = int(parts[1])
                            except ValueError: pass
                            break
        except: pass
        return cycles

    def _parse_booksim_output(self, output_text):
        noc_power = 0.0
        avg_latency = 0.0
        lat_match = re.search(r'(?:average packet latency|packet latency average|network latency)\s*[:=]\s*([\d\.]+)', output_text, re.IGNORECASE)
        if lat_match: avg_latency = float(lat_match.group(1))
        power_match = re.search(r'Total Power\s*[:=]\s*([\d\.]+)', output_text, re.IGNORECASE)
        if power_match: noc_power = float(power_match.group(1)) * 1000.0
        return noc_power, avg_latency

    def _update_booksim_config(self, cfg_path, injection_rate, packet_count):
        if not os.path.exists(cfg_path): return
        with open(cfg_path, 'r') as f: lines = f.readlines()
        new_lines = []
        keys_found = {'injection_rate': False, 'sim_count': False, 'sim_power': False, 'tech_file': False}
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("injection_rate"):
                new_lines.append(f"injection_rate = {injection_rate:.6f};\n"); keys_found['injection_rate'] = True
            elif stripped.startswith("sim_count"):
                new_lines.append(f"sim_count = {int(packet_count)};\n"); keys_found['sim_count'] = True
            elif stripped.startswith("sim_power"):
                new_lines.append("sim_power = 1;\n"); keys_found['sim_power'] = True
            elif stripped.startswith("tech_file"):
                new_lines.append(f"tech_file = {self.tech_file_path};\n"); keys_found['tech_file'] = True
            else: new_lines.append(line)
        if not keys_found['injection_rate']: new_lines.append(f"injection_rate = {injection_rate:.6f};\n")
        if not keys_found['sim_count']: new_lines.append(f"sim_count = {int(packet_count)};\n")
        if not keys_found['sim_power']: new_lines.append("sim_power = 1;\n")
        if not keys_found['tech_file'] and self.tech_file_path: new_lines.append(f"tech_file = {self.tech_file_path};\n")
        with open(cfg_path, 'w') as f: f.writelines(new_lines)

    def run_simulation(self, config_rel_path, trace_rel_path, output_rel_dir, network_config_path=None, num_nodes=1):
        # 彻底静默，无 print
        abs_config = os.path.join(self.project_root, config_rel_path)
        base_trace_path = os.path.join(self.project_root, trace_rel_path)
        trace_basename = os.path.basename(base_trace_path)
        stats_filename = trace_basename + ".stats"
        abs_stats_path = os.path.join(self.project_root, output_rel_dir, stats_filename)
        booksim_log_path = os.path.join(self.project_root, output_rel_dir, "booksim.log")
        os.makedirs(os.path.dirname(abs_stats_path), exist_ok=True)

        # 1. Run Ramulator
        cmd_ram = [self.ramulator_bin, abs_config, "--mode=dram", "--stats", abs_stats_path, base_trace_path]
        ram_cycles = 0
        try:
            subprocess.run(cmd_ram, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)
            if os.path.exists(abs_stats_path): ram_cycles = self._parse_ramulator1_stats(abs_stats_path)
        except subprocess.TimeoutExpired: return {'ram_cycles': 0, 'noc_energy': 0.0, 'avg_network_latency': 0.0}
        except subprocess.CalledProcessError: return {'ram_cycles': 0, 'noc_energy': 0.0, 'avg_network_latency': 0.0}

        # 2. Run BookSim
        noc_energy = 0.0
        avg_network_latency = 0.0
        if network_config_path and ram_cycles > 0:
            if not os.path.exists(self.booksim_bin): return {'ram_cycles': ram_cycles, 'noc_energy': 0, 'avg_network_latency': 0}
            abs_net_cfg = os.path.join(self.project_root, network_config_path)
            req_count = 0
            if os.path.exists(base_trace_path):
                try:
                    with open(base_trace_path, 'r') as f: req_count = sum(1 for _ in f)
                except: req_count = 1000
            real_inj = float(req_count) / float(ram_cycles * max(num_nodes, 1))
            if real_inj < 0.0001: real_inj = 0.0001
            if real_inj > 0.25: return {'ram_cycles': ram_cycles, 'noc_energy': 1e10, 'avg_network_latency': 10000.0}
            
            sample_packet_count = min(req_count, 10000)
            if sample_packet_count < 1000: sample_packet_count = 1000
            self._update_booksim_config(abs_net_cfg, injection_rate=real_inj, packet_count=sample_packet_count)
            cmd_book = [self.booksim_bin, abs_net_cfg]
            try:
                with open(booksim_log_path, 'w') as log_f:
                    subprocess.run(cmd_book, stdout=log_f, stderr=subprocess.STDOUT, check=True, timeout=20)
                with open(booksim_log_path, 'r') as log_f:
                    output_text = log_f.read()
                    power, lat = self._parse_booksim_output(output_text)
                    noc_energy = power * ram_cycles
                    avg_network_latency = lat
            except subprocess.TimeoutExpired:
                avg_network_latency = 5000.0; noc_energy = 5e9
            except subprocess.CalledProcessError:
                avg_network_latency = 8000.0; noc_energy = 8e9

        return {'ram_cycles': ram_cycles, 'noc_energy': noc_energy, 'avg_network_latency': avg_network_latency}
