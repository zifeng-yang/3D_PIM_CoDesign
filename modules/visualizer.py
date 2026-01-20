import sys
import time
import threading
import itertools
import shutil

# ==========================================
# ANSI Color Codes
# ==========================================
C_HEADER = '\033[95m'
C_BLUE = '\033[94m'
C_CYAN = '\033[96m'
C_GREEN = '\033[92m'
C_YELLOW = '\033[93m'
C_RED = '\033[91m'
C_PURPLE = '\033[95m'
C_END = '\033[0m'
C_BOLD = '\033[1m'
C_UNDERLINE = '\033[4m'

# 光标控制
CURSOR_HIDE = '\033[?25l'
CURSOR_SHOW = '\033[?25h'

# ==========================================
# Async Spinner (防刷屏版)
# ==========================================
class AsyncSpinner:
    def __init__(self, message="", interval=0.1):
        self.message = message
        self.interval = interval
        self.stop_event = threading.Event()
        self.thread = None
        self.lock = threading.Lock()
        # Braille 字符
        self.spinner_cycle = itertools.cycle(['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏'])

    def __enter__(self):
        # 如果不是终端（如重定向到文件），直接打印并跳过
        if not sys.stdout.isatty():
            print(self.message)
            return self

        sys.stdout.write(CURSOR_HIDE)
        sys.stdout.flush()
        
        self.stop_event.clear()
        self.thread = threading.Thread(target=self._spin)
        self.thread.daemon = True 
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.thread:
            self.stop_event.set()
            self.thread.join()
            
            # 恢复光标并清理行
            sys.stdout.write(f"\r{CURSOR_SHOW}")
            # 用静态消息覆盖，清除 spinner 字符
            # 这里我们需要重新计算长度以清除残留
            cols = shutil.get_terminal_size((80, 20)).columns
            clean_msg = self._truncate(self.message, cols - 1)
            sys.stdout.write(f"\r{clean_msg} \033[K") # \033[K 清除行尾
            sys.stdout.flush()

    def _truncate(self, text, max_len):
        """简单粗暴的截断，忽略颜色代码长度的精细计算（为了性能和稳定性）"""
        # 注意：这里按字符截断，ANSI颜色代码可能会占用长度导致实际显示更短，
        # 但这比换行刷屏要好。为了安全，我们预留更多空间。
        if len(text) > max_len:
            return text[:max_len-3] + "..."
        return text

    def _spin(self):
        while not self.stop_event.is_set():
            spin_char = next(self.spinner_cycle)
            
            # 获取当前终端宽度
            cols = shutil.get_terminal_size((80, 20)).columns
            # 预留 5 个字符给 spinner 和边距
            avail_len = max(10, cols - 5)
            
            # 构造行内容
            display_msg = self._truncate(self.message, avail_len)
            line = f"\r{display_msg} {C_GREEN}{spin_char}{C_END}\033[K"
            
            with self.lock:
                sys.stdout.write(line)
                sys.stdout.flush()
            
            time.sleep(self.interval)

    def update_message(self, new_message):
        self.message = new_message

# ==========================================
# Legacy Helper
# ==========================================
class DualProgressBar:
    def __init__(self, task_name, total_steps): pass
