# 文件路径: modules/wrapper_timeloop.py

import subprocess
import os
import sys
import time
import threading

class TimeloopWrapper:
    def __init__(self, docker_image_name="timeloopaccelergy/timeloop-accelergy-pytorch:latest-amd64"):
        self.image = docker_image_name
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
        # 清除行
        sys.stdout.write("\r" + " " * 80 + "\r")
        sys.stdout.flush()

    def run_mapper(self, arch_path, prob_path, mapper_path, output_dir, component_dir=None):
        host_uid = os.getuid()
        host_gid = os.getgid()

        # Docker 命令构建 (保持不变)
        user_cmd = f"--user {host_uid}:{host_gid}"
        env_cmd = "-e HOME=/home/workspace"
        entrypoint_cmd = "--entrypoint /bin/sh"
        mount_cmd = f"-v {self.project_root}:/home/workspace"
        
        def to_container_path(host_path):
            if not host_path: return ""
            rel_path = os.path.relpath(host_path, self.project_root)
            return f"/home/workspace/{rel_path}"

        c_arch   = to_container_path(arch_path)
        c_prob   = to_container_path(prob_path)
        c_mapper = to_container_path(mapper_path)
        c_out    = to_container_path(output_dir)
        c_comp   = to_container_path(component_dir) if (component_dir and os.path.exists(component_dir)) else ""
        
        bridge_script = "/home/workspace/modules/run_v4_inside_docker.py"
        
        python_cmd = (
            f"python3 {bridge_script} "
            f"--arch {c_arch} "
            f"--prob {c_prob} "
            f"--mapper {c_mapper} "
            f"--output-dir {c_out}"
        )
        if c_comp:
            python_cmd += f" --comp-dir {c_comp}"

        docker_cmd = (
            f"docker run --rm {entrypoint_cmd} {user_cmd} {env_cmd} {mount_cmd} -w {c_out} {self.image} "
            f"-c '{python_cmd}'"
        )
        
        # === [UI 优化核心] ===
        stop_spinner = threading.Event()
        spinner_thread = threading.Thread(target=self._spinner_task, args=(stop_spinner,))
        
        # 捕获输出用于错误诊断，但不直接打印
        captured_output = []
        
        try:
            spinner_thread.start() # 启动动画
            
            process = subprocess.Popen(
                docker_cmd, 
                shell=True, 
                stdout=subprocess.PIPE, 
                stderr=subprocess.STDOUT,
                text=True
            )
            
            # 实时读取输出但不打印，防止缓冲区满死锁
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
                # 只打印最后 30 行错误日志
                print("".join(captured_output[-30:])) 
                print("-" * 50)
                return False
                
        except Exception as e:
            stop_spinner.set()
            spinner_thread.join()
            print(f"\n  [Exception] Failed to run Docker command: {e}")
            return False
