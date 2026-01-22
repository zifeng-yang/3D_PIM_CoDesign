import subprocess
import os
import re
import sys
import math

C_RED = '\033[91m'
C_YELLOW = '\033[93m'
C_END = '\033[0m'

class RamulatorWrapper:
    def __init__(self):
        self.project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        
        # [关键配置] 仿真器路径
        self.ramulator_bin = "/home/yangzifeng/ramulator-pim/ramulator/ramulator"
        self.booksim_bin   = "/home/yangzifeng/booksim2/src/booksim" 
        
        # 生成安全 tech file 供 BookSim 使用
        self.tech_file_path = self._find_or_create_tech_file()

        if not os.path.exists(self.ramulator_bin):
            print(f"{C_RED}[Wrapper Warning] Ramulator-PIM binary not found at: {self.ramulator_bin}{C_END}")
        if not os.path.exists(self.booksim_bin):
            print(f"{C_RED}[Wrapper Warning] BookSim binary not found at: {self.booksim_bin}{C_END}")

    def _find_or_create_tech_file(self):
        dummy_path = os.path.join(self.project_root, "configs", "ramulator", "safe_45nm.tech")
        if not os.path.exists(os.path.dirname(dummy_path)): os.makedirs(os.path.dirname(dummy_path), exist_ok=True)
        content = """
        Vdd = 1.0; R = 1.0; H_SRAM = 1; W_SRAM = 1;
        Cg_pwr = 1e-15; Cd_pwr = 1e-15; Cgdl = 1e-15; Cg = 1e-15; Cd = 1e-15;
        Cw_gnd = 1e-15; Cw_cpl = 1e-15;
        IoffSRAM = 1e-9; IoffP = 1e-9; IoffN = 1e-9;
        """
        with open(dummy_path, 'w') as f: f.write(content)
        return dummy_path

    def _parse_ramulator1_stats(self, stats_file):
        """解析 ramulator-pim 统计数据"""
        cycles = 0
        total_energy_pj = 0.0
        stats = {'act': 0, 'pre': 0, 'rd': 0, 'wr': 0}
        
        if not os.path.exists(stats_file): return 0, 0.0
        
        try:
            with open(stats_file, 'r') as f:
                for line in f:
                    parts = line.split()
                    if not parts: continue
                    name = parts[0]
                    
                    if "ramulator.dram_cycles" in name:
                        try: cycles = int(parts[1])
                        except: pass
                    
                    # 尝试直接读取 DRAMPower 能耗 (J -> pJ or pJ -> pJ)
                    if "ramulator.total_energy" in name or "energy_total_pj" in name:
                        try:
                            val = float(parts[1])
                            if val < 100.0: total_energy_pj = val * 1e12
                            else: total_energy_pj = val
                        except: pass
                        
                    # 统计指令用于保底计算
                    if "cmd_act" in name: stats['act'] += int(parts[1])
                    elif "cmd_read" in name: stats['rd'] += int(parts[1])
                    elif "cmd_write" in name: stats['wr'] += int(parts[1])
                    elif "cmd_pre" in name: stats['pre'] += int(parts[1])
        except: pass
        
        # 保底公式 (如果 DRAMPower 未启用)
        if total_energy_pj == 0 and cycles > 0:
            E_ACT, E_RD, E_WR = 3500.0, 1500.0, 1500.0
            P_BG = 100.0 # mW
            total_energy_pj = (stats['act'] * E_ACT) + (stats['rd'] * E_RD) + \
                              (stats['wr'] * E_WR) + (cycles * P_BG)
        
        return cycles, total_energy_pj

    def _parse_booksim_output(self, output_text):
        noc_power_w = 0.0
        accepted_rate = 0.0
        avg_hops = 0.0
        
        try:
            pm = re.search(r'Total Power\s*[:=]\s*([\d\.]+)', output_text, re.IGNORECASE)
            if pm: noc_power_w = float(pm.group(1))
            
            rm = re.search(r'Accepted flit rate average\s*=\s*([\d\.]+)', output_text, re.IGNORECASE)
            if rm: accepted_rate = float(rm.group(1))
            
            hm = re.search(r'Hops average\s*=\s*([\d\.]+)', output_text, re.IGNORECASE)
            if hm: avg_hops = float(hm.group(1))
        except: pass
        
        return avg_hops, noc_power_w, accepted_rate

    def _generate_booksim_config(self, cfg_path, injection_rate, packet_count, num_nodes):
        k_dim = int(math.ceil(math.sqrt(num_nodes)))
        if k_dim < 2: k_dim = 2
        content = f"""
topology = mesh;
k = {k_dim};
n = 2;
routing_function = dim_order;
num_vcs = 4;
vc_buf_size = 8;
wait_for_tail_credit = 1;
traffic = uniform;
injection_rate = {min(injection_rate, 0.5):.6f};
sim_count = {int(packet_count)};
warmup_periods = 0;
sim_type = latency;
sim_power = 1;
tech_file = {self.tech_file_path};
"""
        os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
        with open(cfg_path, 'w') as f: f.write(content)

    def run_simulation(self, config_rel_path, trace_rel_path, output_rel_dir, network_config_path=None, num_nodes=1):
        abs_config = os.path.join(self.project_root, config_rel_path)
        base_trace_path = os.path.join(self.project_root, trace_rel_path)
        stats_filename = os.path.basename(base_trace_path) + ".stats"
        abs_stats_path = os.path.join(self.project_root, output_rel_dir, stats_filename)
        booksim_log_path = os.path.join(self.project_root, output_rel_dir, "booksim.log")
        os.makedirs(os.path.dirname(abs_stats_path), exist_ok=True)

        # 1. Ramulator
        ram_cycles, ram_energy_pj = 0, 0.0
        if os.path.exists(self.ramulator_bin):
            cmd_ram = [self.ramulator_bin, abs_config, "--mode=dram", "--stats", abs_stats_path, base_trace_path]
            try:
                subprocess.run(cmd_ram, capture_output=True, text=True, timeout=30)
                if os.path.exists(abs_stats_path): 
                    ram_cycles, ram_energy_pj = self._parse_ramulator1_stats(abs_stats_path)
            except: pass

        # 2. BookSim
        noc_energy_pj, noc_cycles = 0.0, 0.0
        if ram_cycles > 0 and os.path.exists(self.booksim_bin):
            temp_cfg_name = f"booksim_generated_{os.path.basename(output_rel_dir)}.cfg"
            abs_net_cfg = os.path.join(self.project_root, output_rel_dir, temp_cfg_name)
            
            total_reqs = 1000
            try:
                with open(base_trace_path, 'r') as f: total_reqs = sum(1 for _ in f)
            except: pass
            
            real_inj = float(total_reqs) / float(ram_cycles * max(num_nodes, 1))
            self._generate_booksim_config(abs_net_cfg, real_inj, min(total_reqs, 5000), num_nodes)
            
            cmd_book = [self.booksim_bin, abs_net_cfg]
            try:
                with open(booksim_log_path, 'w') as log_f:
                    subprocess.run(cmd_book, stdout=log_f, stderr=subprocess.STDOUT, check=False, timeout=15)
                
                if os.path.exists(booksim_log_path):
                    with open(booksim_log_path, 'r') as log_f:
                        output_text = log_f.read()
                        avg_hops, noc_power_w, accepted_rate = self._parse_booksim_output(output_text)
                        
                        if noc_power_w > 0:
                            noc_energy_pj = noc_power_w * ram_cycles * 1000.0
                        
                        if accepted_rate > 0.0001:
                            noc_cycles = float(total_reqs) / (accepted_rate * max(num_nodes, 1))
                        else:
                            noc_cycles = float(total_reqs) * 10 
            except: pass

        return {
            'ram_cycles': ram_cycles, 
            'ram_energy_pj': ram_energy_pj, 
            'noc_energy_pj': noc_energy_pj, 
            'noc_cycles': noc_cycles
        }
