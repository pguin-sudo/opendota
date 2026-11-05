import argparse
import importlib
import pkgutil
import sqlite3
import sys
from pathlib import Path
from typing import cast

import analysis
from analysis._base import BaseAnalysis, Options
from matchdb.cli import positive_int
from matchdb.reader import load_matches

from .csv import write_csv
from .plots import plot_report


def available_analyses() -> list[str]:
    return sorted(
        module.name
        for module in pkgutil.iter_modules(analysis.__path__)
        if not module.name.startswith("_")
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Анализ сохранённых матчей")
    names = available_analyses()
    parser.add_argument(
        "analysis", choices=names, nargs="?", help="Без имени выполняются все анализы"
    )
    parser.add_argument("--db", type=Path, default=Path("data/matches.sqlite3"))
    parser.add_argument("--csv", action="store_true", help="Дополнительно вывести CSV")
    parser.add_argument(
        "--output",
        type=Path,
        help="CSV-файл с --csv; для всех анализов — каталог (data/reports)",
    )
    parser.add_argument(
        "--plot",
        type=Path,
        help="Путь графика; для всех анализов — каталог SVG (по умолчанию data/reports)",
    )
    parser.add_argument("--bin-seconds", type=positive_int, default=60)
    parser.add_argument("--min-matches", type=positive_int, default=1)
    parser.add_argument(
        "--position-source",
        choices=("explicit", "networth"),
        default="networth",
        help="Способ определения позиции (по умолчанию networth)",
    )
    args = parser.parse_args()
    if args.output is not None and not args.csv:
        parser.error(
            "--output задаёт путь CSV и требует --csv; для графиков используйте --plot"
        )
    try:
        batch = args.analysis is None
        selected = names if batch else [args.analysis]
        instances = []
        for name in selected:
            module = importlib.import_module(f"analysis.{name}")
            analysis_class = cast(type[BaseAnalysis], module.Analysis)
            instances.append((name, analysis_class()))
        matches = load_matches(
            args.db,
            include_players=any(instance.requires_players for _, instance in instances),
        )
        options = Options(args.bin_seconds, args.min_matches, args.position_source)
        failed = False
        for name, instance in instances:
            try:
                result = instance.run(matches, options)
                for note in result.notes:
                    print(f"{name}: {note}", file=sys.stderr)
                if not result.rows:
                    print(
                        f"{name}: нет данных для анализа. Проверьте фильтры и наличие необходимых полей.",
                        file=sys.stderr,
                    )
                if args.csv:
                    output = (
                        ((args.output or Path("data/reports")) / f"{name}.csv")
                        if batch
                        else args.output
                    )
                    write_csv(result.columns, result.rows, output)
                    if output is not None:
                        print(f"{name}: CSV → {output}", file=sys.stderr)
                if not result.rows or result.plot is None:
                    print(
                        f"{name}: график пропущен — нет данных или описания графика.",
                        file=sys.stderr,
                    )
                    continue
                plot = (
                    (args.plot or Path("data/reports")) / f"{name}.svg"
                    if batch
                    else args.plot or Path("data/reports") / f"{name}.svg"
                )
                plot_report(result, plot)
                print(f"{name}: график → {plot}", file=sys.stderr)
            except (OSError, ValueError, sqlite3.Error) as error:
                if not batch:
                    raise
                failed = True
                print(f"{name}: ошибка: {error}", file=sys.stderr)
        if failed:
            parser.exit(1, "Часть анализов завершилась с ошибкой.\n")
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f"Ошибка: {error}\n")


if __name__ == "__main__":
    main()
