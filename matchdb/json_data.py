import json
from dataclasses import dataclass
from typing import cast

type JsonValue = None | bool | int | float | str | list[JsonValue] | JsonObject


@dataclass(frozen=True, slots=True)
class JsonObject:
    members: tuple[tuple[str, JsonValue], ...]

    def value(self, name: str) -> JsonValue:
        return next(
            (value for key, value in reversed(self.members) if key == name), None
        )

    def integer(self, name: str) -> int | None:
        value = self.value(name)
        if value is not None and type(value) is not int:
            raise ValueError(f"Поле {name} должно быть целым числом или null")
        return value

    def boolean(self, name: str) -> bool | None:
        value = self.value(name)
        if value is not None and type(value) is not bool:
            raise ValueError(f"Поле {name} должно быть логическим значением или null")
        return value


def _object(pairs: list[tuple[str, JsonValue]]) -> JsonObject:
    if len({key for key, _ in pairs}) != len(pairs):
        raise ValueError("JSON содержит повторяющиеся имена полей")
    return JsonObject(tuple(pairs))


def _invalid_constant(value: str) -> None:
    raise ValueError(f"Недопустимая константа JSON: {value}")


def decode_json(payload: str) -> JsonValue:
    return cast(
        JsonValue,
        json.loads(
            payload,
            object_pairs_hook=_object,
            parse_constant=_invalid_constant,
        ),
    )


def encode_json(value: JsonValue) -> str:
    if isinstance(value, JsonObject):
        return (
            "{"
            + ",".join(
                json.dumps(key, ensure_ascii=False) + ":" + encode_json(item)
                for key, item in value.members
            )
            + "}"
        )
    if isinstance(value, list):
        return "[" + ",".join(encode_json(item) for item in value) + "]"
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def require_object(value: JsonValue) -> JsonObject:
    if not isinstance(value, JsonObject):
        raise ValueError("Ожидался JSON-объект")
    return value


def _merge_players(old: JsonValue, new: list[JsonValue]) -> list[JsonValue]:
    players = (
        [require_object(player) for player in old] if isinstance(old, list) else []
    )
    for value in new:
        player = require_object(value)
        slot = player.integer("player_slot")
        if slot is None:
            raise ValueError("У участника отсутствует player_slot")
        index = next(
            (
                i
                for i, previous in enumerate(players)
                if previous.integer("player_slot") == slot
            ),
            None,
        )
        if index is None:
            players.append(player)
        else:
            players[index] = merge_objects(players[index], player)
    return list(players)


def merge_objects(old: JsonObject, new: JsonObject) -> JsonObject:
    members = list(old.members)
    for name, value in new.members:
        if value is None:
            continue
        previous = old.value(name)
        if name == "players" and isinstance(value, list):
            value = _merge_players(previous, value)
        elif isinstance(previous, JsonObject) and isinstance(value, JsonObject):
            value = merge_objects(previous, value)
        index = next((i for i, (key, _) in enumerate(members) if key == name), None)
        if index is None:
            members.append((name, value))
        else:
            members[index] = (name, value)
    return JsonObject(tuple(members))
