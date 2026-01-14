import os
import random

class TraceGenerator:
    def __init__(self, output_path="output/dram.trace"):
        self.output_path = output_path
        os.makedirs(os.path.dirname(self.output_path), exist_ok=True)

    def generate_structured_trace(self, timeloop_results, mode="baseline", output_path=None, stats_path=None):
        if output_path:
            self.output_path = output_path
            os.makedirs(os.path.dirname(self.output_path), exist_ok=True)

        dram_reads = timeloop_results.get('dram_reads', 0)
        dram_writes = timeloop_results.get('dram_writes', 0)
        
        if dram_reads + dram_writes == 0: dram_reads = 100

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
        max_addr = 0x80000000 
        current_addr = base_addr
        
        for _ in range(scaled_reads):
            lines.append(f"{hex(current_addr)} R\n")
            current_addr = (current_addr + stride) % max_addr
            if random.random() < 0.05: current_addr = (current_addr + 0x10000) % max_addr
            
        for _ in range(scaled_writes):
            lines.append(f"{hex(current_addr)} W\n")
            current_addr = (current_addr + stride) % max_addr
            if random.random() < 0.05: current_addr = (current_addr + 0x10000) % max_addr
            
        random.shuffle(lines)
        
        with open(self.output_path, 'w') as f:
            f.writelines(lines)
            
        # [静默模式] 移除打印
        # print(f"[TraceGen] Generated {len(lines)} reqs ...")
        return self.output_path, len(lines)
