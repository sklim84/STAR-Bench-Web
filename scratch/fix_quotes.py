import os
import re

def fix_file(filepath):
    print(f"Fixing {filepath}...")
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # Replace \" with "
    new_content = content.replace('\\"', '"')
    
    if new_content != content:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return True
    return False

def main():
    paths = ['src', '_pages', 'app.py']
    for p in paths:
        if os.path.isfile(p):
            fix_file(p)
        else:
            for root, dirs, files in os.walk(p):
                for file in files:
                    if file.endswith('.py'):
                        fix_file(os.path.join(root, file))

if __name__ == "__main__":
    main()
