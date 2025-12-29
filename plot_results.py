# 文件路径: plot_results.py
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import os

# 读取数据
csv_file = "dse_results_nicepim.csv"
if not os.path.exists(csv_file):
    print("Error: CSV file not found.")
    exit()

df = pd.read_csv(csv_file)

# 数据清洗：移除失败点 (EDP太大的)
valid_df = df[df['EDP'] < 1e16].copy()

# 设置绘图风格
sns.set(style="whitegrid")
plt.rcParams.update({'font.size': 12})

# === 图表 1: EDP 收敛曲线 (Convergence) ===
plt.figure(figsize=(10, 6))
sns.lineplot(data=valid_df, x='Iter', y='EDP', hue='Mode', marker='o')
plt.yscale('log')
plt.title('TuRBO Convergence: Baseline vs Atomic')
plt.xlabel('Iteration')
plt.ylabel('EDP (Energy-Delay Product) [Log Scale]')
plt.savefig('fig_convergence.png')
print("Generated fig_convergence.png")

# === 图表 2: 面积-性能 权衡图 (Pareto Frontier) ===
# 我们用 Latency 或 Energy 作为 Y 轴，Area 作为 X 轴
plt.figure(figsize=(10, 6))
sns.scatterplot(data=valid_df, x='Area_mm2', y='EDP', hue='Mode', style='Nodes', s=100)
plt.yscale('log')
plt.axvline(x=48.0, color='r', linestyle='--', label='NicePIM Limit (48mm2)')
plt.title('Design Space Exploration: Area vs EDP')
plt.xlabel('Area ($mm^2$)')
plt.ylabel('EDP')
plt.legend(bbox_to_anchor=(1.05, 1), loc='upper left')
plt.tight_layout()
plt.savefig('fig_bottleneck.png')
print("Generated fig_bottleneck.png")
