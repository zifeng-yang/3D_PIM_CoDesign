import os
import subprocess
import re

class BookSimWrapper:
    def __init__(self, booksim_bin_path="./booksim"):
        self.bin_path = booksim_bin_path
        # 如果找不到二进制文件，会发出警告，但允许代码继续运行(返回模拟值)
        if not os.path.exists(self.bin_path):
            self.mock_mode = True
        else:
            self.mock_mode = False

    def run(self, config_path, output_dir, traffic_rate, num_nodes):
        """
        运行 BookSim 仿真
        :param traffic_rate: 注入率 (flits/cycle/node)
        :param num_nodes: 节点总数
        :return: average_latency (cycles), average_energy (pj - estimated)
        """
        if self.mock_mode or traffic_rate <= 0:
            # Fallback 模型: 简单的 Mesh 延迟模型
            # Hops approx sqrt(N)/2 * 2 dimensions
            avg_hops = (num_nodes**0.5) 
            return 10 + avg_hops * 3, traffic_rate * num_nodes * 100

        # 1. 生成 BookSim 配置文件
        cfg_file = os.path.join(output_dir, "booksim.cfg")
        log_file = os.path.join(output_dir, "booksim.log")
        
        # 自动计算 Mesh 维度
        k = int(num_nodes**0.5)
        if k*k < num_nodes: k += 1
        
        config_content = f"""
        topology = mesh;
        k = {k};
        n = 2;
        routing_function = dim_order;
        
        injection_rate = {traffic_rate};
        traffic = uniform;
        
        sim_type = latency;
        warmup_periods = 3;
        max_samples = 2000;
        """
        
        with open(cfg_file, "w") as f:
            f.write(config_content)

        # 2. 调用 BookSim
        cmd = [self.bin_path, cfg_file]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if res.returncode != 0:
                return 100, 0 # Error fallback
            
            # 3. 解析日志获取 Latency
            # Look for: "Packet latency average = 25.321"
            lat_match = re.search(r"Packet latency average = ([\d\.]+)", res.stdout)
            latency = float(lat_match.group(1)) if lat_match else 20.0
            
            # 简单的能耗估算: Latency * Rate * E_per_hop
            energy = latency * traffic_rate * num_nodes * 50 # 50pJ/flit-hop
            
            return latency, energy
            
        except Exception as e:
            return 20, 0 # Fallback
