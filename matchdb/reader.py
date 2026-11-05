import sqlite3
from collections import defaultdict
from pathlib import Path

from .dataset import HistoryGame, MatchData, PlayerData
from .history_coverage import load_coverage
from .json_data import JsonObject, decode_json


def load_matches(path: Path, *, include_players: bool = True) -> tuple[MatchData, ...]:
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        with db:
            db.execute("BEGIN")
            players: defaultdict[int, list[PlayerData]] = defaultdict(list)
            if include_players:
                histories = _load_history(db)
                coverage = load_coverage(db)
                for row in db.execute(
                    """SELECT match_id, player_slot, hero_id, account_id, kills, deaths, assists, net_worth,
                    CASE WHEN json_type(payload, '$.position') = 'integer'
                         AND json_extract(payload, '$.position') BETWEEN 1 AND 5
                         THEN json_extract(payload, '$.position') END AS position
                    FROM players ORDER BY match_id, player_slot"""
                ):
                    players[row["match_id"]].append(
                        PlayerData(
                            player_slot=row["player_slot"],
                            hero_id=row["hero_id"],
                            kills=row["kills"],
                            deaths=row["deaths"],
                            assists=row["assists"],
                            net_worth=row["net_worth"],
                            position=row["position"],
                            account_id=row["account_id"],
                            history=histories.get(row["account_id"], ()),
                            history_complete_until=(
                                coverage[row["account_id"]].complete_until
                                if row["account_id"] in coverage
                                else None
                            ),
                            history_ranges=(
                                coverage[row["account_id"]].ranges
                                if row["account_id"] in coverage
                                else ()
                            ),
                        )
                    )
            return tuple(
                MatchData(
                    match_id=row["match_id"],
                    duration=row["duration"],
                    lobby_type=row["lobby_type"],
                    radiant_win=bool(row["radiant_win"])
                    if row["radiant_win"] is not None
                    else None,
                    avg_rank_tier=row["avg_rank_tier"],
                    players=tuple(players[row["match_id"]]),
                    start_time=row["start_time"],
                    banned_heroes=_banned_heroes(row["draft"]),
                )
                for row in db.execute(
                    """SELECT m.match_id, duration, lobby_type, radiant_win, avg_rank_tier, start_time,
                    CASE WHEN json_type(s.payload, '$.picks_bans') = 'array'
                    THEN json_extract(s.payload, '$.picks_bans') END AS draft
                    FROM matches m LEFT JOIN snapshots s
                    ON s.match_id = m.match_id AND s.source = 'match'
                    ORDER BY m.match_id"""
                )
            )
    finally:
        db.close()


def _banned_heroes(payload: str | None) -> tuple[int, ...] | None:
    if payload is None:
        return None
    draft = decode_json(payload)
    if not isinstance(draft, list) or not draft:
        return None
    bans = set()
    for entry in draft:
        if not isinstance(entry, JsonObject):
            return None
        hero = entry.value("hero_id")
        picked = entry.value("is_pick")
        if type(hero) is not int or hero <= 0 or type(picked) is not bool:
            return None
        if not picked:
            bans.add(hero)
    return tuple(sorted(bans))


def _load_history(db: sqlite3.Connection) -> dict[int, tuple[HistoryGame, ...]]:
    if (
        db.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'player_history'"
        ).fetchone()
        is None
    ):
        return {}
    histories: defaultdict[int, list[HistoryGame]] = defaultdict(list)
    for row in db.execute("SELECT * FROM player_history ORDER BY start_time, match_id"):
        histories[row["account_id"]].append(
            HistoryGame(
                row["match_id"],
                row["start_time"],
                row["duration"],
                row["hero_id"],
                bool(row["won"]),
            )
        )
    return {account: tuple(games) for account, games in histories.items()}
