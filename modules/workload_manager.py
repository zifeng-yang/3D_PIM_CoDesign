import os
import glob
import yaml
import torch
import torch.nn as nn
import torch.fx as fx
import torchvision.models as models
from dataclasses import dataclass

# === 数据结构 ===
@dataclass
class LayerParams:
    name: str
    N: int = 1
    C: int = 0
    M: int = 0
    P: int = 0
    Q: int = 0
    R: int = 0
    S: int = 0
    Wstride: int = 1
    Hstride: int = 1
    Wdilation: int = 1
    Hdilation: int = 1
    Groups: int = 1

# === 核心转换器 ===
class WorkloadConverter(fx.Interpreter):
    def __init__(self, model, input_size=(1, 3, 224, 224), output_dir="configs/prob"):
        super().__init__(fx.symbolic_trace(model))
        self.input_size = input_size
        self.output_dir = output_dir
        self.generated_files = []
        os.makedirs(output_dir, exist_ok=True)

    def run(self):
        try:
            dummy_input = torch.randn(self.input_size)
            super().run(dummy_input)
        except Exception as e:
            print(f"  [Warning] FX Trace partial fail: {e}")
        return self.generated_files

    def call_module(self, target, args: tuple, kwargs: dict):
        output = super().call_module(target, args, kwargs)
        submod = self.fetch_attr(target)
        params = None
        # 替换非法字符，增加索引
        layer_idx = len(self.generated_files)
        layer_name = f"{layer_idx:03d}_" + target.replace('.', '_')
        
        if isinstance(submod, nn.Conv2d):
            input_tensor = args[0]
            N, C, H, W = input_tensor.shape
            _, M, P, Q = output.shape
            
            params = LayerParams(
                name=layer_name,
                N=N, C=C, M=M, P=P, Q=Q,
                R=submod.kernel_size[0], S=submod.kernel_size[1],
                Wstride=submod.stride[1], Hstride=submod.stride[0],
                Wdilation=submod.dilation[1], Hdilation=submod.dilation[0],
                Groups=submod.groups
            )
            
        if params:
            filename = os.path.join(self.output_dir, f"{layer_name}.yaml")
            self._write_yaml(filename, params)
            self.generated_files.append(filename)
            
        return output

    def _write_yaml(self, filename, params):
        problem = {
            'problem': {
                'version': 0.4,
                'shape': {
                    'name': 'CNN_Layer',
                    'dimensions': ['C', 'M', 'R', 'S', 'N', 'P', 'Q'],
                    'coefficients': [
                        {'name': 'Wstride', 'default': 1},
                        {'name': 'Hstride', 'default': 1},
                        {'name': 'Wdilation', 'default': 1},
                        {'name': 'Hdilation', 'default': 1}
                    ],
                    'data_spaces': [
                        {
                            'name': 'Weights', 
                            'projection': [[['C']], [['M']], [['R']], [['S']]]
                        },
                        {
                            'name': 'Inputs', 
                            'projection': [
                                [['N']], 
                                [['C']], 
                                # [修正] R/P 是高度，对应 Hdilation/Hstride
                                [['R', 'Hdilation'], ['P', 'Hstride']], 
                                # [修正] S/Q 是宽度，对应 Wdilation/Wstride
                                [['S', 'Wdilation'], ['Q', 'Wstride']]
                            ]
                        },
                        {
                            'name': 'Outputs', 
                            'projection': [[['N']], [['M']], [['P']], [['Q']]], 
                            'read_write': True
                        }
                    ]
                },
                'instance': {
                    'C': params.C, 'M': params.M, 'R': params.R, 'S': params.S,
                    'N': params.N, 'P': params.P, 'Q': params.Q,
                    'Wstride': getattr(params, 'Wstride', 1),
                    'Hstride': getattr(params, 'Hstride', 1),
                    'Wdilation': getattr(params, 'Wdilation', 1),
                    'Hdilation': getattr(params, 'Hdilation', 1)
                }
            }
        }
        with open(filename, 'w') as f:
            yaml.dump(problem, f, default_flow_style=False)

# === 管理器 ===
class WorkloadManager:
    def __init__(self, config_dir="configs/prob/generated"):
        self.config_dir = config_dir
        os.makedirs(self.config_dir, exist_ok=True)

    def generate_full_model(self, model_name="resnet18"):
        model_dir = os.path.join(self.config_dir, model_name)
        
        # 即使文件存在也强制重新生成，以确保修正后的格式被应用
        # existing_files = sorted(glob.glob(os.path.join(model_dir, "*.yaml")))
        # if len(existing_files) > 0: return existing_files

        print(f"[Workload] Generating full workload for {model_name}...")
        try:
            if model_name == "resnet18":
                model = models.resnet18()
            elif model_name == "mobilenet_v2":
                model = models.mobilenet_v2()
            else:
                model = models.resnet18()
            
            converter = WorkloadConverter(model, output_dir=model_dir)
            files = converter.run()
            print(f"[Workload] Generated {len(files)} layers.")
            return sorted(files)
            
        except Exception as e:
            print(f"[Error] Model conversion failed: {e}")
            return []
