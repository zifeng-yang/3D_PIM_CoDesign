<<<<<<< HEAD
# 文件路径: modules/arch_gen.py

import os
import jinja2
import yaml
import logging

# [保持不变] 注册 YAML 标签
def dummy_constructor(loader, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    elif isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node)
    return None

for tag in ['!Container', '!Component', '!Hierarchical', '!Parallel', '!Pipelined', '!Nothing']:
    yaml.SafeLoader.add_constructor(tag, dummy_constructor)

class ArchGenerator:
    def __init__(self, template_path, output_dir):
        self.template_path = template_path
        self.output_dir = output_dir
        self.logger = logging.getLogger("ArchGen")
        
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
            
        template_dir = os.path.dirname(template_path)
        template_file = os.path.basename(template_path)
        self.env = jinja2.Environment(loader=jinja2.FileSystemLoader(template_dir))
        self.template = self.env.get_template(template_file)

    def generate_config(self, params, filename="arch.yaml"):
        try:
            # 在 defaults 字典中添加 NUM_NODES
            defaults = {
                'TECHNOLOGY': '28nm',
                'GLOBAL_CYCLE_SECONDS': '1e-9',
                'NUM_NODES': 1,      # [New] 默认节点数
                'DRAM_WIDTH': 64,
                'WORD_BITS': 16,
                'SRAM_WIDTH': 64,
                'SRAM_DEPTH': 32768, 
                'PE_DIM_X': 4,       
                'PE_DIM_Y': 4,       
                'MAC_CLASS': 'intmac'
            }
            render_context = {**defaults, **params}
            yaml_content = self.template.render(render_context)
            
        except Exception as e:
            self.logger.error(f"Jinja2 Rendering failed: {e}")
            raise e

        try:
            yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            self.logger.error("Generated content is not valid YAML!")
            print(f"[ERROR CONTENT] {yaml_content[:200]}...") 
            raise e

        output_path = os.path.join(self.output_dir, filename)
        with open(output_path, 'w') as f:
            f.write(yaml_content)
            
=======
import os
import yaml
import logging
from jinja2 import Template, Environment, FileSystemLoader

# 配置日志
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

class ArchGenerator:
    # === NicePIM 论文核心硬件约束 (默认值) ===
    # 这里的参数直接对应论文 Table IV 和 Section VIII.B
    PAPER_DEFAULTS = {
        # 核心架构参数 (会被优化器覆盖)
        'SRAM_DEPTH': 16384,        
        'PE_DIM_X': 14,             
        'PE_DIM_Y': 12,
        
        # 工艺与时序
        'TECHNOLOGY': '28nm',       
        'GLOBAL_CYCLE_SECONDS': 2.5e-9, # 400 MHz
        
        # 数据精度
        'WORD_BITS': 16,            
        'ACCUM_BITS': 32,           
        
        # 存储接口
        'DRAM_WIDTH': 64,           
        'SRAM_WIDTH': 64,
        
        # 组件类型
        'MAC_CLASS': 'intmac'       
    }

    def __init__(self, template_path, output_dir):
        """
        初始化硬件生成器
        """
        self.template_path = template_path
        self.output_dir = output_dir
        
        # 路径预处理
        self.template_dir = os.path.dirname(self.template_path)
        self.template_file = os.path.basename(self.template_path)

        if not os.path.exists(self.output_dir):
            os.makedirs(self.output_dir, exist_ok=True)

    def generate_config(self, design_params, filename="arch_generated.yaml"):
        """
        生成 YAML 配置文件
        """
        # 1. 准备渲染数据 (合并默认值与动态参数)
        render_data = self.PAPER_DEFAULTS.copy()
        
        for k, v in design_params.items():
            render_data[k.upper()] = v
            render_data[k] = v

        # [自动计算] 根据 SRAM 大小(Bytes)自动计算深度
        if 'sram_size' in design_params:
            word_bytes = render_data['WORD_BITS'] // 8
            calculated_depth = design_params['sram_size'] // word_bytes
            render_data['SRAM_DEPTH'] = max(calculated_depth, 64)

        # 2. 加载模板
        try:
            env = Environment(loader=FileSystemLoader(self.template_dir))
            template = env.get_template(self.template_file)
        except Exception as e:
            logging.error(f"Failed to load template from {self.template_path}")
            raise e

        # 3. 渲染内容
        try:
            yaml_content = template.render(render_data)
        except Exception as e:
            logging.error(f"Jinja2 rendering failed. Params: {render_data.keys()}")
            raise e

        # 4. YAML 语法自检
        try:
            yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            logging.error("Generated content is not valid YAML!")
            logging.error(yaml_content)
            raise e

        # 5. 写入文件
        output_path = os.path.join(self.output_dir, filename)
        with open(output_path, 'w') as f:
            f.write(yaml_content)
        
>>>>>>> d2ec8543f2de6810717e0b3d892adc03f09692e8
        return output_path
