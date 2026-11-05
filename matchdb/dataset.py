from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HistoryGame:
    match_id: int
    start_time: int
    duration: int
    hero_id: int
    won: bool


@dataclass(frozen=True, slots=True)
class PlayerData:
    player_slot: int
    hero_id: int | None = None
    kills: int | None = None
    deaths: int | None = None
    assists: int | None = None
    net_worth: int | None = None
    position: int | None = None
    account_id: int | None = None
    history: tuple[HistoryGame, ...] = ()
    history_complete_until: int | None = None
    history_ranges: tuple[tuple[int, int], ...] = ()


@dataclass(frozen=True, slots=True)
class MatchData:
    match_id: int
    duration: int | None
    lobby_type: int | None
    radiant_win: bool | None
    avg_rank_tier: int | None
    players: tuple[PlayerData, ...] = ()
    start_time: int | None = None
    banned_heroes: tuple[int, ...] | None = None
