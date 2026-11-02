import os, re
# Resolve frontend/src relative to this script so the audit works from any
# working directory (npm runs it from frontend/, which previously scanned 0 files).
SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src')
color_pattern = re.compile(r'\b(bg|text|border|ring)-(indigo|blue|purple|violet)-[456789]00\b')

for root, _, files in os.walk(SRC_DIR):
    for file in files:
        if file.endswith('.tsx') or file.endswith('.ts'):
            filepath = os.path.join(root, file)
            with open(filepath, 'r') as f:
                lines = f.readlines()
                for i, line in enumerate(lines):
                    if color_pattern.search(line):
                        print(f"{filepath}:{i+1}: {line.strip()}")
