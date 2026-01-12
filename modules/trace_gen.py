import os
import random

class TraceGenerator:
    def __init__(self, output_path="output/dram.trace"):
        self.output_path = output_path
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)

    def generate_structured_trace(self, timeloop_results, mode="baseline", output_path=None, stats_path=None):
        """
        [Ramulator 1.0 标准兼容版]
        生成标准的 Memory Trace，用于 --mode=dram 模式。
        
        格式: <HexAddress> <R/W>
        示例: 0x12345680 R
        说明: 这是 Ramulator 官方推荐的内存 Trace 格式，避免了 CPU 模式下的解析歧义。
        """
        if output_path:
            self.output_path = output_path
            os.makedirs(os.path.dirname(self.output_path), exist_ok=True)

        dram_reads = timeloop_results.get('dram_reads', 0)
        dram_writes = timeloop_results.get('dram_writes', 0)
        
        # 兜底逻辑：如果没有访存，生成少量请求以防止仿真器报错或除零错误
        if dram_reads + dram_writes == 0:
            dram_reads = 100

        # 缩放 Trace 大小，防止仿真时间过长
        MAX_TRACE_LINES = 100000 
        total_accesses = dram_reads + dram_writes
        scale_factor = 1.0
        if total_accesses > MAX_TRACE_LINES:
            scale_factor = MAX_TRACE_LINES / total_accesses
            
        scaled_reads = int(dram_reads * scale_factor)
        scaled_writes = int(dram_writes * scale_factor)
        
        lines = []
        base_addr = 0x400000 
        stride = 64 
        max_addr = 0x80000000 # 2GB
        current_addr = base_addr
        
        # 生成读请求 (R)
        for _ in range(scaled_reads):
            lines.append(f"{hex(current_addr)} R\n")
            # 简单的地址跳跃模拟，增加随机性
            current_addr = (current_addr + stride) % max_addr
            if random.random() < 0.05: current_addr = (current_addr + 0x10000) % max_addr
            
        # 生成写请求 (W)
        for _ in range(scaled_writes):
            lines.append(f"{hex(current_addr)} W\n")
            current_addr = (current_addr + stride) % max_addr
            if random.random() < 0.05: current_addr = (current_addr + 0x10000) % max_addr
            
        # 打乱读写顺序，模拟真实混合访问
        random.shuffle(lines)
        
        with open(self.output_path, 'w') as f:
            f.writelines(lines)
            
        print(f"[TraceGen] Generated {len(lines)} reqs (Reads:{scaled_reads}, Writes:{scaled_writes}) at {self.output_path}")
        return self.output_path, len(lines)
