import pandas as pd
import numpy as np

def inspect():
    print("=== 1. Reading CSV ===")
    try:
        df = pd.read_csv("optimization_results.csv")
    except Exception as e:
        print(f"[Fatal Error] Cannot read CSV: {e}")
        return

    print(f"Shape: {df.shape} (Rows, Columns)")
    print("\n=== 2. Column Data Types ===")
    print(df.dtypes)

    print("\n=== 3. First 5 Rows ===")
    print(df.head())

    print("\n=== 4. Checking for NaN/Infinity ===")
    if df.isnull().values.any():
        print("[Warning] Found NaN values!")
        print(df.isnull().sum())
    else:
        print("[OK] No NaN values found.")

    print("\n=== 5. Checking 'EDP' Column ===")
    # 检查 EDP 是否真的是数字
    if not np.issubdtype(df['EDP'].dtype, np.number):
        print("[CRITICAL ERROR] 'EDP' column is NOT numeric! Check for strings like 'Failed'.")
    else:
        print(f"[OK] EDP is numeric. Min: {df['EDP'].min()}, Max: {df['EDP'].max()}")

if __name__ == "__main__":
    inspect()
