import os, re
# Resolve frontend/src relative to this script so the audit works from any
# working directory (npm runs it from frontend/, which previously scanned 0 files).
SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src')
for root, _, files in os.walk(SRC_DIR):
    for file in files:
        if file.endswith('.tsx') or file.endswith('.ts'):
            filepath = os.path.join(root, file)
            with open(filepath, 'r') as f:
                content = f.read()
                if '/ 5000' in content or '/ 4000' in content or 'length * width' in content or 'divisor' in content:
                    print(f"VOLUMETRIC MATH IN {filepath}")
                    lines = content.split('\n')
                    for i, line in enumerate(lines):
                        if '/ 5000' in line or '/ 4000' in line or 'length * width' in line:
                            print(f"{i+1}: {line.strip()}")
