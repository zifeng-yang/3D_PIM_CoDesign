import random
import os

class TraceGenerator:
    def __init__(self, trace_output_path="dram.trace"):
        # 处理 .0 后缀
        if not trace_output_path.endswith(".0"):
            self.real_file_path = trace_output_path + ".0"
            self.base_path = trace_output_path
        else:
            self.real_file_path = trace_output_path
            self.base_path = trace_output_path[:-2]

    def generate_from_stats(self, timeloop_stats, scaling_factor=0.01):
        # 1. 设定足够的行数，确保 DRAM 预热
        num_lines = 10000 
        
        print(f"[TraceGen] Generating {num_lines} ZSim requests (I + L/S pairs)...")

        # 2. 生成符合 ZSim 规范的 Trace
        # 官方样本结构:
        # 0 0 - I 4197020 64       <-- 指令行 (Instruction)
        # 0 0 0 L 140737488348000 8 <-- 访存行 (Load/Store)
        
        with open(self.real_file_path, 'w') as f:
            # 模拟 PC 指针
            pc_addr = 4197000
            
            for _ in range(num_lines):
                # 生成随机内存地址 (模拟 4GB 空间, 64字节对齐)
                mem_addr = random.randint(0, 1024 * 1024 * 16) * 64 + 0x10000000
                
                # 随机读写
                rw = 'L' if random.random() < 0.7 else 'S'
                
                # --- 关键修正：先写入指令行 ---
                # 格式: <Core> <Thread> <Dep> <Type> <Addr> <Size>
                # Dep 为 '-' 表示无依赖，I 表示指令
                f.write(f"0 0 - I {pc_addr} 4\n")
                
                # --- 然后写入访存行 ---
                # Dep 为 '0'，表示依赖上一条指令
                f.write(f"0 0 0 {rw} {mem_addr} 64\n")
                
                pc_addr += 4 # PC 指针自增
        
        return self.base_path, num_lines
