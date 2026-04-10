import re

with open('ppt_engine_v2.py', 'r', encoding='utf-8') as f:
    content = f.read()

lines = content.split('\n')
fixed_lines = []
count = 0

for line in lines:
    stripped = line.strip()
    # 匹配以 f' 开头且包含 c[" 的行
    if (stripped.startswith("f'") or stripped.startswith("f'")) and 'c["' in line:
        # 1. 将 c["..."] 替换为 c['...']
        new_line = line.replace('c["', "c['").replace('"]', "']")
        
        # 2. 将开头的 f' 改为 f"
        if new_line.startswith("f'"):
            new_line = 'f"' + new_line[2:]
        
        # 3. 处理结尾
        if new_line.endswith("',"):
            new_line = new_line[:-2] + '",'
        elif new_line.endswith("'"):
            new_line = new_line[:-1] + '"'
        
        fixed_lines.append(new_line)
        count += 1
    else:
        fixed_lines.append(line)

with open('ppt_engine_v2.py', 'w', encoding='utf-8') as f:
    f.write('\n'.join(fixed_lines))

print(f"✅ 已修复 {count} 行引号嵌套问题")
