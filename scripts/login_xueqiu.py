#!/usr/bin/env python3
"""
雪球自动登录脚本
使用 Playwright 模拟登录并保存 Cookie
"""
import os
import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

# 从环境变量读取账号配置（安全方式）
XUEQIU_ACCOUNT = {
    'phone': os.environ.get('XUEQIU_PHONE', ''),
    'password': os.environ.get('XUEQIU_PASSWORD', '')
}

# Cookie 保存路径 - 使用相对路径
PROJECT_ROOT = Path(__file__).parent.parent
COOKIE_FILE = PROJECT_ROOT / 'config' / 'cookies' / 'xueqiu.json'

def login_xueqiu():
    """登录雪球并保存 Cookie"""
    
    COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    # 使用已安装的 Chrome
    chrome_path = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
    
    with sync_playwright() as p:
        # 启动浏览器
        try:
            browser = p.chromium.launch(executable_path=chrome_path, headless=True)
        except Exception as e:
            browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        
        print("1. 访问雪球首页...")
        page.goto('https://xueqiu.com/')
        time.sleep(2)
        
        print("2. 点击登录按钮...")
        # 点击登录按钮
        try:
            login_btn = page.query_selector('text=登录')
            if login_btn:
                login_btn.click()
                time.sleep(2)
        except Exception as e:
            print(f"  点击登录按钮失败: {e}")
        
        print("3. 切换到手机号登录...")
        try:
            # 点击"手机号登录"
            phone_login = page.query_selector('text=手机号登录')
            if phone_login:
                phone_login.click()
                time.sleep(1)
        except Exception as e:
            print(f"  切换失败: {e}")
        
        print("4. 输入手机号和密码...")
        try:
            # 输入手机号
            phone_input = page.query_selector('input[placeholder*="手机号"]')
            if phone_input:
                phone_input.fill(XUEQIU_ACCOUNT['phone'])
            
            # 输入密码
            password_input = page.query_selector('input[placeholder*="密码"]')
            if password_input:
                password_input.fill(XUEQIU_ACCOUNT['password'])
            
            time.sleep(1)
            
        except Exception as e:
            print(f"  输入失败: {e}")
        
        print("5. 点击登录...")
        try:
            submit_btn = page.query_selector('button:has-text("登录")')
            if submit_btn:
                submit_btn.click()
                time.sleep(5)
        except Exception as e:
            print(f"  点击登录失败: {e}")
        
        # 检查是否需要滑块验证
        print("6. 等待人工处理滑块验证（如果有）...")
        print("  请在浏览器中完成滑块验证...")
        time.sleep(30)  # 等待人工处理
        
        # 保存 Cookie
        print("7. 保存 Cookie...")
        cookies = context.cookies()
        
        with open(COOKIE_FILE, 'w') as f:
            json.dump(cookies, f, indent=2)
        
        print(f"  ✅ Cookie 已保存到: {COOKIE_FILE}")
        
        # 测试访问页面
        print("8. 测试访问页面...")
        page.goto('https://xueqiu.com/1936609590/378428546')
        time.sleep(3)
        
        # 截图
        screenshot_file = COOKIE_FILE.parent / 'xueqiu_test.png'
        page.screenshot(path=str(screenshot_file))
        print(f"  截图已保存: {screenshot_file}")
        
        browser.close()

if __name__ == '__main__':
    login_xueqiu()