import fcntl
import heapq
import os
import sqlite3
import subprocess
import sys
from collections import Counter, defaultdict, deque
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from urllib.error import HTTPError

from .api import OpenDotaClient
from .collection import RANKED
from .history import collect_account_page
from .history_coverage import HistoryCoverage, load_coverage
from .models import Source
from .storage import save_match

SLOTS = (0, 1, 2, 3, 4, 128, 129, 130, 131, 132)
LINEUP = """(SELECT COUNT(*) FROM players p WHERE p.match_id = m.match_id
    AND p.player_slot IN (0, 1, 2, 3, 4, 128, 129, 130, 131, 132)
    AND p.hero_id > 0) = 10 AND
    (SELECT COUNT(DISTINCT hero_id) FROM players p WHERE p.match_id = m.match_id
     AND p.player_slot IN (0, 1, 2, 3, 4, 128, 129, 130, 131, 132)) = 10"""


@dataclass(slots=True)
class Account:
    account_id: int
    until: int
    coverage: HistoryCoverage
    targets: set[int] = field(default_factory=set)
    pages: int = 0
    blocked: bool = False
    version: int = 0


@dataclass(slots=True)
class Target:
    match_id: int
    start_time: int
    players: dict[int, int | None] = field(default_factory=dict)
    unavailable: bool = False
    contributions: dict[int, float] = field(default_factory=dict)
    observations: Counter[str] = field(default_factory=Counter)


def _checkpoint(
    db: sqlite3.Connection, match_id: int, *, complete: bool, unavailable: bool = False
) -> None:
    with db:
        db.execute(
            """INSERT INTO analysis_preparation(match_id, complete, unavailable)
            VALUES (?, ?, ?) ON CONFLICT(match_id) DO UPDATE SET
            complete = excluded.complete, unavailable = excluded.unavailable,
            updated_at = CURRENT_TIMESTAMP
            WHERE complete != excluded.complete OR unavailable != excluded.unavailable""",
            (match_id, complete, unavailable),
        )


class Scheduler:
    def __init__(
        self,
        db: sqlite3.Connection,
        client: OpenDotaClient,
        limit: int | None,
        max_pages: int,
        recent_games: int,
        min_history: int,
        progress: Callable[[str], None],
    ) -> None:
        self.db = db
        self.client = client
        self.max_pages = max_pages
        self.recent_games = recent_games
        self.min_history = min_history
        self.progress = progress
        rows = db.execute(
            f"""SELECT m.match_id, start_time, COALESCE(a.unavailable, 0) AS unavailable
            FROM matches m LEFT JOIN analysis_preparation a ON a.match_id = m.match_id
            WHERE {RANKED} ORDER BY ({LINEUP}) DESC, m.match_id DESC LIMIT ?""",
            (limit if limit is not None else -1,),
        ).fetchall()
        self.targets = {
            row["match_id"]: Target(
                row["match_id"],
                row["start_time"] or 0,
                unavailable=bool(row["unavailable"]),
            )
            for row in rows
        }
        self.until = max(
            (target.start_time for target in self.targets.values()), default=0
        )
        self.accounts: dict[int, Account] = {}
        self.coverage = load_coverage(db)
        self.utility: defaultdict[int, float] = defaultdict(float)
        self.fast: list[tuple[float, int, int, int]] = []
        self.breadth: deque[int] = deque()
        self.details: deque[int] = deque()
        self.observations: Counter[str] = Counter()
        players: defaultdict[int, list[sqlite3.Row]] = defaultdict(list)
        for row in db.execute(
            "SELECT match_id, player_slot, hero_id, account_id FROM players"
        ):
            if row["match_id"] in self.targets:
                players[row["match_id"]].append(row)
        for target in self.targets.values():
            self._set_players(target, players[target.match_id])
            if target.players:
                target.unavailable = False
                self._register(target)
            elif not target.unavailable:
                self.details.append(target.match_id)
        for account in self.accounts.values():
            self._queue(account)

    def _set_players(self, target: Target, rows: list[sqlite3.Row]) -> None:
        valid = [
            row
            for row in rows
            if row["player_slot"] in SLOTS
            and row["hero_id"] is not None
            and row["hero_id"] > 0
        ]
        if (
            target.start_time <= 0
            or len(valid) != 10
            or len({row["player_slot"] for row in valid}) != 10
            or len({row["hero_id"] for row in valid}) != 10
        ):
            return
        accounts = Counter(row["account_id"] for row in valid)
        target.players = {
            row["player_slot"]: (
                row["account_id"]
                if row["account_id"] is not None
                and 0 < row["account_id"] < 4294967295
                and accounts[row["account_id"]] == 1
                else None
            )
            for row in valid
        }

    def _register(self, target: Target) -> set[int]:
        for account_id in target.players.values():
            if account_id is None:
                continue
            if account_id not in self.accounts:
                self.accounts[account_id] = Account(
                    account_id,
                    max(self.until, target.start_time),
                    self.coverage.get(account_id, HistoryCoverage()),
                )
                self.breadth.append(account_id)
            account = self.accounts[account_id]
            account.until = max(account.until, target.start_time)
            account.targets.add(target.match_id)
        return self._refresh(target)

    def _active(self, account: Account) -> bool:
        return (
            not account.blocked
            and account.pages < self.max_pages
            and (account.coverage.checked_until or 0) < account.until
        )

    def _ready(self, account: Account, target: Target) -> bool:
        coverage = account.coverage
        if (coverage.complete_until or 0) >= target.start_time:
            lower, required = 0, self.min_history
        else:
            ranges = [
                lower for lower, upper in coverage.ranges if upper >= target.start_time
            ]
            if not ranges:
                return False
            lower, required = min(ranges), max(self.recent_games, self.min_history)
        rows = self.db.execute(
            """SELECT match_id FROM player_history WHERE account_id = ?
            AND start_time > ? AND start_time < ? AND start_time + duration < ?
            AND match_id != ? ORDER BY start_time DESC LIMIT ?""",
            (
                account.account_id,
                lower,
                target.start_time,
                target.start_time,
                target.match_id,
                required,
            ),
        ).fetchall()
        return len(rows) >= required

    def _tasks(self, target: Target) -> Counter[tuple[str, frozenset[int]]]:
        tasks: Counter[tuple[str, frozenset[int]]] = Counter()
        for slot, account in target.players.items():
            if account is None:
                continue
            tasks["players", frozenset((account,))] += 1
            for name, same_side in (("allies", True), ("enemies", False)):
                group = [
                    other
                    for other_slot, other in target.players.items()
                    if other_slot != slot
                    and ((other_slot < 128) == (slot < 128)) == same_side
                ]
                if all(other is not None for other in group):
                    tasks[
                        name,
                        frozenset(
                            (account, *(other for other in group if other is not None))
                        ),
                    ] += 1
        return tasks

    def _refresh(self, target: Target) -> set[int]:
        affected = set(target.contributions)
        for account, score in target.contributions.items():
            self.utility[account] -= score
        self.observations.subtract(target.observations)
        target.contributions = {}
        target.observations = Counter()
        ready = {
            account
            for account in target.players.values()
            if account is not None and self._ready(self.accounts[account], target)
        }
        for (kind, group), reward in self._tasks(target).items():
            missing = group - ready
            if not missing:
                target.observations[kind] += reward
            elif all(self._active(self.accounts[account]) for account in missing):
                for account in missing:
                    target.contributions[account] = (
                        target.contributions.get(account, 0.0)
                        + reward / len(missing) ** 2
                    )
        for account, score in target.contributions.items():
            self.utility[account] += score
        self.observations.update(target.observations)
        affected.update(target.contributions)
        return affected

    def _queue(self, account: Account) -> None:
        account.version += 1
        score = self.utility[account.account_id]
        if score > 1e-12 and self._active(account):
            heapq.heappush(
                self.fast,
                (-round(score, 12), account.pages, account.account_id, account.version),
            )
        if len(self.fast) > max(100, 4 * len(self.accounts)):
            self.fast = [
                (
                    -round(self.utility[a.account_id], 12),
                    a.pages,
                    a.account_id,
                    a.version,
                )
                for a in self.accounts.values()
                if self.utility[a.account_id] > 1e-12 and self._active(a)
            ]
            heapq.heapify(self.fast)

    def _next_fast(self) -> Account | None:
        while self.fast:
            _, _, account_id, version = heapq.heappop(self.fast)
            account = self.accounts[account_id]
            if version == account.version and self._active(account):
                return account
        return None

    def _next_breadth(self, *, recent_ready: bool = False) -> Account | None:
        for _ in range(len(self.breadth)):
            account_id = self.breadth.popleft()
            self.breadth.append(account_id)
            account = self.accounts[account_id]
            if self._active(account) and (
                not recent_ready or self.utility[account_id] <= 1e-12
            ):
                return account
        return None

    def _detail(self) -> None:
        target = self.targets[self.details.popleft()]
        self.progress(f"Матч {target.match_id}: загрузка состава.")
        try:
            match = self.client.match(target.match_id)
        except HTTPError as error:
            if error.code not in (403, 404):
                raise
            code = error.code
            error.close()
            target.unavailable = True
            self.progress(f"Матч {target.match_id}: HTTP {code}, пропущен.")
        else:
            save_match(self.db, match, Source.MATCH)
            row = self.db.execute(
                "SELECT * FROM matches WHERE match_id = ?", (target.match_id,)
            ).fetchone()
            target.start_time = row["start_time"] or 0
            if (
                row["lobby_type"] == 7
                and row["radiant_win"] is not None
                and (row["duration"] or 0) > 0
            ):
                self._set_players(
                    target,
                    self.db.execute(
                        "SELECT player_slot, hero_id, account_id FROM players WHERE match_id = ?",
                        (target.match_id,),
                    ).fetchall(),
                )
            target.unavailable = not bool(target.players)
            if target.players:
                for account_id in self._register(target):
                    self._queue(self.accounts[account_id])
        if target.unavailable:
            _checkpoint(self.db, target.match_id, complete=True, unavailable=True)

    def _page(self, account: Account) -> None:
        result = collect_account_page(
            self.db,
            self.client,
            account.account_id,
            0,
            account.until,
            self.progress,
        )
        account.pages += 1
        account.blocked = result is None
        account.coverage = load_coverage(self.db, account.account_id).get(
            account.account_id, HistoryCoverage()
        )
        affected = {account.account_id}
        for match_id in account.targets:
            affected.update(self._refresh(self.targets[match_id]))
        for account_id in affected:
            self._queue(self.accounts[account_id])

    def run(self) -> bool:
        self.progress(
            f"Подготовка: {len(self.targets)} матчей, {len(self.accounts)} аккаунтов; "
            f"сначала {self.recent_games} подтверждённых прошлых игр, затем полный хвост."
        )
        steps = 0
        while True:
            if steps % 10 == 9 and self.details:
                self._detail()
            else:
                account = (
                    (self._next_breadth(recent_ready=True) or self._next_fast())
                    if steps % 20 == 18
                    else self._next_fast()
                )
                if account is not None:
                    self._page(account)
                elif self.details:
                    self._detail()
                else:
                    account = self._next_breadth()
                    if account is None:
                        break
                    self._page(account)
            steps += 1
            self.progress(
                f"Шагов загрузки: {steps}; готовность истории: "
                f"игроки={self.observations['players']}, союзники={self.observations['allies']}, "
                f"враги={self.observations['enemies']}. Очередь пересчитана."
            )
        pending = 0
        for target in self.targets.values():
            known = {
                account for account in target.players.values() if account is not None
            }
            unavailable = target.unavailable or not known
            complete = unavailable or all(
                (self.accounts[account].coverage.checked_until or 0)
                >= self.accounts[account].until
                for account in known
            )
            _checkpoint(
                self.db, target.match_id, complete=complete, unavailable=unavailable
            )
            pending += not complete
        self.progress(
            f"Проход закончен: {steps} шагов; матчей с незавершёнными историями: {pending}."
        )
        return pending == 0


def prepare_analysis(
    db: sqlite3.Connection,
    client: OpenDotaClient,
    limit: int | None = None,
    max_pages: int = 1000,
    progress: Callable[[str], None] = print,
    *,
    recent_games: int = 40,
    min_history: int = 10,
) -> bool:
    if (limit is not None and limit <= 0) or min(
        max_pages, recent_games, min_history
    ) <= 0:
        raise ValueError("Лимиты подготовки должны быть положительными")
    return Scheduler(
        db, client, limit, max_pages, recent_games, min_history, progress
    ).run()


@contextmanager
def preparation_lock(path: Path) -> Iterator[None]:
    lock_path = path.with_suffix(".prepare.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("Подготовка этой базы уже запущена") from error
        lock.seek(0)
        lock.truncate()
        lock.write(f"{os.getpid()}\n")
        lock.flush()
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def start_background(
    path: Path,
    interval: float,
    limit: int | None,
    max_pages: int,
    recent_games: int = 40,
    min_history: int = 10,
) -> tuple[int, Path]:
    path = path.resolve()
    with preparation_lock(path):
        pass
    log_path = path.with_suffix(".prepare.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    args = [
        sys.executable,
        "-u",
        "-m",
        "matchdb",
        "--db",
        str(path),
        "--interval",
        str(interval),
        "prepare",
        "--max-pages",
        str(max_pages),
        "--recent-games",
        str(recent_games),
        "--min-history",
        str(min_history),
    ]
    if limit is not None:
        args.extend(("--limit", str(limit)))
    with log_path.open("ab", buffering=0) as log:
        process = subprocess.Popen(
            args,
            cwd=Path(__file__).resolve().parent.parent,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    return process.pid, log_path
