"""Small OpenTelemetry-shaped span records for local harness tracing.

Records use trace/span IDs, parent relationships, nanosecond timestamps,
status, and attributes without requiring an exporter or SDK dependency.
"""
from __future__ import annotations

from datetime import datetime, timezone
import time
import uuid
from typing import Any


def make_span(
    event: str,
    trace_id: str,
    *,
    name: str,
    parent_span_id: str | None = None,
    attributes: dict[str, Any] | None = None,
    status: str = "OK",
    start_time_unix_nano: int | None = None,
    duration_ns: int = 0,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build JSON-safe span data while preserving the harness event contract."""
    duration_ns = max(0, int(duration_ns))
    if start_time_unix_nano is None:
        start_time_unix_nano = time.time_ns()
    end_time_unix_nano = start_time_unix_nano + duration_ns
    timestamp = datetime.fromtimestamp(
        start_time_unix_nano / 1_000_000_000, tz=timezone.utc
    ).isoformat(timespec="microseconds").replace("+00:00", "Z")
    return {
        **(payload or {}),
        "event": event,
        "name": name,
        "run_id": trace_id,
        "trace_id": trace_id,
        "span_id": uuid.uuid4().hex[:16],
        "parent_span_id": parent_span_id,
        "kind": "INTERNAL",
        "timestamp": timestamp,
        "start_time_unix_nano": start_time_unix_nano,
        "end_time_unix_nano": end_time_unix_nano,
        "duration_ns": duration_ns,
        "status": status,
        "attributes": {
            key: value for key, value in (attributes or {}).items() if value is not None
        },
    }
