"""Shared log format and context for synchronous word-processing stages."""

import logging
from contextlib import contextmanager
from contextvars import ContextVar


LOG_FORMAT = "%(asctime)s %(levelname)-7s %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_context = ContextVar("processing_log_context", default={})


def get_log_context():
    return _context.get()


@contextmanager
def log_context(**values):
    token = _context.set(dict(_context.get(), **values))
    try:
        yield
    finally:
        _context.reset(token)


class ContextLogger(logging.LoggerAdapter):
    def process(self, message, kwargs):
        context = get_log_context()
        batch = context.get("batch", "")
        progress = context.get("progress", "")
        word = context.get("word", "")
        stage = " ".join(value for value in (batch, progress) if value)
        prefix = (f"[{stage}]" if stage else "") + (f"[{word}]" if word else "")
        return f"{prefix} {message}" if prefix else message, kwargs


def get_logger(name):
    return ContextLogger(logging.getLogger(name), {})


def configure_logging(handlers=None):
    logging.basicConfig(
        level=logging.INFO,
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
        handlers=handlers,
    )
