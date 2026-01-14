import os
import yaml
import torch
import torch.nn as nn
import torch.fx as fx
from dataclasses import dataclass

# === 1. 定义层描述数据结构 (简化版) ===
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

    def to_timeloop_yaml(self):
        """生成 Timeloop 问题描述"""
        # 处理 Depthwise 卷积 (Groups > 1 且 Groups == C)
        if self.Groups > 1 and self.Groups == self.C:
            # Depthwise: 把 C 设为 1，Groups 设为原 C
            # Timeloop 通常将 Depthwise 建模为 M=C 的特殊卷积
            problem_dims = ['R', 'S', 'P', 'Q', 'C', 'N'] 
            instance = {
                'R': self.R, 'S': self.S, 'P': self.P, 'Q': self.Q,
                'C': self.C, 'N': self.N, # Depthwise 下 M=C
                'Wstride': self.Wstride, 'Hstride': self.Hstride,
                'Wdilation': self.Wdilation, 'Hdilation': self.Hdilation
            }
            shape_name = "DepthWise_Conv"
        else:
            # 标准卷积
            problem_dims = ['R', 'S', 'P', 'Q', 'C', 'M', 'N']
            instance = {
                'R': self.R, 'S': self.S, 'P': self.P, 'Q': self.Q,
                'C': self.C // self.Groups, 'M': self.M // self.Groups, # 分组处理
                'N': self.N,
                'Wstride': self.Wstride, 'Hstride': self.Hstride,
                'Wdilation': self.Wdilation, 'Hdilation': self.Hdilation
            }
            shape_name = "CNN_Layer"

        config = {
            'problem': {
                'shape': {
                    'name': shape_name,
                    'dimensions': problem_dims,
                    # ... 省略了 data-spaces 的详细定义，使用 Timeloop 默认模板即可
                    # 为简化代码，这里假设 Timeloop 能够根据 dimension 自动推断 data-space
                    # 或者我们使用通用的 CNN_Layer 模板
                },
                'instance': instance
            }
        }
        return config

# === 2. FX 解释器用于提取层信息 ===
class WorkloadConverter(fx.Interpreter):
    def __init__(self, model, input_size=(1, 3, 224, 224), output_dir="configs/prob"):
        super().__init__(fx.symbolic_trace(model))
        self.input_size = input_size
        self.output_dir = output_dir
        self.generated_files = []
        os.makedirs(output_dir, exist_ok=True)

    def run(self):
        # 运行一次以前向传播获取 shape
        dummy_input = torch.randn(self.input_size)
        super().run(dummy_input)
        return self.generated_files

    def call_module(self, target, args: tuple, kwargs: dict):
        # 执行实际模块以获取输出 shape
        output = super().call_module(target, args, kwargs)
        
        # 获取子模块对象
        submod = self.fetch_attr(target)
        
        # 提取参数
        params = None
        layer_name = target.replace('.', '_')
        
        if isinstance(submod, nn.Conv2d):
            # args[0] 是输入 tensor
            input_tensor = args[0]
            N, C, H, W = input_tensor.shape
            
            # 计算输出 P, Q (output.shape 也可以直接用)
            _, M, P, Q = output.shape
            
            params = LayerParams(
                name=layer_name,
                N=N, C=C, M=M, P=P, Q=Q,
                R=submod.kernel_size[0], S=submod.kernel_size[1],
                Wstride=submod.stride[1], Hstride=submod.stride[0],
                Wdilation=submod.dilation[1], Hdilation=submod.dilation[0],
                Groups=submod.groups
            )
            
        elif isinstance(submod, nn.Linear):
            # 转换为 1x1 卷积处理
            input_tensor = args[0]
            # Linear 输入通常是 (N, *, Cin)，输出 (N, *, Cout)
            # 简化：假设输入是平铺的 (N, Cin)
            if len(input_tensor.shape) == 2:
                N, Cin = input_tensor.shape
                Cout = submod.out_features
                params = LayerParams(
                    name=layer_name,
                    N=N, C=Cin, M=Cout, P=1, Q=1, R=1, S=1
                )

        # 保存为 YAML
        if params:
            filename = f"{self.output_dir}/{layer_name}.yaml"
            self._write_yaml(filename, params)
            self.generated_files.append(filename)
            
        return output

    def _write_yaml(self, filename, params):
        # 这里为了确保 Timeloop 能跑，我们需要注入完整的 data-space 定义
        # 使用一个标准的 CNN 模板
        base_yaml = {
            'problem': {
                'shape': {
                    'name': 'CNN_Layer',
                    'dimensions': ['C', 'M', 'R', 'S', 'N', 'P', 'Q'],
                    'data-spaces': [
                        {'name': 'Weights', 'projection': [['C'], ['M'], ['R'], ['S']]},
                        {'name': 'Inputs', 'projection': [['N'], ['C'], ['R'], ['S'], ['P'], ['Q']]}, # 简化投影，实际需加上 stride 逻辑
                        {'name': 'Outputs', 'projection': [['N'], ['M'], ['P'], ['Q']], 'read-write': True}
                    ]
                },
                'instance': {
                    'C': params.C, 'M': params.M, 'R': params.R, 'S': params.S,
                    'N': params.N, 'P': params.P, 'Q': params.Q
                }
            }
        }
        
        # 修正 Inputs 投影以支持 stride (Timeloop 语法)
        # R*1 + P*Wstride
        # 这里直接生成简单的 version，Timeloop v4 支持更简单的写法
        # 如果使用旧版 Timeloop，可能需要复杂的 coefficients
        # 这里我们生成最简配置，假设 Timeloop 能处理
        
        with open(filename, 'w') as f:
            yaml.dump(base_yaml, f, default_flow_style=False)

def convert_torch_model(model_name, save_dir="configs/prob/generated"):
    import torchvision.models as models
    
    print(f"[Converter] Loading {model_name} from torchvision...")
    try:
        if model_name == "mobilenet_v2":
            model = models.mobilenet_v2()
        elif model_name == "resnet18":
            model = models.resnet18()
        else:
            model = models.mobilenet_v2() # Default
    except:
        print("Model not found, using MobileNetV2")
        model = models.mobilenet_v2()
        
    converter = WorkloadConverter(model, output_dir=save_dir)
    files = converter.run()
    print(f"[Converter] Generated {len(files)} layer configs in {save_dir}")
    return files
