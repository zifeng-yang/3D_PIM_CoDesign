from modules.hardware_gen import HardwareGenerator
from modules.wrapper_timeloop import TimeloopWrapper
import os

def test_phase_2():
    print("=== Phase 2: System Integration Test (Full Stack) ===")
    
    # 1. 获取当前工作目录 (Project Root)
    cwd = os.getcwd()
    
    # 2. 定义关键路径 (Laboratory Configuration)
    # 硬件模板
    template_path = os.path.join(cwd, "configs/arch/pim_template.yaml")
    # 组件目录 (存放 smartbuffer_RF.yaml 等)
    component_dir = os.path.join(cwd, "configs/arch/components")
    # 负载定义
    prob_path     = os.path.join(cwd, "configs/prob/cnn_layer.yaml")
    # 映射器配置
    mapper_path   = os.path.join(cwd, "configs/mapper/mapper.yaml")
    
    # 定义输出目录
    gen_dir   = os.path.join(cwd, "output/generated_arch")
    stats_dir = os.path.join(cwd, "output/timeloop_stats")
    
    # 确保输出目录存在
    os.makedirs(gen_dir, exist_ok=True)
    os.makedirs(stats_dir, exist_ok=True)
    
    # --- Step A: 生成硬件配置 (Hardware Instantiation) ---
    print(f"\n[Step A] Generating Hardware Config...")
    
    if not os.path.exists(template_path):
        print(f"[ERROR] Template file missing: {template_path}")
        return

    hw_gen = HardwareGenerator(template_path, gen_dir)
    
    # 定义测试参数 (必须与 v0.4 模板中的 {{ variables }} 对应)
    # 我们使用了稍大的 SRAM 以适应 CNN Layer 负载
    test_params = {
        'pe_dim_x': 16,            
        'pe_dim_y': 16,            
        'sram_depth': 16384,        # 16KB Depth (约 1MB+ 容量), 给予充足空间
        'input_weight_datawidth': 16, 
        'psum_datawidth': 16,
        'mac_class': 'intmac'       # 确保组件中有 intmac.yaml
    }
    
    try:
        # 生成具体的 test_arch.yaml
        arch_file = hw_gen.generate_config(test_params, filename="test_arch.yaml")
        print(f"   [OK] Hardware generated at: {arch_file}")
    except Exception as e:
        print(f"[FAILURE] Hardware generation stopped: {e}")
        return
    
    # --- Step B: 运行 Timeloop 仿真 (Simulation Execution) ---
    print(f"\n[Step B] Running Timeloop Simulation...")
    print(f"   Architecture: {os.path.basename(arch_file)}")
    print(f"   Problem:      {os.path.basename(prob_path)}")
    print(f"   Mapper:       {os.path.basename(mapper_path)}")
    print(f"   Components:   {component_dir}")
    
    # 完整性检查 (Sanity Check)
    missing_files = []
    if not os.path.exists(prob_path): missing_files.append("prob/cnn_layer.yaml")
    if not os.path.exists(mapper_path): missing_files.append("mapper/mapper.yaml")
    if not os.path.exists(component_dir): missing_files.append("arch/components/")
    
    if missing_files:
        print(f"[ERROR] Missing critical configuration files: {missing_files}")
        print("Please check your 'configs' directory structure.")
        return

    # 初始化 Docker 包装器
    tl_wrapper = TimeloopWrapper(docker_image_name="timeloopaccelergy/timeloop-accelergy-pytorch:latest-amd64")
    
    # 执行 run_mapper (传入所有必要路径)
    success = tl_wrapper.run_mapper(
        arch_path=arch_file, 
        prob_path=prob_path, 
        mapper_path=mapper_path, 
        output_dir=stats_dir,
        component_dir=component_dir
    )
    
    # --- Step C: 验证结果 (Result Validation) ---
    if success:
        # 检查统计文件
        expected_stats = os.path.join(stats_dir, "timeloop-mapper.stats.txt")
        
        if os.path.exists(expected_stats):
            print(f"\n[SUCCESS] Simulation Complete! Stats found at:\n{expected_stats}")
            print("-" * 50)
            # 简单的结果预览
            try:
                with open(expected_stats, 'r') as f:
                    lines = f.readlines()
                    # 尝试抓取前几行 Summary
                    summary_lines = [l.strip() for l in lines if "Energy" in l or "Cycles" in l]
                    for sl in summary_lines[:5]: 
                        print(f"   >> {sl}")
            except:
                pass
            print("-" * 50)
        else:
            print(f"\n[WARNING] Docker ran successfully, but output file '{os.path.basename(expected_stats)}' is missing.")
            print(f"   Check folder: {stats_dir}")
            # 有时可能是 XML 或 JSON 格式，取决于 Mapper 版本
    else:
        print("\n[FAILURE] Simulation failed inside Docker.")

if __name__ == "__main__":
    test_phase_2()
