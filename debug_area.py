import os
import yaml

# 目标文件路径 (根据你的日志，是在 step_0)
target_file = "output/step_0/timeloop-mapper.ART_summary.yaml"

if os.path.exists(target_file):
    print(f"Loading {target_file}...")
    with open(target_file, 'r') as f:
        data = yaml.safe_load(f)
    
    print("\n=== ART Summary Structure ===")
    print(yaml.dump(data, default_flow_style=False))
    
    print("\n=== Try Parsing ===")
    # 模拟 ResultParser 的逻辑
    if 'ART_summary' in data and 'table_summary' in data['ART_summary']:
        table = data['ART_summary']['table_summary']
        for entry in table:
            print(f"Name: {entry.get('name')}, Area: {entry.get('area')}")
    else:
        print("[Warning] Standard structure not found.")
else:
    print(f"[Error] File not found: {target_file}")
    print("Please run main_optimization.py first.")
