"""Variant registry for the THOR P2 relay-credit / event / ACK experiments.

Each variant changes exactly one dimension relative to ``control``. The
registry enforces that property, so a reported gain can be attributed to one
knob instead of a combination that was never measured separately.
"""
from __future__ import annotations

from dataclasses import dataclass, fields
from typing import Any

from ..telescoping import (
    INITIAL_STREAM_WINDOW_BYTES,
    MAX_STREAM_WINDOW_BYTES,
    STREAM_CHUNK_BYTES,
    WINDOW_UPDATE_BATCH_BYTES,
    WINDOW_UPDATE_MAX_DELAY_SECONDS,
)

__all__ = ["DIMENSIONS", "VARIANTS", "VariantSpec", "variant_by_name"]

# One experimental dimension may be backed by more than one field (the credit
# policy is a byte threshold plus a deadline; the event size is the relay read
# size plus the client bound). A variant is allowed to change one *dimension*.
DIMENSIONS: dict[str, tuple[str, ...]] = {
    "credit_window": ("credit_window_bytes",),
    "credit_policy": ("credit_batch_bytes", "credit_delay_seconds", "flush_floor_bytes"),
    "event_size": ("relay_read_chunk_bytes", "max_event_bytes"),
    "ack_pipeline": ("credit_pipeline",),
}

_CONTROL = dict(
    credit_window_bytes=INITIAL_STREAM_WINDOW_BYTES,
    credit_batch_bytes=WINDOW_UPDATE_BATCH_BYTES,
    credit_delay_seconds=WINDOW_UPDATE_MAX_DELAY_SECONDS,
    flush_floor_bytes=0,
    relay_read_chunk_bytes=STREAM_CHUNK_BYTES,
    max_event_bytes=STREAM_CHUNK_BYTES,
    credit_pipeline=False,
)


@dataclass(frozen=True, slots=True)
class VariantSpec:
    """One explicit lab configuration.

    ``credit_window_bytes`` is the total per-stream read window the client grants
    before the transfer starts; the control value is the protocol default, and
    larger values are applied with a protocol-legal ``WINDOW_UPDATE`` right after
    ``STREAM_STARTED`` (never by raising the relay's maximum).
    """

    name: str
    description: str
    credit_window_bytes: int = INITIAL_STREAM_WINDOW_BYTES
    credit_batch_bytes: int = WINDOW_UPDATE_BATCH_BYTES
    credit_delay_seconds: float = WINDOW_UPDATE_MAX_DELAY_SECONDS
    flush_floor_bytes: int = 0
    relay_read_chunk_bytes: int = STREAM_CHUNK_BYTES
    max_event_bytes: int = STREAM_CHUNK_BYTES
    credit_pipeline: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.credit_window_bytes, int)
            or isinstance(self.credit_window_bytes, bool)
            or not INITIAL_STREAM_WINDOW_BYTES <= self.credit_window_bytes <= MAX_STREAM_WINDOW_BYTES
        ):
            raise ValueError(
                "credit_window_bytes must be within "
                f"{INITIAL_STREAM_WINDOW_BYTES}..{MAX_STREAM_WINDOW_BYTES}"
            )
        if (
            not isinstance(self.credit_batch_bytes, int)
            or isinstance(self.credit_batch_bytes, bool)
            or not 1 <= self.credit_batch_bytes <= MAX_STREAM_WINDOW_BYTES
        ):
            raise ValueError("credit_batch_bytes must be within 1..MAX_STREAM_WINDOW_BYTES")
        if (
            not isinstance(self.credit_delay_seconds, (int, float))
            or isinstance(self.credit_delay_seconds, bool)
            or not 0 < float(self.credit_delay_seconds) <= 1.0
        ):
            raise ValueError("credit_delay_seconds must be within (0, 1.0]")
        if (
            not isinstance(self.relay_read_chunk_bytes, int)
            or isinstance(self.relay_read_chunk_bytes, bool)
            or not 1 <= self.relay_read_chunk_bytes <= MAX_STREAM_WINDOW_BYTES
        ):
            raise ValueError("relay_read_chunk_bytes must be within 1..MAX_STREAM_WINDOW_BYTES")
        if (
            not isinstance(self.max_event_bytes, int)
            or isinstance(self.max_event_bytes, bool)
            or not 1 <= self.max_event_bytes <= MAX_STREAM_WINDOW_BYTES
        ):
            raise ValueError("max_event_bytes must be within 1..MAX_STREAM_WINDOW_BYTES")
        if (
            not isinstance(self.flush_floor_bytes, int)
            or isinstance(self.flush_floor_bytes, bool)
            or not 0 <= self.flush_floor_bytes <= MAX_STREAM_WINDOW_BYTES
        ):
            raise ValueError("flush_floor_bytes must be within 0..MAX_STREAM_WINDOW_BYTES")
        if self.flush_floor_bytes > self.credit_window_bytes // 2:
            # Safety bound: while the caller is waiting with an empty receive
            # buffer, the relay holds ``window - pending`` credit and must still
            # be able to deliver at least one chunk. Keeping the floor at or
            # below half the window preserves progress without a control round
            # trip; larger values could stall a slow producer.
            raise ValueError("flush_floor_bytes must not exceed half the credit window")
        if self.max_event_bytes < self.relay_read_chunk_bytes:
            # The client would reject the very events the relay is configured to
            # send: refuse the combination instead of failing mid-transfer.
            raise ValueError("max_event_bytes must be >= relay_read_chunk_bytes")
        if not isinstance(self.credit_pipeline, bool):
            raise ValueError("credit_pipeline must be a boolean")

    def to_dict(self) -> dict[str, Any]:
        return {field.name: getattr(self, field.name) for field in fields(self)}

    def changed_dimensions(self) -> tuple[str, ...]:
        """Dimensions that differ from ``control`` (must be exactly one)."""
        control = VARIANTS["control"]
        return tuple(
            dimension
            for dimension, field_names in DIMENSIONS.items()
            if any(getattr(self, field_name) != getattr(control, field_name)
                   for field_name in field_names)
        )


def _variant(name: str, description: str, **overrides: Any) -> VariantSpec:
    known = set(_CONTROL) | {"name", "description"}
    unknown = set(overrides) - known
    if unknown:
        raise ValueError(f"unknown variant field(s): {sorted(unknown)}")
    return VariantSpec(name=name, description=description, **{**_CONTROL, **overrides})


VARIANTS: dict[str, VariantSpec] = {
    "control": _variant(
        "control",
        "Protocol default: 64 KiB window, 64 KiB/2 ms credit updates, 16 KiB events, ACK awaited inline.",
    ),
    "credit-window-128k": _variant(
        "credit-window-128k",
        "Control plus a 128 KiB total read window granted right after STREAM_STARTED.",
        credit_window_bytes=128 * 1024,
    ),
    "credit-window-256k": _variant(
        "credit-window-256k",
        "Control plus the maximum 256 KiB total read window granted right after STREAM_STARTED.",
        credit_window_bytes=256 * 1024,
    ),
    "credit-policy-32k-1ms": _variant(
        "credit-policy-32k-1ms",
        "Control with finer credit updates: 32 KiB batch, 1 ms deadline flush.",
        credit_batch_bytes=32 * 1024,
        credit_delay_seconds=0.001,
    ),
    "credit-policy-128k-4ms": _variant(
        "credit-policy-128k-4ms",
        "Control with coarser credit updates: 128 KiB batch, 4 ms deadline flush.",
        credit_batch_bytes=128 * 1024,
        credit_delay_seconds=0.004,
    ),
    "events-32k": _variant(
        "events-32k",
        "Control with 32 KiB destination reads and a 32 KiB client event bound.",
        relay_read_chunk_bytes=32 * 1024,
        max_event_bytes=32 * 1024,
    ),
    "events-64k": _variant(
        "events-64k",
        "Control with 64 KiB destination reads and a 64 KiB client event bound.",
        relay_read_chunk_bytes=64 * 1024,
        max_event_bytes=64 * 1024,
    ),
    "credit-policy-window-aware": _variant(
        "credit-policy-window-aware",
        "Control with the deadline flush gated by outstanding credit: no "
        "WINDOW_UPDATE while the relay still holds at least half the window "
        "(bounded and deadlock-free; the 2 ms deadline still applies above it).",
        flush_floor_bytes=32 * 1024,
    ),
    "ack-pipeline": _variant(
        "ack-pipeline",
        "Control with the WINDOW_UPDATE acknowledgement validated off the read path "
        "(single-flight, bounded backlog, same relay-side credit limits).",
        credit_pipeline=True,
    ),
}


def variant_by_name(name: str) -> VariantSpec:
    """Return a registered variant or raise a clear error."""
    try:
        return VARIANTS[name]
    except KeyError:
        raise ValueError(f"unknown variant {name!r}; known: {sorted(VARIANTS)}") from None


def assert_single_dimension() -> None:
    """Fail loudly if any variant silently combines two dimensions."""
    for name, spec in VARIANTS.items():
        changed = spec.changed_dimensions()
        expected = 0 if name == "control" else 1
        if len(changed) != expected:
            raise AssertionError(
                f"variant {name!r} changes {changed}; expected {expected} dimension(s)"
            )


assert_single_dimension()
