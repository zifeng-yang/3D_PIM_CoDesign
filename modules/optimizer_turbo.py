import math
import numpy as np
from skopt.space import Integer
from modules.visualizer import C_YELLOW, C_END

class TuRBOState:
    def __init__(self, dim, length_min=0.5, length_max=2.0, length_init=1.0):
        self.dim = dim
        self.length = length_init
        self.length_min = length_min
        self.length_max = length_max
        self.length_init = length_init 
        self.failure_counter = 0
        self.success_counter = 0
        self.best_value = float('inf')
        self.best_x = None
        self.succ_tol = 3
        self.fail_tol = 5 # 稍微放宽失败容忍度
        self.restart_count = 0

    def update(self, y, x):
        if y < self.best_value:
            self.best_value = y
            self.best_x = x
            self.success_counter += 1
            self.failure_counter = 0
        else:
            self.success_counter = 0
            self.failure_counter += 1

        # 动态调整信赖域
        if self.success_counter >= self.succ_tol:
            self.length = min(self.length * 2.0, self.length_max)
            self.success_counter = 0
        elif self.failure_counter >= self.fail_tol:
            self.length /= 2.0
            self.failure_counter = 0
        
        # 重启检测
        if self.length < self.length_min:
            self.length = self.length_init
            self.failure_counter = 0
            self.success_counter = 0
            self.restart_count += 1

    def get_trust_region_bounds(self, space):
        """
        计算信赖域边界，并针对整数空间进行特殊保护
        """
        if self.best_x is None: return space
        
        bounds = []
        for i, dim in enumerate(space):
            low, high = dim.low, dim.high
            
            # 计算半径
            range_width = high - low
            tr_radius = (self.length * range_width) / 2.0
            
            # [优化] 整数空间保护：半径至少为 1，否则无法探索邻居
            if isinstance(dim, Integer):
                tr_radius = max(1.0, tr_radius)

            center = self.best_x[i]
            
            x_min = int(max(low, center - tr_radius))
            x_max = int(min(high, center + tr_radius))
            
            # [优化] 确保窗口并未塌缩 (至少保留 3 个点的宽度用于探索，除非触碰边界)
            # 如果 x_min == x_max，TuRBO 就无法采样新点
            if x_max == x_min:
                if x_min > low: x_min -= 1
                elif x_max < high: x_max += 1
            
            bounds.append(Integer(x_min, x_max, name=dim.name))
        return bounds
