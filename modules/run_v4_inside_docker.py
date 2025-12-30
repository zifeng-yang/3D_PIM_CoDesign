# 文件路径: modules/run_v4_inside_docker.py

import argparse
import subprocess
import os
import sys
import shutil
import glob

def main():
    parser = argparse.ArgumentParser(description="Run Timeloop v4 via 'tl' frontend")
    parser.add_argument("--arch", required=True, help="Path to architecture YAML")
    parser.add_argument("--prob", required=True, help="Path to problem YAML")
    parser.add_argument("--mapper", required=True, help="Path to mapper YAML")
    parser.add_argument("--comp-dir", required=False, help="Path to component directory")
    parser.add_argument("--output-dir", required=True, help="Output directory")

    args = parser.parse_args()
    os.makedirs(args.output_dir, exist_ok=True)
    
    # 1. 构建基础命令
    cmd = ["tl", "mapper", args.arch, args.prob, args.mapper]

    # 2. [关键修复] 注入所有组件定义文件
    # Timeloop 需要读取 smartbuffer_SRAM.yaml 等文件才能理解架构中的 class 定义
    if args.comp_dir and os.path.exists(args.comp_dir):
        comp_files = glob.glob(os.path.join(args.comp_dir, "*.yaml"))
        cmd.extend(comp_files)
        print(f"[Docker-Internal] Including {len(comp_files)} component specs from {args.comp_dir}")

    print(f"[Docker-Internal] Using 'tl mapper' frontend...")
    # print(f"  CMD: {' '.join(cmd)}") # Debug info

    try:
        # 3. 执行命令
        process = subprocess.Popen(
            cmd,
            cwd=args.output_dir,
            stdout=sys.stdout,
            stderr=sys.stderr,
            text=True
        )
        process.wait()
        
        if process.returncode != 0:
            print(f"[Docker-Internal] 'tl mapper' failed with return code {process.returncode}")
            sys.exit(process.returncode)
            
        # 4. 结果文件兼容处理
        # 'tl' 默认生成 stats.txt，我们需要确保 ResultParser 能找到它
        stats_file = os.path.join(args.output_dir, "stats.txt")
        target_file = os.path.join(args.output_dir, "timeloop-mapper.stats.txt")
        
        if os.path.exists(stats_file) and not os.path.exists(target_file):
            shutil.copy(stats_file, target_file)
            
        # 复制其他关键输出文件
        for ext in ["ART.yaml", "ERT.yaml", "ART_summary.yaml", "ERT_summary.yaml"]:
             base_f = os.path.join(args.output_dir, ext)
             target_f = os.path.join(args.output_dir, f"timeloop-mapper.{ext}")
             if os.path.exists(base_f) and not os.path.exists(target_f):
                 shutil.copy(base_f, target_f)

    except Exception as e:
        print(f"[Docker-Internal] Exception: {e}")
        sys.exit(1)

    print("[Docker-Internal] Mapper finished successfully.")

if __name__ == "__main__":
    main()
