import os
import sys
import subprocess
import yaml
# [颜色代码保持不变]
C_RED = "\033[91m"
C_GREEN = "\033[92m"
C_YELLOW = "\033[93m"
C_BLUE = "\033[94m"
C_END = "\033[0m"

from modules.workload_manager import WorkloadManager
from modules.arch_gen import ArchGenerator

def debug_run():
    print(f"{C_YELLOW}=== 3D PIM Co-Design Debugger (Multi-Layer Ver) ==={C_END}")
    
    cwd = os.getcwd()

    # 1. 测试负载生成 (使用新 API)
    print(f"\n{C_BLUE}[Step 1] Testing Workload Generation...{C_END}")
    prob_dir = "configs/prob/generated"
    
    try:
        wm = WorkloadManager(config_dir=prob_dir)
        # [修改] 调用新方法 generate_full_model
        layer_files = wm.generate_full_model("resnet18")
        
        if len(layer_files) > 0:
            print(f"  {C_GREEN}✔ Generated {len(layer_files)} layers for ResNet18{C_END}")
            
            # [策略] 选取中间某一层进行测试 (例如第5层，或者第0层)
            target_idx = 0
            target_prob = layer_files[target_idx]
            print(f"  -> Selecting layer {target_idx} for debug: {os.path.basename(target_prob)}")
            
            # 打印预览
            with open(target_prob, 'r') as f:
                lines = f.readlines()
                preview = "".join(lines[:15]) 
                print(f"  --- Content Preview ---\n{preview}  ...\n  -----------------------")
        else:
            print(f"  {C_RED}✘ No layers generated.{C_END}")
            return
            
    except Exception as e:
        print(f"  {C_RED}✘ Error in WorkloadManager:{C_END} {e}")
        import traceback
        traceback.print_exc()
        return

    # 2. 生成临时硬件配置
    print(f"\n{C_BLUE}[Step 2] Generating Debug Architecture...{C_END}")
    arch_file = os.path.join(cwd, "debug_output", "arch_debug.yaml")
    try:
        debug_arch_params = {
            'NUM_NODES': 1, 
            'PE_DIM_X': 4, 
            'PE_DIM_Y': 4, 
            'SRAM_DEPTH': 1048576, 
            'SRAM_WIDTH': 64
        }
        
        arch_gen = ArchGenerator(
            template_path=os.path.join(cwd, "templates/arch.yaml.jinja2"),
            output_dir=os.path.join(cwd, "debug_output")
        )
        if not os.path.exists("debug_output"): os.makedirs("debug_output")
        
        arch_gen.generate_config(debug_arch_params, filename="arch_debug.yaml")
        print(f"  {C_GREEN}✔ Architecture generated:{C_END} {arch_file}")
        
    except Exception as e:
        print(f"  {C_RED}✘ Error in ArchGenerator:{C_END} {e}")
        return

    # 3. 准备 Mapper 文件
    print(f"\n{C_BLUE}[Step 3] Checking Mapper...{C_END}")
    mapper_file = os.path.join(cwd, "configs/mapper/mapper.yaml")
    if not os.path.exists(mapper_file):
        print(f"  {C_YELLOW}⚠ configs/mapper/mapper.yaml not found, creating a minimal one.{C_END}")
        # 创建一个带有加速参数的 Mapper
        minimal_mapper = {
            'mapper': {
                'optimization-metrics': ['edp'],
                'live-status': False,
                'num-threads': 4,
                'timeout': 30,           # 加速
                'victory-condition': 50, # 加速
                'algorithm': 'random-pruned'
            }
        }
        if not os.path.exists("debug_output"): os.makedirs("debug_output")
        mapper_file = "debug_output/mapper_debug.yaml"
        with open(mapper_file, 'w') as f:
            yaml.dump(minimal_mapper, f)
    print(f"  {C_GREEN}✔ Using Mapper:{C_END} {mapper_file}")

    # 4. 显式运行 Timeloop
    print(f"\n{C_BLUE}[Step 4] Running Timeloop (Single Layer Test)...{C_END}")
    
    input_files = [arch_file, target_prob, mapper_file]
    
    comp_dir = os.path.join(cwd, "configs/arch/components")
    if os.path.exists(comp_dir):
        for root, _, files in os.walk(comp_dir):
            for file in files:
                if file.endswith(".yaml"):
                    input_files.append(os.path.join(root, file))

    # 使用 tl mapper 前端
    cmd = ["tl", "mapper"] + input_files + ["-o", "debug_output/"]
    
    print(f"Executing: {' '.join(cmd)}\n")
    
    try:
        result = subprocess.run(cmd, text=True)
        
        if result.returncode == 0:
            print(f"\n{C_GREEN}✔ Timeloop finished successfully!{C_END}")
            stats_path = "debug_output/timeloop-mapper.stats.txt"
            if os.path.exists(stats_path):
                # 简单读取结果展示
                with open(stats_path, 'r') as f:
                    content = f.read()
                    if "Energy" in content or "Cycles" in content:
                        print("  (Stats file contains valid data)")
            else:
                print(f"  {C_YELLOW}⚠ Warning: Success reported but stats file not found?{C_END}")
        else:
            print(f"\n{C_RED}✘ Timeloop FAILED with return code {result.returncode}{C_END}")
            
    except FileNotFoundError:
        print(f"\n{C_RED}✘ Error: 'tl' command not found.{C_END}")

if __name__ == "__main__":
    debug_run()
