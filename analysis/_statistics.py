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


DISTRIBUTION_NOTE = (
    "Распределение: линия — медиана, тёмная область — P25–P75 (центральные 50%), "
    "светлая — P5–P95 (центральные 90%). Квантили вычислены линейной интерполяцией; "
    "это разброс наблюдений, а не доверительный интервал. "
    "По умолчанию квантили исходные; --normalize сглаживает их по соседним X."
)


def distribution(values: list[float]) -> tuple[float, ...]:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("Пустая выборка распределения")
    result = []
    for fraction in (0.05, 0.25, 0.5, 0.75, 0.95):
        position = (len(ordered) - 1) * fraction
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        result.append(
            ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)
        )
    return tuple(result)


def distribution_columns(prefix: str) -> tuple[str, ...]:
    return tuple(f"{prefix}_p{percent}" for percent in (5, 25, 50, 75, 95))
