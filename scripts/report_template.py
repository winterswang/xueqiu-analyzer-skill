#!/usr/bin/env python3
"""
报告模板生成器

按照需求文档定义的模板格式生成报告
"""

# 报告模板
REPORT_TEMPLATE = '''
# {name}({symbol})投资价值分析报告

**分析日期：{date}**
**分析模型：智谱 GLM-5**

---

## 📚 数据来源

本报告基于以下雪球专栏文章和讨论进行分析：

### 专栏文章

| # | 文章标题 | 作者 | 时间 | 链接 |
|---|----------|------|------|------|
{articles_table}

### 热门讨论

| # | 作者 | 观点摘要 | 时间 | 链接 |
|---|------|----------|------|------|
{discussions_table}

### 相关资讯

| # | 标题 | 时间 | 链接 |
|---|------|------|
{news_table}

---

## 📊 执行摘要

### 核心结论

**估值判断**：{valuation_judgment}

**投资建议**：{investment_advice}

**核心逻辑**：
{core_logic}

**关键风险**：{key_risks}

---

### 关键数据速览

| 指标 | 当前值 | 说明 |
|------|--------|------|
{key_data_table}

---

## 一、公司业务分析

### 1.1 业务结构

{business_structure}

### 1.2 竞争优势

{competitive_advantage}

---

## 二、财务数据

### 2.1 核心财务指标

| 指标 | 数值 | 说明 |
|------|------|------|
{financial_table}

### 2.2 增长趋势

{growth_trend}

---

## 三、估值评估

### 3.1 当前估值

{valuation_analysis}

### 3.2 估值是否合理？

{valuation_reasonable}

---

## 四、投资逻辑分析

### 4.1 核心投资逻辑

{investment_logic}

### 4.2 关键引用

{key_quotes}

---

## 五、风险分析

### 5.1 风险矩阵

| 风险类型 | 概率 | 影响 | 综合评级 |
|----------|------|------|----------|
{risk_matrix}

### 5.2 核心风险详解

{risk_details}

---

## 六、投资建议

### 6.1 操作建议

| 操作 | 建议 |
|------|------|
| 建仓时机 | {entry_timing} |
| 仓位控制 | {position_size} |
| 止损线 | {stop_loss} |

### 6.2 加仓条件

{add_conditions}

### 6.3 减仓/清仓条件

{reduce_conditions}

---

## 七、总结

### 7.1 投资评级

| 维度 | 评分 | 说明 |
|------|------|------|
| 估值吸引力 | {valuation_score} | {valuation_desc} |
| 成长性 | {growth_score} | {growth_desc} |
| 竞争护城河 | {moat_score} | {moat_desc} |
| 风险可控性 | {risk_score} | {risk_desc} |
| **综合评分** | **{total_score}** | **{rating}** |

### 7.2 最终结论

{final_conclusion}

---

## 📚 原文引用汇总

{reference_summary}

---

**风险提示：本报告仅供参考，不构成投资建议。投资有风险，决策需谨慎。**

*报告生成时间：{report_time}*
*分析模型：智谱 GLM-5*
*数据来源：雪球、AkShare*
'''


def format_articles_table(articles: list) -> str:
    """格式化文章表格"""
    if not articles:
        return "| - | 暂无专栏文章 | - | - | - |"
    
    rows = []
    for i, a in enumerate(articles, 1):
        title = a.get('title', '无标题')[:40]
        author = a.get('author', '未知')[:15]
        time_str = a.get('time', '')
        link = a.get('link', '')
        if link:
            rows.append(f"| {i} | {title} | {author} | {time_str} | [查看原文]({link}) |")
        else:
            rows.append(f"| {i} | {title} | {author} | {time_str} | - |")
    
    return '\n'.join(rows)


def format_discussions_table(discussions: list) -> str:
    """格式化讨论表格"""
    if not discussions:
        return "| - | 暂无讨论 | - | - | - |"
    
    rows = []
    for i, d in enumerate(discussions[:5], 1):
        author = d.get('author', '未知')[:15]
        content = d.get('content', '')[:40].replace('\n', ' ')
        time_str = d.get('time', '')
        link = d.get('link', '')
        if link:
            rows.append(f"| {i} | {author} | {content}... | {time_str} | [查看原文]({link}) |")
        else:
            rows.append(f"| {i} | {author} | {content}... | {time_str} | - |")
    
    return '\n'.join(rows)


def format_news_table(news: list) -> str:
    """格式化资讯表格"""
    if not news:
        return "| - | 暂无资讯 | - | - |"
    
    rows = []
    for i, n in enumerate(news[:5], 1):
        title = n.get('title', '')[:50]
        time_str = n.get('time', '')
        link = n.get('link', '')
        if link:
            rows.append(f"| {i} | {title} | {time_str} | [查看详情]({link}) |")
        else:
            rows.append(f"| {i} | {title} | {time_str} | - |")
    
    return '\n'.join(rows)


def format_financial_table(financial_data: dict) -> str:
    """格式化财务数据表格"""
    if not financial_data:
        return "| PE | 暂无数据 | 财务数据获取失败 |"
    
    rows = []
    
    # 雪球数据（更可靠）
    if financial_data.get('pe_ttm'):
        rows.append(f"| PE(TTM) | {financial_data.get('pe_ttm', 0):.1f} | 市盈率（雪球） |")
    if financial_data.get('pb'):
        rows.append(f"| 市净率 | {financial_data.get('pb', 0):.1f} | PB（雪球） |")
    if financial_data.get('current_price'):
        rows.append(f"| 当前价 | ${financial_data.get('current_price', 0):.2f} | - |")
    if financial_data.get('market_cap'):
        cap = financial_data.get('market_cap', 0) / 1e9  # 转换为十亿
        rows.append(f"| 总市值 | ${cap:.1f}B | - |")
    
    # AkShare 数据
    if financial_data.get('roe'):
        rows.append(f"| ROE | {financial_data.get('roe', 0):.1f}% | 净资产收益率（AkShare） |")
    if financial_data.get('gross_margin'):
        rows.append(f"| 毛利率 | {financial_data.get('gross_margin', 0):.1f}% | 销售毛利率（AkShare） |")
    if financial_data.get('net_margin'):
        rows.append(f"| 净利率 | {financial_data.get('net_margin', 0):.1f}% | 销售净利率（AkShare） |")
    
    return '\n'.join(rows) if rows else "| PE | 暂无数据 | 财务数据获取失败 |"


def format_key_data_table(price: str, financial_data: dict) -> str:
    """格式化关键数据表格"""
    rows = [
        f"| 当前价 | {price or '-'} | - |",
    ]
    
    if financial_data and financial_data.get('roe'):
        rows.extend([
            f"| ROE | {financial_data.get('roe', 0):.1f}% | 盈利能力 |",
            f"| 毛利率 | {financial_data.get('gross_margin', 0):.1f}% | 竞争力 |",
            f"| 营收增速 | {financial_data.get('revenue_growth', 0):.1f}% | 成长性 |",
        ])
    
    return '\n'.join(rows)


def format_reference_summary(articles: list, discussions: list) -> str:
    """格式化原文引用汇总"""
    lines = []
    
    if articles:
        lines.append("### 专栏文章")
        for i, a in enumerate(articles, 1):
            title = a.get('title', '无标题')
            author = a.get('author', '未知')
            link = a.get('link', '')
            if link:
                lines.append(f"{i}. **{author}** - [{title}]({link})")
            else:
                lines.append(f"{i}. **{author}** - {title}")
    
    if discussions:
        lines.append("\n### 热门讨论")
        for i, d in enumerate(discussions[:5], 1):
            author = d.get('author', '未知')
            link = d.get('link', '')
            content = d.get('content', '')[:50]
            if link:
                lines.append(f"{i}. **{author}** - [查看原文]({link}) - {content}...")
            else:
                lines.append(f"{i}. **{author}** - {content}...")
    
    return '\n'.join(lines) if lines else "暂无引用内容"


# GLM-5 分析 Prompt
ANALYSIS_PROMPT_TEMPLATE = '''
你是一位专业的投资研究分析师，请分析以下股票的投资价值。

## 股票基本信息
- 代码: {symbol}
- 名称: {name}
- 价格: {price}

## 专栏文章内容

{articles_content}

## 财务数据

{financial_content}

---

请严格按照以下要求输出分析报告：

1. **估值判断**：根据财务数据和文章内容，判断当前估值是否合理
2. **核心逻辑**：提取 3-5 条核心投资逻辑
3. **关键风险**：识别主要风险点
4. **业务分析**：分析公司业务结构和竞争优势
5. **投资建议**：给出具体的建仓时机、仓位控制建议

**重要**：
- 在分析中引用原文时，使用格式：> 📌 **引用自文章《标题》**："原文内容"
- 每个引用都要标注来源
- 分析要基于提供的数据和文章内容
'''


def build_analysis_prompt(symbol: str, name: str, price: str, 
                          articles: list, financial_data: dict) -> str:
    """构建 GLM-5 分析 prompt"""
    
    # 文章内容
    articles_content = ""
    for i, a in enumerate(articles[:3], 1):
        articles_content += f"""
### 文章 {i}: {a.get('title', '无标题')}
**作者**: {a.get('author', '未知')}
**链接**: {a.get('link', '')}

{a.get('content', '')[:2000]}

---

"""
    
    # 财务数据
    financial_content = "暂无财务数据"
    if financial_data and financial_data.get('roe'):
        financial_content = f"""
| 指标 | 数值 |
|------|------|
| ROE | {financial_data.get('roe', 0):.1f}% |
| 毛利率 | {financial_data.get('gross_margin', 0):.1f}% |
| 净利率 | {financial_data.get('net_margin', 0):.1f}% |
| 营收增速 | {financial_data.get('revenue_growth', 0):.1f}% |
| 利润增速 | {financial_data.get('profit_growth', 0):.1f}% |
| PE | {financial_data.get('pe', 0):.1f} |
"""
    
    return ANALYSIS_PROMPT_TEMPLATE.format(
        symbol=symbol,
        name=name or symbol,
        price=price or '-',
        articles_content=articles_content or "暂无文章",
        financial_content=financial_content
    )