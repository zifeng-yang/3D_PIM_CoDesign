# 文件路径: modules/arch_gen.py

import os
import jinja2
import yaml
import logging

# 注册 YAML 标签以防止 PyYAML 报错
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
            defaults = {
                'TECHNOLOGY': '28nm',
                'GLOBAL_CYCLE_SECONDS': '1e-9',
                'NUM_NODES': 1,
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

        # 简单的 YAML 验证
        try:
            yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            self.logger.error("Generated content is not valid YAML!")
            print(f"[ERROR CONTENT] {yaml_content[:200]}...") 
            raise e

        output_path = os.path.join(self.output_dir, filename)
        with open(output_path, 'w') as f:
            f.write(yaml_content)
            
        return output_path
