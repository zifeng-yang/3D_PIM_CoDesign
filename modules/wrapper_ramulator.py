import subprocess
import os

class RamulatorWrapper:
    def __init__(self, docker_image="ramulator-pim-test:latest"):
        self.image = docker_image
        self.project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

    def run_simulation(self, config_rel_path, trace_rel_path, output_rel_dir):
        work_dir = "/home/workspace"
        
        # 处理路径：传入不带 .0 的基础名
        if trace_rel_path.endswith(".0"):
            trace_base_arg = trace_rel_path[:-2]
        else:
            trace_base_arg = trace_rel_path

        c_cfg = f"{work_dir}/{config_rel_path}"
        c_trace = f"{work_dir}/{trace_base_arg}"
        c_stats = f"{work_dir}/{output_rel_dir}/ramulator.stats"
        ramulator_bin = "/ramulator-pim/ramulator/ramulator"
        
        # [CRITICAL UPDATE]
        # 1. trace-format 改为 zsim
        # 2. split-trace 改为 true (这样它会自动找 trace_base_arg + ".0")
        cmd = (
            f"docker run --rm -v {self.project_root}:{work_dir} "
            f"-w {work_dir} {self.image} "
            f"{ramulator_bin} "
            f"--config {c_cfg} "
            f"--disable-perf-scheduling true "
            f"--mode=cpu "
            f"--stats {c_stats} "
            f"--trace {c_trace} "
            f"--core-org=inOrder "
            f"--number-cores=1 "
            f"--trace-format=zsim "  # <--- 改为 zsim
            f"--split-trace=true"    # <--- 改为 true
        )
        
        try:
            # 运行仿真
            subprocess.run(cmd, shell=True, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            
            # 解析结果
            stats_file_host = os.path.join(self.project_root, output_rel_dir, "ramulator.stats")
            return self.parse_cycles(stats_file_host)
            
        except Exception as e:
            print(f"[Wrapper Error] {e}")
            return 1000 # 失败时的保底值

    def parse_cycles(self, stats_file):
        if not os.path.exists(stats_file):
            return 1000
        try:
            with open(stats_file, 'r') as f:
                for line in f:
                    # 优先找 dram_cycles
                    if "ramulator.dram_cycles" in line:
                        val = int(line.split()[1])
                        return val if val > 0 else 1000
                    # 备选 cpu_cycles
                    if "ramulator.cpu_cycles" in line:
                        val = int(line.split()[1])
                        return val if val > 0 else 1000
            return 1000
        except Exception:
            return 1000
