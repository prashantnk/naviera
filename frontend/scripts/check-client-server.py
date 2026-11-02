import os

# Resolve frontend/src relative to this script so the audit works from any
# working directory (npm runs it from frontend/, which previously scanned 0 files).
SRC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'src')
directories = [os.path.join(SRC_DIR, 'app'), os.path.join(SRC_DIR, 'components')]
for directory in directories:
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith('.tsx') or file.endswith('.ts'):
                path = os.path.join(root, file)
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        has_client = '"use client"' in content or "'use client'" in content
                        has_server = '"use server"' in content or "'use server'" in content
                        
                        has_hooks = 'useState(' in content or 'useEffect(' in content or 'useContext(' in content or 'useRef(' in content
                        
                        if has_hooks and not has_client:
                            print(f"MISSING 'use client' (has hooks): {path}")
                        
                        if has_client and has_server:
                            print(f"BOTH 'use client' AND 'use server': {path}")
                            
                except Exception as e:
                    pass
