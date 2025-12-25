import sys
import os
import glob
import argparse
import pytimeloop.timeloopfe.v4 as tl

def main():
    parser = argparse.ArgumentParser(description="Run Timeloop v0.4 inside Docker")
    parser.add_argument("--arch", required=True, help="Path to arch.yaml")
    parser.add_argument("--prob", required=True, help="Path to prob.yaml")
    parser.add_argument("--mapper", required=True, help="Path to mapper.yaml")
    parser.add_argument("--comp-dir", required=True, help="Directory containing components")
    parser.add_argument("--output-dir", required=True, help="Output directory")
    
    args = parser.parse_args()

    print(f"[Docker-Internal] Loading v0.4 specs...")
    print(f"  Arch: {args.arch}")
    print(f"  Prob: {args.prob}")

    # 1. 收集所有 YAML 文件路径
    input_files = [args.arch, args.prob, args.mapper]
    
    # 2. 加入组件文件
    if os.path.exists(args.comp_dir):
        comp_files = glob.glob(os.path.join(args.comp_dir, "*.yaml"))
        input_files.extend(comp_files)
        print(f"  Components loaded: {len(comp_files)}")

    # 3. 使用 PyTimeloop 加载 v0.4 规范
    # 这是最关键的一步，它会自动处理 'nodes' 到 'subtree' 的转换
    try:
        spec = tl.Specification.from_yaml_files(*input_files)
    except Exception as e:
        print(f"[Docker-Internal] Error parsing YAMLs: {e}")
        sys.exit(1)

    # 4. 调用 Mapper
    print(f"[Docker-Internal] Calling C++ Mapper Engine...")
    # output_dir 会自动创建子文件夹，所以我们指向 output_dir 即可
    # 注意：timeloopfe 通常会在 output_dir 下创建 arch_xml 等文件
    try:
        tl.call_mapper(spec, output_dir=args.output_dir)
        print("[Docker-Internal] Mapper finished successfully.")
    except Exception as e:
        print(f"[Docker-Internal] Mapper failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
