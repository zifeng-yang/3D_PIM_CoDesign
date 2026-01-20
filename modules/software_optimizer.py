import os
import yaml

class SoftwareOptimizer:
    def __init__(self, config_dir):
        """
        初始化软件优化器
        config_dir: 用于存放生成的 constraints 和 mapper 配置的目录
        """
        self.config_dir = config_dir
        if not os.path.exists(config_dir):
            os.makedirs(config_dir)

    def optimize(self, hw_params, prob_paths, iter_id):
        """
        [Stage 1: Software Optimization]
        根据硬件参数 (SRAM大小, PE阵列) 为每一层生成最优的 Tiling 约束 (Atoms)。
        """
        # 提取硬件关键参数
        sram_sz_bytes = (2 ** hw_params['sram_log2']) 
        pe_dim = hw_params['pe']
        
        # 定义输出路径
        schedule = {
            'constraints_path': os.path.join(self.config_dir, f"constraints_iter_{iter_id}.yaml"),
            'mapper_path': os.path.join(self.config_dir, f"mapper_iter_{iter_id}.yaml"),
            'prob_paths': prob_paths
        }

        # 1. 生成 Mapper 配置 (算法参数)
        self._generate_mapper_config(schedule['mapper_path'])

        # 2. 生成 Tiling 约束 (适配 2D PE_column/PE_row 架构 + 正确的 SRAM 名称)
        self._generate_tiling_constraints(schedule['constraints_path'], sram_sz_bytes, pe_dim)

        return schedule

    def _generate_mapper_config(self, output_path):
        """生成 Mapper 搜索算法配置"""
        config = {
            'mapper': {
                'version': 0.4,
                'algorithm': 'random_pruned', 
                'timeout': 100,             
                'optimization_metrics': ['edp', 'delay'],
                'live_status': False,
                'num_threads': 8,           
                'search_size': 0
            },
            'mapspace': {
                'version': 0.4, 
                'template': 'uber',         
            }
        }
        with open(output_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False)

    def _generate_tiling_constraints(self, output_path, sram_limit, pe_dim):
        """
        [关键算法] 计算适合当前 SRAM 大小的 Mapspace Constraints
        针对 2D 脉动阵列 (PE_column, PE_row) 生成空间约束。
        """
        constraints = {
            'constraints': {
                'version': 0.4,
                'targets': [
                    # 1. 空间映射 - 维度 X (PE_column)
                    # 将输出通道 M 映射到 PE_column
                    {
                        'target': 'PE_column', 
                        'type': 'spatial',
                        'factors': [f'M={pe_dim}', f'C=1', f'P=1', f'Q=1', f'R=1', f'S=1', f'N=1'],
                        'permutation': ['M', 'C', 'P', 'Q', 'R', 'S', 'N'] 
                    },
                    # 2. 空间映射 - 维度 Y (PE_row)
                    # 将输出特征图高度 P 映射到 PE_row
                    {
                        'target': 'PE_row', 
                        'type': 'spatial',
                        'factors': [f'P={pe_dim}', f'M=1', f'C=1', f'Q=1', f'R=1', f'S=1', f'N=1'],
                        'permutation': ['P', 'M', 'C', 'Q', 'R', 'S', 'N'] 
                    },
                    
                    # 3. 允许 Node_SRAM 旁路 (Bypass)
                    # [关键修复] 必须使用 'Node_SRAM' 而非 'GlobalBuffer'
                    # [关键修复] 必须使用 'dataspace' 类型而非 'bypass'
                    {
                        'target': 'Node_SRAM',
                        'type': 'dataspace',  
                        'keep': ['Weights'],           
                        'bypass': ['Inputs', 'Outputs'] 
                    },
                    
                    # 4. 允许 RegisterFile (RF) 旁路
                    {
                        'target': 'shared_rf',
                        'type': 'dataspace',
                        'keep': [], # 让 Mapper 决定 keep 什么
                        'bypass': ['Inputs', 'Outputs', 'Weights']
                    }
                ]
            }
        }

        with open(output_path, 'w') as f:
            yaml.dump(constraints, f, default_flow_style=False)
