import sqlite3
from collections.abc import Callable
from urllib.error import HTTPError

from .api import OpenDotaClient
from .models import CollectionStatus, Source
from .storage import save_match

RANKED = "lobby_type = 7 AND duration > 0 AND radiant_win IS NOT NULL"
DETAILED = """EXISTS (
    SELECT 1 FROM snapshots s WHERE s.match_id = m.match_id AND s.source = 'match'
) AND (SELECT COUNT(*) FROM players p WHERE p.match_id = m.match_id
       AND p.player_slot IN (0, 1, 2, 3, 4, 128, 129, 130, 131, 132)
       AND p.hero_id > 0 AND p.kills >= 0
       AND p.deaths >= 0 AND p.assists >= 0 AND p.net_worth >= 0) = 10"""
COMPLETE = f"{RANKED} AND avg_rank_tier > 0 AND {DETAILED}"


def status(db: sqlite3.Connection) -> CollectionStatus:
    counts = db.execute(
        f"""SELECT COUNT(*) AS total,
        COUNT(CASE WHEN {RANKED} THEN 1 END) AS ranked,
        COUNT(CASE WHEN {RANKED} AND avg_rank_tier > 0 THEN 1 END) AS ranked_with_rank
        FROM matches"""
    ).fetchone()
    detailed = db.execute(
        f"SELECT COUNT(*) FROM matches m WHERE {DETAILED}"
    ).fetchone()[0]
    complete = db.execute(
        f"SELECT COUNT(*) FROM matches m WHERE {COMPLETE}"
    ).fetchone()[0]
    cursor = db.execute(
        "SELECT before_match_id FROM collection_state WHERE name = 'ranked'"
    ).fetchone()
    return CollectionStatus(
        counts["total"],
        counts["ranked"],
        counts["ranked_with_rank"],
        detailed,
        cursor[0] if cursor else None,
        complete,
    )


def _is_counted(db: sqlite3.Connection, match_id: int, condition: str) -> bool:
    return (
        db.execute(
            f"SELECT 1 FROM matches m WHERE match_id = ? AND {condition}",
            (match_id,),
        ).fetchone()
        is not None
    )


def _enrich_match(
    db: sqlite3.Connection,
    client: OpenDotaClient,
    match_id: int,
    progress: Callable[[str], None],
) -> bool:
    try:
        data = client.match(match_id)
    except HTTPError as error:
        if error.code != 404:
            raise
        error.close()
        progress(f"Матч {match_id}: подробности недоступны (404), пропущен.")
        return False
    save_match(db, data, Source.MATCH)
    detailed = _is_counted(db, match_id, DETAILED)
    if not detailed:
        progress(
            f"Матч {match_id}: неполные KDA/net worth, данные сохранены; пропущен."
        )
    return detailed


def collect(
    db: sqlite3.Connection,
    client: OpenDotaClient,
    target: int,
    from_latest: bool = False,
    progress: Callable[[str], None] = print,
    *,
    full: bool = False,
) -> int:
    if target <= 0:
        raise ValueError("Целевое количество матчей должно быть положительным")
    current = status(db)
    condition = COMPLETE if full else RANKED
    count = current.complete if full else current.ranked
    label = "Полных рейтинговых матчей" if full else "Рейтинговых матчей"
    if count >= target:
        return count
    if full:
        pending_before: int | None = None
        while count < target:
            pending = db.execute(
                f"""SELECT match_id FROM matches m WHERE {RANKED}
                AND avg_rank_tier > 0 AND NOT ({DETAILED})
                AND (? IS NULL OR match_id < ?) ORDER BY match_id DESC LIMIT 100""",
                (pending_before, pending_before),
            ).fetchall()
            if not pending:
                break
            for row in pending:
                match_id = row["match_id"]
                _enrich_match(db, client, match_id, progress)
                count += int(_is_counted(db, match_id, COMPLETE))
                pending_before = match_id
                progress(f"{label}: {count}/{target}; ID {match_id}")
                if count >= target:
                    return count
    before = None if from_latest else current.before_match_id
    while count < target:
        page = client.public_matches(before)
        if not page:
            progress("Список OpenDota исчерпан; цель пока не достигнута.")
            break
        page = sorted(page, key=lambda match: match.match_id, reverse=True)
        if before is not None and any(match.match_id >= before for match in page):
            raise ValueError("OpenDota не продвинул пагинацию; сбор остановлен")
        for match in page:
            if match.lobby_type == 7:
                was_counted = _is_counted(db, match.match_id, condition)
                save_match(db, match, Source.PUBLIC)
                if full and not _is_counted(db, match.match_id, COMPLETE):
                    eligible = _is_counted(
                        db, match.match_id, f"{RANKED} AND avg_rank_tier > 0"
                    )
                    if eligible:
                        _enrich_match(db, client, match.match_id, progress)
                count += int(_is_counted(db, match.match_id, condition)) - int(
                    was_counted
                )
            before = match.match_id
            with db:
                db.execute(
                    """INSERT INTO collection_state(name, before_match_id) VALUES ('ranked', ?)
                    ON CONFLICT(name) DO UPDATE SET before_match_id = excluded.before_match_id""",
                    (before,),
                )
            if count >= target:
                break
        progress(f"{label}: {count}/{target}; следующий запрос до ID {before}")
    return count


def enrich(
    db: sqlite3.Connection,
    client: OpenDotaClient,
    limit: int,
    progress: Callable[[str], None] = print,
) -> int:
    if limit <= 0:
        raise ValueError("Лимит должен быть положительным")
    pending = db.execute(
        f"""SELECT match_id FROM matches m WHERE {RANKED}
        AND NOT ({DETAILED}) ORDER BY match_id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    completed = 0
    for index, row in enumerate(pending, 1):
        match_id = row["match_id"]
        completed += int(_enrich_match(db, client, match_id, progress))
        progress(
            f"Обработано: {index}/{len(pending)}; дополнено: {completed}; ID {match_id}"
        )
    return completed
