<<<<<<< HEAD
import os
import yaml
import re
=======
import re
import os
>>>>>>> d2ec8543f2de6810717e0b3d892adc03f09692e8

class TimeloopParser:
    def __init__(self, stats_file_path):
        self.stats_file = stats_file_path
<<<<<<< HEAD
        self.output_dir = os.path.dirname(stats_file_path)

    def parse(self):
        """解析所有相关的 Timeloop/Accelergy 结果"""
        results = {}
        
        # 1. 解析基础性能数据 (Cycles, Energy)
        if os.path.exists(self.stats_file):
            results.update(self._parse_stats_txt())
        
        # 2. 解析面积数据 (Area) - 优先读取 ART_summary
        art_file = os.path.join(self.output_dir, "timeloop-mapper.ART_summary.yaml")
        if os.path.exists(art_file):
            area_mm2 = self._parse_art_summary(art_file)
            results['area_mm2'] = area_mm2
        else:
            # 备选：尝试读取 ART.yaml (未汇总的原始表)
            art_raw_file = os.path.join(self.output_dir, "timeloop-mapper.ART.yaml")
            if os.path.exists(art_raw_file):
                 results['area_mm2'] = self._parse_art_summary(art_raw_file)
            else:
                results['area_mm2'] = 0.0
            
        return results

    def _parse_stats_txt(self):
        """解析 timeloop-mapper.stats.txt 获取周期和能耗"""
=======

    def parse(self):
        """
        解析 timeloop-mapper.stats.txt
        目标：提取 Summary Stats 部分的全局指标
        """
        if not os.path.exists(self.stats_file):
            print(f"[Parser] Error: Stats file not found: {self.stats_file}")
            return None

>>>>>>> d2ec8543f2de6810717e0b3d892adc03f09692e8
        data = {}
        try:
            with open(self.stats_file, 'r') as f:
                content = f.read()
                
<<<<<<< HEAD
                # 提取 Cycles
                cycles_match = re.search(r'Cycles:\s+(\d+)', content)
                if cycles_match: 
                    data['cycles'] = int(cycles_match.group(1))
                
                # 提取 Energy (自适应单位)
                energy_match = re.search(r'Energy:\s+([\d\.]+)\s+(\w+)', content)
                if energy_match:
                    val = float(energy_match.group(1))
                    unit = energy_match.group(2)
                    # 统一转换为 pJ
                    if unit == 'uJ': val *= 1e6
                    elif unit == 'nJ': val *= 1e3
                    elif unit == 'mJ': val *= 1e9
                    elif unit == 'J': val *= 1e12
                    data['energy_pj'] = val
                    
        except Exception as e:
            print(f"[Parser Error] Failed to parse stats.txt: {e}")
        return data

    def _parse_art_summary(self, filepath):
        """
        鲁棒地解析 Accelergy 面积摘要。
        支持解析 MAC[1..1024] 这种格式并乘以数量。
        """
        try:
            with open(filepath, 'r') as f:
                data = yaml.safe_load(f)
            
            # 兼容不同的 YAML 结构
            table = []
            if isinstance(data, list):
                table = data
            elif 'ART_summary' in data:
                content = data['ART_summary']
                if isinstance(content, list):
                    table = content
                elif 'table_summary' in content:
                    table = content['table_summary']
            elif 'ART' in data:
                 if 'tables' in data['ART']:
                     table = data['ART']['tables']

            total_area_um2 = 0.0
            
            for entry in table:
                name = entry.get('name', '').lower()
                area_val = float(entry.get('area', 0.0))
                
                # 忽略 System/Total 汇总项，防止重复计算（如果我们要自己累加的话）
                if name in ['system', 'total', 'system_top_level']:
                    continue
                
                # 忽略 DRAM (通常不计入 PIM 逻辑面积)
                if 'dram' in name:
                    continue

                # 解析数量：查找 name[1..N] 模式
                # Accelergy 报告的 area 通常是单实例的 area，需要乘以 count
                count = 1
                match = re.search(r'\[(\d+)\.\.(\d+)\]', entry.get('name', ''))
                if match:
                    start = int(match.group(1))
                    end = int(match.group(2))
                    count = end - start + 1
                
                total_area_um2 += area_val * count

            return total_area_um2 / 1e6 # 转换为 mm^2

        except Exception as e:
            print(f"[Parser Error] Failed to parse ART file {filepath}: {e}")
        
        return 0.0
=======
                # --- 1. 提取全局 Cycles ---
                # 匹配 Summary Stats 下的 "Cycles: 12345"
                # 使用 re.DOTALL 让搜索跨越多行，但为了简单，我们先找 Summary 块
                
                # 策略：先找到 "Summary Stats" 之后的内容
                summary_section = content.split("Summary Stats")[-1] if "Summary Stats" in content else content
                
                cycle_match = re.search(r'Cycles\s*:\s*(\d+)', summary_section)
                if cycle_match:
                    data['cycles'] = int(cycle_match.group(1))
                else:
                    # 备选：如果 Summary 里没找到，再试着找全文第一个（通常也一样）
                    print("[Parser] Warning: Could not find 'Cycles' in Summary, trying global search.")
                    cycle_match = re.search(r'Cycles\s*:\s*(\d+)', content)
                    if cycle_match: data['cycles'] = int(cycle_match.group(1))

                # --- 2. 提取全局 Energy ---
                # 格式通常是 "Energy: 36759.83 uJ"
                energy_match = re.search(r'Energy\s*:\s*([\d\.]+)\s*uJ', summary_section)
                if energy_match:
                    # 获取微焦 (uJ) 并转换为皮焦 (pJ)
                    energy_uj = float(energy_match.group(1))
                    data['energy_pj'] = energy_uj * 1_000_000  # 1 uJ = 10^6 pJ
                else:
                    print("[Parser] Warning: Could not find 'Energy: ... uJ' in Summary.")
                    # 备选尝试 pJ 格式 (有些版本 Timeloop 输出 pJ)
                    energy_match_pj = re.search(r'Energy\s*:\s*([\d\.]+)\s*pJ', summary_section)
                    if energy_match_pj:
                        data['energy_pj'] = float(energy_match_pj.group(1))

                # --- 3. 计算 EDP ---
                if 'cycles' in data and 'energy_pj' in data:
                    data['edp'] = data['cycles'] * data['energy_pj']
                    
        except Exception as e:
            print(f"[Parser] Exception during parsing: {e}")
            return None

        return data

# 测试代码
if __name__ == "__main__":
    # 自动定位到最近一次的输出文件进行测试
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    test_path = os.path.join(base_dir, "output/timeloop_stats/timeloop-mapper.stats.txt")
    
    print(f"Testing parser on: {test_path}")
    parser = TimeloopParser(test_path)
    result = parser.parse()
    print("Parsed Result:", result)
>>>>>>> d2ec8543f2de6810717e0b3d892adc03f09692e8
