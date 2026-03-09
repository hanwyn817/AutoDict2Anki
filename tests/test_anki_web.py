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
