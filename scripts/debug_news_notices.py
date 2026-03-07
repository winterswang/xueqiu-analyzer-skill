#!/usr/bin/env python3
"""
调试资讯和公告页面结构
"""

import json
import time
from playwright.sync_api import sync_playwright

def debug_news_and_notices():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
        context = browser.new_context(viewport={'width': 1920, 'height': 1080}, user_agent='Mozilla/5.0')
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined })")
        
        # 加载 cookies
        try:
            with open('/root/.openclaw/workspace/xueqiu-analyzer-skill/config/xueqiu_cookies.json', 'r') as f:
                cookies = json.load(f)
                context.add_cookies(cookies)
        except:
            pass
        
        page = context.new_page()
        
        # 访问股票页面
        page.goto('https://xueqiu.com', timeout=30000)
        time.sleep(2)
        page.goto('https://xueqiu.com/S/TCOM', timeout=30000)
        time.sleep(2)
        
        # 关闭弹窗
        page.evaluate("document.querySelectorAll('.modals.dimmer').forEach(m => m.remove())")
        
        print("=== 调试资讯 Tab ===")
        
        # 点击资讯 tab
        page.evaluate('''() => {
            const links = document.querySelectorAll('a');
            for (const link of links) {
                if (link.textContent.trim() === '资讯') {
                    link.click();
                    return;
                }
            }
        }''')
        time.sleep(3)
        
        # 检查资讯结构
        items = page.query_selector_all('.timeline__item')
        print(f"\n找到 {len(items)} 条资讯")
        
        print("\n--- 分析前 3 条资讯 ---")
        for i, item in enumerate(items[:3], 1):
            print(f"\n[{i}]")
            
            # 获取所有链接
            links_info = page.evaluate('''(item) => {
                const links = item.querySelectorAll('a');
                const result = [];
                for (const link of links) {
                    result.push({
                        href: link.getAttribute('href'),
                        text: link.textContent.trim().substring(0, 30)
                    });
                }
                return result;
            }''', item)
            
            print(f"  链接数: {len(links_info)}")
            for j, link in enumerate(links_info):
                print(f"    [{j}] {link['href']} -> {link['text']}")
            
            # 获取文本
            text = item.inner_text().strip()[:100]
            print(f"  文本: {text}...")
        
        print("\n=== 调试公告 Tab ===")
        
        # 点击公告 tab
        page.evaluate('''() => {
            const links = document.querySelectorAll('a');
            for (const link of links) {
                if (link.textContent.trim() === '公告') {
                    link.click();
                    return;
                }
            }
        }''')
        time.sleep(3)
        
        # 检查公告结构
        items = page.query_selector_all('.timeline__item')
        print(f"\n找到 {len(items)} 条公告")
        
        print("\n--- 分析前 3 条公告 ---")
        for i, item in enumerate(items[:3], 1):
            print(f"\n[{i}]")
            
            # 获取所有链接
            links_info = page.evaluate('''(item) => {
                const links = item.querySelectorAll('a');
                const result = [];
                for (const link of links) {
                    result.push({
                        href: link.getAttribute('href'),
                        text: link.textContent.trim().substring(0, 30)
                    });
                }
                return result;
            }''', item)
            
            print(f"  链接数: {len(links_info)}")
            for j, link in enumerate(links_info):
                print(f"    [{j}] {link['href']} -> {link['text']}")
            
            # 获取文本
            text = item.inner_text().strip()[:100]
            print(f"  文本: {text}...")
        
        browser.close()


if __name__ == '__main__':
    debug_news_and_notices()