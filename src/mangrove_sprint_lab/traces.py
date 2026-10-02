"""Local execution traces: one JSON line per operation, including failures.

A trace records what ran, where and how it ended. It never records credentials, and question
or dataset content only when the caller passes it explicitly as already-redacted detail.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mangrove_sprint_lab.redact import redact

# Model usage is reported honestly: missing usage is "unavailable", never zero cost.
USAGE_STATES = ("complete", "partial", "unavailable", "not_applicable")


@dataclass
class ModelUsage:
    status: str = "not_applicable"
    provider: str | None = None
    model: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None

    def __post_init__(self) -> None:
        if self.status not in USAGE_STATES:
            raise ValueError(f"usage status must be one of {USAGE_STATES}")


@dataclass
class Trace:
    trace_id: str
    operation: str
    adapter: str
    environment: str
    started_at: str
    duration_ms: float | None = None
    outcome: str = "running"
    error: str | None = None
    upstream: list[dict[str, Any]] = field(default_factory=list)
    model_usage: ModelUsage = field(default_factory=ModelUsage)
    platform_trace: Any = None

    def call(self, **detail: Any) -> None:
        """Record one upstream call (method, url, status, duration...). Secrets are masked."""

        self.upstream.append(redact(detail))


class TraceLog:
    def __init__(self, outputs_dir: Path) -> None:
        self.path = outputs_dir / "traces" / "traces.jsonl"

    def write(self, trace: Trace) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(redact(asdict(trace)), ensure_ascii=False) + "\n")

    def read(self, limit: int = 20) -> list[dict[str, Any]]:
        if not self.path.is_file():
            return []
        lines = self.path.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines[-limit:] if line.strip()]

    @contextmanager
    def trace(self, operation: str, adapter: str, environment: str) -> Iterator[Trace]:
        record = Trace(
            trace_id=uuid.uuid4().hex[:16],
            operation=operation,
            adapter=adapter,
            environment=environment,
            started_at=datetime.now(UTC).isoformat(timespec="seconds"),
        )
        started = time.perf_counter()
        try:
            yield record
            if record.outcome == "running":
                record.outcome = "ok"
        except BaseException as error:
            record.outcome = "error"
            record.error = f"{type(error).__name__}: {error}"
            raise
        finally:
            record.duration_ms = round((time.perf_counter() - started) * 1000, 1)
            self.write(record)
