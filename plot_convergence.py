import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

# 读取数据
try:
    df = pd.read_csv("optimization_results.csv")
except FileNotFoundError:
    print("Error: optimization_results.csv not found.")
    exit()

# 数据预处理
# 过滤掉 EDP 异常大 (1e19以上) 的失败点
df_valid = df[df["EDP"] < 1e19]

if df_valid.empty:
    print("No valid data points found.")
    exit()

# [CRITICAL FIX] 提取数据后，立即转换为 numpy array，避免 Pandas 索引报错
iterations = df_valid["Iteration"].to_numpy()
edp = df_valid["EDP"].to_numpy()
sram_sizes = df_valid["SRAM"].to_numpy()

# 计算累积最小值 (Best So Far)
# 先在完整 df 上计算，再只取有效行的值，最后转 numpy
best_edp_series = df["EDP"].cummin()
best_edp_valid = best_edp_series[df_valid.index].to_numpy()

# === 绘图样式设置 ===
try:
    plt.style.use('seaborn-whitegrid')
except:
    plt.style.use('ggplot')

fig, ax = plt.subplots(figsize=(8, 6))

# 1. 绘制采样点 (Scatter)
# 使用颜色映射表示 SRAM 大小
sc = ax.scatter(iterations, edp, 
                c=np.log2(sram_sizes), cmap='viridis', 
                s=80, alpha=0.7, edgecolors='k', zorder=2, label='Design Point')

# 添加 Colorbar
cbar = plt.colorbar(sc)
cbar.set_label('Log2(SRAM Size)', rotation=270, labelpad=15)

# 2. 绘制收敛曲线 (Line)
ax.plot(iterations, best_edp_valid, 
        color='#d62728', linewidth=3, zorder=1, label='Best Found (TuRBO)')

# 3. 标注优化阶段
plt.axvline(x=5.5, color='black', linestyle='--', alpha=0.8)
# 动态调整文字位置
y_text_pos = min(edp) * 100 # 稍微高一点的位置
ax.text(3, y_text_pos, 'Random\nInit', ha='center', fontsize=11, fontweight='bold')
ax.text(10, y_text_pos, 'Bayesian\nOptimization', ha='center', fontsize=11, fontweight='bold')

# 坐标轴设置
ax.set_yscale('log')
ax.set_xlabel('Iteration', fontsize=12, fontweight='bold')
ax.set_ylabel('EDP (Energy-Delay Product) [log scale]', fontsize=12, fontweight='bold')
ax.set_title('Hardware-Software Co-Design Optimization', fontsize=14, pad=15)

# 网格与图例
ax.grid(True, which="major", ls="-", alpha=0.4)
ax.grid(True, which="minor", ls=":", alpha=0.2)
ax.legend(loc='upper right', frameon=True, framealpha=0.9)

# 保存
output_img = "convergence_plot.png"
plt.savefig(output_img, dpi=300, bbox_inches='tight')
print(f"Plot saved to {output_img}")
