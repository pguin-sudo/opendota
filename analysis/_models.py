from dataclasses import dataclass

from ._ranks import rank_name


@dataclass(frozen=True, slots=True)
class DurationBin:
    from_seconds: int
    to_seconds: int
    matches: int
    percent: float
    cumulative_percent: float

    @property
    def from_minutes(self) -> float:
        return self.from_seconds / 60

    @property
    def to_minutes(self) -> float:
        return self.to_seconds / 60


@dataclass(frozen=True, slots=True)
class RankDuration:
    avg_rank_tier: int
    matches: int
    mean_seconds: float
    median_seconds: float

    @property
    def rank_name(self) -> str:
        return rank_name(self.avg_rank_tier)

    @property
    def mean_minutes(self) -> float:
        return self.mean_seconds / 60

    @property
    def median_minutes(self) -> float:
        return self.median_seconds / 60
