#!/usr/bin/env python3
"""
雪球 Cookie 刷新工具

使用方式：
  # 方式1: 有头模式 - 手动登录后自动保存 (推荐)
  .venv/bin/python3 scripts/refresh_cookies.py

  # 方式2: 指定凭据自动登录 (需要 XUEQIU_PHONE + XUEQIU_PASSWORD 环境变量)
  XUEQIU_PHONE=131xxx XUEQIU_PASSWORD=xxx .venv/bin/python3 scripts/refresh_cookies.py --auto

  # 方式3: 从浏览器导入 cookies JSON
  .venv/bin/python3 scripts/refresh_cookies.py --import cookies.json

Cookie 保存位置（双写）：
  1. config/cookies/xueqiu.json   (项目内)
  2. ~/.xueqiu_crawler/cookies.json (爬虫默认读取)
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path

# 自动加载项目 .env（不依赖 bash 环境）
try:
    from dotenv import load_dotenv
    _project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _dotenv_path = os.path.join(_project_root, '.env')
    if os.path.exists(_dotenv_path):
        load_dotenv(_dotenv_path, override=False)
except ImportError:
    pass

PROJECT_ROOT = Path(__file__).parent.parent
PROJECT_COOKIES = PROJECT_ROOT / 'config' / 'cookies' / 'xueqiu.json'
DEFAULT_COOKIES = Path(os.path.expanduser('~/.xueqiu_crawler/cookies.json'))


def save_cookies(cookies: list):
    """双写 cookies 到项目和默认路径"""
    PROJECT_COOKIES.parent.mkdir(parents=True, exist_ok=True)
    DEFAULT_COOKIES.parent.mkdir(parents=True, exist_ok=True)

    with open(PROJECT_COOKIES, 'w') as f:
        json.dump(cookies, f, indent=2)
    with open(DEFAULT_COOKIES, 'w') as f:
        json.dump(cookies, f, indent=2)

    print(f"✅ Cookies 已保存到:")
    print(f"   - {PROJECT_COOKIES}")
    print(f"   - {DEFAULT_COOKIES}")

    # 统计关键 cookie
    has_xq_a_token = any(c['name'] == 'xq_a_token' for c in cookies)
    has_s = any(c['name'] == 's' for c in cookies)
    print(f"   - xq_a_token: {'✅' if has_xq_a_token else '❌'}")
    print(f"   - s (session): {'✅' if has_s else '❌'}")


def interactive_login():
    """有头模式：打开浏览器让用户手动登录，然后自动保存 cookies"""
    from playwright.sync_api import sync_playwright

    print("🌐 打开浏览器，请手动登录雪球...")
    print("   登录成功后，按 Enter 键保存 cookies\n")

    with sync_playwright() as p:
        launch_opts = {'headless': False, 'args': ['--no-sandbox']}
        sys_chromium = '/usr/bin/chromium-browser'
        if os.path.exists(sys_chromium):
            launch_opts['executable_path'] = sys_chromium

        browser = p.chromium.launch(**launch_opts)
        context = browser.new_context(viewport={'width': 1280, 'height': 800})
        page = context.new_page()

        page.goto('https://xueqiu.com/')
        print("📖 已打开雪球首页，请在浏览器中完成登录")
        print("   ⏳ 等待登录完成...")

        # 等待用户登录：检测 xq_a_token cookie 出现
        max_wait = 300  # 最多等5分钟
        start = time.time()
        logged_in = False

        while time.time() - start < max_wait:
            cookies = context.cookies()
            if any(c['name'] == 'xq_a_token' and c.get('value') for c in cookies):
                logged_in = True
                break
            time.sleep(2)

        if logged_in:
            print("\n✅ 检测到登录成功！")
            # 多等几秒确保所有 cookie 都拿到
            time.sleep(3)
            cookies = context.cookies()
            save_cookies(cookies)
        else:
            print("\n⚠️ 超时未检测到登录，尝试保存当前 cookies...")
            cookies = context.cookies()
            if cookies:
                save_cookies(cookies)
            else:
                print("❌ 没有获取到任何 cookies")

        browser.close()


def auto_login():
    """使用环境变量中的凭据自动登录"""
    from playwright.sync_api import sync_playwright

    phone = os.environ.get('XUEQIU_PHONE', '')
    password = os.environ.get('XUEQIU_PASSWORD', '')

    if not phone or not password:
        print("❌ 请设置环境变量 XUEQIU_PHONE 和 XUEQIU_PASSWORD")
        sys.exit(1)

    print(f"🔑 自动登录: {phone[:3]}****{phone[-4:]}")

    with sync_playwright() as p:
        launch_opts = {'headless': True, 'args': ['--no-sandbox']}
        sys_chromium = '/usr/bin/chromium-browser'
        if os.path.exists(sys_chromium):
            launch_opts['executable_path'] = sys_chromium

        browser = p.chromium.launch(**launch_opts)
        context = browser.new_context(viewport={'width': 1920, 'height': 1080})
        page = context.new_page()

        page.goto('https://xueqiu.com/')
        time.sleep(2)

        # 点击登录按钮
        try:
            login_btn = page.query_selector('text=登录')
            if login_btn:
                login_btn.click()
                time.sleep(2)
        except Exception:
            pass

        # 切换到手机号登录
        try:
            phone_tab = page.query_selector('text=手机号登录')
            if phone_tab:
                phone_tab.click()
                time.sleep(1)
        except Exception:
            pass

        # 输入凭据
        try:
            phone_input = page.query_selector('input[placeholder*="手机号"]')
            if phone_input:
                phone_input.fill(phone)
            password_input = page.query_selector('input[placeholder*="密码"]')
            if password_input:
                password_input.fill(password)
            time.sleep(1)
        except Exception as e:
            print(f"⚠️ 输入凭据失败: {e}")

        # 点击登录
        try:
            submit = page.query_selector('button:has-text("登录")')
            if submit:
                submit.click()
                time.sleep(5)
        except Exception as e:
            print(f"⚠️ 点击登录失败: {e}")

        # 检查登录结果
        cookies = context.cookies()
        logged_in = any(c['name'] == 'xq_a_token' and c.get('value') for c in cookies)

        if logged_in:
            print("✅ 自动登录成功！")
            save_cookies(cookies)
        else:
            print("⚠️ 自动登录可能失败（可能需要滑块验证）")
            print("   尝试保存当前 cookies...")
            save_cookies(cookies)

        browser.close()


def import_cookies(filepath: str):
    """从 JSON 文件导入 cookies"""
    with open(filepath, 'r') as f:
        cookies = json.load(f)

    # 确保格式正确（支持 Cookie-Editor 导出的格式）
    normalized = []
    for c in cookies:
        if isinstance(c, dict) and 'name' in c:
            # Cookie-Editor 格式兼容
            normalized.append({
                'name': c['name'],
                'value': c.get('value', ''),
                'domain': c.get('domain', '.xueqiu.com'),
                'path': c.get('path', '/'),
                'httpOnly': c.get('httpOnly', False),
                'secure': c.get('secure', False),
                'sameSite': c.get('sameSite', 'Lax'),
            })
            if c.get('expirationDate') or c.get('expiry'):
                normalized[-1]['expiry'] = int(c.get('expirationDate') or c.get('expiry'))

    print(f"📦 导入 {len(normalized)} 个 cookies")
    save_cookies(normalized)


def check_cookies():
    """检查当前 cookies 状态"""
    for path in [PROJECT_COOKIES, DEFAULT_COOKIES]:
        if path.exists():
            with open(path) as f:
                cookies = json.load(f)
            has_token = any(c['name'] == 'xq_a_token' for c in cookies)
            # 检查过期
            now = time.time()
            expired_count = sum(1 for c in cookies if c.get('expiry', 0) > 0 and c['expiry'] < now)
            valid_count = len(cookies) - expired_count
            status = "✅ 有效" if has_token and valid_count > 5 else "❌ 无效/过期"
            print(f"📄 {path}: {len(cookies)} cookies, {valid_count} 有效, {expired_count} 过期 → {status}")
        else:
            print(f"📄 {path}: 不存在")


def main():
    parser = argparse.ArgumentParser(description='雪球 Cookie 刷新工具')
    parser.add_argument('--auto', action='store_true', help='使用环境变量凭据自动登录')
    parser.add_argument('--import-file', metavar='FILE', help='从 JSON 文件导入 cookies')
    parser.add_argument('--check', action='store_true', help='检查 cookies 状态')
    args = parser.parse_args()

    if args.check:
        check_cookies()
    elif args.import_file:
        import_cookies(args.import_file)
    elif args.auto:
        auto_login()
    else:
        interactive_login()


if __name__ == '__main__':
    main()
