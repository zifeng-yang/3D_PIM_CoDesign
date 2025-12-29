from modules.wrapper_ramulator import RamulatorWrapper
import os

# 1. 制造一个符合命名规范的 trace 文件 (.0)
os.makedirs("output/timeloop_stats", exist_ok=True)
# 注意：这里我们写入 .0 文件
with open("output/dram.trace.0", "w") as f:
    f.write("10 0x123456\n")
    f.write("5 0x800000\n")

# 2. 运行包装器
wrapper = RamulatorWrapper()
print("Starting Diagnosis...")

# 注意：我们传给 wrapper 的是包含 .0 的全路径， wrapper 会自动处理
cycles = wrapper.run_simulation(
    config_rel_path="configs/ramulator/sedram.cfg",
    trace_rel_path="output/dram.trace.0", 
    output_rel_dir="output/timeloop_stats"
)

if cycles:
    print(f"Success! Cycles: {cycles}")
else:
    print("Diagnosis Failed.")
