#!/usr/bin/env python3
# Запуск: poetry install && poetry run python3 dota_matches.py
# Зависимости: requests, rich (см. pyproject.toml)

from __future__ import annotations

import csv
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from rich.console import Console
from rich.table import Table

PLAYERS: dict[str, int] = {
    "С": 779954703,
    "M": 985882359,
    "Ж": 1128239466,
    "Ф": 1486299073,
    "Р": 1166442409,
}

MATCHES_PER_PLAYER = 20
API_KEY: str | None = None

OPENDOTA_BASE_URL = "https://api.opendota.com/api"
REQUEST_TIMEOUT = 10
REQUEST_DELAY = 1.1
MAX_RETRIES = 5
PARSE_POLL_INTERVAL = 5
PARSE_POLL_ATTEMPTS = 20
TIMEZONE = ZoneInfo("Asia/Yekaterinburg")

GAME_MODES: dict[int, str] = {
    0: "Неизвестный режим",
    1: "All Pick",
    2: "Captains Mode",
    3: "Random Draft",
    4: "Single Draft",
    5: "All Random",
    6: "Intro",
    7: "Diretide",
    8: "Reverse Captains Mode",
    9: "Greeviling",
    10: "Tutorial",
    11: "Mid Only",
    12: "Least Played",
    13: "Limited Heroes",
    14: "Compendium",
    15: "Custom",
    16: "Captains Draft",
    17: "Balanced Draft",
    18: "Ability Draft",
    19: "Event",
    20: "All Random Death Match",
    21: "1v1 Mid",
    22: "All Pick",
    23: "Turbo",
    24: "Mutation",
}

LOBBY_TYPES: dict[int, str] = {
    0: "Unranked",
    1: "Practice",
    2: "Tournament",
    3: "Tutorial",
    4: "Co-op Bots",
    5: "Team Match",
    6: "Solo Queue",
    7: "Ranked",
    8: "1v1 Solo Mid",
    9: "Battle Cup",
}

LINEUP_ORDER: list[str] = list(PLAYERS.keys())


@dataclass
class MatchRow:
    match_id: int
    start_time: int
    game_mode: int
    lobby_type: int
    participants: dict[str, tuple[bool, bool]] = field(default_factory=dict)


def request_json(
    session: requests.Session, url: str, params: dict[str, object], context: str
) -> dict | list | None:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = session.get(url, params=params, timeout=REQUEST_TIMEOUT)
        except requests.exceptions.Timeout:
            print(f"[Предупреждение] Таймаут ({context}), попытка {attempt}/{MAX_RETRIES}.")
            continue
        except requests.exceptions.RequestException as exc:
            print(f"[Предупреждение] Сетевая ошибка ({context}): {exc}")
            return None

        if response.status_code == 429:
            wait = REQUEST_DELAY * attempt * 3
            print(f"[Предупреждение] Лимит запросов OpenDota ({context}), жду {wait:.1f} сек.")
            time.sleep(wait)
            continue
        if response.status_code == 404:
            print(f"[Предупреждение] Не найдено ({context}).")
            return None
        if response.status_code != 200:
            print(f"[Предупреждение] Ошибка {response.status_code} ({context}).")
            return None
        try:
            return response.json()
        except ValueError:
            print(f"[Предупреждение] Некорректный JSON ({context}).")
            return None

    print(f"[Предупреждение] Не удалось выполнить запрос ({context}) после {MAX_RETRIES} попыток.")
    return None


def fetch_player_matches(session: requests.Session, name: str, account_id: int) -> list[dict]:
    if not account_id:
        print(f"[Предупреждение] У игрока «{name}» не задан account_id — пропускаю.")
        return []

    params: dict[str, object] = {"limit": MATCHES_PER_PLAYER}
    if API_KEY:
        params["api_key"] = API_KEY

    data = request_json(
        session, f"{OPENDOTA_BASE_URL}/players/{account_id}/matches", params, f"история «{name}»"
    )
    if not data:
        print(f"[Предупреждение] Пустая история у «{name}» (возможно, закрытый профиль).")
        return []
    return data


def fetch_match_details(session: requests.Session, match_id: int) -> dict | None:
    params: dict[str, object] = {"api_key": API_KEY} if API_KEY else {}
    data = request_json(
        session, f"{OPENDOTA_BASE_URL}/matches/{match_id}", params, f"детали матча {match_id}"
    )
    return data if isinstance(data, dict) else None


def merge_matches(players_matches: dict[str, list[dict]]) -> dict[int, MatchRow]:
    merged: dict[int, MatchRow] = {}

    for name, matches in players_matches.items():
        for match in matches:
            match_id = match["match_id"]
            row = merged.setdefault(
                match_id,
                MatchRow(
                    match_id=match_id,
                    start_time=match["start_time"],
                    game_mode=match.get("game_mode", 0),
                    lobby_type=match.get("lobby_type", 0),
                ),
            )
            row.participants[name] = (match["player_slot"] < 128, bool(match["radiant_win"]))

    return merged


def apply_match_players(
    row: MatchRow, details: dict, reverse_players: dict[int, str]
) -> list[str]:
    radiant_win = bool(details.get("radiant_win"))
    added = []
    for player in details.get("players", []):
        name = reverse_players.get(player.get("account_id"))
        if name and name not in row.participants:
            row.participants[name] = (player["player_slot"] < 128, radiant_win)
            added.append(name)
    return added


def request_match_parse(session: requests.Session, match_id: int) -> int | None:
    try:
        response = session.post(f"{OPENDOTA_BASE_URL}/request/{match_id}", timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException:
        return None
    if response.status_code != 200:
        return None
    try:
        return response.json()["job"]["jobId"]
    except (ValueError, KeyError, TypeError):
        return None


def wait_for_parse(session: requests.Session, job_id: int) -> None:
    for _ in range(PARSE_POLL_ATTEMPTS):
        time.sleep(PARSE_POLL_INTERVAL)
        try:
            response = session.get(f"{OPENDOTA_BASE_URL}/request/{job_id}", timeout=REQUEST_TIMEOUT)
        except requests.exceptions.RequestException:
            continue
        if response.status_code == 404 or response.text.strip() in ("", "null"):
            return


def fill_from_closed_profiles(
    session: requests.Session, merged: dict[int, MatchRow], reverse_players: dict[int, str]
) -> None:
    recovered: dict[str, int] = {}

    for row in merged.values():
        if all(n in row.participants for n in reverse_players.values()):
            continue

        time.sleep(REQUEST_DELAY)
        details = fetch_match_details(session, row.match_id)
        if details is None:
            continue
        for name in apply_match_players(row, details, reverse_players):
            recovered[name] = recovered.get(name, 0) + 1

        if all(n in row.participants for n in reverse_players.values()):
            continue

        job_id = request_match_parse(session, row.match_id)
        if job_id is None:
            continue
        print(f"[Инфо] Матч {row.match_id} не распарсен, запросил парсинг и жду результат...")
        wait_for_parse(session, job_id)

        details = fetch_match_details(session, row.match_id)
        if details is None:
            continue
        for name in apply_match_players(row, details, reverse_players):
            recovered[name] = recovered.get(name, 0) + 1

    for name, count in recovered.items():
        print(f"[Инфо] «{name}» (закрытый профиль) найден в {count} матчах по данным других игроков.")


def resolve_result(row: MatchRow) -> tuple[str, str]:
    teams = {is_radiant for is_radiant, _ in row.participants.values()}
    if len(teams) > 1:
        return "Против друг друга", "yellow"

    is_radiant = next(iter(teams))
    _, radiant_win = next(iter(row.participants.values()))
    won = is_radiant == radiant_win
    return ("Победа", "bold green") if won else ("Поражение", "bold red")


def format_game_mode(game_mode: int, lobby_type: int) -> str:
    mode_name = GAME_MODES.get(game_mode, f"Режим #{game_mode}")
    lobby_name = LOBBY_TYPES.get(lobby_type)

    if lobby_type == 7 and "Ranked" not in mode_name:
        return f"Ranked {mode_name}"
    if lobby_type not in (0, 7) and lobby_name:
        return f"{mode_name} ({lobby_name})"
    return mode_name


def format_lineup(row: MatchRow) -> str:
    return " ".join(name if name in row.participants else "*" for name in LINEUP_ORDER)


def format_date(start_time: int) -> str:
    return datetime.fromtimestamp(start_time, tz=TIMEZONE).strftime("%d.%m.%Y %H:%M")


def build_rows(merged: dict[int, MatchRow]) -> list[tuple[str, str, str, str, str]]:
    rows = sorted(merged.values(), key=lambda r: r.start_time, reverse=True)
    return [
        (format_date(r.start_time), format_game_mode(r.game_mode, r.lobby_type), *resolve_result(r), format_lineup(r))
        for r in rows
    ]


def render_table(rows: list[tuple[str, str, str, str, str]]) -> None:
    table = Table(title="Последние матчи Dota 2")
    table.add_column("Дата", style="cyan", no_wrap=True)
    table.add_column("Режим")
    table.add_column("Результат")
    table.add_column("Состав")

    for date_str, mode_str, result_str, style, lineup_str in rows:
        table.add_row(date_str, mode_str, f"[{style}]{result_str}[/{style}]", lineup_str)

    Console().print(table)


def save_csv(rows: list[tuple[str, str, str, str, str]], path: str = "matches.csv") -> None:
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["Дата", "Режим", "Результат", "Состав"])
        for date_str, mode_str, result_str, _style, lineup_str in rows:
            writer.writerow([date_str, mode_str, result_str, lineup_str])


def main() -> None:
    if not any(PLAYERS.values()):
        print("[Ошибка] В PLAYERS не заданы account_id.")
        sys.exit(1)

    session = requests.Session()
    names = list(PLAYERS.keys())

    players_matches: dict[str, list[dict]] = {}
    for i, name in enumerate(names):
        players_matches[name] = fetch_player_matches(session, name, PLAYERS[name])
        if i < len(names) - 1:
            time.sleep(REQUEST_DELAY)

    merged = merge_matches(players_matches)

    reverse_players = {aid: name for name, aid in PLAYERS.items() if aid}
    fill_from_closed_profiles(session, merged, reverse_players)

    if not merged:
        print("Не найдено ни одного матча — проверь account_id и доступность профилей.")
        return

    rows = build_rows(merged)
    render_table(rows)
    save_csv(rows)
    print(f"\nСохранено {len(rows)} матчей в matches.csv")


if __name__ == "__main__":
    main()
