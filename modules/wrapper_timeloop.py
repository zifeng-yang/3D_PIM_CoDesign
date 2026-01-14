import subprocess
import os
import yaml

class TimeloopWrapper:
    def __init__(self):
        # 假设 timeloop 可执行文件在 PATH 中，或者指定绝对路径
        self.timeloop_mapper_bin = "tl" 

    def run_mapper(self, arch_path, prob_path, mapper_path, output_dir, component_dir=None):
        """
        运行 Timeloop Mapper
        :param timeout: 超时时间 (秒)，防止 Baseline 卡死
        """
        # 构造输入配置列表
        input_files = [arch_path, prob_path, mapper_path]
        if component_dir and os.path.exists(component_dir):
            # 添加组件库中的所有 yaml 文件
            for root, dirs, files in os.walk(component_dir):
                for file in files:
                    if file.endswith(".yaml"):
                        input_files.append(os.path.join(root, file))

        # 确保输出目录存在
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        # 构造命令: tl mapper arch.yaml prob.yaml ... -o output_dir
        cmd = [self.timeloop_mapper_bin, "mapper"] + input_files + ["-o", output_dir]

        try:
            # [关键改进] 
            # 1. capture_output=True: 捕获输出，不让它直接打印到屏幕
            # 2. timeout=120: 限制最大运行时间为 120 秒
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                check=True,
                timeout=120 
            )
            
            # 检查关键输出文件是否存在
            stats_file = os.path.join(output_dir, "timeloop-mapper.stats.txt")
            if os.path.exists(stats_file):
                return True
            else:
                return False

        except subprocess.TimeoutExpired:
            # 超时被视为失败，Wrapper 保持静默，由主程序处理
            return False
            
        except subprocess.CalledProcessError:
            # 运行报错（如约束冲突），视为失败
            return False
            
        except Exception:
            # 其他未知错误
            return False
