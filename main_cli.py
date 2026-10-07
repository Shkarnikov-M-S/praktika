"""Командная строка: отчёт, экспорт и импорт."""

from __future__ import annotations

import argparse
import sys

from data_export import export_to_file, import_from_file
from database import Database, build_report
from logger_config import get_logger


logger = get_logger()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Учёт заказов компании «Быстрая доставка»")
    parser.add_argument(
        "--db",
        choices=("sqlite", "tinydb"),
        default="sqlite",
        help="какая база используется: sqlite или tinydb",
    )
    parser.add_argument(
        "--path",
        default=None,
        help="путь к файлу базы; по умолчанию data/delivery.db или data/tinydb.json",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    report = commands.add_parser("report", help="отчёт за день, неделю или месяц")
    report.add_argument("--period", required=True, help="day, week или month")

    export = commands.add_parser("export", help="выгрузить все заказы в XML или JSON")
    export.add_argument("--file", required=True, help="файл .xml или .json")

    import_command = commands.add_parser("import", help="загрузить заказы из XML или JSON")
    import_command.add_argument("--file", required=True, help="файл .xml или .json")
    return parser


def main(argv=None) -> int:
    _configure_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        db = Database(args.db, args.path, seed=True)
        try:
            if args.command == "report":
                print(build_report(db, args.period))
            elif args.command == "export":
                export_to_file(db.list_customers(), db.list_orders(), args.file)
                print("Экспортировано в {0}".format(args.file))
            elif args.command == "import":
                customers, orders = import_from_file(args.file)
                count = db.import_data(customers, orders)
                print("Импортировано заказов: {0}".format(count))
            else:
                parser.error("Неизвестная команда")
        finally:
            db.close()
        return 0
    except Exception as exc:
        logger.exception("Ошибка команды %s", getattr(args, "command", ""))
        print("Ошибка: {0}".format(exc), file=sys.stderr)
        return 1


def _configure_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except (OSError, ValueError):
                pass


if __name__ == "__main__":
    sys.exit(main())
