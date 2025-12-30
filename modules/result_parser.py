# 文件路径: modules/result_parser.py

import os
import yaml
import re

class TimeloopParser:
    def __init__(self, stats_file_path):
        self.stats_file = stats_file_path
        self.output_dir = os.path.dirname(stats_file_path)

    def parse(self):
        """解析所有相关的 Timeloop/Accelergy 结果"""
        results = {}
        
        if os.path.exists(self.stats_file):
            stats_data = self._parse_stats_txt()
            results.update(stats_data)
        
        # 解析面积
        art_file = os.path.join(self.output_dir, "timeloop-mapper.ART_summary.yaml")
        if os.path.exists(art_file):
            area_mm2 = self._parse_art_summary(art_file)
            results['area_mm2'] = area_mm2
        else:
            results['area_mm2'] = 0.0
            
        return results

    def _parse_stats_txt(self):
        data = {
            'cycles': 0, 'energy_pj': 0,
            'dram_reads': 0, 'dram_writes': 0,
            'sram_reads': 0, 'sram_writes': 0
        }
        try:
            with open(self.stats_file, 'r') as f:
                content = f.read()
                
                # 1. 基础指标
                cycles_match = re.search(r'Cycles:\s+(\d+)', content)
                if cycles_match: data['cycles'] = int(cycles_match.group(1))
                
                energy_match = re.search(r'Energy:\s+([\d\.]+)\s+(\w+)', content)
                if energy_match:
                    val = float(energy_match.group(1))
                    unit = energy_match.group(2)
                    if unit == 'uJ': val *= 1e6
                    elif unit == 'nJ': val *= 1e3
                    elif unit == 'mJ': val *= 1e9
                    elif unit == 'J': val *= 1e12
                    data['energy_pj'] = val

                # 2. [诊断] 提取 SRAM 和 DRAM 的具体访问量
                # 查找 DRAM 块
                dram_section = re.search(r'===\s*(DRAM|MainMemory|Offchip)\s*===(.*?)(?:Level|\Z)', content, re.DOTALL | re.IGNORECASE)
                if dram_section:
                    text = dram_section.group(2)
                    r = re.search(r'(?:Scalar reads|Reads).*?:\s+(\d+)', text)
                    w = re.search(r'(?:Scalar updates|Updates|Writes).*?:\s+(\d+)', text)
                    if r: data['dram_reads'] = int(r.group(1))
                    if w: data['dram_writes'] = int(w.group(1))

                # 查找 SRAM 块 (Node_SRAM 或 SRAM_Buffer)
                sram_section = re.search(r'===\s*(Node_SRAM|SRAM_Buffer)\s*===(.*?)(?:Level|\Z)', content, re.DOTALL | re.IGNORECASE)
                if sram_section:
                    text = sram_section.group(2)
                    r = re.search(r'(?:Scalar reads|Reads).*?:\s+(\d+)', text)
                    w = re.search(r'(?:Scalar updates|Updates|Writes|Scalar fills|Fills).*?:\s+(\d+)', text)
                    if r: data['sram_reads'] = int(r.group(1))
                    # SRAM 的写入通常来自 fill (从 DRAM) 或 update (从 PE)
                    if w: data['sram_writes'] = int(w.group(1))

        except Exception as e:
            print(f"[Parser Error] Failed to parse stats.txt: {e}")
        return data

    def _parse_art_summary(self, filepath):
        try:
            with open(filepath, 'r') as f:
                data = yaml.safe_load(f)
            
            table = []
            if isinstance(data, list): table = data
            elif 'ART_summary' in data:
                if isinstance(data['ART_summary'], list): table = data['ART_summary']
                elif 'table_summary' in data['ART_summary']: table = data['ART_summary']['table_summary']

            total_area_um2 = 0.0
            for entry in table:
                name = entry.get('name', '').lower()
                area_val = float(entry.get('area', 0.0))
                if name in ['system', 'total', 'system_top_level'] or 'dram' in name:
                    continue
                
                count = 1
                match = re.search(r'\[(\d+)\.\.(\d+)\]', entry.get('name', ''))
                if match: count = int(match.group(2)) - int(match.group(1)) + 1
                
                total_area_um2 += area_val * count

            return total_area_um2 / 1e6
        except Exception:
            return 0.0
