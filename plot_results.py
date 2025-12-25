import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

# 使用 Matplotlib 内置的专业样式，不依赖 Seaborn
plt.style.use('ggplot')
plt.rcParams['font.family'] = 'serif' # 论文常用衬线字体
plt.rcParams['axes.linewidth'] = 1.5

def plot_optimization():
    print("[Plot] Initializing robust plotting...")
    try:
        # 1. 读取数据
        df = pd.read_csv("optimization_results.csv")
        
        # [关键清洗] 
        # 1. 确保是数字
        df['EDP'] = pd.to_numeric(df['EDP'], errors='coerce')
        # 2. 去除 Ramulator 没跑通的旧数据 (Cycles == 0)
        df_clean = df[df['Ramulator_Cycles'] > 0].copy()
        
        # 如果没有有效数据（比如全是旧的），则回退到显示所有数据以免报错
        if df_clean.empty:
            print("[Warning] No successful Ramulator runs found. Plotting all data.")
            df_clean = df
        else:
            print(f"[Info] Plotting {len(df_clean)} valid data points (filtered out failures).")

        # 3. 准备 Numpy 数组 (彻底解决版本冲突问题)
        # 将 Pandas Series 剥离为纯数字数组
        iterations = np.arange(len(df_clean)) + 1 # 重新生成 1, 2, 3... 序号
        edp_values = df_clean['EDP'].to_numpy()
        best_edp = df_clean['EDP'].cummin().to_numpy()
        
        pe_counts = (df_clean['PE_X'] * df_clean['PE_Y']).to_numpy()
        compute_cycles = df_clean['Cycles'].to_numpy()
        sram_sizes = df_clean['SRAM'].to_numpy()

        # === 图 1: 优化收敛曲线 (Convergence) ===
        plt.figure(figsize=(10, 6))
        
        # 绘制散点和连线
        plt.plot(iterations, edp_values, 'o-', color='gray', alpha=0.5, label='Exploration', markersize=6)
        # 绘制最佳路径
        plt.plot(iterations, best_edp, color='#d62728', linewidth=3, label='Best Found (TuRBO)')
        
        plt.xlabel('Valid Iterations', fontweight='bold', fontsize=12)
        plt.ylabel('EDP (Energy-Delay Product)', fontweight='bold', fontsize=12)
        plt.yscale('log') # 对数坐标
        plt.title('Optimization Convergence (3D PIM Co-Design)', fontsize=14)
        plt.grid(True, which="both", ls="--", alpha=0.4)
        plt.legend(fontsize=12)
        
        plt.tight_layout()
        plt.savefig('fig_convergence.png', dpi=300)
        print("[Success] Generated fig_convergence.png")

        # === 图 2: 瓶颈分析 (Compute vs Memory) ===
        plt.figure(figsize=(10, 7))
        
        # 绘制散点图 (计算周期)
        sc = plt.scatter(pe_counts, compute_cycles, c=sram_sizes, cmap='viridis', 
                         s=120, alpha=0.9, edgecolors='k', zorder=10, label='Compute Cycles')
        
        # 绘制内存墙基准线 (Memory Cycles)
        # 计算平均内存周期
        ram_cyc_vals = df_clean['Ramulator_Cycles'].to_numpy()
        avg_mem_cyc = np.median(ram_cyc_vals)
        
        plt.axhline(y=avg_mem_cyc, color='#d62728', linestyle='--', linewidth=2.5, 
                    label=f'Memory Wall (~{int(avg_mem_cyc/1000)}k Cyc)', zorder=5)
        
        plt.xlabel('Total PE Count', fontweight='bold', fontsize=12)
        plt.ylabel('Latency (Cycles)', fontweight='bold', fontsize=12)
        plt.yscale('log')
        plt.title('Design Space: Compute Bound Analysis', fontsize=14)
        
        # 颜色条
        cbar = plt.colorbar(sc)
        cbar.set_label('SRAM Size (Bytes)', fontweight='bold')
        
        plt.legend(loc='upper right', frameon=True, framealpha=0.9)
        plt.tight_layout()
        plt.savefig('fig_bottleneck.png', dpi=300)
        print("[Success] Generated fig_bottleneck.png")

    except Exception as e:
        print(f"[Fatal Error] {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    plot_optimization()
