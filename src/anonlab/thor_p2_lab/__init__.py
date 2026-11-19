"""THOR P2 lab: relay read credit, WINDOW_UPDATE policy, response-event size and ACK pipelining.

Everything in this package is **laboratory-only** and opt-in. The default AEGIS
path is untouched: :class:`VariantSpec` values default to the production
constants, and ``control`` is byte-for-byte the current behaviour.

The package never claims anonymity or WAN performance. It measures loopback
cost on one host and records exactly what it did not demonstrate.
"""
from __future__ import annotations

from .variants import VARIANTS, VariantSpec, variant_by_name

__all__ = ["VARIANTS", "VariantSpec", "variant_by_name"]
