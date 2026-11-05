import csv
import sys
from collections.abc import Iterable, Sequence
from contextlib import nullcontext
from pathlib import Path

from analysis._base import Cell


def write_csv(
    header: Sequence[str],
    rows: Iterable[Sequence[Cell]],
    output: Path | None = None,
) -> None:
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
    with (
        output.open("w", encoding="utf-8", newline="")
        if output is not None
        else nullcontext(sys.stdout)
    ) as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)
