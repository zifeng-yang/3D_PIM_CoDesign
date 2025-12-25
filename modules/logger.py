import csv
import os
import time

class ExperimentLogger:
    def __init__(self, output_file="experiment_results.csv"):
        self.output_file = output_file
        self.headers = [
            "Iteration", 
            "PE_X", "PE_Y", "SRAM_Depth", "Mac_Class", # 输入变量 (X)
            "Cycles", "Energy_pJ", "EDP",              # 输出指标 (Y)
            "Timestamp"
        ]
        
        # 如果文件不存在，写入表头
        if not os.path.exists(self.output_file):
            with open(self.output_file, mode='w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(self.headers)

    def log(self, iteration, params, results):
        """
        记录一行数据
        params: 硬件参数字典
        results: 解析器返回的结果字典
        """
        with open(self.output_file, mode='a', newline='') as f:
            writer = csv.writer(f)
            row = [
                iteration,
                params.get('pe_dim_x'),
                params.get('pe_dim_y'),
                params.get('sram_depth'),
                params.get('mac_class'),
                results.get('cycles', 'N/A'),
                results.get('energy_pj', 'N/A'),
                results.get('edp', 'N/A'),
                time.strftime("%Y-%m-%d %H:%M:%S")
            ]
            writer.writerow(row)
        print(f"[Logger] Recorded iteration {iteration} to {self.output_file}")
