from contextlib import contextmanager
from dataclasses import dataclass
from functools import wraps
from threading import Lock
from time import perf_counter


@dataclass(frozen=True)
class PerformanceRecord:
    name: str
    calls: int
    last_ms: float
    average_ms: float
    maximum_ms: float


class PerformanceChecker:
    """Thread-safe timing registry for worker and UI code paths."""

    def __init__(self):
        self._lock = Lock()
        self._records: dict[str, PerformanceRecord] = {}

    @contextmanager
    def measure(self, name: str):
        started = perf_counter()
        try:
            yield
        finally:
            self.record(name, (perf_counter() - started) * 1000.0)

    def record(self, name: str, duration_ms: float):
        with self._lock:
            previous = self._records.get(name)
            calls = previous.calls + 1 if previous else 1
            total = (
                previous.average_ms * previous.calls
                if previous
                else 0.0
            ) + duration_ms
            self._records[name] = PerformanceRecord(
                name=name,
                calls=calls,
                last_ms=duration_ms,
                average_ms=total / calls,
                maximum_ms=max(previous.maximum_ms, duration_ms)
                if previous
                else duration_ms,
            )

    def wrap(self, name: str, function):
        """Return a callable that records each invocation of function."""
        @wraps(function)
        def timed(*args, **kwargs):
            with self.measure(name):
                return function(*args, **kwargs)

        return timed

    def snapshot(self) -> tuple[PerformanceRecord, ...]:
        with self._lock:
            return tuple(
                sorted(self._records.values(), key=lambda record: record.name)
            )
