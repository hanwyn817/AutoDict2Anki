"""处理事件独立于日志；交互界面和后台任务共用处理流程。"""
from contextlib import contextmanager
from contextvars import ContextVar
from log_utils import get_log_context

_listener = ContextVar("processing_listener", default=None)


def emit(kind, **values):
    listener = _listener.get()
    if listener:
        listener(dict(get_log_context(), kind=kind, **values))


@contextmanager
def listen(callback):
    token = _listener.set(callback)
    try:
        yield
    finally:
        _listener.reset(token)
