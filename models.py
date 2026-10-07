"""Классы клиента и заказа и проверки корректности данных."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional


STATUSES = ("новый", "в доставке", "выполнен", "отменён")

PERIODS = {
    "day": "day",
    "день": "day",
    "week": "week",
    "неделя": "week",
    "month": "month",
    "месяц": "month",
}

PERIOD_TITLES = {
    "day": "день",
    "week": "неделя",
    "month": "месяц",
}


class DeliveryError(Exception):
    """Ошибка предметной области, которую можно показать пользователю."""


class ValidationError(DeliveryError):
    """Данные не прошли проверку."""


class NotFoundError(DeliveryError):
    """Запись не найдена."""


class CustomerHasOrdersError(DeliveryError):
    """Клиента нельзя удалить, пока у него есть заказы."""


def _as_int(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise ValidationError("Поле {0} должно быть целым числом".format(field))
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not value.is_integer():
            raise ValidationError("Поле {0} должно быть целым числом".format(field))
        return int(value)
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value.strip())
    raise ValidationError("Поле {0} должно быть целым числом".format(field))


def _as_float(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValidationError("Поле {0} должно быть числом".format(field))
    try:
        return float(str(value).strip().replace(",", "."))
    except ValueError as exc:
        raise ValidationError("Поле {0} должно быть числом".format(field)) from exc


@dataclass
class Customer:
    id: Optional[int]
    name: str
    phone: str
    address: str

    def validate(self) -> None:
        self.name = (self.name or "").strip()
        self.phone = (self.phone or "").strip()
        self.address = (self.address or "").strip()
        if not self.name:
            raise ValidationError("Имя клиента не может быть пустым")
        if self.id is not None and self.id <= 0:
            raise ValidationError("id клиента должен быть положительным")


@dataclass
class OrderItem:
    product_name: str
    quantity: int
    price: float

    @property
    def line_total(self) -> float:
        return round(self.quantity * self.price, 2)

    def validate(self) -> None:
        self.product_name = (self.product_name or "").strip()
        if not self.product_name:
            raise ValidationError("Название товара не может быть пустым")
        if isinstance(self.quantity, bool) or not isinstance(self.quantity, int):
            raise ValidationError("Количество товара должно быть целым числом")
        if self.quantity < 1:
            raise ValidationError("Количество товара должно быть больше нуля")
        if isinstance(self.price, bool) or not isinstance(self.price, (int, float)):
            raise ValidationError("Цена товара должна быть числом")
        if self.price < 0:
            raise ValidationError("Цена товара не может быть отрицательной")
        self.price = float(self.price)


@dataclass
class Order:
    customer_id: int
    order_date: str
    status: str
    items: List[OrderItem] = field(default_factory=list)
    id: Optional[int] = None
    total: Optional[float] = None

    def calculated_total(self) -> float:
        return round(sum(item.line_total for item in self.items), 2)

    def validate(self) -> None:
        if isinstance(self.customer_id, bool) or not isinstance(self.customer_id, int):
            raise ValidationError("Не выбран клиент")
        if self.customer_id <= 0:
            raise ValidationError("Не выбран клиент")
        if self.id is not None and self.id <= 0:
            raise ValidationError("id заказа должен быть положительным")
        self.order_date = (self.order_date or "").strip()
        try:
            datetime.strptime(self.order_date, "%Y-%m-%d")
        except ValueError as exc:
            raise ValidationError("Дата заказа должна быть в формате ГГГГ-ММ-ДД") from exc
        self.status = (self.status or "").strip()
        if self.status not in STATUSES:
            raise ValidationError(
                "Статус должен быть одним из: {0}".format(", ".join(STATUSES))
            )
        if not self.items:
            raise ValidationError("В заказе нет товаров")
        for item in self.items:
            item.validate()
        expected = self.calculated_total()
        if self.total is None:
            self.total = expected
        elif abs(float(self.total) - expected) > 0.01:
            raise ValidationError("Итоговая сумма не совпадает со списком товаров")
        else:
            self.total = expected


def normalize_period(period: str) -> str:
    key = (period or "").strip().lower()
    if key not in PERIODS:
        raise ValidationError("Период должен быть day, week или month")
    return PERIODS[key]


def period_bounds(period: str, today: Optional[date] = None) -> tuple:
    """Границы периода: день, текущая неделя (пн–вс) или текущий месяц."""
    kind = normalize_period(period)
    current = today or date.today()
    if kind == "day":
        return current.isoformat(), current.isoformat()
    if kind == "week":
        start = current - timedelta(days=current.weekday())
        end = start + timedelta(days=6)
        return start.isoformat(), end.isoformat()
    start = current.replace(day=1)
    if current.month == 12:
        next_month = date(current.year + 1, 1, 1)
    else:
        next_month = date(current.year, current.month + 1, 1)
    end = next_month - timedelta(days=1)
    return start.isoformat(), end.isoformat()


def parse_customer(data: Dict) -> Customer:
    if not isinstance(data, dict):
        raise ValidationError("Клиент должен быть объектом")
    for key in ("id", "name", "phone", "address"):
        if key not in data or data[key] is None:
            raise ValidationError("У клиента нет поля {0}".format(key))
    customer = Customer(
        id=_as_int(data["id"], "id"),
        name=str(data["name"]),
        phone=str(data["phone"]),
        address=str(data["address"]),
    )
    customer.validate()
    return customer


def parse_order(data: Dict) -> Order:
    if not isinstance(data, dict):
        raise ValidationError("Заказ должен быть объектом")
    for key in ("id", "customer_id", "order_date", "status", "total", "items"):
        if key not in data or data[key] is None:
            raise ValidationError("У заказа нет поля {0}".format(key))
    if not isinstance(data["items"], list):
        raise ValidationError("Список товаров должен быть массивом")
    items = []
    for index, raw_item in enumerate(data["items"], start=1):
        if not isinstance(raw_item, dict):
            raise ValidationError("Товар №{0} должен быть объектом".format(index))
        for key in ("product_name", "quantity", "price"):
            if key not in raw_item or raw_item[key] is None:
                raise ValidationError("У товара №{0} нет поля {1}".format(index, key))
        items.append(
            OrderItem(
                product_name=str(raw_item["product_name"]),
                quantity=_as_int(raw_item["quantity"], "quantity"),
                price=_as_float(raw_item["price"], "price"),
            )
        )
    order = Order(
        id=_as_int(data["id"], "id"),
        customer_id=_as_int(data["customer_id"], "customer_id"),
        order_date=str(data["order_date"]),
        status=str(data["status"]),
        items=items,
        total=_as_float(data["total"], "total"),
    )
    order.validate()
    return order
