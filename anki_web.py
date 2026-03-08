import logging
from typing import Any, Dict

from playwright.sync_api import sync_playwright, Page

import config

logger = logging.getLogger(__name__)


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


def _select_deck(page: Page, deck_name: str) -> str | None:
    """
    检查当前牌组是否匹配，如果不匹配则尝试切换。
    AnkiWeb 使用 Svelte 自定义下拉框组件 (svelte-select)。
    返回 None 表示成功，否则返回错误信息。
    """
    # Deck 区域是第二个 svelte-select 组件（第一个是 Type）
    deck_row = page.locator('div.form-group.row', has_text='Deck')
    selected_item = deck_row.locator('div.selected-item')

    current_deck = selected_item.inner_text().strip()
    if current_deck == deck_name:
        logger.info("当前牌组已经是 '%s'，无需切换。", deck_name)
        return None

    # 需要切换牌组：点击输入框打开下拉列表
    logger.info("当前牌组为 '%s'，需要切换到 '%s'", current_deck, deck_name)
    deck_input = deck_row.locator('input[type="text"]')
    deck_input.click()
    deck_input.fill(deck_name)

    # 等待下拉选项出现并点击匹配的选项
    try:
        option = page.locator(f'div.list-item .item:has-text("{deck_name}")').first
        option.wait_for(state="visible", timeout=3000)
        option.click()
    except Exception:
        return f"未能在 AnkiWeb 中找到名为 '{deck_name}' 的牌组。"

    return None


def add_card_to_ankiweb(front: str, back: str, deck_name: str) -> Dict[str, Any]:
    """
    通过 Playwright 无头浏览器自动导航至 AnkiWeb (ankiuser.net/add) 并添加卡片。

    AnkiWeb 页面结构 (Svelte 应用):
      - Type / Deck: svelte-select 自定义下拉框
      - 正面 / 背面: <div class="form-control field" contenteditable="true">
      - Tags: <input type="text" class="form-control">
      - Add 按钮: <button class="btn btn-primary btn-large mt-2"> (初始 disabled)
    """
    if not config.ANKIWEB_COOKIE:
        return {"error": "未配置 ANKIWEB_COOKIE，无法使用 AnkiWeb 同步模式。"}

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/145.0.0.0 Safari/537.36',
            )

            # Inject the cookies
            cookies = _parse_cookie_string(config.ANKIWEB_COOKIE, "ankiuser.net")
            cookies.extend(_parse_cookie_string(config.ANKIWEB_COOKIE, ".ankiuser.net"))
            context.add_cookies(cookies)

            page = context.new_page()

            # Go to the add page
            logger.info("Navigate to https://ankiuser.net/add")
            page.goto("https://ankiuser.net/add", wait_until="networkidle")

            # Check if we didn't land on add page (e.g., redirected to login due to bad cookie)
            if "login" in page.url.lower() or "account" in page.url.lower():
                browser.close()
                return {"error": "AnkiWeb 登录失效，请使用 update_cookie.py 更新 ANKIWEB_COOKIE。"}

            # Wait for the form to be rendered (正面 field)
            try:
                page.locator('div.form-control.field').first.wait_for(state="visible", timeout=10000)
            except Exception:
                browser.close()
                return {"error": "AnkiWeb 页面加载超时，找不到输入字段。可能是 Cookie 失效或页面结构变更。"}

            # Select the correct deck
            deck_error = _select_deck(page, deck_name)
            if deck_error:
                browser.close()
                return {"error": deck_error}

            # Fill the front field (first contenteditable div)
            front_field = page.locator('div.form-control.field').nth(0)
            front_field.click()
            front_field.fill(front)

            # Fill the back field (second contenteditable div)
            # Using evaluate to set innerHTML for definitions which may contain HTML formatting
            back_field = page.locator('div.form-control.field').nth(1)
            back_field.click()
            back_field.evaluate('(el, content) => el.innerHTML = content', back)
            # Trigger input event so Svelte picks up the change and enables the Add button
            back_field.dispatch_event('input')

            # Wait for the Add button to become enabled
            add_button = page.locator('button:has-text("Add")')
            try:
                add_button.wait_for(state="visible", timeout=3000)
                # Wait until button is enabled (disabled attribute removed)
                page.wait_for_function(
                    '() => !document.querySelector("button.btn-primary").disabled',
                    timeout=3000,
                )
            except Exception:
                browser.close()
                return {"error": "Add 按钮未能启用，可能是页面字段未正确填入。"}

            # Click the Add button
            add_button.click()

            # Wait for the save to complete - the fields should be cleared after successful save
            try:
                page.wait_for_function(
                    '() => document.querySelectorAll("div.form-control.field")[0].innerText.trim() === ""',
                    timeout=10000,
                )
            except Exception:
                # Check if there's an alert/error on the page
                alert = page.locator('.alert').first
                if alert.is_visible():
                    err_text = alert.inner_text()
                    browser.close()
                    return {"error": f"AnkiWeb 返回错误: {err_text}"}
                browser.close()
                return {"error": "添加卡片后未检测到预期的字段清空反馈，可能添加失败。"}

            logger.info("卡片已成功提交到 AnkiWeb。")
            browser.close()
            return {}  # Empty dict on success, mimicking AnkiConnect success shape

    except Exception as exc:
        logger.error("Playwright 交互时发生错误: %s", exc)
        return {"error": f"Playwright 交互错误: {exc}"}
