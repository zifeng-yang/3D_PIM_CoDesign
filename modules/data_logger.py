import os
import csv
import json
import shutil
import pickle
import datetime

class DataLogger:
    def __init__(self, config_dict):
        # 1. 创建带时间戳的根目录
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        self.root_dir = f"results/run_{timestamp}"
        self.configs_dir = os.path.join(self.root_dir, "configs")
        self.checkpoints_dir = os.path.join(self.root_dir, "checkpoints")
        
        os.makedirs(self.root_dir, exist_ok=True)
        os.makedirs(self.configs_dir, exist_ok=True)
        os.makedirs(self.checkpoints_dir, exist_ok=True)

        # 2. 保存实验元数据 (Metadata)
        self._save_metadata(config_dict)

        # 3. 初始化 CSV 文件句柄
        self.summary_file = os.path.join(self.root_dir, "dse_summary.csv")
        self.details_file = os.path.join(self.root_dir, "dse_details.csv")
        self._init_csvs()

    def _save_metadata(self, config):
        """保存全局配置，确保实验可追溯"""
        meta_path = os.path.join(self.root_dir, "experiment_metadata.json")
        with open(meta_path, 'w') as f:
            json.dump(config, f, indent=4)

    def _init_csvs(self):
        """初始化 CSV 表头"""
        with open(self.summary_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["Iter", "Nodes", "PE", "SRAM_KB", 
                             "EDP_Base", "Lat_Base", "En_Base", 
                             "EDP_Atom", "Lat_Atom", "En_Atom", 
                             "Area_mm2", "Runtime_s", "Improvement"])
        
        with open(self.details_file, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(["Iter", "Mode", "Cycles", "DRAM_Acc", "SRAM_Acc", "NoC_Lat", "NoC_Pwr"])

    def log_iteration(self, iter_id, hw_params, metrics, duration, improvement):
        """
        记录单次迭代的核心数据到 CSV
        """
        # metrics 是一个包含 base 和 atom 结果的字典
        # hw_params: [nodes, pe, sram]
        
        # 写入 Summary
        with open(self.summary_file, 'a', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                iter_id, hw_params[0], hw_params[1], hw_params[2] // 1024,
                f"{metrics['base_edp']:.2e}", f"{metrics['base_lat']:.2e}", f"{metrics['base_en']:.2e}",
                f"{metrics['atom_edp']:.2e}", f"{metrics['atom_lat']:.2e}", f"{metrics['atom_en']:.2e}",
                f"{metrics['area']:.2f}", f"{duration:.2f}", improvement
            ])

        # 写入 Details
        with open(self.details_file, 'a', newline='') as f:
            w = csv.writer(f)
            db = metrics['base_det']
            da = metrics['atom_det']
            w.writerow([iter_id, "baseline", db.get('cycles',0), db.get('dram_acc',0), db.get('sram_acc',0), db.get('noc_lat',0), db.get('noc_pwr',0)])
            w.writerow([iter_id, "atomic", da.get('cycles',0), da.get('dram_acc',0), da.get('sram_acc',0), da.get('noc_lat',0), da.get('noc_pwr',0)])

    def archive_artifacts(self, iter_id, files_to_save):
        """
        备份关键的配置文件 (arch.yaml, mapper.yaml)
        这样如果某次结果很好，你可以直接查看当时生成的 yaml 是什么样
        """
        iter_dir = os.path.join(self.configs_dir, f"iter_{iter_id}")
        os.makedirs(iter_dir, exist_ok=True)
        
        for src_path in files_to_save:
            if os.path.exists(src_path):
                filename = os.path.basename(src_path)
                dst_path = os.path.join(iter_dir, filename)
                shutil.copy(src_path, dst_path)

    def save_checkpoint(self, optimizer_state, filename="turbo_state.pkl"):
        """
        保存优化器状态，支持断点续传
        """
        path = os.path.join(self.checkpoints_dir, filename)
        with open(path, 'wb') as f:
            pickle.dump(optimizer_state, f)
            
    def get_results_dir(self):
        return self.root_dir
