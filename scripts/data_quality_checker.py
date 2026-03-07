#!/usr/bin/env python3
"""
数据质量检验和初筛模块

功能：
1. 数据质量检验 - 检测数据问题
2. 数据清洗 - 移除无关标记
3. 数据初筛 - 过滤低质量内容
"""

import re
from typing import Dict, List, Tuple
from dataclasses import dataclass


@dataclass
class QualityReport:
    """数据质量报告"""
    total: int
    valid: int
    issues: List[str]
    suggestions: List[str]


class DataQualityChecker:
    """数据质量检查器"""
    
    # 无关标记模式
    NOISE_PATTERNS = [
        r'收起\s*',
        r'来自\w+\s*',
        r'\s*',  # 特殊字符
        r'\s*',
        r'\s*',
        r'\s*',
        r'\s*',
        r'展开\s*$',
        r'转发\s*$',
        r'赞\s*$',
        r'收藏\s*$',
        r'讨论\s*$',
    ]
    
    # 最小内容长度
    MIN_CONTENT_LENGTH = 50
    
    def check_discussions(self, discussions: List[dict]) -> QualityReport:
        """检验讨论数据质量"""
        issues = []
        suggestions = []
        valid_count = 0
        
        for i, d in enumerate(discussions):
            content = d.get('content', '')
            author = d.get('author', '')
            content_len = len(content)
            
            # 检验作者
            if not author or author.startswith('收起') or '用户' in author:
                issues.append(f"[{i+1}] 作者格式异常: \"{author}\"")
            
            # 检验内容长度
            if content_len < self.MIN_CONTENT_LENGTH:
                issues.append(f"[{i+1}] 内容过短: {content_len} 字符")
            else:
                valid_count += 1
            
            # 检验无关标记
            if '收起' in content or '来自' in content:
                issues.append(f"[{i+1}] 内容包含无关标记")
                suggestions.append(f"[{i+1}] 需要清洗")
        
        return QualityReport(
            total=len(discussions),
            valid=valid_count,
            issues=issues,
            suggestions=suggestions
        )
    
    def clean_content(self, content: str) -> str:
        """清洗内容，移除无关标记"""
        cleaned = content
        
        # 先移除时间标记（如 "昨天 15:55· 来自iPhone"）
        cleaned = re.sub(r'\d+小时前·?\s*', '', cleaned)
        cleaned = re.sub(r'\d+天前·?\s*', '', cleaned)
        cleaned = re.sub(r'昨天\s*\d{1,2}:\d{2}·?\s*', '', cleaned)
        cleaned = re.sub(r'今天\s*\d{1,2}:\d{2}·?\s*', '', cleaned)
        cleaned = re.sub(r'来自\w+\s*', '', cleaned)
        
        # 移除用户ID前缀（如 "用户6545593514"）
        cleaned = re.sub(r'^用户\d+\s*', '', cleaned)
        cleaned = re.sub(r'^[^\s]+昨天\s*', '', cleaned)
        
        # 移除无关标记
        for pattern in self.NOISE_PATTERNS:
            cleaned = re.sub(pattern, '', cleaned)
        
        # 清理多余空白
        cleaned = re.sub(r'\s+', ' ', cleaned)
        cleaned = cleaned.strip()
        
        return cleaned
    
    def clean_author(self, author: str, content: str) -> str:
        """清洗作者字段"""
        # 如果作者为空或异常，尝试从内容中提取
        if not author or author.startswith('收起') or author == '用户':
            # 尝试从链接中提取（如果有）
            return ''  # 返回空，后续可以从文章详情获取
        
        # 移除特殊字符
        author = re.sub(r'收起|用户|', '', author).strip()
        
        return author if author else ''
    
    def filter_quality_discussions(self, discussions: List[dict], 
                                    min_length: int = None) -> Tuple[List[dict], QualityReport]:
        """
        过滤高质量讨论
        
        Args:
            discussions: 讨论列表
            min_length: 最小内容长度
            
        Returns:
            (过滤后的讨论列表, 质量报告)
        """
        if min_length is None:
            min_length = self.MIN_CONTENT_LENGTH
        
        filtered = []
        issues = []
        
        for i, d in enumerate(discussions):
            # 清洗数据
            content = self.clean_content(d.get('content', ''))
            author = self.clean_author(d.get('author', ''), content)
            
            # 检验质量
            content_len = len(content)
            
            if content_len < min_length:
                issues.append(f"[{i+1}] 内容过短 ({content_len}字符), 已过滤")
                continue
            
            # 创建清洗后的讨论
            cleaned_d = d.copy()
            cleaned_d['content'] = content
            cleaned_d['author'] = author
            cleaned_d['content_length'] = content_len
            
            filtered.append(cleaned_d)
        
        report = QualityReport(
            total=len(discussions),
            valid=len(filtered),
            issues=issues,
            suggestions=[]
        )
        
        return filtered, report
    
    def filter_quality_news(self, news: List[dict], min_length: int = 20) -> Tuple[List[dict], QualityReport]:
        """过滤高质量资讯"""
        filtered = []
        issues = []
        
        for i, n in enumerate(news):
            title = n.get('title', '')
            
            if len(title) < min_length:
                issues.append(f"[{i+1}] 标题过短, 已过滤")
                continue
            
            cleaned_n = n.copy()
            cleaned_n['title_length'] = len(title)
            filtered.append(cleaned_n)
        
        report = QualityReport(
            total=len(news),
            valid=len(filtered),
            issues=issues,
            suggestions=[]
        )
        
        return filtered, report


def test_quality_check():
    """测试数据质量检查"""
    import json
    
    # 读取测试数据
    with open('data/reports/TCOM_data_20260306_104646.json', 'r') as f:
        data = json.load(f)
    
    checker = DataQualityChecker()
    
    print("=== 数据质量检验 ===\n")
    
    # 检验讨论
    discussions = data.get('discussions', [])
    report = checker.check_discussions(discussions)
    print(f"讨论: {report.valid}/{report.total} 有效")
    if report.issues:
        print("问题:")
        for issue in report.issues[:5]:
            print(f"  {issue}")
    
    # 过滤高质量讨论
    filtered, filter_report = checker.filter_quality_discussions(discussions)
    print(f"\n过滤后: {filter_report.valid}/{filter_report.total}")
    
    # 显示清洗后的示例
    print("\n清洗后示例:")
    for i, d in enumerate(filtered[:3], 1):
        print(f"\n[{i}] 作者: {d['author']}")
        print(f"    内容: {d['content'][:80]}...")


if __name__ == '__main__':
    test_quality_check()