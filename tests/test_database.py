from datetime import date

import pytest

from factories import add_sample
from database import Database, build_report
from models import Customer, CustomerHasOrdersError, NotFoundError, Order, OrderItem, ValidationError


def test_customer_and_order_crud(db):
    ivan, maria = add_sample(db)
    assert ivan.name == "Иван Петров"
    ivan.phone = "+7000"
    updated = db.update_customer(ivan)
    assert updated.phone == "+7000"
    assert len(db.list_customers()) == 2

    orders = db.list_orders()
    assert len(orders) == 4
    first = orders[0]
    first.status = "в доставке"
    first.items = [OrderItem("Чай", 1, 15)]
    saved = db.update_order(first)
    assert saved.status == "в доставке"
    assert saved.total == 15
    assert len(saved.items) == 1

    db.delete_order(saved.id)
    assert len(db.list_orders()) == 3
    with pytest.raises(NotFoundError):
        db.get_order(saved.id)
    with pytest.raises(NotFoundError):
        db.delete_order(saved.id)


def test_cannot_delete_customer_with_orders(db):
    ivan, maria = add_sample(db)
    with pytest.raises(CustomerHasOrdersError):
        db.delete_customer(ivan.id)
    lonely = db.add_customer(Customer(None, "Без заказов", "1", "адрес"))
    db.delete_customer(lonely.id)
    with pytest.raises(NotFoundError):
        db.get_customer(lonely.id)
    with pytest.raises(ValidationError):
        db.add_order(Order(999, "2026-10-07", "новый", [OrderItem("Чай", 1, 10)]))
    with pytest.raises(ValidationError):
        db.add_customer(Customer(None, " ", "1", "адрес"))
    assert maria.id != ivan.id


def test_filter_by_status_and_date(db):
    add_sample(db)
    assert len(db.filter_orders(status="новый")) == 1
    assert len(db.filter_orders(on_date="2026-10-07")) == 2
    assert db.filter_orders(status="новый", on_date="2026-10-07") == []
    assert len(db.filter_orders(date_from="2026-10-01", date_to="2026-10-31")) == 3
    with pytest.raises(ValidationError):
        db.filter_orders(status="готов")


def test_report_for_day_week_and_month(db):
    add_sample(db)
    today = date(2026, 10, 7)
    month = build_report(db, "month", today)
    assert "2026-10-01 — 2026-10-31" in month
    assert "новый: 1" in month
    assert "в доставке: 0" in month
    assert "выполнен: 1" in month
    assert "отменён: 1" in month
    assert "Общая выручка: 280.00" in month
    assert "1. Иван Петров — 200.00" in month
    assert "2. Мария Сидорова — 80.00" in month
    assert "Кофе" not in month

    week = build_report(db, "неделя", today)
    assert "Общая выручка: 200.00" in week
    day = build_report(db, "day", today)
    assert "Общая выручка: 200.00" in day


def test_backends_build_same_report(tmp_path):
    reports = []
    for backend, name in (("sqlite", "same.db"), ("tinydb", "same.json")):
        database = Database(backend, tmp_path / name, seed=False)
        add_sample(database)
        reports.append(build_report(database, "месяц", date(2026, 10, 7)))
        database.close()
    assert reports[0] == reports[1]


def test_seed_once(tmp_path):
    path = tmp_path / "seed.db"
    database = Database("sqlite", path, seed=True)
    count = len(database.list_customers())
    orders = database.list_orders()
    assert count >= 4
    assert len(orders) >= 4
    assert "выполнен" in {order.status for order in orders}
    assert "отменён" in {order.status for order in orders}
    assert "Топ-3" in build_report(database, "month")
    database.close()

    again = Database("sqlite", path, seed=True)
    assert len(again.list_customers()) == count
    again.close()

    tiny = Database("tinydb", tmp_path / "seed.json", seed=True)
    assert len(tiny.list_customers()) >= 4
    tiny.close()


def test_sqlite_schema_restrictions(tmp_path):
    database = Database("sqlite", tmp_path / "schema.db", seed=False)
    names = {
        row[0]
        for row in database._impl.conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert {"customers", "orders", "order_items"} <= names
    customer = database.add_customer(Customer(None, "Иван", "1", "адрес"))
    database.add_order(Order(customer.id, "2026-10-07", "новый", [OrderItem("Чай", 1, 10)]))
    with pytest.raises(CustomerHasOrdersError):
        database._impl.delete_customer(customer.id)
    with pytest.raises(ValidationError):
        database._impl.add_order(
            Order(customer.id, "2026-10-07", "плохой", [OrderItem("Чай", 1, 10)], total=10)
        )
    database.close()


def test_unknown_backend(tmp_path):
    with pytest.raises(ValueError):
        Database("mysql", tmp_path / "x.db")


def test_logging_writes_customer_name(db):
    from logger_config import LOG_FILE

    db.add_customer(Customer(None, "КлиентЛогПроверка123", "1", "адрес"))
    assert "КлиентЛогПроверка123" in LOG_FILE.read_text(encoding="utf-8")
