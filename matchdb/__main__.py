import argparse
import math
import sqlite3
import sys
from urllib.error import HTTPError, URLError

from .api import OpenDotaClient
from .cli import positive_int
from .collection import collect, enrich, status
from .models import Source, parse_matches
from .storage import connect, save_match


def request_interval(value: str) -> float:
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise argparse.ArgumentTypeError(
            "Интервал должен быть конечным и неотрицательным"
        )
    return number


def main() -> None:
    parser = argparse.ArgumentParser(description="Локальная база рейтинговых матчей")
    parser.add_argument("--db", default="data/matches.sqlite3")
    parser.add_argument(
        "--interval",
        type=request_interval,
        default=1.2,
        help="Минимальная пауза между запросами в секундах (1.2)",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init")
    importer = commands.add_parser("import", help="Импорт ответа OpenDota из JSON")
    importer.add_argument("file")
    importer.add_argument("--source", choices=("public", "match"), required=True)
    fetch = commands.add_parser("fetch", help="Загрузить подробности одного матча")
    fetch.add_argument("match_id", type=positive_int)
    public = commands.add_parser(
        "public", help="Загрузить одну страницу публичных матчей"
    )
    public.add_argument("--less-than-match-id", type=positive_int)
    collector = commands.add_parser(
        "collect", help="Собрать целевое число рейтинговых матчей"
    )
    collector.add_argument(
        "--count",
        type=positive_int,
        required=True,
        help="Целевое общее количество матчей в базе",
    )
    collector.add_argument(
        "--from-latest",
        action="store_true",
        help="Начать с последних матчей вместо сохранённой позиции",
    )
    collector.add_argument(
        "--full",
        action="store_true",
        help="Цель — полные матчи с рангом и KDA/net worth десяти игроков",
    )
    enricher = commands.add_parser(
        "enrich", help="Дополнить матчи статистикой участников"
    )
    enricher.add_argument(
        "--limit",
        type=positive_int,
        default=100,
        help="Максимальное число матчей за запуск (100)",
    )
    commands.add_parser("status", help="Количество матчей и позиция сбора")
    args = parser.parse_args()
    db = connect(args.db)
    try:
        client = OpenDotaClient(
            interval=args.interval,
            retries=None if args.command == "collect" and args.full else 4,
        )

        def progress(message: str) -> None:
            print(message, file=sys.stderr)

        if args.command in {"import", "fetch", "public"}:
            if args.command == "import":
                with open(args.file, encoding="utf-8") as stream:
                    matches = parse_matches(stream.read())
                source = Source(args.source)
            else:
                source = Source.MATCH if args.command == "fetch" else Source.PUBLIC
                matches = (
                    [client.match(args.match_id)]
                    if source == Source.MATCH
                    else client.public_matches(args.less_than_match_id)
                )
            for match in matches:
                save_match(db, match, source)
            print(f"Сохранено записей: {len(matches)}")
        elif args.command == "collect":
            count = collect(
                db, client, args.count, args.from_latest, progress, full=args.full
            )
            label = "Полных рейтинговых матчей" if args.full else "Рейтинговых матчей"
            print(f"{label} в базе: {count}")
            if count < args.count:
                raise SystemExit(1)
        elif args.command == "enrich":
            count = enrich(db, client, args.limit, progress)
            print(f"Дополнено матчей: {count}")
        elif args.command == "status":
            print(status(db).to_json())
    finally:
        db.close()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nОстановлено. Сохранённые данные останутся в базе.", file=sys.stderr)
        sys.exit(130)
    except HTTPError as error:
        print(
            f"Ошибка OpenDota: HTTP {error.code}. Повторите команду позднее.",
            file=sys.stderr,
        )
        sys.exit(1)
    except (OSError, URLError, ValueError, RuntimeError, sqlite3.Error) as error:
        print(f"Ошибка: {error}", file=sys.stderr)
        sys.exit(1)
