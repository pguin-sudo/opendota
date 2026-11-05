import sqlite3
from collections import defaultdict
from pathlib import Path

from .dataset import MatchData, PlayerData


def load_matches(path: Path, *, include_players: bool = True) -> tuple[MatchData, ...]:
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        with db:
            db.execute("BEGIN")
            players: defaultdict[int, list[PlayerData]] = defaultdict(list)
            if include_players:
                for row in db.execute(
                    """SELECT match_id, player_slot, hero_id, kills, deaths, assists, net_worth,
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
                )
                for row in db.execute(
                    "SELECT match_id, duration, lobby_type, radiant_win, avg_rank_tier FROM matches ORDER BY match_id"
                )
            )
    finally:
        db.close()
