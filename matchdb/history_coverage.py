import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HistoryCoverage:
    complete_until: int | None = None
    checked_until: int | None = None
    ranges: tuple[tuple[int, int], ...] = ()


def load_coverage(
    db: sqlite3.Connection, account_id: int | None = None
) -> dict[int, HistoryCoverage]:
    columns = {row[1] for row in db.execute("PRAGMA table_info(history_requests)")}
    if not columns:
        return {}
    modern = "prefix_valid" in columns
    query = "SELECT * FROM history_requests"
    params: tuple[int, ...] = ()
    if account_id is not None:
        query += " WHERE account_id = ?"
        params = (account_id,)
    full: dict[int, int] = {}
    checked: dict[int, int] = {}
    ranges: dict[int, list[tuple[int, int]]] = {}
    for row in db.execute(query, params):
        account = row["account_id"]
        if row["since"] == 0 and row["complete"]:
            checked[account] = max(checked.get(account, 0), row["until"])
        valid = bool(row["prefix_valid"]) if modern else bool(row["complete"])
        if not valid or row["offset"] <= 0:
            continue
        if row["complete"]:
            lower = row["since"]
            if lower == 0:
                full[account] = max(full.get(account, 0), row["until"])
        else:
            lower = row["oldest_start_time"]
        if lower is not None and lower < row["until"]:
            ranges.setdefault(account, []).append((lower, row["until"]))
    return {
        account: HistoryCoverage(
            full.get(account), checked.get(account), tuple(ranges.get(account, ()))
        )
        for account in full.keys() | checked.keys() | ranges.keys()
    }
