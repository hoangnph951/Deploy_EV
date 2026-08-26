"""Detailed, per-run planning trace logger used by F1 algorithm tests.

The logger is deliberately independent from the application's normal logging
configuration.  Every planning invocation gets one JSONL file under
``log_F1``; each line is a self-contained event with serialized inputs and
outputs so a test run can be inspected without rerunning the algorithm.
"""
from __future__ import annotations

import contextvars
import json
import threading
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from time import perf_counter
from typing import Any
from uuid import uuid4

_CURRENT_RUN: contextvars.ContextVar[PlanningRunLogger | None] = contextvars.ContextVar(
    "f1_planning_run_logger", default=None
)


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if hasattr(value, "model_dump"):
        try:
            return _jsonable(value.model_dump(mode="json"))
        except TypeError:
            return _jsonable(value.model_dump())
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "__dict__"):
        return {str(k): _jsonable(v) for k, v in vars(value).items() if not k.startswith("_")}
    return repr(value)


class PlanningRunLogger:
    def __init__(self, initial_state: dict[str, Any], directory: str | Path = "log_F1"):
        root = Path(directory)
        root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
        self.run_id = uuid4().hex
        self.path = root / f"F1_{stamp}_{self.run_id[:8]}.jsonl"
        self._lock = threading.Lock()
        self._started = perf_counter()
        self.event("run_started", input_state=initial_state)

    def event(self, event: str, **payload: Any) -> None:
        record = {
            "run_id": self.run_id,
            "timestamp": datetime.now().astimezone().isoformat(),
            "elapsed_ms": round((perf_counter() - self._started) * 1000, 3),
            "event": event,
            **{key: _jsonable(value) for key, value in payload.items()},
        }
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(line)

    def finish(self, output_state: Any = None, error: BaseException | None = None) -> None:
        self.event("run_finished", output_state=output_state, error=error)


def start_run(initial_state: dict[str, Any]) -> PlanningRunLogger:
    logger = PlanningRunLogger(initial_state)
    _CURRENT_RUN.set(logger)
    return logger


def current_run() -> PlanningRunLogger | None:
    return _CURRENT_RUN.get()


def log_event(event: str, **payload: Any) -> None:
    logger = current_run()
    if logger is not None:
        logger.event(event, **payload)


def finish_run(output_state: Any = None, error: BaseException | None = None) -> None:
    logger = current_run()
    if logger is not None:
        logger.finish(output_state, error)
        _CURRENT_RUN.set(None)

