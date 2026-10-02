"""The one result shape every adapter returns, so the UI/CLI never guesses what happened."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ok                 the call completed; `data` is the platform's answer, verbatim.
# sign_in_required   no usable token, or the platform answered 401.
# unsupported        this transport has no documented contract for the operation.
# unconfigured       a setting or local dependency is missing; `error` names it.
# failed             the platform or network refused or broke; nothing ambiguous happened.
# outcome_unknown    a write may or may not have been applied (e.g. POST timeout). Never retried.
STATES = ("ok", "sign_in_required", "unsupported", "unconfigured", "failed", "outcome_unknown")


@dataclass
class OperationResult:
    state: str
    operation: str
    adapter: str
    environment: str
    data: Any = None
    error: str | None = None
    http_status: int | None = None
    raw: Any = None
    trace_id: str | None = None
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.state not in STATES:
            raise ValueError(f"unknown state {self.state!r}")

    @property
    def ok(self) -> bool:
        return self.state == "ok"

    def contribution_status(self) -> str | None:
        """`approved`, `staged`, `declined` or whatever else the platform said, exactly."""

        if isinstance(self.data, dict):
            status = self.data.get("status")
            return str(status) if status is not None else None
        return None
