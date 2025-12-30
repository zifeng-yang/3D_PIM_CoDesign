# 文件路径: modules/trace_gen.py

import os
import re
import math

class TraceGenerator:
    def __init__(self, default_output_path="output/dram.trace"):
        self.default_output_path = default_output_path
        self.CL_SIZE = 64        
        self.BURST_SIZE = 16
        self.ADDR_INPUT  = 0x00000000
        self.ADDR_WEIGHT = 0x40000000
        self.ADDR_OUTPUT = 0x80000000

    def _parse_dram_stats(self, stats_file):
        """解析 Timeloop 真实的访存次数"""
        reads = 0
        writes = 0
        
        if not os.path.exists(stats_file):
            print(f"  [TraceGen DEBUG] ❌ File not found: {stats_file}")
            return 1000, 100
            
        try:
            with open(stats_file, 'r') as f:
                content = f.read()
            
            # 搜索 DRAM/MainMemory/Offchip 块
            dram_section = re.search(r'===\s*(DRAM|MainMemory|Offchip)\s*===(.*?)(?:Level|\Z)', content, re.DOTALL | re.IGNORECASE)
            
            if dram_section:
                text = dram_section.group(2)
                # 兼容 Scalar reads 或 Reads
                r_match = re.search(r'(?:Scalar reads|Reads)\s*(?:\(per-instance\))?\s*:\s+(\d+)', text, re.IGNORECASE)
                w_match = re.search(r'(?:Scalar updates|Updates|Writes)\s*(?:\(per-instance\))?\s*:\s+(\d+)', text, re.IGNORECASE)
                
                if r_match: reads = int(r_match.group(1))
                if w_match: writes = int(w_match.group(1))
            else:
                print(f"  [TraceGen DEBUG] ⚠️ '=== DRAM ===' section not found in stats.")
                
        except Exception as e:
            print(f"  [TraceGen DEBUG] Exception parsing stats: {e}")
        
        # [Precision Fix] Timeloop(32B) -> Ramulator(64B)
        reads = math.ceil(reads / 2)
        writes = math.ceil(writes / 2)
        
        return reads, writes

    def generate_structured_trace(self, timeloop_results, mode="baseline", output_path=None, stats_path=None):
        """
        生成 Trace。
        [New Arg] stats_path: 显式指定统计文件路径，解决路径不一致问题。
        """
        if output_path is None: output_path = self.default_output_path
        
        # [FIX] 优先使用传入的 stats_path，否则回退到 output_path 同级目录
        if stats_path:
            stats_file = stats_path
        else:
            stats_dir = os.path.dirname(output_path)
            stats_file = os.path.join(stats_dir, "timeloop-mapper.stats.txt")
        
        real_reads, real_writes = self._parse_dram_stats(stats_file)
        total_real = real_reads + real_writes
        
        # 限制 Trace 大小
        target_lines = min(total_real, 50000)
        reqs_per_tile = self.BURST_SIZE * 3 
        num_tiles = max(1, int(target_lines // reqs_per_tile))
        
        with open(output_path, 'w') as f:
            ptr_w, ptr_i, ptr_o = self.ADDR_WEIGHT, self.ADDR_INPUT, self.ADDR_OUTPUT
            stride = self.CL_SIZE
            bank_jump = 0 if mode == "atomic" else (4096 + 64)
            
            for _ in range(num_tiles):
                # Weights
                for _ in range(self.BURST_SIZE):
                    f.write(f"0 0x{ptr_w:X}\n"); ptr_w += stride
                if mode == "baseline": ptr_w += bank_jump
                # Inputs
                for _ in range(self.BURST_SIZE):
                    f.write(f"0 0x{ptr_i:X}\n"); ptr_i += stride
                if mode == "baseline": ptr_i += bank_jump
                # Outputs
                if real_writes > 0:
                    wb = max(1, int(self.BURST_SIZE * (real_writes / (real_reads+1))))
                    for _ in range(wb):
                        f.write(f"1 0x{ptr_o:X}\n"); ptr_o += stride
                    if mode == "baseline": ptr_o += bank_jump

        print(f"  [TraceGen] Mode: {mode.upper()} | Real Reqs: {real_reads}R/{real_writes}W | Sim Tiles: {num_tiles}")
        return output_path, total_real
