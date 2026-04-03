import config
#!/usr/bin/env python3
"""获取雪球用户名称"""

import time
import json
from playwright.sync_api import sync_playwright

def get_user_name(user_id: str):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=['--disable-blink-features=AutomationControlled'])
        context = browser.new_context(user_agent='Mozilla/5.0')
        context.add_init_script("Object.defineProperty(navigator, 'webdriver', { get: () => undefined })")
        
        # 加载 cookies
        try:
            with open('str(config.CONFIG_DIR / "xueqiu_cookies.json")', 'r') as f:
                cookies = json.load(f)
                context.add_cookies(cookies)
        except Exception as e:
            pass
        
        page = context.new_page()
        page.goto('https://xueqiu.com', timeout=30000)
        time.sleep(1)
        
        url = f'https://xueqiu.com/u/{user_id}'
        print(f"访问: {url}")
        page.goto(url, timeout=30000)
        time.sleep(2)
        
        # 移除弹窗
        page.evaluate("document.querySelectorAll('.modals.dimmer').forEach(m => m.remove())")
        
        # 获取用户名
        name_elem = page.query_selector('.user-name, .username, .profile__name')
        if name_elem:
            name = name_elem.inner_text().strip()
            print(f"用户名: {name}")
            return name
        
        # 尝试从标题获取
        title = page.title()
        print(f"页面标题: {title}")
        if '的雪球专栏' in title:
            name = title.split('的雪球专栏')[0].strip()
            print(f"用户名: {name}")
            return name
        
        browser.close()
        return None

if __name__ == '__main__':
    import sys
    user_id = sys.argv[1] if len(sys.argv) > 1 else "3181890538"
    name = get_user_name(user_id)
    if name:
        print(f"\n账号 {user_id} 的用户名是: {name}")