import subprocess
import os
import sys

class TimeloopWrapper:
    def __init__(self):
        # 尝试自动寻找 tl
        self.timeloop_mapper_bin = "tl" 

    def run_mapper(self, arch_path, prob_path, mapper_path, output_dir, component_dir=None):
        """
        运行 Timeloop Mapper，具备更好的错误处理
        """
        input_files = [arch_path, prob_path, mapper_path]
        if component_dir and os.path.exists(component_dir):
            for root, dirs, files in os.walk(component_dir):
                for file in files:
                    if file.endswith(".yaml"):
                        input_files.append(os.path.join(root, file))

        if not os.path.exists(output_dir):
            os.makedirs(output_dir)

        cmd = [self.timeloop_mapper_bin, "mapper"] + input_files + ["-o", output_dir]

        try:
            # 使用 subprocess.run 而不是 check_output，这样可以检查 returncode
            result = subprocess.run(
                cmd, 
                capture_output=True, 
                text=True, 
                timeout=120  # 防止死锁
            )
            
            if result.returncode != 0:
                # 记录简短错误，但不抛出异常中断主程序
                # print(f"[Wrapper] Timeloop failed with code {result.returncode}")
                return False
            
            # 再次确认文件生成
            stats_file = os.path.join(output_dir, "timeloop-mapper.stats.txt")
            return os.path.exists(stats_file)

        except subprocess.TimeoutExpired:
            print(f"[Wrapper] Timeloop timed out after 120s")
            return False
        except Exception as e:
            print(f"[Wrapper] Execution error: {e}")
            return False
