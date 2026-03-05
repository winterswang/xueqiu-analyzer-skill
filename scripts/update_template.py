# 读取文件
with open('report_template.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# 找到 format_news_table 函数并更新
new_lines = []
in_news_func = False
for i, line in enumerate(lines):
    if 'def format_news_table' in line:
        in_news_func = True
        new_lines.append(line)
    elif in_news_func and "rows.append(f\"| {i} | {title} | {time_str} |\")" in line:
        # 替换这一行
        new_lines.append("        link = n.get('link', '')\n")
        new_lines.append("        if link:\n")
        new_lines.append("            rows.append(f\"| {i} | {title} | {time_str} | [查看详情]({link}) |\\")\n\"")
        new_lines.append("        else:\n")
        new_lines.append("            rows.append(f\"| {i} | {title} | {time_str} | - |\\")\n\"")
        in_news_func = False
    else:
        new_lines.append(line)

# 写回文件
with open('report_template.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("更新完成")
