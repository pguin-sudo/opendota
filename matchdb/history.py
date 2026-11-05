import sqlite3
from collections.abc import Callable
from urllib.error import HTTPError

from .api import OpenDotaClient
from .collection import RANKED
from .history_coverage import load_coverage
from .models import Match


def _save_game(db: sqlite3.Connection, account: int, match: Match) -> bool:
    player = match.players[0]
    if (
        match.lobby_type != 7
        or match.start_time is None
        or match.start_time <= 0
        or match.duration is None
        or match.duration <= 0
        or match.radiant_win is None
        or player.player_slot not in (0, 1, 2, 3, 4, 128, 129, 130, 131, 132)
        or player.hero_id is None
        or player.hero_id <= 0
    ):
        return False
    db.execute(
        """INSERT INTO player_history(account_id, match_id, start_time, duration, hero_id, won)
        VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(account_id, match_id) DO UPDATE SET
        start_time = excluded.start_time, duration = excluded.duration,
        hero_id = excluded.hero_id, won = excluded.won""",
        (
            account,
            match.match_id,
            match.start_time,
            match.duration,
            player.hero_id,
            match.radiant_win == (player.player_slot < 128),
        ),
    )
    return True


def collect_history(
    db: sqlite3.Connection,
    client: OpenDotaClient,
    limit: int = 10,
    days: int = 30,
    max_pages: int = 20,
    progress: Callable[[str], None] = print,
    *,
    refresh: bool = False,
    all_history: bool = False,
    match_id: int | None = None,
    history_until: int | None = None,
) -> bool:
    if min(limit, days, max_pages) <= 0:
        raise ValueError("Лимиты загрузки истории должны быть положительными")
    if match_id is not None and match_id <= 0:
        raise ValueError("ID матча должен быть положительным")
    if history_until is not None and history_until <= 0:
        raise ValueError("Верхняя граница истории должна быть положительной")
    targets = db.execute(
        f"""SELECT match_id, start_time FROM matches m WHERE {RANKED}
        AND start_time > 0 AND (? IS NULL OR m.match_id = ?) AND EXISTS (
            SELECT 1 FROM players p WHERE p.match_id = m.match_id
            AND p.account_id > 0 AND p.account_id < 4294967295
            AND p.player_slot IN (0, 1, 2, 3, 4, 128, 129, 130, 131, 132)
            AND p.hero_id > 0
        ) AND
        (SELECT COUNT(*) FROM players p WHERE p.match_id = m.match_id
         AND p.player_slot IN (0, 1, 2, 3, 4, 128, 129, 130, 131, 132)
         AND p.hero_id > 0) = 10 AND
        (SELECT COUNT(DISTINCT hero_id) FROM players p
         WHERE p.match_id = m.match_id
         AND p.player_slot IN (0, 1, 2, 3, 4, 128, 129, 130, 131, 132)) = 10
        ORDER BY start_time DESC, match_id DESC LIMIT ?""",
        (match_id, match_id, limit),
    ).fetchall()
    windows: dict[int, tuple[int, int]] = {}
    for target in targets:
        for row in db.execute(
            """SELECT account_id FROM players WHERE match_id = ?
            AND account_id > 0 AND account_id < 4294967295
            AND player_slot IN (0, 1, 2, 3, 4, 128, 129, 130, 131, 132)
            AND hero_id > 0
            GROUP BY account_id HAVING COUNT(*) = 1""",
            (target["match_id"],),
        ):
            account = row["account_id"]
            since, until = windows.get(
                account, (target["start_time"], target["start_time"])
            )
            windows[account] = (
                0
                if all_history
                else max(0, min(since, target["start_time"] - days * 86400)),
                max(until, target["start_time"], history_until or 0),
            )
    progress(
        f"Матчей для анализа: {len(targets)}; аккаунтов для загрузки: {len(windows)}."
    )
    if not windows:
        progress("Нет участников с известными ID. Сначала выполните matchdb enrich.")
        return False
    completed = 0
    for account, (since, until) in windows.items():
        complete = False
        for page_index in range(max_pages):
            result = collect_account_page(
                db,
                client,
                account,
                since,
                until,
                progress,
                refresh=refresh and page_index == 0,
                reuse_complete=not refresh,
            )
            if result is None:
                break
            complete = result
            if complete:
                break
        if complete:
            completed += 1
        else:
            progress(
                f"Аккаунт {account}: загрузка не закончена; повторный запуск продолжит её."
            )
    progress(f"Проверены окна истории для {completed}/{len(windows)} аккаунтов.")
    return completed == len(windows)


def collect_account_page(
    db: sqlite3.Connection,
    client: OpenDotaClient,
    account: int,
    since: int,
    until: int,
    progress: Callable[[str], None] = print,
    *,
    refresh: bool = False,
    reuse_complete: bool = True,
) -> bool | None:
    if not 0 < account < 4294967295 or not 0 <= since < until:
        raise ValueError("Некорректный аккаунт или границы истории")
    coverage = load_coverage(db, account).get(account)
    if (
        reuse_complete
        and not refresh
        and db.execute(
            """SELECT 1 FROM history_requests WHERE account_id = ?
        AND since <= ? AND until >= ? AND complete = 1 LIMIT 1""",
            (account, since, until),
        ).fetchone()
        is not None
    ):
        progress(f"Аккаунт {account}: окно истории уже покрыто кешем.")
        return True
    request = (
        None
        if refresh
        else db.execute(
            """SELECT * FROM history_requests WHERE account_id = ? AND since = ?
        AND until >= ? AND complete = 0 ORDER BY prefix_valid DESC, offset DESC LIMIT 1""",
            (account, since, until),
        ).fetchone()
    )
    if request is not None:
        until = request["until"]
    key = (account, since, until)
    with db:
        db.execute(
            """INSERT OR IGNORE INTO history_requests(account_id, since, until, prefix_valid)
            VALUES (?, ?, ?, 1)""",
            key,
        )
        if refresh:
            db.execute(
                """UPDATE history_requests SET offset = 0, complete = 0,
                oldest_start_time = NULL, prefix_valid = 1
                WHERE account_id = ? AND since = ? AND until = ?""",
                key,
            )
    request = db.execute(
        "SELECT * FROM history_requests WHERE account_id = ? AND since = ? AND until = ?",
        key,
    ).fetchone()
    offset = request["offset"]
    valid = offset == 0 or bool(request["prefix_valid"])
    if request["complete"]:
        return True
    if offset > 0 and request["oldest_start_time"] is None and not valid:
        progress(
            f"Аккаунт {account}: проверка старого неполного кеша с первой страницы."
        )
        offset = 0
        valid = True
    try:
        page = client.player_matches(account, offset)
    except HTTPError as error:
        if error.code not in (403, 404):
            raise
        code = error.code
        error.close()
        progress(f"Аккаунт {account}: история недоступна (HTTP {code}).")
        return None
    if any(m.start_time is None or m.start_time <= 0 for m in page):
        raise ValueError(
            f"История аккаунта {account} содержит матчи без времени начала"
        )
    times = [m.start_time for m in page if m.start_time is not None]
    if times != sorted(times, reverse=True):
        raise ValueError(f"История аккаунта {account} не отсортирована по времени")
    if (
        request["oldest_start_time"] is not None
        and times
        and times[0] > request["oldest_start_time"]
    ):
        valid = False
        progress(
            f"Аккаунт {account}: нарушен порядок страниц; непрерывность истории не подтверждена."
        )
    complete = not page or times[-1] <= since
    oldest = times[-1] if times else request["oldest_start_time"]
    saved = 0
    with db:
        for match in page:
            assert match.start_time is not None
            if since <= match.start_time < until:
                accepted = _save_game(db, account, match)
                saved += accepted
                if not accepted and (match.lobby_type is None or match.lobby_type == 7):
                    valid = False
        if (
            reuse_complete
            and valid
            and since == 0
            and coverage is not None
            and coverage.complete_until is not None
            and oldest is not None
            and oldest <= coverage.complete_until
        ):
            complete = True
        offset += len(page)
        db.execute(
            """UPDATE history_requests SET offset = ?, complete = ?,
            oldest_start_time = ?, prefix_valid = ?
            WHERE account_id = ? AND since = ? AND until = ?""",
            (offset, complete, oldest, valid, *key),
        )
    if offset == 0 and complete:
        progress(
            f"Аккаунт {account}: API вернул пустую историю; "
            "обход завершён, полнота истории не подтверждена."
        )
    else:
        progress(
            f"Аккаунт {account}: просмотрено {offset}, сохранено на странице {saved}; "
            f"обход завершён: {complete}; непрерывность: {valid}."
        )
    return complete
