"""终端动态进度：处理事件驱动状态，日志文件保留完整过程。"""
import logging
import os
import shutil
import sys
import threading
import time
import unicodedata
from collections import Counter
from contextlib import contextmanager

from events import listen
from log_utils import LOG_DATE_FORMAT, LOG_FORMAT


def clip(text, width):
    result, used = [], 0
    for char in str(text):
        if unicodedata.category(char).startswith("C"):
            char = " "
        size = 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
        if used + size > width:
            break
        result.append(char)
        used += size
    return "".join(result)


class Progress(logging.Handler):
    def __init__(self, total, stream=None, verbose=False):
        super().__init__(logging.INFO if verbose else logging.WARNING)
        self.stream = stream if stream is not None else sys.stderr
        self.dynamic = self.stream.isatty() and os.environ.get("TERM") != "dumb" and not verbose
        self.total = total
        self.results = {}
        self.word = ""
        self.stage = "准备中"
        self.started = time.monotonic()
        self.lock_ui = threading.RLock()
        self.stop = threading.Event()
        self.thread = None
        self.rendered = False

    def event(self, event):
        with self.lock_ui:
            self.word = event.get("word", self.word)
            if event["kind"] == "result":
                result = event["result"]
                self.results[result.word] = result.status
                self.stage = "已完成" if result.status in ("added", "skipped_duplicate") else "处理失败"
                if not self.dynamic:
                    self.stream.write(f"[{len(self.results)}/{self.total}] {clip(result.word, 60)} · {result.status}\n")
                    self.stream.flush()
            else:
                self.stage = event["stage"]
            self.draw()

    def draw(self):
        if not self.dynamic:
            return
        counts = Counter(self.results.values())
        done = sum(v in ("added", "skipped_duplicate") for v in self.results.values())
        failed = len(self.results) - done
        elapsed = int(time.monotonic() - self.started)
        bar = "━" * int(12 * len(self.results) / max(self.total, 1))
        bar = bar.ljust(12, "─")
        lines = [f"{bar} {len(self.results)}/{self.total} · 已用时 {elapsed // 60:02}:{elapsed % 60:02}",
                 f"当前：{self.word or '—'} · {self.stage}",
                 f"已添加 {counts['added']}    重复跳过 {counts['skipped_duplicate']}    失败或未处理 {failed}"]
        width = max(1, shutil.get_terminal_size().columns - 1)
        self.stream.write("\r" + "\n".join("\033[2K" + clip(line, width) for line in lines) + "\033[2A\r")
        self.rendered = True
        self.stream.flush()

    def clear(self):
        if self.dynamic and self.rendered:
            self.stream.write("\r\033[2K\n\033[2K\n\033[2K\033[2A\r")
            self.rendered = False

    def emit(self, record):
        with self.lock_ui:
            self.clear()
            self.stream.write(self.format(record) + "\n")
            self.draw()
            self.stream.flush()

    def tick(self):
        while not self.stop.wait(0.2):
            with self.lock_ui:
                self.draw()

    def __enter__(self):
        if self.dynamic:
            self.thread = threading.Thread(target=self.tick, daemon=True)
            self.thread.start()
        return self

    def __exit__(self, *args):
        self.stop.set()
        if self.thread:
            self.thread.join()
        self.clear()
        self.stream.flush()


@contextmanager
def display(total, log_path, verbose=False, on_event=None):
    root_logger = logging.getLogger()
    handlers, level = root_logger.handlers[:], root_logger.level
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
    with Progress(total, verbose=verbose) as progress:
        progress.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
        root_logger.handlers = [file_handler, progress]
        root_logger.setLevel(logging.DEBUG)
        try:
            def handle_event(event):
                progress.event(event)
                if on_event:
                    on_event(event)

            with listen(handle_event):
                yield progress
        finally:
            root_logger.handlers = handlers
            root_logger.setLevel(level)
            file_handler.close()
