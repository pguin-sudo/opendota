from dataclasses import dataclass
from statistics import mean, median, stdev


@dataclass(frozen=True, slots=True)
class Summary:
    samples: int
    mean: float
    median: float
    stddev: float | None
    cv: float | None

    @classmethod
    def from_values(cls, values: list[float]) -> Summary:
        average = mean(values)
        deviation = stdev(values) if len(values) > 1 else None
        return cls(
            len(values),
            average,
            median(values),
            deviation,
            deviation / average if deviation is not None and average != 0 else None,
        )
