import sys
import time
import threading
import itertools
from datetime import datetime

# === 颜色代码 ===
C_RED    = "\033[91m"
C_GREEN  = "\033[92m"
C_YELLOW = "\033[93m"
C_BLUE   = "\033[94m"
C_CYAN   = "\033[96m"
C_END    = "\033[0m"

class DualProgressBar:
    def __init__(self, mode, total_layers):
        self.mode = mode.upper()
        self.total_layers = total_layers
        
        # 层级状态 (Global)
        self.current_layer_idx = 0
        self.current_layer_name = "Init"
        
        # 步骤状态 (Local)
        self.current_step_idx = 0
        self.total_steps = 5  # Config, Map, Parse, NoC, Calc
        self.step_name = "Waiting"
        
        # 时间记录
        self.start_time = time.time()
        self.layer_start_time = time.time()
        self.start_str = datetime.now().strftime('%H:%M:%S')
        
        # 线程控制
        self.stop_event = threading.Event()
        self.stream = sys.__stdout__
        self.thread = threading.Thread(target=self._render)

    def start(self):
        print(f"{C_BLUE}[System] Task Started at: {self.start_str}{C_END}")
        self.thread.start()

    def update_layer(self, idx, name):
        """更新外层进度（哪一层）"""
        self.current_layer_idx = idx
        self.current_layer_name = name
        self.layer_start_time = time.time()
        self.current_step_idx = 0
        self.step_name = "Init"

    def update_step(self, idx, name):
        """更新内层进度（哪一步）"""
        self.current_step_idx = idx
        self.step_name = name

    def finish(self):
        self.stop_event.set()
        self.thread.join()
        self.stream.write('\n') # 换行防止覆盖最后一行结果
        self.stream.flush()

    def _render(self):
        spinner = itertools.cycle(['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'])
        bar_len = 8 # 进度条长度
        
        while not self.stop_event.is_set():
            now = time.time()
            total_elapsed = now - self.start_time
            layer_elapsed = now - self.layer_start_time
            
            # 1. 总进度 (Layer N/Total)
            l_pct = min(1.0, self.current_layer_idx / max(1, self.total_layers))
            l_fill = int(bar_len * l_pct)
            l_bar = '█' * l_fill + '░' * (bar_len - l_fill)
            
            # 2. 当前层步骤进度 (Step N/5)
            s_pct = min(1.0, self.current_step_idx / max(1, self.total_steps))
            s_fill = int(bar_len * s_pct)
            s_bar = '▓' * s_fill + '▒' * (bar_len - s_fill)
            
            spin = next(spinner)
            
            # 格式设计：
            # [MODE] Lyr: 2/20 [██░░] ResNet_L2 | Stp: 3/5 [▓▓▒▒] NoC Sim | ⠋ 3.2s (Tot:15s)
            status = (
                f"\r{C_BLUE}[{self.mode}]{C_END} "
                f"Lyr: {self.current_layer_idx}/{self.total_layers} {C_GREEN}[{l_bar}]{C_END} {self.current_layer_name[:12]:<12} | "
                f"Stp: {self.current_step_idx}/{self.total_steps} {C_YELLOW}[{s_bar}]{C_END} {self.step_name:<10} | "
                f"{spin} {layer_elapsed:.1f}s (Tot:{total_elapsed:.0f}s)   "
            )
            
            self.stream.write(status)
            self.stream.flush()
            time.sleep(0.1)
