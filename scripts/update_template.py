#!/usr/bin/env python3
"""
更新报告模板脚本
用于修复 report_template.py 中的 format_news_table 函数
"""
import re

def fix_template():
    """修复 report_template.py"""
    template_file = 'report_template.py'
    
    with open(template_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 检查是否已经包含 link 列
    if '查看详情' in content:
        print("模板已经包含 link 列，无需更新")
        return
    
    # 替换旧的行
    old_pattern = r'rows\.append\(f"\| \{i\} \| \{title\} \| \{time_str\} \|"\)'
    new_content = '''        # 添加链接列
        link = n.get('link', '')
        if link:
            rows.append(f"| {i} | {title} | {time_str} | [查看详情]({link}) |")
        else:
            rows.append(f"| {i} | {title} | {time_str} | - |")'''
    
    content = re.sub(old_pattern, new_content, content)
    
    with open(template_file, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("更新完成")


if __name__ == '__main__':
    fix_template()
