import subprocess
import os

class TimeloopWrapper:
    def __init__(self, docker_image_name="timeloopaccelergy/timeloop-accelergy-pytorch:latest-amd64"):
        self.image = docker_image_name
        self.project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        
    def run_mapper(self, arch_path, prob_path, mapper_path, output_dir, component_dir=None):
        host_uid = os.getuid()
        host_gid = os.getgid()

        # [FIX 1] 保持 User 模式，确保文件归属权是你
        user_cmd = f"--user {host_uid}:{host_gid}"
        
        # [FIX 2] 设置 HOME，防止工具因无法访问 /root 而崩溃
        env_cmd = "-e HOME=/home/workspace"

        # [FIX 3 - NEW] 关键修改：绕过容器的 s6-overlay 启动脚本
        # 直接调用 shell，彻底根除 "s6-chown: permission denied" 这种噪音
        entrypoint_cmd = "--entrypoint /bin/sh"

        mount_cmd = f"-v {self.project_root}:/home/workspace"
        
        def to_container_path(host_path):
            rel_path = os.path.relpath(host_path, self.project_root)
            return f"/home/workspace/{rel_path}"

        c_arch   = to_container_path(arch_path)
        c_prob   = to_container_path(prob_path)
        c_mapper = to_container_path(mapper_path)
        c_out    = to_container_path(output_dir)
        c_comp   = to_container_path(component_dir) if component_dir else ""
        
        bridge_script = "/home/workspace/modules/run_v4_inside_docker.py"

        # 构建 Python 命令
        python_cmd = (
            f"python3 {bridge_script} "
            f"--arch {c_arch} "
            f"--prob {c_prob} "
            f"--mapper {c_mapper} "
            f"--comp-dir {c_comp} "
            f"--output-dir {c_out}"
        )

        # 组合 Docker 命令
        # 使用 -c 将 python 命令传给 /bin/sh
        docker_cmd = (
            f"docker run --rm {entrypoint_cmd} {user_cmd} {env_cmd} {mount_cmd} -w {c_out} {self.image} "
            f"-c '{python_cmd}'"
        )
        
        try:
            result = subprocess.run(docker_cmd, shell=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            # print(result.stdout.decode()) # 调试用
            print("[LabLog] Simulation finished successfully.")
            return True
            
        except subprocess.CalledProcessError as e:
            # 只有当 Python 脚本真正失败（比如 Mapper 找不到解）时，这里才会报错
            # 我们不打印 stderr，因为 Timeloop 的失败信息通常在 stdout 里或者文件中
            print(f"[Warning] Timeloop Mapper failed to find a valid mapping (Hardware might be too small).")
            return False
