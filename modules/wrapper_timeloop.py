# 文件路径: modules/wrapper_timeloop.py

import subprocess
import os
import sys
import time
import threading

class TimeloopWrapper:
    def __init__(self, docker_image_name="timeloopaccelergy/timeloop-accelergy-pytorch:latest-amd64"):
        self.image = docker_image_name
        # 自动定位项目根目录 (假设此脚本在 modules/ 下)
        self.project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        
    def _spinner_task(self, stop_event):
        """显示旋转动画的后台线程"""
        spinner_chars = ['|', '/', '-', '\\']
        idx = 0
        start_time = time.time()
        while not stop_event.is_set():
            elapsed = time.time() - start_time
            sys.stdout.write(f"\r  >> [Timeloop Running] Searching Mapspace... {spinner_chars[idx]} ({elapsed:.1f}s)")
            sys.stdout.flush()
            idx = (idx + 1) % len(spinner_chars)
            time.sleep(0.1)
        sys.stdout.write("\r" + " " * 80 + "\r")
        sys.stdout.flush()

    def run_mapper(self, arch_path, prob_path, mapper_path, output_dir, component_dir=None):
        host_uid = os.getuid()
        host_gid = os.getgid()

        user_cmd = f"--user {host_uid}:{host_gid}"
        env_cmd = "-e HOME=/home/workspace"
        entrypoint_cmd = "--entrypoint /bin/sh"
        mount_cmd = f"-v {self.project_root}:/home/workspace"
        
        # 路径映射辅助函数
        def to_container_path(host_path):
            if not host_path or not os.path.exists(host_path):
                return ""
            abs_host = os.path.abspath(host_path)
            abs_root = os.path.abspath(self.project_root)
            if abs_host.startswith(abs_root):
                rel_path = os.path.relpath(abs_host, abs_root)
                return f"/home/workspace/{rel_path}"
            return ""

        # 转换路径
        c_arch   = to_container_path(arch_path)
        c_prob   = to_container_path(prob_path)
        c_mapper = to_container_path(mapper_path)
        c_out    = to_container_path(output_dir)
        c_comp   = to_container_path(component_dir) if component_dir else ""

        # [关键检查] 确保所有必要参数都不为空
        if not c_arch or not c_prob or not c_mapper or not c_out:
            print(f"\n  [Wrapper Error] Invalid paths detected:")
            print(f"    Arch: {arch_path} -> {c_arch}")
            print(f"    Prob: {prob_path} -> {c_prob}")
            print(f"    Mapper: {mapper_path} -> {c_mapper}")
            return False

        bridge_script = "/home/workspace/modules/run_v4_inside_docker.py"
        
        # 构建 Python 命令 (注意引号的使用)
        python_cmd = (
            f"python3 {bridge_script} "
            f"--arch {c_arch} "
            f"--prob {c_prob} "
            f"--mapper {c_mapper} "
            f"--output-dir {c_out}"
        )
        if c_comp:
            python_cmd += f" --comp-dir {c_comp}"

        # 组合 Docker 命令
        docker_cmd = (
            f"docker run --rm {entrypoint_cmd} {user_cmd} {env_cmd} {mount_cmd} -w {c_out} {self.image} "
            f"-c '{python_cmd}'"
        )
        
        # UI 动画与执行
        stop_spinner = threading.Event()
        spinner_thread = threading.Thread(target=self._spinner_task, args=(stop_spinner,))
        captured_output = []
        
        try:
            spinner_thread.start()
            
            process = subprocess.Popen(
                docker_cmd, 
                shell=True, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT,
                text=True
            )
            
            for line in process.stdout:
                captured_output.append(line)
            
            process.wait()
            stop_spinner.set()
            spinner_thread.join()

            if process.returncode == 0:
                print(f"  >> [Timeloop] Mapping Finished Successfully. ✅")
                return True
            else:
                print(f"\n  [Error] Timeloop exited with code {process.returncode} ❌")
                print("-" * 50)
                print("".join(captured_output[-30:])) # 打印最后30行日志
                print("-" * 50)
                return False
                
        except Exception as e:
            stop_spinner.set()
            spinner_thread.join()
            print(f"\n  [Exception] Failed to run Docker command: {e}")
            return False
