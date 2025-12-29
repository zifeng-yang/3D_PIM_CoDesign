import os
import random
from modules.hardware_gen import HardwareGenerator
from modules.wrapper_timeloop import TimeloopWrapper
from modules.result_parser import TimeloopParser
from modules.logger import ExperimentLogger

def run_dse_campaign(num_iterations=5):
    print(f"=== Starting Automated DSE Campaign ({num_iterations} iterations) ===")
    
    # 1. 初始化组件
    cwd = os.getcwd()
    template_path = os.path.join(cwd, "configs/arch/pim_template.yaml")
    prob_path     = os.path.join(cwd, "configs/prob/cnn_layer.yaml")
    mapper_path   = os.path.join(cwd, "configs/mapper/mapper.yaml")
    comp_dir      = os.path.join(cwd, "configs/arch/components")
    
    output_base   = os.path.join(cwd, "output")
    gen_dir       = os.path.join(output_base, "generated_arch")
    stats_dir     = os.path.join(output_base, "timeloop_stats")
    
    # 确保目录存在
    os.makedirs(gen_dir, exist_ok=True)
    os.makedirs(stats_dir, exist_ok=True)

    hw_gen = HardwareGenerator(template_path, gen_dir)
    # 使用正确的 Docker 镜像名
    tl_wrapper = TimeloopWrapper(docker_image_name="timeloopaccelergy/timeloop-accelergy-pytorch:latest-amd64")
    logger = ExperimentLogger(os.path.join(cwd, "dse_results.csv"))

    # 2. 循环迭代
    for i in range(1, num_iterations + 1):
        print(f"\n--- Iteration {i}/{num_iterations} ---")
        
        # [Step 1] 采样：随机生成硬件参数 (Design Space Sampling)
        # 这里模拟 TuRBO 的探索过程
        current_params = {
            'pe_dim_x': random.choice([12, 14, 16, 24]), 
            'pe_dim_y': random.choice([12, 14, 16, 24]),
            'sram_depth': random.choice([16384, 32768, 65536]), # 加大 Buffer
            'input_weight_datawidth': 16,
            'psum_datawidth': 16,
            'mac_class': 'intmac'
        }
        print(f"Sampling Params: {current_params}")

        # [Step 2] 生成硬件
        arch_file = hw_gen.generate_config(current_params, filename=f"arch_iter_{i}.yaml")
        
        # [Step 3] 运行仿真
        # 注意：每次覆盖同一个 stats 目录是安全的，因为我们马上就会解析它
        success = tl_wrapper.run_mapper(
            arch_path=arch_file,
            prob_path=prob_path,
            mapper_path=mapper_path,
            output_dir=stats_dir,
            component_dir=comp_dir
        )

        # [Step 4] 解析结果 & 记录
        if success:
            stats_file = os.path.join(stats_dir, "timeloop-mapper.stats.txt")
            parser = TimeloopParser(stats_file)
            results = parser.parse()
            
            if results:
                print(f"Result: Energy={results.get('energy_pj')} pJ, Cycles={results.get('cycles')}")
                logger.log(i, current_params, results)
            else:
                print("[Error] Failed to parse results.")
        else:
            print("[Error] Simulation failed.")

    print("\n=== DSE Campaign Finished ===")
    print("Check dse_results.csv for data.")

if __name__ == "__main__":
    run_dse_campaign(num_iterations=5)
