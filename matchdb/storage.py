import json
import sqlite3
from pathlib import Path

from .json_data import (
    JsonObject,
    decode_json,
    encode_json,
    merge_objects,
    require_object,
)
from .models import Match, Source

SCHEMA = """
CREATE TABLE IF NOT EXISTS player_history (
    account_id INTEGER NOT NULL CHECK (account_id > 0),
    match_id INTEGER NOT NULL CHECK (match_id > 0),
    start_time INTEGER NOT NULL CHECK (start_time > 0),
    duration INTEGER NOT NULL CHECK (duration > 0),
    hero_id INTEGER NOT NULL CHECK (hero_id > 0),
    won INTEGER NOT NULL CHECK (won IN (0, 1)),
    PRIMARY KEY (account_id, match_id)
);
CREATE TABLE IF NOT EXISTS history_requests (
    account_id INTEGER NOT NULL,
    since INTEGER NOT NULL,
    until INTEGER NOT NULL,
    offset INTEGER NOT NULL DEFAULT 0,
    complete INTEGER NOT NULL DEFAULT 0,
    oldest_start_time INTEGER,
    prefix_valid INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (account_id, since, until)
);
CREATE TABLE IF NOT EXISTS collection_state (
    name TEXT PRIMARY KEY,
    before_match_id INTEGER NOT NULL CHECK (before_match_id > 0)
);
CREATE TABLE IF NOT EXISTS snapshots (
    match_id INTEGER NOT NULL CHECK (match_id > 0),
    source TEXT NOT NULL CHECK (source IN ('public', 'match')),
    payload TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (match_id, source)
);
CREATE TABLE IF NOT EXISTS matches (
    match_id INTEGER PRIMARY KEY,
    start_time INTEGER,
    duration INTEGER CHECK (duration >= 0),
    lobby_type INTEGER,
    game_mode INTEGER,
    patch INTEGER,
    avg_rank_tier INTEGER,
    num_rank_tier INTEGER,
    radiant_win INTEGER CHECK (radiant_win IN (0, 1)),
    radiant_score INTEGER,
    dire_score INTEGER,
    radiant_team TEXT,
    dire_team TEXT
);
CREATE TABLE IF NOT EXISTS analysis_preparation (
    match_id INTEGER PRIMARY KEY REFERENCES matches(match_id),
    complete INTEGER NOT NULL DEFAULT 0 CHECK (complete IN (0, 1)),
    unavailable INTEGER NOT NULL DEFAULT 0 CHECK (unavailable IN (0, 1)),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS players (
    match_id INTEGER NOT NULL REFERENCES matches(match_id),
    player_slot INTEGER NOT NULL,
    hero_id INTEGER,
    account_id INTEGER,
    kills INTEGER,
    deaths INTEGER,
    assists INTEGER,
    gold_per_min INTEGER,
    xp_per_min INTEGER,
    last_hits INTEGER,
    denies INTEGER,
    level INTEGER,
    hero_damage INTEGER,
    tower_damage INTEGER,
    hero_healing INTEGER,
    net_worth INTEGER,
    payload TEXT NOT NULL,
    PRIMARY KEY (match_id, player_slot)
);
CREATE INDEX IF NOT EXISTS history_time ON player_history(account_id, start_time);
CREATE INDEX IF NOT EXISTS matches_rank ON matches(lobby_type, avg_rank_tier);
CREATE INDEX IF NOT EXISTS players_hero ON players(hero_id, match_id);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL")
    db.executescript(SCHEMA)
    columns = {row[1] for row in db.execute("PRAGMA table_info(history_requests)")}
    with db:
        if "oldest_start_time" not in columns:
            db.execute(
                "ALTER TABLE history_requests ADD COLUMN oldest_start_time INTEGER"
            )
        if "prefix_valid" not in columns:
            db.execute(
                "ALTER TABLE history_requests ADD COLUMN prefix_valid INTEGER NOT NULL DEFAULT 0"
            )
            db.execute(
                "UPDATE history_requests SET prefix_valid = 1 WHERE complete = 1"
            )
    return db


def _lineup(match: Match, offset: int, fallback: tuple[int, ...] | None) -> str | None:
    heroes = tuple(
        player.hero_id
        for player in match.players
        if offset <= player.player_slot < offset + 5 and player.hero_id is not None
    )
    if len(heroes) != 5 or not all(hero > 0 for hero in heroes):
        heroes = fallback or ()
    if (
        len(heroes) != 5
        or len(set(heroes)) != 5
        or not all(hero > 0 for hero in heroes)
    ):
        return None
    return json.dumps(sorted(heroes))


def save_match(db: sqlite3.Connection, match: Match, source: Source) -> None:
    match_id = match.match_id
    with db:
        old = db.execute(
            "SELECT payload FROM snapshots WHERE match_id = ? AND source = ?",
            (match_id, source),
        ).fetchone()
        snapshot = merge_objects(
            require_object(decode_json(old[0])) if old else JsonObject(()),
            require_object(decode_json(match.payload)),
        )
        db.execute(
            """INSERT INTO snapshots(match_id, source, payload) VALUES (?, ?, ?)
            ON CONFLICT(match_id, source) DO UPDATE SET
            payload = excluded.payload, updated_at = CURRENT_TIMESTAMP""",
            (match_id, source, encode_json(snapshot)),
        )
        data = JsonObject(())
        for row in db.execute(
            "SELECT payload FROM snapshots WHERE match_id = ? "
            "ORDER BY CASE source WHEN 'public' THEN 0 ELSE 1 END",
            (match_id,),
        ):
            data = merge_objects(data, require_object(decode_json(row[0])))
        combined = Match.from_json(encode_json(data))
        db.execute(
            """INSERT INTO matches (
                match_id, start_time, duration, lobby_type, game_mode, patch,
                avg_rank_tier, num_rank_tier, radiant_win, radiant_score, dire_score,
                radiant_team, dire_team
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(match_id) DO UPDATE SET
                start_time = excluded.start_time, duration = excluded.duration,
                lobby_type = excluded.lobby_type, game_mode = excluded.game_mode,
                patch = excluded.patch, avg_rank_tier = excluded.avg_rank_tier,
                num_rank_tier = excluded.num_rank_tier, radiant_win = excluded.radiant_win,
                radiant_score = excluded.radiant_score, dire_score = excluded.dire_score,
                radiant_team = excluded.radiant_team, dire_team = excluded.dire_team""",
            (
                combined.match_id,
                combined.start_time,
                combined.duration,
                combined.lobby_type,
                combined.game_mode,
                combined.patch,
                combined.avg_rank_tier,
                combined.num_rank_tier,
                combined.radiant_win,
                combined.radiant_score,
                combined.dire_score,
                _lineup(combined, 0, combined.radiant_team),
                _lineup(combined, 128, combined.dire_team),
            ),
        )
        for player in combined.players:
            db.execute(
                """INSERT OR REPLACE INTO players (
                    match_id, player_slot, hero_id, account_id, kills, deaths, assists,
                    gold_per_min, xp_per_min, last_hits, denies, level, hero_damage,
                    tower_damage, hero_healing, net_worth, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    combined.match_id,
                    player.player_slot,
                    player.hero_id,
                    player.account_id,
                    player.kills,
                    player.deaths,
                    player.assists,
                    player.gold_per_min,
                    player.xp_per_min,
                    player.last_hits,
                    player.denies,
                    player.level,
                    player.hero_damage,
                    player.tower_damage,
                    player.hero_healing,
                    player.net_worth,
                    player.payload,
                ),
            )
