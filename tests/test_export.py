import json
import logging
from pathlib import Path

import pytest

from data_export import export_to_file, import_from_file
from database import Database
from factories import add_sample
from logger_config import LOG_FILE, setup_logging
from main_cli import main
from models import Customer, Order, OrderItem, ValidationError


def test_roundtrip_json_and_xml(db, tmp_path):
    add_sample(db)
    for suffix in (".json", ".xml"):
        path = tmp_path / "orders{0}".format(suffix)
        export_to_file(db.list_customers(), db.list_orders(), str(path))
        customers, orders = import_from_file(str(path))
        fresh_name = "fresh{0}.db".format(suffix) if db.backend == "sqlite" else "fresh{0}.json".format(suffix)
        fresh = Database(db.backend, tmp_path / fresh_name, seed=False)
        fresh.import_data(customers, orders)
        assert {item.name for item in fresh.list_customers()} == {
            item.name for item in db.list_customers()
        }
        assert sorted(item.total for item in fresh.list_orders()) == sorted(
            item.total for item in db.list_orders()
        )
        fresh.close()


def test_import_updates_existing_order(db, tmp_path):
    ivan, _maria = add_sample(db)
    path = tmp_path / "once.json"
    export_to_file(db.list_customers(), db.list_orders(), str(path))
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["orders"][0]["status"] = "в доставке"
    payload["orders"][0]["items"] = [{"product_name": "Чай", "quantity": 1, "price": 15}]
    payload["orders"][0]["total"] = 15
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    customers, orders = import_from_file(str(path))
    db.import_data(customers, orders)
    loaded = db.get_order(payload["orders"][0]["id"])
    assert loaded.status == "в доставке"
    assert loaded.total == 15
    assert ivan.id in {item.id for item in db.list_customers()}


def test_import_rejects_incorrect_files(db, tmp_path):
    before = len(db.list_orders())
    samples = {
        "broken.json": "{",
        "list.json": "[]",
        "empty.json": "{}",
        "customers.json": json.dumps({"orders": [], "customers": {}}),
        "broken.xml": "<notxml",
        "root.xml": "<root></root>",
    }
    for name, text in samples.items():
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        with pytest.raises(ValidationError):
            import_from_file(str(path))
    assert len(db.list_orders()) == before

    mismatch = {
        "customers": [{"id": 1, "name": "Анна", "phone": "1", "address": "ул"}],
        "orders": [
            {
                "id": 1,
                "customer_id": 1,
                "order_date": "2026-10-07",
                "status": "выполнен",
                "total": 999,
                "items": [{"product_name": "Чай", "quantity": 1, "price": 10}],
            }
        ],
    }
    path = tmp_path / "mismatch.json"
    path.write_text(json.dumps(mismatch), encoding="utf-8")
    with pytest.raises(ValidationError):
        import_from_file(str(path))

    mismatch["orders"][0]["total"] = 10
    mismatch["orders"][0]["status"] = "готов"
    path.write_text(json.dumps(mismatch, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(ValidationError):
        import_from_file(str(path))

    mismatch["orders"][0]["status"] = "новый"
    mismatch["orders"][0]["customer_id"] = 5
    path.write_text(json.dumps(mismatch, ensure_ascii=False), encoding="utf-8")
    customers, orders = import_from_file(str(path))
    with pytest.raises(ValidationError):
        db.import_data(customers, orders)
    assert db.list_orders() == []

    with pytest.raises(ValidationError):
        export_to_file([], [], str(tmp_path / "bad.txt"))
    with pytest.raises(ValidationError):
        import_from_file(str(tmp_path / "no-such.json"))


def test_duplicate_ids_rejected(db):
    customer = Customer(1, "Анна", "1", "ул")
    with pytest.raises(ValidationError):
        db.import_data([customer, Customer(1, "Борис", "2", "дом")], [])
    order = Order(1, "2026-10-07", "новый", [OrderItem("Чай", 1, 10)], id=3, total=10)
    order.validate()
    with pytest.raises(ValidationError):
        db.import_data([customer], [order, order])


def test_logger_configured_once():
    logger = setup_logging()
    again = setup_logging()
    assert again is logger

    def own_files():
        return [
            handler
            for handler in logger.handlers
            if isinstance(handler, logging.FileHandler) and Path(handler.baseFilename) == LOG_FILE
        ]

    assert len(own_files()) == 1


def test_cli_report_export_import(tmp_path, capsys):
    db_path = tmp_path / "cli.db"
    assert main(["--db", "sqlite", "--path", str(db_path), "report", "--period", "month"]) == 0
    report = capsys.readouterr().out
    assert "Общая выручка" in report
    assert "Топ-3" in report

    json_path = tmp_path / "orders_backup.json"
    xml_path = tmp_path / "orders_backup.xml"
    assert main(["--db", "sqlite", "--path", str(db_path), "export", "--file", str(json_path)]) == 0
    assert main(["--db", "sqlite", "--path", str(db_path), "export", "--file", str(xml_path)]) == 0
    assert json_path.exists()
    assert xml_path.exists()
    capsys.readouterr()

    other = tmp_path / "imported.db"
    assert main(["--db", "sqlite", "--path", str(other), "import", "--file", str(xml_path)]) == 0
    assert "Импортировано заказов" in capsys.readouterr().out

    tiny = tmp_path / "cli.json"
    assert main(["--db", "tinydb", "--path", str(tiny), "report", "--period", "неделя"]) == 0
    assert "неделя" in capsys.readouterr().out

    assert main(["--path", str(db_path), "report", "--period", "year"]) == 1
    assert main(["--path", str(db_path), "import", "--file", str(tmp_path / "missing.xml")]) == 1
    assert main(["--path", str(db_path), "export", "--file", str(tmp_path / "bad.txt")]) == 1
    assert "Ошибка" in capsys.readouterr().err
