import subprocess
import os

def run_probe():
    print("=== Deep Probe Diagnosis ===")
    
    # 1. 准备环境
    work_dir = os.getcwd()
    stats_dir = os.path.join(work_dir, "output", "timeloop_stats")
    os.makedirs(stats_dir, exist_ok=True)
    
    # 2. 准备 Trace 文件 (确保是以 .0 结尾)
    trace_file = os.path.join(work_dir, "output", "dram.trace.0")
    with open(trace_file, "w") as f:
        # 写入几行符合 PISA/Simple 格式的数据
        f.write("10 0x123456\n")
        f.write("5 0x800000\n")
    print(f"[Probe] Created trace file at: {trace_file}")

    # 3. 准备配置文件 (确保 sedram.cfg 存在)
    config_file = os.path.join(work_dir, "configs", "ramulator", "sedram.cfg")
    if not os.path.exists(config_file):
        print(f"[Probe Error] Config file missing: {config_file}")
        return

    # 4. 构造 Docker 命令 (注意：传给 trace 的路径不带 .0)
    # Ramulator 会自动寻找 <trace_path>.0
    trace_base_path = os.path.join("/home/workspace", "output", "dram.trace")
    
    cmd = (
        f"docker run --rm "
        f"-v {work_dir}:/home/workspace "
        f"-w /home/workspace "
        f"ramulator-pim-test:latest "
        f"/ramulator-pim/ramulator/ramulator "
        f"--config configs/ramulator/sedram.cfg "
        f"--disable-perf-scheduling true "
        f"--mode=cpu "
        f"--stats output/timeloop_stats/ramulator.stats "
        f"--trace output/dram.trace "
        f"--core-org=inOrder "
        f"--number-cores=1 "
        f"--trace-format=pisa "
        f"--split-trace=false"
    )

    print(f"[Probe] Executing Docker Command:\n{cmd}\n")

    # 5. 执行并捕获所有输出
    result = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    
    print("--- STDOUT (Docker) ---")
    print(result.stdout.decode())
    print("-----------------------")
    
    print("--- STDERR (Docker) ---")
    print(result.stderr.decode())
    print("-----------------------")
    
    # 6. 检查输出文件
    stats_out = os.path.join(stats_dir, "ramulator.stats")
    if os.path.exists(stats_out):
        print(f"[Probe] Stats file found at {stats_out}. Content:")
        print(">>>>>>>>>>>>>>>>>>>>>>>")
        with open(stats_out, 'r') as f:
            print(f.read())
        print("<<<<<<<<<<<<<<<<<<<<<<<")
    else:
        print("[Probe] Stats file was NOT generated.")

if __name__ == "__main__":
    run_probe()
