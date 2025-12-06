#!/usr/bin/env python3
"""
Fix imports to use src. prefix for Docker compatibility
"""
import re
from pathlib import Path


def fix_imports_in_file(filepath: Path) -> bool:
    """Fix imports in a single file."""
    try:
        with open(filepath, encoding='utf-8') as f:
            content = f.read()

        original_content = content

        # Pattern to match imports that need fixing
        patterns = [
            (r'^from (config|core|caching|monitoring|streaming|rate_limiting|llm_providers|message_queue)\.', r'from src.\1.'),
            (r'^from (config|core|caching|monitoring|streaming|rate_limiting|llm_providers|message_queue) import', r'from src.\1 import'),
        ]

        for pattern, replacement in patterns:
            content = re.sub(pattern, replacement, content, flags=re.MULTILINE)

        if content != original_content:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"Fixed: {filepath}")
            return True
        return False
    except Exception as e:
        print(f"Error processing {filepath}: {e}")
        return False

def main():
    """Main function to fix all Python files."""
    src_dir = Path(__file__).parent / 'src'

    if not src_dir.exists():
        print(f"Error: {src_dir} does not exist")
        return

    fixed_count = 0
    for py_file in src_dir.rglob('*.py'):
        if fix_imports_in_file(py_file):
            fixed_count += 1

    print(f"\nTotal files fixed: {fixed_count}")

if __name__ == '__main__':
    main()
