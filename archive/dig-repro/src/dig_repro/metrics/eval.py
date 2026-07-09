"""Evaluation helpers."""

from __future__ import annotations

from collections import Counter


def count_detections(detections: list) -> dict[str, int]:
    return dict(Counter(item.kind for item in detections))

