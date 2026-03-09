import logging
import time
from typing import Any, Dict, List, Optional

from playwright.sync_api import sync_playwright, Page, BrowserContext, Browser

import config

logger = logging.getLogger(__name__)

# 每张卡片之间的间隔秒数，防止被限流
CARD_ADD_INTERVAL = 2

# 会话级错误标记：在 add_card 返回的 error 中携带此前缀时，调用方应中止整批处理
SESSION_ERROR_PREFIX = "[SESSION_ERROR]"


def _parse_cookie_string(cookie_str: str, domain: str) -> list[dict]:
    """Parse a raw cookie string into the format expected by Playwright."""
    cookies = []
    if not cookie_str:
        return cookies

    for item in cookie_str.split(";"):
        if "=" in item:
            name, value = item.strip().split("=", 1)
            cookies.append(
                {
                    "name": name,
                    "value": value,
                    "domain": domain,
                    "path": "/",
                }
            )
    return cookies


def _select_svelte_dropdown(page: Page, label: str, target_value: str) -> str | None:
    """
    检查并切换 AnkiWeb 页面上的 svelte-select 下拉框。
    label: 行标签文本，如 'Type' 或 'Deck'。
    target_value: 目标值。
    返回 None 表示成功，否则返回错误信息。
    """
    row = page.locator('div.form-group.row', has_text=label)
    selected_item = row.locator('div.selected-item')

    current_value = selected_item.inner_text().strip()
    if current_value == target_value:
        logger.info("当前 %s 已经是 '%s'，无需切换。", label, target_value)
        return None

    logger.info("当前 %s 为 '%s'，需要切换到 '%s'", label, current_value, target_value)
    dropdown_input = row.locator('input[type="text"]')
    dropdown_input.click()
    dropdown_input.fill(target_value)

    try:
        # 等待下拉列表出现后，用精确文本匹配避免误匹配子串
        page.wait_for_selector('div.list-item .item', timeout=3000)
        options = page.locator('div.list-item .item').all()
        matched = None
        for opt in options:
            if opt.inner_text().strip() == target_value:
                matched = opt
                break
        if matched is None:
            available = [o.inner_text().strip() for o in options]
            return f"未能在 AnkiWeb 中找到名为 '{target_value}' 的 {label}。现有选项: {available}"
        matched.click()
    except Exception as e:
        return f"切换 {label} 时发生错误: {e}"

    return None


class AnkiWebSession:
    """管理 Playwright 浏览器会话，在多张卡片之间复用同一个浏览器上下文。"""

    def __init__(self):
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._dropdown_selected = False

    def open(self) -> str | None:
        """
        启动浏览器，注入 Cookie，导航到 AnkiWeb 添加页面。
        返回 None 表示成功，否则返回错误信息。
        """
        if not config.ANKIWEB_COOKIE:
            return "未配置 ANKIWEB_COOKIE，无法使用 AnkiWeb 同步模式。"

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)
        self._context = self._browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36',
        )

        cookies = _parse_cookie_string(config.ANKIWEB_COOKIE, "ankiuser.net")
        cookies.extend(_parse_cookie_string(config.ANKIWEB_COOKIE, ".ankiuser.net"))
        self._context.add_cookies(cookies)

        self._page = self._context.new_page()

        logger.info("Navigate to https://ankiuser.net/add")
        self._page.goto("https://ankiuser.net/add", wait_until="networkidle")

        if "login" in self._page.url.lower() or "account" in self._page.url.lower():
            self.close()
            return "AnkiWeb 登录失效，请使用 update_cookie.py 更新 ANKI_WEB_COOKIE。"

        try:
            self._page.locator('div.form-control.field').first.wait_for(state="visible", timeout=10000)
        except Exception:
            self.close()
            return "AnkiWeb 页面加载超时，找不到输入字段。可能是 Cookie 失效或页面结构变更。"

        return None

    def close(self):
        """关闭浏览器释放资源。"""
        try:
            if self._browser:
                self._browser.close()
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass
        self._page = None
        self._context = None
        self._browser = None
        self._playwright = None
        self._dropdown_selected = False

    def add_card(self, front: str, back: str, deck_name: str, progress: str = "") -> Dict[str, Any]:
        """
        在已打开的浏览器会话中添加一张卡片。

        AnkiWeb 页面结构 (Svelte 应用):
          - Type / Deck: svelte-select 自定义下拉框
          - 正面 / 背面: <div class="form-control field" contenteditable="true">
          - Tags: <input type="text" class="form-control">
          - Add 按钮: <button class="btn btn-primary btn-large mt-2"> (初始 disabled)
        """
        if not self._page:
            return {"error": "浏览器会话未打开，请先调用 open()。"}

        page = self._page

        try:
            if progress:
                logger.info("[%s] 正在处理: %s", progress, front)

            # 仅在首张卡片时检查并切换 Type 和 Deck（之后页面会保持选择）
            if not self._dropdown_selected:
                type_error = _select_svelte_dropdown(page, 'Type', config.ANKI_NOTE_TYPE)
                if type_error:
                    return {"error": f"{SESSION_ERROR_PREFIX} {type_error}"}
                deck_error = _select_svelte_dropdown(page, 'Deck', deck_name)
                if deck_error:
                    return {"error": f"{SESSION_ERROR_PREFIX} {deck_error}"}
                self._dropdown_selected = True

            # Fill the front field
            front_field = page.locator('div.form-control.field').nth(0)
            front_field.click()
            front_field.fill(front)

            # Fill the back field (may contain HTML)
            back_field = page.locator('div.form-control.field').nth(1)
            back_field.click()
            back_field.evaluate('(el, content) => el.innerHTML = content', back)
            back_field.dispatch_event('input')

            # Wait for the Add button to become enabled
            add_button = page.locator('button:has-text("Add")')
            try:
                add_button.wait_for(state="visible", timeout=3000)
                page.wait_for_function(
                    '() => !document.querySelector("button.btn-primary").disabled',
                    timeout=3000,
                )
            except Exception:
                return {"error": "Add 按钮未能启用，可能是页面字段未正确填入。"}

            # Click the Add button
            add_button.click()

            # Wait for save completion — fields should be cleared
            try:
                page.wait_for_function(
                    '() => document.querySelectorAll("div.form-control.field")[0].innerText.trim() === ""',
                    timeout=10000,
                )
            except Exception:
                alert = page.locator('.alert').first
                if alert.is_visible():
                    err_text = alert.inner_text()
                    return {"error": f"AnkiWeb 返回错误: {err_text}"}
                return {"error": "添加卡片后未检测到预期的字段清空反馈，可能添加失败。"}

            logger.info("卡片 '%s' 已成功提交到 AnkiWeb。", front)
            return {}

        except Exception as exc:
            logger.error("Playwright 交互时发生错误: %s", exc)
            return {"error": f"Playwright 交互错误: {exc}"}


# ───────── 对外兼容接口（供 main.py 的 process_word 单张调用时使用） ─────────

def add_card_to_ankiweb(front: str, back: str, deck_name: str) -> Dict[str, Any]:
    """
    单张卡片的便捷方法（兼容旧接口）。
    每次调用都会启动和关闭浏览器，适用于测试等单次场景。
    批量添加时请使用 AnkiWebSession。
    """
    session = AnkiWebSession()
    err = session.open()
    if err:
        return {"error": err}
    try:
        return session.add_card(front, back, deck_name)
    finally:
        session.close()
