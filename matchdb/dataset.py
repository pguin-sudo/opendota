from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PlayerData:
    player_slot: int
    hero_id: int | None = None
    kills: int | None = None
    deaths: int | None = None
    assists: int | None = None
    net_worth: int | None = None
    position: int | None = None


@dataclass(frozen=True, slots=True)
class MatchData:
    match_id: int
    duration: int | None
    lobby_type: int | None
    radiant_win: bool | None
    avg_rank_tier: int | None
    players: tuple[PlayerData, ...] = ()
