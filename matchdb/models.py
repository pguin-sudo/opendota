from dataclasses import dataclass
from enum import StrEnum

from .json_data import JsonObject, decode_json, encode_json, require_object


class Source(StrEnum):
    PUBLIC = "public"
    MATCH = "match"


@dataclass(frozen=True, slots=True)
class Player:
    player_slot: int
    payload: str
    hero_id: int | None = None
    account_id: int | None = None
    kills: int | None = None
    deaths: int | None = None
    assists: int | None = None
    gold_per_min: int | None = None
    xp_per_min: int | None = None
    last_hits: int | None = None
    denies: int | None = None
    level: int | None = None
    hero_damage: int | None = None
    tower_damage: int | None = None
    hero_healing: int | None = None
    net_worth: int | None = None

    @classmethod
    def from_object(cls, data: JsonObject) -> Player:
        slot = data.integer("player_slot")
        if slot is None or not 0 <= slot <= 255:
            raise ValueError("player_slot должен быть целым числом от 0 до 255")
        return cls(
            player_slot=slot,
            hero_id=data.integer("hero_id"),
            account_id=data.integer("account_id"),
            kills=data.integer("kills"),
            deaths=data.integer("deaths"),
            assists=data.integer("assists"),
            gold_per_min=data.integer("gold_per_min"),
            xp_per_min=data.integer("xp_per_min"),
            last_hits=data.integer("last_hits"),
            denies=data.integer("denies"),
            level=data.integer("level"),
            hero_damage=data.integer("hero_damage"),
            tower_damage=data.integer("tower_damage"),
            hero_healing=data.integer("hero_healing"),
            net_worth=data.integer("net_worth"),
            payload=encode_json(data),
        )

    @property
    def has_summary(self) -> bool:
        return (
            self.hero_id is not None
            and self.hero_id > 0
            and self.kills is not None
            and self.deaths is not None
            and self.assists is not None
        )


def _team(data: JsonObject, name: str) -> tuple[int, ...] | None:
    values = data.value(name)
    if values is None:
        return None
    if not isinstance(values, list) or any(type(value) is not int for value in values):
        raise ValueError(f"Поле {name} должно быть массивом ID героев")
    return tuple(value for value in values if type(value) is int)


@dataclass(frozen=True, slots=True)
class Match:
    match_id: int
    payload: str
    start_time: int | None = None
    duration: int | None = None
    lobby_type: int | None = None
    game_mode: int | None = None
    patch: int | None = None
    avg_rank_tier: int | None = None
    num_rank_tier: int | None = None
    radiant_win: bool | None = None
    radiant_score: int | None = None
    dire_score: int | None = None
    radiant_team: tuple[int, ...] | None = None
    dire_team: tuple[int, ...] | None = None
    players: tuple[Player, ...] = ()

    @classmethod
    def from_json(cls, payload: str) -> Match:
        return cls.from_object(require_object(decode_json(payload)))

    @classmethod
    def from_object(cls, data: JsonObject) -> Match:
        match_id = data.integer("match_id")
        if match_id is None or match_id <= 0:
            raise ValueError("match_id должен быть положительным целым числом")
        raw_players = data.value("players")
        if raw_players is not None and not isinstance(raw_players, list):
            raise ValueError("Поле players должно быть массивом участников")
        players = tuple(
            Player.from_object(require_object(value)) for value in (raw_players or [])
        )
        if len({player.player_slot for player in players}) != len(players):
            raise ValueError("Слоты участников не должны повторяться")
        duration = data.integer("duration")
        if duration is not None and duration < 0:
            raise ValueError("Длительность матча не может быть отрицательной")
        return cls(
            match_id=match_id,
            start_time=data.integer("start_time"),
            duration=duration,
            lobby_type=data.integer("lobby_type"),
            game_mode=data.integer("game_mode"),
            patch=data.integer("patch"),
            avg_rank_tier=data.integer("avg_rank_tier"),
            num_rank_tier=data.integer("num_rank_tier"),
            radiant_win=data.boolean("radiant_win"),
            radiant_score=data.integer("radiant_score"),
            dire_score=data.integer("dire_score"),
            radiant_team=_team(data, "radiant_team"),
            dire_team=_team(data, "dire_team"),
            players=players,
            payload=encode_json(data),
        )

    @property
    def has_summary(self) -> bool:
        return (
            len(self.players) == 10
            and {player.player_slot for player in self.players}
            == {0, 1, 2, 3, 4, 128, 129, 130, 131, 132}
            and all(player.has_summary for player in self.players)
        )


def parse_matches(payload: str) -> list[Match]:
    data = decode_json(payload)
    return [
        Match.from_object(require_object(value))
        for value in (data if isinstance(data, list) else [data])
    ]


@dataclass(frozen=True, slots=True)
class CollectionStatus:
    total: int
    ranked: int
    ranked_with_rank: int
    detailed: int
    before_match_id: int | None
    complete: int = 0

    def to_json(self) -> str:
        return encode_json(
            JsonObject(
                (
                    ("total", self.total),
                    ("ranked", self.ranked),
                    ("ranked_with_rank", self.ranked_with_rank),
                    ("detailed", self.detailed),
                    ("complete", self.complete),
                    ("before_match_id", self.before_match_id),
                )
            )
        )
