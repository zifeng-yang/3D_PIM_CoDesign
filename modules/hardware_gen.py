import os
import yaml
import logging
from jinja2 import Template, Environment, FileSystemLoader

# 配置日志
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')

class HardwareGenerator:
    # === NicePIM 论文核心硬件约束 (默认值) ===
    # 如果优化器没有传入特定值，将使用这些经过验证的参数
    PAPER_DEFAULTS = {
        # 核心架构参数
        'SRAM_DEPTH': 16384,        # 默认 16KB (会由优化器覆盖)
        'PE_DIM_X': 14,             # 默认阵列大小
        'PE_DIM_Y': 12,
        
        # 工艺与时序 (来自论文 Section VIII.B)
        'TECHNOLOGY': '28nm',       # 工艺节点
        'GLOBAL_CYCLE_SECONDS': 2.5e-9, # 400 MHz = 2.5 ns
        
        # 数据精度 (来自论文 Section VIII.B)
        'WORD_BITS': 16,            # Input/Output: 16-bit
        'ACCUM_BITS': 32,           # Partial Sum: 32-bit
        
        # 存储接口
        'DRAM_WIDTH': 64,           # 这里的 Width 是 Timeloop 接口宽度，非物理 128-bit
        'SRAM_WIDTH': 64,
        
        # 组件类型
        'MAC_CLASS': 'intmac'       # 整数运算单元
    }

    def __init__(self, template_path, output_dir):
        """
        初始化硬件生成器
        :param template_path: 架构模板文件的路径
        :param output_dir: 生成文件的存放目录
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
        :param design_params: 动态设计参数 (来自 TuRBO/BayesOpt)
        :param filename: 输出文件名
        """
        # 1. 准备渲染数据
        # 优先级：传入的 design_params > PAPER_DEFAULTS
        render_data = self.PAPER_DEFAULTS.copy()
        
        # 将传入的小写参数转换为大写（假设模板中使用大写变量如 {{ SRAM_DEPTH }}）
        # 并合并到渲染字典中
        for k, v in design_params.items():
            render_data[k.upper()] = v
            # 同时保留原键名，以防模板使用小写
            render_data[k] = v

        # [自动计算] 根据 SRAM 大小自动计算深度 (Depth = Bytes / (WordBits / 8))
        # 如果 design_params 传入的是 'sram_size' (Bytes)，我们需要转换为 depth
        if 'sram_size' in design_params:
            word_bytes = render_data['WORD_BITS'] // 8
            calculated_depth = design_params['sram_size'] // word_bytes
            render_data['SRAM_DEPTH'] = max(calculated_depth, 64) # 最小深度保护

        # 2. 加载模板
        try:
            # 使用 FileSystemLoader 可以支持模板继承 (include/extends)
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

        # 4. [关键] YAML 语法自检
        # 在写入文件前，尝试解析一下，确保生成的不是乱码
        try:
            yaml.safe_load(yaml_content)
        except yaml.YAMLError as e:
            logging.error("Generated content is not valid YAML!")
            logging.error(yaml_content) # 打印出来以便调试
            raise e

        # 5. 写入文件
        output_path = os.path.join(self.output_dir, filename)
        with open(output_path, 'w') as f:
            f.write(yaml_content)
        
        # logging.info(f"Hardware config generated: {output_path}")
        return output_path
