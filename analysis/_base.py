from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Literal

from matchdb.dataset import MatchData, PlayerData

type Cell = str | int | float | None


@dataclass(frozen=True, slots=True)
class Options:
    bin_seconds: int = 60
    min_matches: int = 1
    position_source: Literal["explicit", "networth"] = "networth"

    def __post_init__(self) -> None:
        if self.bin_seconds <= 0 or self.min_matches <= 0:
            raise ValueError(
                "Размер интервала и размер выборки должны быть положительными"
            )


@dataclass(frozen=True, slots=True)
class Plot:
    x: str
    y: tuple[str, ...]
    title: str
    xlabel: str
    ylabel: str
    kind: Literal["line", "bar"] = "line"
    labels: str | None = None
    counts: str | None = None
    width: float = 0.8
    series: str | None = None


@dataclass(frozen=True, slots=True)
class Report:
    columns: tuple[str, ...]
    rows: tuple[tuple[Cell, ...], ...]
    plot: Plot | None = None
    notes: tuple[str, ...] = ()


def valid_player(player: PlayerData) -> bool:
    return (
        player.player_slot in (0, 1, 2, 3, 4, 128, 129, 130, 131, 132)
        and player.hero_id is not None
        and player.hero_id > 0
    )


def ranked_matches(matches: tuple[MatchData, ...]) -> tuple[MatchData, ...]:
    return tuple(
        match
        for match in matches
        if match.lobby_type == 7
        and match.duration is not None
        and match.duration > 0
        and match.radiant_win is not None
    )


class BaseAnalysis(ABC):
    requires_players: bool = False

    @abstractmethod
    def run(self, matches: tuple[MatchData, ...], options: Options) -> Report:
        raise NotImplementedError
