# 文件路径: modules/trace_gen.py

<<<<<<< HEAD
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
=======
import random
import os

class TraceGenerator:
    def __init__(self, default_path="dram.trace"):
        self.default_path = default_path

    def generate_structured_trace(self, tl_stats, mode='baseline', output_path=None):
        """
        基于统计数据生成结构化 Trace，模拟不同的数据调度策略。
        
        Args:
            tl_stats: Timeloop 返回的统计字典 (包含 total_accesses 等信息)
            mode: 'baseline' (NicePIM) 或 'atomic' (Proposed)
        """
        if output_path is None:
            output_path = self.default_path
        
        # 处理 .0 后缀 (Ramulator 要求)
        real_file_path = output_path + ".0" if not output_path.endswith(".0") else output_path
        base_path = output_path[:-2] if output_path.endswith(".0") else output_path
        
        # 从统计中估算访问量 (如果没有精确值，给一个默认值)
        # 假设每次 DRAM 访问对应一次 Last Level Buffer 的缺失
        # 这里为了演示，基于 cycle 数估算一个访问密度
        cycles = tl_stats.get('cycles', 100000)
        num_reqs = int(cycles * 0.1) # 假设 10% 的指令产生 DRAM 访问
        num_reqs = min(max(num_reqs, 1000), 50000) # 限制 Trace 长度

        print(f"[TraceGen] Generating {mode} trace with {num_reqs} requests...")

        with open(real_file_path, 'w') as f:
            pc_addr = 0x400000
            base_data_addr = 0x10000000
            
            # === 核心差异逻辑 ===
            if mode == 'atomic':
                # [Atomic Mode] 高空间局部性 (Spatial Locality)
                # 模拟: 读取一个原子块 (连续 64-256 Bytes)，处理完再读下一个
                # 模式: A, A+64, A+128 ... (Sequential)
                stride_prob = 0.1  # 只有 10% 的概率跳跃到新地址
                locality_window = 64 # 字节
            else:
                # [Baseline Mode] 跨步访问 (Strided Access)
                # 模拟: 传统 Tiling 下，访问 input channel 后跳跃到下一个位置
                # 模式: A, A+Stride, A+2*Stride ...
                stride_prob = 0.8  # 80% 的概率跳跃 (Row Buffer Miss 高)
                locality_window = 1024 * 4 # 大跳跃

            current_addr = base_data_addr
            
            for _ in range(num_reqs):
                # 1. 写入 CPU 指令 (模拟计算流)
                f.write(f"0 0 - I {pc_addr} 4\n")
                
                # 2. 写入 DRAM 请求
                is_write = 'S' if random.random() < 0.3 else 'L'
                
                # 生成地址
                if random.random() < stride_prob:
                    # 跳跃 (Stride)
                    jump = random.randint(1, 16) * 64 
                    current_addr = (current_addr + jump) % (1024*1024*1024) # 1GB Wrap
                else:
                    # 连续 (Sequential)
                    current_addr += 64
                
                # 保持地址对齐
                aligned_addr = (current_addr // 64) * 64 + base_data_addr
                
                f.write(f"0 0 0 {is_write} {aligned_addr} 64\n")
                pc_addr += 4

        return base_path, num_reqs

    # 兼容旧接口
    def generate_from_stats(self, tl_stats, scaling_factor=1.0):
        return self.generate_structured_trace(tl_stats, mode='baseline')
>>>>>>> d2ec8543f2de6810717e0b3d892adc03f09692e8
