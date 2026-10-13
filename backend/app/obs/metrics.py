from __future__ import annotations

from collections import defaultdict
from threading import Lock

_COUNTERS: dict[tuple[str, tuple[tuple[str, str], ...]], float] = defaultdict(float)
_HISTOGRAMS: dict[tuple[str, tuple[tuple[str, str], ...]], list[float]] = defaultdict(list)
_lock = Lock()

HISTOGRAM_MAX_SAMPLES = 512


def incr(name: str, value: float = 1.0, **labels: str) -> None:
    key = (name, tuple(sorted(labels.items())))
    with _lock:
        _COUNTERS[key] += value


def observe(name: str, value: float, **labels: str) -> None:
    key = (name, tuple(sorted(labels.items())))
    with _lock:
        samples = _HISTOGRAMS[key]
        samples.append(value)
        if len(samples) > HISTOGRAM_MAX_SAMPLES:
            del samples[: len(samples) - HISTOGRAM_MAX_SAMPLES]


def _format_labels(labels: tuple[tuple[str, str], ...], extra: dict[str, str] | None = None) -> str:
    merged = dict(labels)
    if extra:
        merged.update(extra)
    if not merged:
        return ""
    body = ",".join(f'{key}="{value}"' for key, value in sorted(merged.items()))
    return f"{{{body}}}"


def render_prometheus() -> str:
    """Expose metrics in Prometheus text format without pulling in a client library."""
    lines: list[str] = []
    with _lock:
        for (name, labels), value in sorted(_COUNTERS.items()):
            lines.append(f"{name}_total{_format_labels(labels)} {value}")
        for (name, labels), samples in sorted(_HISTOGRAMS.items()):
            lines.append(f"{name}_count{_format_labels(labels)} {len(samples)}")
            if samples:
                ordered = sorted(samples)
                lines.append(f"{name}_sum{_format_labels(labels)} {sum(ordered):.4f}")
                for quantile, position in (("0.5", 0.5), ("0.95", 0.95), ("0.99", 0.99)):
                    index = min(int(len(ordered) * position), len(ordered) - 1)
                    lines.append(
                        f"{name}{_format_labels(labels, {'quantile': quantile})} "
                        f"{ordered[index]:.4f}"
                    )
    return "\n".join(lines) + "\n"
