from dataclasses import dataclass
from math import floor, ldexp

from matchdb.dataset import HistoryGame, MatchData, PlayerData

from ._base import Options
from ._history import completed_games


def history_score(games: tuple[HistoryGame, ...]) -> float:
    score = 0.0
    for game in games:
        score = (score + (1 if game.won else -1)) / 2
    return score


def score_bin(score: float, bins: int) -> int:
    return max(0, min(bins - 1, floor((score + 1) * bins / 2)))


def score_interval(index: int, bins: int) -> tuple[float, float, float]:
    return (
        (2 * index - bins) / bins,
        (2 * (index + 1) - bins) / bins,
        (2 * index + 1 - bins) / bins,
    )


@dataclass(frozen=True, slots=True)
class Weight:
    value: float
    games: int
    tail_error: float | None
    complete: bool


def tail_bound(games: int) -> float:
    return ldexp(1.0, -min(games, 1074))


def estimate_weight(
    player: PlayerData,
    match: MatchData,
    history: tuple[HistoryGame, ...],
    options: Options,
) -> Weight | None:
    previous = completed_games(history, match)
    if len(previous) < options.min_history:
        return None
    assert match.start_time is not None
    if (
        player.history_complete_until is not None
        and player.history_complete_until >= match.start_time
    ):
        return Weight(history_score(previous), len(previous), 0.0, True)
    certified = ()
    for lower, upper in player.history_ranges:
        if upper >= match.start_time:
            suffix = tuple(game for game in previous if game.start_time > lower)
            if len(suffix) > len(certified):
                certified = suffix
    if len(certified) >= options.min_history:
        estimate = Weight(
            history_score(certified), len(certified), tail_bound(len(certified)), False
        )
    else:
        estimate = Weight(history_score(previous), len(previous), None, False)
    if options.complete_history:
        return None
    if options.bounded_history and (
        estimate.tail_error is None or estimate.games < options.recent_games
    ):
        return None
    return estimate


def weight_bin(weight: Weight, bins: int) -> int | None:
    index = score_bin(weight.value, bins)
    if weight.tail_error is not None and weight.tail_error > 0:
        lower = score_bin(weight.value - weight.tail_error, bins)
        upper = score_bin(weight.value + weight.tail_error, bins)
        if lower != upper:
            return None
    return index
