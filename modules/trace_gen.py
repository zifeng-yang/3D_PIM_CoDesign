# 文件路径: modules/trace_gen.py

import os
import random
import math

class TraceGenerator:
    def __init__(self, output_path="output/dram.trace"):
        self.default_output_path = output_path
        # Ramulator 通常读取 CPU traces，格式通常为: <0/1 (read/write)> <address>
        # 对于 PIM 仿真，我们主要关注访存密度和模式

    def generate_structured_trace(self, timeloop_stats, mode="baseline", output_path=None):
        """
        基于 Timeloop 的统计数据生成 Ramulator 可用的 Trace 文件。
        
        Args:
            timeloop_stats (dict): 包含 'cycles', 'energy_pj' 等数据的字典
            mode (str): 'baseline' 或 'atomic'，决定访存模式
            output_path (str): 输出文件路径
            
        Returns:
            (str, int): 生成的 trace 文件路径, 生成的请求总数
        """
        if output_path is None:
            output_path = self.default_output_path
            
        # 确保父目录存在
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        # 1. 估算访存量 (如果没有精确的 DRAM 访问计数，基于周期估算)
        # 注意：理想情况下应从 timeloop-mapper.stats.txt 解析具体的 DRAM 读写数
        # 这里使用简化模型：假设每 N 个周期产生一个 DRAM 请求
        total_cycles = timeloop_stats.get('cycles', 10000)
        
        # 访存强度 (Intensity): Atomic 模式通常具有更高的局部性（较少的 DRAM 访问）
        if mode == "atomic":
            access_probability = 0.05 # 5% 的周期有 DRAM 请求
        else:
            access_probability = 0.15 # 15% 的周期有 DRAM 请求 (Baseline 较差)

        num_reqs = int(total_cycles * access_probability)
        # 限制最大请求数以防仿真时间过长
        num_reqs = min(num_reqs, 50000) 

        # 2. 生成 Trace 内容
        # 格式: <0/1> <hex_address>
        # 0: Read, 1: Write
        with open(output_path, 'w') as f:
            current_addr = 0x100000
            for _ in range(num_reqs):
                is_write = 1 if random.random() < 0.3 else 0 # 30% 写，70% 读
                
                # 地址模式生成
                if mode == "atomic":
                    # Atomic 模式：更规则、流式的访问 (Stride Access)
                    stride = 64 # 64 bytes cache line
                    current_addr = (current_addr + stride) % 0xFFFFFFFF
                else:
                    # Baseline 模式：可能包含更多随机跳跃
                    if random.random() < 0.2:
                        current_addr = random.randint(0, 0xFFFFFFFF) & 0xFFFFFFC0 # Align to 64B
                    else:
                        current_addr = (current_addr + 64) % 0xFFFFFFFF
                
                f.write(f"{is_write} 0x{current_addr:X}\n")

        # Ramulator 有时需要额外的 .trace 后缀或特定命名，这里返回生成的路径
        print(f"  [TraceGen] Generated {num_reqs} requests for {mode} mode at {output_path}")
        return output_path, num_reqs
