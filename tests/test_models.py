from datetime import date

import pytest

from models import (
    STATUSES,
    Customer,
    Order,
    OrderItem,
    ValidationError,
    normalize_period,
    parse_customer,
    parse_order,
    period_bounds,
)


def test_customer_name_required():
    customer = Customer(None, "   ", "+7", "адрес")
    with pytest.raises(ValidationError):
        customer.validate()


def test_customer_strips_fields():
    customer = Customer(None, " Иван ", " 123 ", " ул ")
    customer.validate()
    assert customer.name == "Иван"
    assert customer.phone == "123"
    assert customer.address == "ул"


def test_order_total_and_statuses():
    order = Order(1, "2026-10-07", "новый", [OrderItem("Пицца", 2, 750), OrderItem("Сок", 1, 120)])
    order.validate()
    assert order.total == 1620
    assert set(STATUSES) == {"новый", "в доставке", "выполнен", "отменён"}


def test_order_rejects_bad_fields():
    with pytest.raises(ValidationError):
        Order(1, "07.10.2026", "новый", [OrderItem("Чай", 1, 10)], total=10).validate()
    with pytest.raises(ValidationError):
        Order(1, "2026-10-07", "готов", [OrderItem("Чай", 1, 10)], total=10).validate()
    with pytest.raises(ValidationError):
        Order(1, "2026-10-07", "новый", [], total=0).validate()
    with pytest.raises(ValidationError):
        Order(1, "2026-10-07", "новый", [OrderItem("Чай", 1, 10)], total=50).validate()
    with pytest.raises(ValidationError):
        OrderItem("", 1, 10).validate()
    with pytest.raises(ValidationError):
        OrderItem("Чай", 0, 10).validate()
    with pytest.raises(ValidationError):
        OrderItem("Чай", 1, -1).validate()


def test_period_bounds():
    assert normalize_period("Месяц") == "month"
    assert period_bounds("day", date(2026, 10, 7)) == ("2026-10-07", "2026-10-07")
    assert period_bounds("неделя", date(2026, 10, 7)) == ("2026-10-05", "2026-10-11")
    assert period_bounds("month", date(2026, 10, 7)) == ("2026-10-01", "2026-10-31")
    assert period_bounds("month", date(2026, 2, 10)) == ("2026-02-01", "2026-02-28")
    assert period_bounds("month", date(2024, 2, 10)) == ("2024-02-01", "2024-02-29")
    assert period_bounds("month", date(2026, 12, 15)) == ("2026-12-01", "2026-12-31")
    with pytest.raises(ValidationError):
        normalize_period("year")


def test_parse_customer_and_order():
    customer = parse_customer({"id": "2", "name": "Ольга", "phone": "1", "address": "дом"})
    assert customer.id == 2
    order = parse_order(
        {
            "id": 5,
            "customer_id": 2,
            "order_date": "2026-10-07",
            "status": "выполнен",
            "total": 20,
            "items": [{"product_name": "Чай", "quantity": "2", "price": "10"}],
        }
    )
    assert order.total == 20
    assert order.items[0].quantity == 2
    with pytest.raises(ValidationError):
        parse_customer({"name": "Без id"})
    with pytest.raises(ValidationError):
        parse_order({"id": 1, "customer_id": 1, "order_date": "2026-10-07", "status": "новый", "total": 0, "items": []})
