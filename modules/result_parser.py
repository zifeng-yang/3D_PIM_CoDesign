import re
import os

class TimeloopParser:
    def __init__(self, stats_file_path):
        self.stats_file = stats_file_path

    def parse(self):
        """
        解析 timeloop-mapper.stats.txt
        目标：提取 Summary Stats 部分的全局指标
        """
        if not os.path.exists(self.stats_file):
            print(f"[Parser] Error: Stats file not found: {self.stats_file}")
            return None

        data = {}
        try:
            with open(self.stats_file, 'r') as f:
                content = f.read()
                
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
