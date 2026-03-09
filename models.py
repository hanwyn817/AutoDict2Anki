from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional, Union

ProcessStatus = Literal[
    "added",
    "skipped_duplicate",
    "retryable_failed",
    "fatal_failed",
]


@dataclass(frozen=True)
class WordEntry:
    id: Optional[Union[int, str]]
    uuid: str
    exp: str
    addtime: datetime


@dataclass(frozen=True)
class ProcessResult:
    status: ProcessStatus
    word: str
    reason: str = ""
    failure_kind: str = ""
