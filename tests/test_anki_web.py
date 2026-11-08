from types import SimpleNamespace

import anki_web


class _DummyPage:
    url = "https://ankiuser.net/add"

    def goto(self, *args, **kwargs):
        return None

    def locator(self, *args, **kwargs):
        return self

    @property
    def first(self):
        return self

    def wait_for(self, *args, **kwargs):
        return None


class _DummyContext:
    def __init__(self):
        self.cookies = None

    def add_cookies(self, cookies):
        self.cookies = cookies

    def new_page(self):
        return _DummyPage()


class _DummyBrowser:
    def __init__(self):
        self.context = _DummyContext()

    def new_context(self, **kwargs):
        return self.context

    def close(self):
        return None


class _DummyChromium:
    def __init__(self):
        self.launch_kwargs = None

    def launch(self, **kwargs):
        self.launch_kwargs = kwargs
        return _DummyBrowser()


class _DummyPlaywrightRunner:
    def __init__(self, chromium):
        self.chromium = chromium

    def stop(self):
        return None


def test_open_launches_chromium_with_container_safe_args(monkeypatch):
    chromium = _DummyChromium()

    monkeypatch.setattr(
        anki_web,
        "sync_playwright",
        lambda: SimpleNamespace(start=lambda: _DummyPlaywrightRunner(chromium)),
    )
    monkeypatch.setattr(anki_web.config, "ANKIWEB_COOKIE", "a=b; c=d")

    session = anki_web.AnkiWebSession()

    assert session.open() is None
    assert chromium.launch_kwargs["headless"] is True
    assert chromium.launch_kwargs["args"] == anki_web.CHROMIUM_LAUNCH_ARGS


def test_open_returns_clear_error_when_chromium_launch_fails(monkeypatch):
    class _BrokenChromium:
        def launch(self, **kwargs):
            raise RuntimeError("sandbox init failed")

    monkeypatch.setattr(
        anki_web,
        "sync_playwright",
        lambda: SimpleNamespace(start=lambda: _DummyPlaywrightRunner(_BrokenChromium())),
    )
    monkeypatch.setattr(anki_web.config, "ANKIWEB_COOKIE", "a=b")

    session = anki_web.AnkiWebSession()

    assert session.open() == "启动 Chromium 失败: sandbox init failed"


import pytest
from playwright.sync_api import sync_playwright


@pytest.fixture
def dropdown_page():
    with sync_playwright() as runner:
        try:
            browser = runner.chromium.launch(headless=True, args=anki_web.CHROMIUM_LAUNCH_ARGS)
        except Exception as exc:
            pytest.skip(f"Chromium unavailable: {exc}")
        try:
            page = browser.new_page()
            page.set_content('''
                <div class="form-group row">
                  <span class="col-2 col-form-label">Type</span>
                  <div class="selected-item">Basic</div><input type="text">
                  <div class="list-item"><span class="item" onclick="this.parentElement.parentElement.querySelector('.selected-item').textContent=this.textContent">Basic</span></div>
                  <div class="list-item"><span class="item" onclick="this.parentElement.parentElement.querySelector('.selected-item').textContent=this.textContent">基础</span></div>
                </div>
                <div class="form-group row">
                  <span class="col-2 col-form-label">Deck</span>
                  <div class="selected-item">Type vocabulary</div><input type="text">
                  <div class="list-item"><span class="item">Type vocabulary</span></div>
                  <div class="list-item"><span class="item">基础</span></div>
                </div>
                <div class="form-group row"><span class="col-form-label">Front</span>
                  <div class="col-10"><div class="form-control field" contenteditable="true"></div></div></div>
                <div class="form-group row"><span class="col-form-label">Back</span>
                  <div class="col-10"><div class="form-control field" contenteditable="true"></div></div></div>
            ''')
            yield page
        finally:
            browser.close()


def test_exact_caption_ignores_type_text_in_deck(dropdown_page):
    page = dropdown_page
    assert page.locator('div.form-group.row', has_text="Type").locator('input[type="text"]').count() == 2
    row = anki_web._dropdown_row(page, "Type")
    assert row.locator('input[type="text"]').count() == 1
    assert row.locator('.selected-item').inner_text() == "Basic"


def test_catalog_keeps_options_scoped_to_dropdown(dropdown_page):
    session = anki_web.AnkiWebSession()
    session._page = dropdown_page
    decks, models = session.get_catalog()
    assert decks == ["Type vocabulary", "基础"]
    assert list(models) == ["Basic", "基础"]


def test_select_does_not_click_same_named_option_in_other_dropdown(dropdown_page):
    assert anki_web._select_svelte_dropdown(dropdown_page, "Type", "基础") is None
    assert anki_web._dropdown_row(dropdown_page, "Type").locator('.selected-item').inner_text() == "基础"
    assert anki_web._dropdown_row(dropdown_page, "Deck").locator('.selected-item').inner_text() == "Type vocabulary"


def test_missing_caption_returns_clear_error(dropdown_page):
    error = anki_web._select_svelte_dropdown(dropdown_page, "Missing", "Basic")
    assert "无法唯一定位" in error
    assert "strict mode violation" not in error


def test_catalog_filters_fields_and_cloze_and_restores_selection(dropdown_page, monkeypatch):
    dropdown_page.evaluate('''() => {
        const row = document.querySelector('.form-group.row');
        for (const name of ['Cloze', 'Renamed', 'Three']) {
            const item = row.querySelector('.list-item').cloneNode(true);
            item.querySelector('.item').textContent = name;
            row.appendChild(item);
        }
    }''')
    session = anki_web.AnkiWebSession()
    session._page = dropdown_page
    def fields():
        name = anki_web._dropdown_row(dropdown_page, "Type").locator('.selected-item').inner_text()
        if name == "Three":
            return ["Word", "Meaning", "Extra"]
        if name == "Renamed":
            return ["Text", "Back Extra"]
        return ["Front", "Back"]
    monkeypatch.setattr(session, "note_fields", fields)
    _, models = session.get_catalog()
    assert list(models) == ["Basic", "基础"]
    assert set(models.excluded) == {"Cloze", "Renamed", "Three"}
    assert "3 个字段" in models.excluded["Three"]
    assert anki_web._dropdown_row(dropdown_page, "Type").locator('.selected-item').inner_text() == "Basic"


def test_note_fields_reads_actual_field_labels(dropdown_page):
    session = anki_web.AnkiWebSession()
    session._page = dropdown_page
    assert session.note_fields() == ["Front", "Back"]


def test_field_named_type_does_not_confuse_type_dropdown(dropdown_page):
    dropdown_page.locator('div.form-group.row').nth(2).locator('.col-form-label').evaluate('(el) => el.textContent = "Type"')
    row = anki_web._dropdown_row(dropdown_page, "Type")
    assert row.locator('input[type="text"]').count() == 1
    assert row.locator('.selected-item').inner_text() == "Basic"
