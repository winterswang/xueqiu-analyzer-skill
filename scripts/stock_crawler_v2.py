#!/usr/bin/env python3
"""
雪球股票详情页爬虫 v2

解决问题：
1. 登录弹窗拦截 - 自动关闭
2. 滚动加载 - 使用正确的方式
3. Tab 切换 - 使用 JavaScript 点击绕过遮罩
"""

import os
import sys
import json
import re
import time
import random
import logging
import yaml
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict

try:
    from playwright.sync_api import sync_playwright, Page, BrowserContext
except ImportError:
    print("请先安装 playwright: pip install playwright && playwright install chromium")
    sys.exit(1)


@dataclass
class Article:
    """专栏文章"""
    title: str
    author: str
    time: str
    content: str
    link: str
    article_id: str = ""


@dataclass
class Discussion:
    """讨论数据"""
    author: str
    time: str
    content: str
    link: str = ""


@dataclass
class News:
    """资讯数据"""
    title: str
    time: str
    source: str = ""
    link: str = ""


@dataclass
class Notice:
    """公告数据"""
    title: str
    link: str
    id: str = ""


@dataclass
class StockInfo:
    """股票信息"""
    symbol: str
    name: str = ""
    price: str = ""
    change: str = ""
    discussions: List[Discussion] = None
    news: List[News] = None
    notices: List[Notice] = None
    articles: List[Article] = None
    financial_data: dict = None
    
    def __post_init__(self):
        if self.discussions is None:
            self.discussions = []
        if self.news is None:
            self.news = []
        if self.notices is None:
            self.notices = []
        if self.articles is None:
            self.articles = []
        if self.financial_data is None:
            self.financial_data = {}


class XueqiuStockCrawlerV2:
    """雪球股票详情页爬虫 v2"""
    
    def __init__(self, headless: bool = True, cookies_path: str = None, credentials_path: str = None):
        self.headless = headless
        self.cookies_path = cookies_path or os.path.expanduser('~/.openclaw/workspace/xueqiu-analyzer-skill/config/xueqiu_cookies.json')
        self.credentials_path = credentials_path or os.path.expanduser('~/.openclaw/workspace/xueqiu-analyzer-skill/config/xueqiu_credentials.yaml')
        self.credentials = self._load_credentials()
        self.logger = self._setup_logger()
        
    def _load_credentials(self) -> dict:
        """加载登录凭据"""
        if os.path.exists(self.credentials_path):
            try:
                with open(self.credentials_path, 'r') as f:
                    return yaml.safe_load(f) or {}
            except Exception as e:
                self.logger.warning(f"加载凭据失败: {e}")
        return {}
        
    def _setup_logger(self) -> logging.Logger:
        logger = logging.getLogger('XueqiuStockCrawlerV2')
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter('%(asctime)s - %(message)s')
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger
    
    def _create_browser_context(self, playwright) -> Tuple:
        """创建反检测浏览器上下文"""
        browser = playwright.chromium.launch(
            headless=self.headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage',
            ]
        )
        
        context = browser.new_context(
            viewport={'width': 1920, 'height': 1080},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            locale='zh-CN',
        )
        
        # 绕过 webdriver 检测
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
            Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
            window.chrome = { runtime: {} };
        """)
        
        # 加载保存的 cookies
        if os.path.exists(self.cookies_path):
            try:
                with open(self.cookies_path, 'r') as f:
                    cookies = json.load(f)
                    context.add_cookies(cookies)
                    self.logger.info(f"已加载 {len(cookies)} 个 cookies")
            except Exception as e:
                self.logger.warning(f"加载 cookies 失败: {e}")
        
        return browser, context
    
    def _save_cookies(self, context: BrowserContext):
        """保存 cookies"""
        try:
            cookies = context.cookies()
            os.makedirs(os.path.dirname(self.cookies_path), exist_ok=True)
            with open(self.cookies_path, 'w') as f:
                json.dump(cookies, f)
            self.logger.info(f"已保存 {len(cookies)} 个 cookies")
        except Exception as e:
            self.logger.warning(f"保存 cookies 失败: {e}")
    
    def _check_login_status(self, page: Page) -> bool:
        """检查是否已登录"""
        try:
            # 检查是否有用户头像/名称（已登录状态）
            user_elem = page.query_selector('.nav__user, .user-avatar, .username, .topbar__user')
            if user_elem:
                return True
            
            # 使用 JavaScript 检查登录状态
            is_logged_in = page.evaluate('''() => {
                // 检查是否有登录按钮（未登录状态）
                const loginTexts = ['登录', '注册'];
                const links = document.querySelectorAll('a, button');
                for (const link of links) {
                    const text = link.textContent.trim();
                    if (loginTexts.includes(text)) {
                        return false;
                    }
                }
                
                // 检查是否有用户相关元素
                const userSelectors = ['.nav__user', '.user-avatar', '.username', '.topbar__user'];
                for (const selector of userSelectors) {
                    if (document.querySelector(selector)) {
                        return true;
                    }
                }
                
                // 默认返回 true（假设已登录）
                return true;
            }''')
            
            return is_logged_in
        except:
            return False
    
    def _login(self, page: Page) -> bool:
        """登录雪球"""
        try:
            phone = self.credentials.get('phone')
            password = self.credentials.get('password')
            
            if not phone or not password:
                self.logger.warning("未配置登录凭据，跳过登录")
                return False
            
            self.logger.info(f"尝试登录雪球 (手机: {phone[:3]}****{phone[-4:]})...")
            
            # 1. 点击登录按钮
            login_clicked = page.evaluate('''() => {
                const links = document.querySelectorAll('a, button');
                for (const link of links) {
                    if (link.textContent.trim() === '登录') {
                        link.click();
                        return true;
                    }
                }
                return false;
            }''')
            
            if login_clicked:
                self.logger.info("点击登录按钮...")
                time.sleep(2)
            else:
                self.logger.info("未找到登录按钮，可能已在登录页面")
            
            # 2. 切换到手机号登录（如果存在）
            page.evaluate('''() => {
                const tabs = document.querySelectorAll('[class*="tab"], .login-type');
                for (const tab of tabs) {
                    if (tab.textContent.includes('手机号')) {
                        tab.click();
                        return;
                    }
                }
            }''')
            time.sleep(1)
            
            # 3. 输入手机号
            phone_input = page.query_selector('input[placeholder*="手机号"], input[name="username"], input[type="tel"], input.phone')
            if not phone_input:
                # 使用 JavaScript 查找
                phone_input = page.evaluate('''() => {
                    const inputs = document.querySelectorAll('input');
                    for (const input of inputs) {
                        const placeholder = input.placeholder || '';
                        const name = input.name || '';
                        const type = input.type || '';
                        if (placeholder.includes('手机') || name === 'username' || type === 'tel') {
                            return true;
                        }
                    }
                    return false;
                }''')
            
            if phone_input:
                # 使用 JavaScript 填充
                page.evaluate(f'''() => {{
                    const inputs = document.querySelectorAll('input');
                    for (const input of inputs) {{
                        const placeholder = input.placeholder || '';
                        const name = input.name || '';
                        const type = input.type || '';
                        if (placeholder.includes('手机') || name === 'username' || type === 'tel') {{
                            input.value = '{phone}';
                            input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                            input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                            return;
                        }}
                    }}
                }}''')
                self.logger.info(f"已输入手机号: {phone}")
            else:
                self.logger.warning("未找到手机号输入框")
                return False
            
            # 4. 输入密码
            page.evaluate(f'''() => {{
                const inputs = document.querySelectorAll('input');
                for (const input of inputs) {{
                    const placeholder = input.placeholder || '';
                    const name = input.name || '';
                    const type = input.type || '';
                    if (placeholder.includes('密码') || name === 'password' || type === 'password') {{
                        input.value = '{password}';
                        input.dispatchEvent(new Event('input', {{ bubbles: true }}));
                        input.dispatchEvent(new Event('change', {{ bubbles: true }}));
                        return;
                    }}
                }}
            }}''')
            self.logger.info("已输入密码")
            
            # 5. 点击登录按钮
            submit_clicked = page.evaluate('''() => {
                const buttons = document.querySelectorAll('button');
                for (const btn of buttons) {
                    if (btn.textContent.trim() === '登录' || btn.type === 'submit') {
                        btn.click();
                        return true;
                    }
                }
                return false;
            }''')
            
            if submit_clicked:
                self.logger.info("点击登录按钮...")
                time.sleep(3)
            else:
                self.logger.warning("未找到登录按钮")
                return False
            
            # 6. 检查是否需要验证码
            captcha = page.query_selector('.captcha, .verify-code, input[placeholder*="验证码"]')
            if captcha:
                self.logger.warning("检测到验证码，需要人工处理")
                # 等待用户处理验证码（最多60秒）
                for i in range(60):
                    time.sleep(1)
                    if self._check_login_status(page):
                        self.logger.info("登录成功！")
                        return True
                    if not page.query_selector('.captcha, .verify-code'):
                        break
                
                return self._check_login_status(page)
            
            # 7. 验证登录状态
            time.sleep(2)
            if self._check_login_status(page):
                self.logger.info("登录成功！")
                return True
            else:
                self.logger.warning("登录可能失败，继续尝试...")
                return True  # 继续尝试，可能已登录
                
        except Exception as e:
            self.logger.error(f"登录失败: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def _close_modal(self, page: Page) -> bool:
        """关闭登录弹窗"""
        try:
            # 检查是否有遮罩层
            modal = page.query_selector('.modals.dimmer.js-shown')
            if modal:
                self.logger.info("检测到登录弹窗，尝试关闭...")
                
                # 方法1: 点击关闭按钮
                close_btn = page.query_selector('.modal__close, .close, [class*="close"]')
                if close_btn:
                    try:
                        close_btn.click(timeout=3000)
                        time.sleep(0.5)
                        self.logger.info("点击关闭按钮成功")
                        return True
                    except:
                        pass
                
                # 方法2: 使用 JavaScript 关闭
                page.evaluate('''() => {
                    // 移除遮罩层
                    const modals = document.querySelectorAll('.modals.dimmer');
                    modals.forEach(m => m.remove());
                    
                    // 移除 body 上的类
                    document.body.classList.remove('modal-open');
                    document.body.style.overflow = '';
                }''')
                self.logger.info("JavaScript 移除弹窗成功")
                time.sleep(0.5)
                return True
            
            return False
        except Exception as e:
            self.logger.warning(f"关闭弹窗失败: {e}")
            return False
    
    def _js_click(self, page: Page, text: str) -> bool:
        """使用 JavaScript 点击包含指定文本的元素（绕过遮罩）"""
        try:
            result = page.evaluate('''(text) => {
                // 查找所有包含指定文本的 a 标签
                const links = document.querySelectorAll('a');
                for (const link of links) {
                    if (link.textContent.trim() === text || link.textContent.includes(text)) {
                        link.click();
                        return true;
                    }
                }
                return false;
            }''', text)
            return result
        except Exception as e:
            self.logger.warning(f"JS 点击失败: {e}")
            return False
    
    def _scroll_and_load(self, page: Page, max_scrolls: int = 10, target_count: int = 30) -> int:
        """翻页加载更多内容（累积收集）"""
        page_num = 1
        all_items = []  # 累积所有页面的内容
        seen_links = set()  # 去重
        
        while page_num <= max_scrolls:
            # 解析当前页内容并累积
            items = page.query_selector_all('.timeline__item')
            new_count = 0
            
            for item in items:
                # 获取链接用于去重
                link_elem = item.query_selector('a[href*="/"]')
                if link_elem:
                    href = link_elem.get_attribute('href') or ''
                    if href and href not in seen_links:
                        seen_links.add(href)
                        all_items.append(item)
                        new_count += 1
            
            self.logger.info(f"分页 [{page_num}] 本页新增: {new_count}, 累计: {len(all_items)} 条")
            
            # 检查是否达到目标
            if len(all_items) >= target_count:
                self.logger.info(f"已达到目标数量 {target_count}")
                break
            
            # 查找并点击"下一页"按钮
            next_page_clicked = page.evaluate('''() => {
                // 方法1: 查找"下一页"文字
                const links = document.querySelectorAll('a');
                for (const link of links) {
                    if (link.textContent.trim() === '下一页') {
                        link.click();
                        return true;
                    }
                }
                
                // 方法2: 查找分页区域的下一个数字
                const pagination = document.querySelector('.pagination, .pager, [class*="page"]');
                if (pagination) {
                    const current = pagination.querySelector('.active, .current');
                    if (current) {
                        const next = current.nextElementSibling;
                        if (next && next.tagName === 'A') {
                            next.click();
                            return true;
                        }
                    }
                }
                
                return false;
            }''')
            
            if next_page_clicked:
                time.sleep(2)
                # 等待内容加载
                try:
                    page.wait_for_selector('.timeline__item', timeout=5000)
                except:
                    pass
                page_num += 1
            else:
                self.logger.info("未找到下一页按钮，停止分页")
                break
        
        return len(all_items)
    
    def _parse_items_with_pagination(self, page: Page, max_pages: int = 3, target_count: int = 30) -> List:
        """分页爬取并累积数据（返回原始 item 列表）"""
        page_num = 1
        all_items = []
        seen_links = set()
        
        while page_num <= max_pages:
            # 解析当前页
            items = page.query_selector_all('.timeline__item')
            new_count = 0
            
            for item in items:
                # 使用内容的 hash 去重（而非链接）
                try:
                    text = item.inner_text().strip()[:100]  # 取前100字符作为标识
                    item_hash = hash(text)
                    
                    if item_hash not in seen_links:
                        seen_links.add(item_hash)
                        all_items.append(item)
                        new_count += 1
                except:
                    pass
            
            self.logger.info(f"分页 [{page_num}] 本页新增: {new_count}, 累计: {len(all_items)} 条")
            
            if len(all_items) >= target_count:
                break
            
            # 点击下一页
            next_clicked = page.evaluate('''() => {
                const links = document.querySelectorAll('a');
                for (const link of links) {
                    if (link.textContent.trim() === '下一页') {
                        link.click();
                        return true;
                    }
                }
                return false;
            }''')
            
            if next_clicked:
                time.sleep(2)
                try:
                    page.wait_for_selector('.timeline__item', timeout=5000)
                except:
                    pass
                page_num += 1
            else:
                break
        
        return all_items
    
    def _switch_tab(self, page: Page, tab_name: str) -> bool:
        """切换 tab"""
        try:
            # 先关闭可能存在的弹窗
            self._close_modal(page)
            
            self.logger.info(f"切换到 '{tab_name}' tab...")
            
            # 使用 JavaScript 点击绕过遮罩
            if self._js_click(page, tab_name):
                time.sleep(2)
                
                # 等待内容加载
                try:
                    page.wait_for_selector('.timeline__item', timeout=5000)
                except:
                    pass
                
                # 再次检查弹窗
                self._close_modal(page)
                
                return True
            else:
                self.logger.warning(f"点击 '{tab_name}' 失败")
                return False
                
        except Exception as e:
            self.logger.warning(f"切换 tab 失败: {e}")
            return False
    
    def _parse_discussions(self, page: Page, max_count: int = 20) -> List[Discussion]:
        """解析讨论内容"""
        discussions = []
        items = page.query_selector_all('.timeline__item')
        
        self.logger.info(f"解析讨论: 找到 {len(items)} 条")
        
        for item in items[:max_count]:
            try:
                text = item.inner_text().strip()
                
                # 提取作者（通常在开头）
                author_match = re.search(r'^([^\d]+?)(?=\d+小时|\d+天|昨天|今天|\d{4}|\d{2}:\d{2})', text)
                author = author_match.group(1).strip() if author_match else ''
                
                # 提取时间
                time_match = re.search(r'(\d+小时前|\d+天前|昨天|今天|\d{2}:\d{2}|\d{4}-\d{2}-\d{2})', text)
                time_str = time_match.group(1) if time_match else ''
                
                # 提取内容 - 清理元数据
                content = text
                content = re.sub(r'^[^\d]+?(\d+小时前|\d+天前|昨天|今天)[^\n]*', '', content)
                content = re.sub(r'展开.*$', '', content, flags=re.MULTILINE)
                content = re.sub(r'转发.*$', '', content, flags=re.MULTILINE)
                content = re.sub(r'赞.*$', '', content, flags=re.MULTILINE)
                content = re.sub(r'收藏.*$', '', content, flags=re.MULTILINE)
                content = content.strip()[:500]
                
                # 获取链接
                link = ''
                link_elems = item.query_selector_all('a')
                for link_elem in link_elems:
                    href = link_elem.get_attribute('href') or ''
                    # 文章链接格式: /用户ID/文章ID
                    if re.match(r'/\d+/\d+$', href):
                        link = 'https://xueqiu.com' + href
                        break
                
                if content and len(content) > 10:
                    discussions.append(Discussion(
                        author=author[:30],
                        time=time_str,
                        content=content,
                        link=link
                    ))
                    
            except Exception as e:
                self.logger.debug(f"解析讨论失败: {e}")
        
        return discussions
    
    def _parse_news(self, page: Page, max_count: int = 20) -> List[News]:
        """解析资讯内容"""
        news_list = []
        items = page.query_selector_all('.timeline__item')
        
        self.logger.info(f"解析资讯: 找到 {len(items)} 条")
        
        for idx, item in enumerate(items[:max_count]):
            try:
                text = item.inner_text().strip()
                
                # 提取标题 - 清理无关内容
                title = text
                title = re.sub(r'^携程\(TCOM\)\d{2}-\d{2}\s*\d{1,2}:\d{2}·\s*来自新闻\s*', '', title)
                title = re.sub(r'^收起\s*', '', title)
                title = title[:100].strip()
                
                # 提取时间
                time_match = re.search(r'(\d{2}-\d{2})', text)
                time_str = time_match.group(1) if time_match else ''
                
                # 获取链接 - 直接遍历所有链接
                link = ''
                link_elems = item.query_selector_all('a')
                
                # 调试：打印前3个链接
                if idx < 3:
                    self.logger.info(f"  资讯[{idx+1}] 找到 {len(link_elems)} 个链接")
                    for j, le in enumerate(link_elems[:5]):
                        h = le.get_attribute('href') or ''
                        self.logger.info(f"    [{j}] {h}")
                
                for link_elem in link_elems:
                    href = link_elem.get_attribute('href') or ''
                    # 匹配格式: /S/股票代码/文章ID
                    if re.match(r'^/S/\w+/\d+$', href):
                        link = 'https://xueqiu.com' + href
                        self.logger.info(f"  资讯[{idx+1}] 匹配成功: {link}")
                        break
                    # 外部链接
                    if href.startswith('http') and 'xueqiu.com/S/' not in href:
                        link = href
                        break
                
                if not link and idx < 3:
                    self.logger.warning(f"  资讯[{idx+1}] 未找到有效链接")
                
                if title and len(title) > 5:
                    news_list.append(News(
                        title=title,
                        time=time_str,
                        source='雪球资讯',
                        link=link or 'https://xueqiu.com/S/TCOM'
                    ))
                    
            except Exception as e:
                self.logger.warning(f"解析资讯失败: {e}")
        
        return news_list
    
    def _parse_notices(self, page: Page) -> List[Notice]:
        """解析公告链接"""
        notices = []
        
        try:
            # 等待公告内容加载
            time.sleep(1)
            
            # 使用 JavaScript 获取公告列表
            notice_items = page.evaluate('''() => {
                const items = [];
                const timelineItems = document.querySelectorAll('.timeline__item');
                
                for (const item of timelineItems) {
                    const text = item.innerText || '';
                    const links = item.querySelectorAll('a');
                    
                    for (const link of links) {
                        const href = link.getAttribute('href') || '';
                        // 匹配格式: /S/股票代码/文章ID
                        if (/^\\/S\\/\\w+\\/\\d+$/.test(href)) {
                            let title = text.split('\\n')[0] || '公告';
                            // 清理标题
                            title = title.replace(/^携程\\(TCOM\\)\\d{2}-\\d{2}\\s*\\d{1,2}:\\d{2}·\\s*来自公告\\s*/, '');
                            title = title.substring(0, 50);
                            
                            const idMatch = href.match(/\\/(\\d+)$/);
                            const id = idMatch ? idMatch[1] : '';
                            
                            items.push({
                                title: title || '公告',
                                link: 'https://xueqiu.com' + href,
                                id: id
                            });
                            break;
                        }
                    }
                }
                
                return items;
            }''')
            
            for item in notice_items[:10]:
                notices.append(Notice(
                    title=item.get('title', '公告'),
                    link=item.get('link', ''),
                    id=item.get('id', '')
                ))
            
            self.logger.info(f"解析公告: 找到 {len(notices)} 条")
                
        except Exception as e:
            self.logger.warning(f"解析公告失败: {e}")
        
        return notices
    
    def _crawl_article_detail(self, page: Page, url: str) -> Optional[Article]:
        """爬取文章详情"""
        try:
            page.goto(url, timeout=30000)
            page.wait_for_timeout(2000)
            
            # 关闭可能出现的弹窗
            self._close_modal(page)
            
            # 获取标题
            title = page.title()
            if '雪球' in title:
                parts = title.split('-')
                title = parts[0].strip()
            
            # 获取作者
            author_elem = page.query_selector('.article__bd__from a, .user-name, .author-name')
            author = author_elem.inner_text().strip() if author_elem else ''
            
            # 获取时间
            time_elem = page.query_selector('.article__bd__from .date, .time, .date')
            time_str = time_elem.inner_text().strip() if time_elem else ''
            
            # 获取正文
            content_elem = page.query_selector('.article__bd__detail')
            content = ''
            if content_elem:
                content = content_elem.inner_text().strip()
            else:
                # 备选选择器
                content_elem = page.query_selector('.status-content, article')
                content = content_elem.inner_text().strip() if content_elem else ''
            
            # 提取文章ID
            article_id = ''
            match = re.search(r'/(\d+)$', url)
            if match:
                article_id = match.group(1)
            
            return Article(
                title=title[:100],
                author=author,
                time=time_str,
                content=content[:5000],
                link=url,
                article_id=article_id
            )
            
        except Exception as e:
            self.logger.warning(f"爬取文章详情失败 {url}: {e}")
            return None
    
    def crawl(self, symbol: str, max_discussions: int = 20, max_news: int = 20, 
              max_articles: int = 10, max_scrolls: int = 10) -> StockInfo:
        """
        爬取股票详情页数据
        
        Args:
            symbol: 股票代码
            max_discussions: 最大讨论数
            max_news: 最大资讯数
            max_articles: 最大文章数
            max_scrolls: 最大滚动次数
            
        Returns:
            StockInfo: 股票信息
        """
        self.logger.info(f"开始爬取股票: {symbol}")
        
        stock_info = StockInfo(symbol=symbol)
        
        with sync_playwright() as p:
            browser, context = self._create_browser_context(p)
            page = context.new_page()
            
            try:
                # 1. 访问首页
                self.logger.info("访问雪球首页...")
                page.goto('https://xueqiu.com', timeout=30000)
                time.sleep(2)
                
                # 检查登录状态，如未登录则尝试登录
                if not self._check_login_status(page):
                    self.logger.info("未登录，尝试登录...")
                    self._login(page)
                    time.sleep(2)
                else:
                    self.logger.info("已登录")
                
                # 关闭可能的弹窗
                self._close_modal(page)
                
                # 2. 访问股票详情页
                url = f'https://xueqiu.com/S/{symbol}'
                self.logger.info(f"访问股票详情页: {url}")
                page.goto(url, timeout=30000)
                time.sleep(3)
                
                # 关闭登录弹窗
                self._close_modal(page)
                
                # 获取股票名称
                name_elem = page.query_selector('.stock-name')
                if name_elem:
                    stock_info.name = name_elem.inner_text().strip()
                    self.logger.info(f"股票名称: {stock_info.name}")
                
                # 获取价格
                price_elem = page.query_selector('.stock-current')
                if price_elem:
                    stock_info.price = price_elem.inner_text().strip()[:50]
                
                # ========== 爬取讨论 ==========
                self.logger.info("\n" + "="*50)
                self.logger.info("=== 爬取讨论 ===")
                self.logger.info("="*50)
                
                # 切换到讨论 tab
                if self._switch_tab(page, '讨论'):
                    # 分页累积加载
                    all_items = self._parse_items_with_pagination(page, max_pages=max_scrolls, target_count=max_discussions)
                    
                    # 解析累积的讨论
                    for item in all_items[:max_discussions]:
                        try:
                            text = item.inner_text().strip()
                            author_match = re.search(r'^([^\d]+?)(?=\d+小时|\d+天|昨天|今天|\d{4}|\d{2}:\d{2})', text)
                            author = author_match.group(1).strip() if author_match else ''
                            time_match = re.search(r'(\d+小时前|\d+天前|昨天|今天|\d{2}:\d{2}|\d{4}-\d{2}-\d{2})', text)
                            time_str = time_match.group(1) if time_match else ''
                            content = text
                            content = re.sub(r'^[^\d]+?(\d+小时前|\d+天前|昨天|今天)[^\n]*', '', content)
                            content = re.sub(r'展开.*$', '', content, flags=re.MULTILINE)
                            content = re.sub(r'转发.*$', '', content, flags=re.MULTILINE)
                            content = re.sub(r'赞.*$', '', content, flags=re.MULTILINE)
                            content = re.sub(r'收藏.*$', '', content, flags=re.MULTILINE)
                            content = content.strip()[:500]
                            
                            link = ''
                            link_elems = item.query_selector_all('a')
                            for link_elem in link_elems:
                                href = link_elem.get_attribute('href') or ''
                                if re.match(r'/\d+/\d+$', href):
                                    link = 'https://xueqiu.com' + href
                                    break
                            
                            if content and len(content) > 10:
                                stock_info.discussions.append(Discussion(
                                    author=author[:30],
                                    time=time_str,
                                    content=content,
                                    link=link
                                ))
                        except Exception as e:
                            pass
                    
                    self.logger.info(f"获取 {len(stock_info.discussions)} 条讨论")
                
                # ========== 爬取资讯 ==========
                self.logger.info("\n" + "="*50)
                self.logger.info("=== 爬取资讯 ===")
                self.logger.info("="*50)
                
                if self._switch_tab(page, '资讯'):
                    time.sleep(2)
                    all_items = self._parse_items_with_pagination(page, max_pages=max_scrolls, target_count=max_news)
                    
                    for item in all_items[:max_news]:
                        try:
                            text = item.inner_text().strip()
                            lines = text.split('\n')
                            title = lines[0] if lines else text[:100]
                            time_match = re.search(r'(\d+小时前|\d+天前|昨天|\d{2}-\d{2}|\d{4}-\d{2}-\d{2})', text)
                            time_str = time_match.group(1) if time_match else ''
                            source_match = re.search(r'来自([^\n]+)', text)
                            source = source_match.group(1).strip()[:30] if source_match else '雪球'
                            
                            link = ''
                            link_elems = item.query_selector_all('a')
                            for link_elem in link_elems:
                                href = link_elem.get_attribute('href') or ''
                                # 优先匹配: /S/股票代码/文章ID
                                if re.match(r'^/S/\w+/\d+$', href):
                                    link = 'https://xueqiu.com' + href
                                    break
                                # 外部链接
                                if href.startswith('http') and 'xueqiu.com/S/' not in href:
                                    link = href
                                    break
                            
                            if title and len(title) > 5:
                                stock_info.news.append(News(
                                    title=title[:100],
                                    time=time_str,
                                    source=source,
                                    link=link
                                ))
                        except Exception as e:
                            pass
                    
                    self.logger.info(f"获取 {len(stock_info.news)} 条资讯")
                
                # ========== 爬取公告 ==========
                self.logger.info("\n" + "="*50)
                self.logger.info("=== 爬取公告 ===")
                self.logger.info("="*50)
                
                if self._switch_tab(page, '公告'):
                    time.sleep(2)
                    stock_info.notices = self._parse_notices(page)
                    self.logger.info(f"获取 {len(stock_info.notices)} 条公告")
                
                # ========== 爬取文章详情 ==========
                # 从讨论中提取文章链接
                article_links = []
                seen_links = set()
                
                for d in stock_info.discussions:
                    if d.link and d.link not in seen_links:
                        # 检查是否是文章链接
                        if re.match(r'https://xueqiu\.com/\d+/\d+$', d.link):
                            article_links.append(d.link)
                            seen_links.add(d.link)
                
                if article_links and max_articles > 0:
                    self.logger.info(f"\n爬取 {min(len(article_links), max_articles)} 篇文章详情...")
                    
                    for i, link in enumerate(article_links[:max_articles]):
                        try:
                            time.sleep(random.uniform(2, 4))
                            article = self._crawl_article_detail(page, link)
                            if article and article.content:
                                stock_info.articles.append(article)
                                self.logger.info(f"  [{i+1}] {article.title[:40]}...")
                        except Exception as e:
                            self.logger.warning(f"爬取文章失败: {e}")
                
                # 保存 cookies
                self._save_cookies(context)
                
            except Exception as e:
                self.logger.error(f"爬取失败: {e}")
                import traceback
                traceback.print_exc()
                
            finally:
                browser.close()
        
        self.logger.info(f"\n爬取完成: {len(stock_info.discussions)} 讨论, {len(stock_info.news)} 资讯, {len(stock_info.notices)} 公告, {len(stock_info.articles)} 文章")
        return stock_info
    
    def to_dict(self, stock_info: StockInfo) -> dict:
        """转换为字典"""
        return {
            'symbol': stock_info.symbol,
            'name': stock_info.name,
            'price': stock_info.price,
            'discussions': [asdict(d) for d in stock_info.discussions],
            'articles': [asdict(a) for a in stock_info.articles],
            'news': [asdict(n) for n in stock_info.news],
            'notices': [asdict(n) for n in stock_info.notices],
            'financial_data': stock_info.financial_data,
            'crawl_time': datetime.now().isoformat()
        }


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='雪球股票详情页爬虫 v2')
    parser.add_argument('symbol', nargs='?', default='TCOM', help='股票代码')
    parser.add_argument('--max-discussions', type=int, default=20, help='最大讨论数')
    parser.add_argument('--max-news', type=int, default=20, help='最大资讯数')
    parser.add_argument('--max-articles', type=int, default=10, help='最大文章数')
    parser.add_argument('--max-scrolls', type=int, default=10, help='最大滚动次数')
    parser.add_argument('--output', '-o', help='输出文件路径')
    parser.add_argument('--headful', action='store_true', help='显示浏览器界面')
    
    args = parser.parse_args()
    
    crawler = XueqiuStockCrawlerV2(headless=not args.headful)
    result = crawler.crawl(
        symbol=args.symbol,
        max_discussions=args.max_discussions,
        max_news=args.max_news,
        max_articles=args.max_articles,
        max_scrolls=args.max_scrolls
    )
    
    data = crawler.to_dict(result)
    
    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"结果已保存到: {args.output}")
    else:
        # 打印摘要
        print(f"\n=== 爬取结果 ===")
        print(f"股票: {result.name} ({result.symbol})")
        print(f"讨论: {len(result.discussions)} 条")
        print(f"资讯: {len(result.news)} 条")
        print(f"公告: {len(result.notices)} 条")
        print(f"文章: {len(result.articles)} 篇")


if __name__ == '__main__':
    main()