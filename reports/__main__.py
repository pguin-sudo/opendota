import argparse
import importlib
import pkgutil
import sqlite3
import sys
from pathlib import Path
from typing import cast

import analysis
from analysis._base import BaseAnalysis, Options, ranked_matches
from analysis._normalization import normalize_report
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
    parser.add_argument("--history-days", type=positive_int, default=30)
    parser.add_argument("--history-matches", type=positive_int, default=20)
    parser.add_argument("--min-history", type=positive_int, default=10)
    parser.add_argument(
        "--detailed-ranks",
        action="store_true",
        help="Группировать по исходным кодам ранга вместо восьми медалей",
    )
    normalization = parser.add_mutually_exclusive_group()
    normalization.add_argument(
        "--normalize",
        action="store_true",
        help="Сглаживать показатели по соседним значениям X с весами по размеру выборки",
    )
    normalization.add_argument(
        "--raw",
        "--unnormalized",
        action="store_true",
        help="Выводить исходные показатели (по умолчанию)",
    )
    parser.add_argument(
        "--form-bins",
        type=positive_int,
        default=10,
        help="Число интервалов веса истории от -1 до +1 (10)",
    )
    history_quality = parser.add_mutually_exclusive_group()
    history_quality.add_argument(
        "--complete-history",
        action="store_true",
        help="В анализах весов использовать только полностью загруженную доступную историю",
    )
    history_quality.add_argument(
        "--bounded-history",
        action="store_true",
        help="В анализах весов допускать только полную историю или подтверждённый недавний участок",
    )
    parser.add_argument(
        "--recent-games",
        type=positive_int,
        default=40,
        help="Минимум последовательных игр для --bounded-history (40)",
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
        matches = ranked_matches(
            load_matches(
                args.db,
                include_players=any(
                    instance.requires_players for _, instance in instances
                ),
            )
        )
        options = Options(
            args.bin_seconds,
            args.min_matches,
            args.position_source,
            args.history_days,
            args.history_matches,
            args.min_history,
            detailed_ranks=args.detailed_ranks,
            form_bins=args.form_bins,
            complete_history=args.complete_history,
            bounded_history=args.bounded_history,
            recent_games=args.recent_games,
        )
        failed = False
        for name, instance in instances:
            try:
                result = instance.run(matches, options)
                if args.normalize:
                    result = normalize_report(result)
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
