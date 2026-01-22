import os
import re

class TimeloopParser:
    def __init__(self, stats_file_path):
        self.stats_file = stats_file_path

    def parse(self):
        """
        解析 timeloop-mapper.stats.txt
        返回: 
            - cycles
            - energy_pj (排除 DRAM 后的逻辑能耗)
            - area_mm2
            - dram_accesses (用于传给 Ramulator)
        """
        stats = {
            'cycles': 0,
            'energy_pj': 0.0,
            'area_mm2': 0.0,
            'dram_accesses': 0
        }

        if not os.path.exists(self.stats_file):
            return stats

        with open(self.stats_file, 'r') as f:
            content = f.read()

        # 1. 解析 Cycles
        # 匹配: Cycles: 129024
        cyc_match = re.search(r'^Cycles:\s+(\d+)', content, re.MULTILINE)
        if cyc_match:
            stats['cycles'] = int(cyc_match.group(1))

        # 2. 解析 Area
        # 优先读取 Summary Stats 中的 Area
        area_match = re.search(r'^Area:\s+([\d\.]+)\s+mm\^2', content, re.MULTILINE)
        if area_match:
            stats['area_mm2'] = float(area_match.group(1))
        
        # 如果 Summary Area 为 0 (常见于 Accelergy 某些版本)，则累加各 Level 的 Area
        if stats['area_mm2'] == 0:
            total_area_um2 = 0.0
            # 匹配: Area (total)            : 288467.97 um^2
            area_matches = re.findall(r'Area \(total\)\s+:\s+([\d\.]+)\s+um\^2', content)
            for a in area_matches:
                total_area_um2 += float(a)
            stats['area_mm2'] = total_area_um2 / 1e6 # um2 -> mm2

        # 3. [关键] 解析 SEDRAM/DRAM 访问次数
        # 查找 === SEDRAM === 下面的 Total scalar accesses
        # 逻辑：找到 SEDRAM 标题，然后找它下面的 Accesses
        dram_section = re.search(r'===\s+(SEDRAM|DRAM)\s+===.*?(?====|$)', content, re.DOTALL | re.MULTILINE)
        if dram_section:
            dram_text = dram_section.group(0)
            acc_match = re.search(r'Total scalar accesses\s+:\s+(\d+)', dram_text)
            if acc_match:
                stats['dram_accesses'] = int(acc_match.group(1))
        
        # 如果上面没找到，尝试在 Operational Intensity Stats 里找
        if stats['dram_accesses'] == 0:
            op_stats = re.search(r'=== (SEDRAM|DRAM) ===\n\s+Total scalar accesses\s+:\s+(\d+)', content)
            if op_stats:
                stats['dram_accesses'] = int(op_stats.group(2))

        # 4. [核心修复] 计算 Logic Energy (剔除 DRAM)
        # 方法：解析 "fJ/Compute" 表格
        # Computes = 115605504
        computes = 0
        comp_match = re.search(r'^Computes\s+=\s+(\d+)', content, re.MULTILINE)
        if comp_match:
            computes = int(comp_match.group(1))

        if computes > 0:
            # 找到 fJ/Compute 区块
            fj_section = re.search(r'fJ/Compute(.*?)(?=\n\n|\Z)', content, re.DOTALL)
            total_logic_fj_per_op = 0.0
            
            if fj_section:
                lines = fj_section.group(1).strip().split('\n')
                for line in lines:
                    # line format: ComponentName   = 123.45
                    if '=' in line:
                        parts = line.split('=')
                        name = parts[0].strip()
                        try:
                            val = float(parts[1].strip())
                            # [过滤逻辑] 排除 DRAM, SEDRAM, Total
                            if 'DRAM' not in name and 'SEDRAM' not in name and 'Total' not in name:
                                total_logic_fj_per_op += val
                        except: pass
            
            # Logic Energy (pJ) = (fJ/Op * Ops) / 1000
            stats['energy_pj'] = (total_logic_fj_per_op * computes) / 1000.0
        
        # 兜底：如果没找到 fJ/Compute 表格，尝试累加各 Level 的 Energy (排除 DRAM)
        if stats['energy_pj'] == 0:
            raw_energy_pj = 0.0
            # 这种正则比较复杂，需要匹配 Level 和其 Energy，简单起见如果上面失败，这步作为备选
            # 暂时假设 fJ/Compute 表格总是存在（这是 Timeloop 标准输出）
            pass

        return stats
