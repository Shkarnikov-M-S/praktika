"""Работа с базой SQLite и TinyDB.

Обе базы дают один и тот же набор операций. В TinyDB связи между
клиентом и заказами проверяются в коде, без внешних ключей СУБД.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional

from tinydb import Query, TinyDB

from logger_config import get_logger
from models import (
    STATUSES,
    PERIOD_TITLES,
    Customer,
    CustomerHasOrdersError,
    NotFoundError,
    Order,
    OrderItem,
    ValidationError,
    normalize_period,
    period_bounds,
)


logger = get_logger()

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT,
    address TEXT
);

CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER REFERENCES customers(id) ON DELETE RESTRICT,
    order_date TEXT NOT NULL,
    status TEXT CHECK(status IN ('новый', 'в доставке', 'выполнен', 'отменён')),
    total REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS order_items (
    id INTEGER PRIMARY KEY,
    order_id INTEGER REFERENCES orders(id),
    product_name TEXT,
    quantity INTEGER,
    price REAL
);
"""


def default_path(backend: str) -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if backend == "sqlite":
        return DATA_DIR / "delivery.db"
    if backend == "tinydb":
        return DATA_DIR / "tinydb.json"
    raise ValueError("Поддерживаются только базы sqlite и tinydb")


class SQLiteStorage:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")

    def init_schema(self) -> None:
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def add_customer(self, customer: Customer) -> int:
        try:
            if customer.id is None:
                cursor = self.conn.execute(
                    "INSERT INTO customers (name, phone, address) VALUES (?, ?, ?)",
                    (customer.name, customer.phone, customer.address),
                )
                new_id = int(cursor.lastrowid)
            else:
                self.conn.execute(
                    "INSERT INTO customers (id, name, phone, address) VALUES (?, ?, ?, ?)",
                    (customer.id, customer.name, customer.phone, customer.address),
                )
                new_id = customer.id
            self.conn.commit()
            return new_id
        except sqlite3.IntegrityError as exc:
            self.conn.rollback()
            raise ValidationError("Не удалось сохранить клиента") from exc

    def update_customer(self, customer: Customer) -> None:
        cursor = self.conn.execute(
            "UPDATE customers SET name = ?, phone = ?, address = ? WHERE id = ?",
            (customer.name, customer.phone, customer.address, customer.id),
        )
        self.conn.commit()
        if cursor.rowcount == 0:
            raise NotFoundError("Клиент {0} не найден".format(customer.id))

    def delete_customer(self, customer_id: int) -> None:
        try:
            cursor = self.conn.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
            self.conn.commit()
        except sqlite3.IntegrityError as exc:
            self.conn.rollback()
            raise CustomerHasOrdersError(
                "Нельзя удалить клиента, у которого есть заказы"
            ) from exc
        if cursor.rowcount == 0:
            raise NotFoundError("Клиент {0} не найден".format(customer_id))

    def get_customer(self, customer_id: int) -> Customer:
        row = self.conn.execute(
            "SELECT id, name, phone, address FROM customers WHERE id = ?",
            (customer_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError("Клиент {0} не найден".format(customer_id))
        return self._customer(row)

    def list_customers(self) -> List[Customer]:
        rows = self.conn.execute(
            "SELECT id, name, phone, address FROM customers ORDER BY id"
        ).fetchall()
        return [self._customer(row) for row in rows]

    def customer_exists(self, customer_id: int) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM customers WHERE id = ?",
            (customer_id,),
        ).fetchone()
        return row is not None

    def count_orders_for_customer(self, customer_id: int) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS amount FROM orders WHERE customer_id = ?",
            (customer_id,),
        ).fetchone()
        return int(row["amount"])

    def add_order(self, order: Order) -> int:
        try:
            if order.id is None:
                cursor = self.conn.execute(
                    """
                    INSERT INTO orders (customer_id, order_date, status, total)
                    VALUES (?, ?, ?, ?)
                    """,
                    (order.customer_id, order.order_date, order.status, order.total),
                )
                new_id = int(cursor.lastrowid)
            else:
                self.conn.execute(
                    """
                    INSERT INTO orders (id, customer_id, order_date, status, total)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (order.id, order.customer_id, order.order_date, order.status, order.total),
                )
                new_id = order.id
            self._insert_items(new_id, order.items)
            self.conn.commit()
            return new_id
        except sqlite3.IntegrityError as exc:
            self.conn.rollback()
            raise ValidationError("Не удалось сохранить заказ") from exc

    def update_order(self, order: Order) -> None:
        try:
            cursor = self.conn.execute(
                """
                UPDATE orders
                SET customer_id = ?, order_date = ?, status = ?, total = ?
                WHERE id = ?
                """,
                (order.customer_id, order.order_date, order.status, order.total, order.id),
            )
            if cursor.rowcount == 0:
                self.conn.rollback()
                raise NotFoundError("Заказ {0} не найден".format(order.id))
            self.conn.execute("DELETE FROM order_items WHERE order_id = ?", (order.id,))
            self._insert_items(order.id, order.items)
            self.conn.commit()
        except sqlite3.IntegrityError as exc:
            self.conn.rollback()
            raise ValidationError("Не удалось сохранить заказ") from exc

    def delete_order(self, order_id: int) -> None:
        self.conn.execute("DELETE FROM order_items WHERE order_id = ?", (order_id,))
        cursor = self.conn.execute("DELETE FROM orders WHERE id = ?", (order_id,))
        self.conn.commit()
        if cursor.rowcount == 0:
            raise NotFoundError("Заказ {0} не найден".format(order_id))

    def order_exists(self, order_id: int) -> bool:
        row = self.conn.execute("SELECT 1 FROM orders WHERE id = ?", (order_id,)).fetchone()
        return row is not None

    def get_order(self, order_id: int) -> Order:
        row = self.conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        if row is None:
            raise NotFoundError("Заказ {0} не найден".format(order_id))
        return self._order(row)

    def filter_orders(
        self,
        status: Optional[str] = None,
        on_date: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[Order]:
        query = "SELECT * FROM orders WHERE 1 = 1"
        params = []
        if status:
            query += " AND status = ?"
            params.append(status)
        if on_date:
            query += " AND order_date = ?"
            params.append(on_date)
        if date_from:
            query += " AND order_date >= ?"
            params.append(date_from)
        if date_to:
            query += " AND order_date <= ?"
            params.append(date_to)
        query += " ORDER BY order_date DESC, id DESC"
        rows = self.conn.execute(query, params).fetchall()
        return [self._order(row) for row in rows]

    def _insert_items(self, order_id: int, items: List[OrderItem]) -> None:
        self.conn.executemany(
            """
            INSERT INTO order_items (order_id, product_name, quantity, price)
            VALUES (?, ?, ?, ?)
            """,
            [(order_id, item.product_name, item.quantity, item.price) for item in items],
        )

    def _customer(self, row: sqlite3.Row) -> Customer:
        return Customer(int(row["id"]), row["name"], row["phone"] or "", row["address"] or "")

    def _order(self, row: sqlite3.Row) -> Order:
        item_rows = self.conn.execute(
            """
            SELECT product_name, quantity, price
            FROM order_items
            WHERE order_id = ?
            ORDER BY id
            """,
            (row["id"],),
        ).fetchall()
        items = [
            OrderItem(item["product_name"], int(item["quantity"]), float(item["price"]))
            for item in item_rows
        ]
        return Order(
            id=int(row["id"]),
            customer_id=int(row["customer_id"]),
            order_date=row["order_date"],
            status=row["status"],
            items=items,
            total=float(row["total"]),
        )


class TinyDBStorage:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = TinyDB(self.path, ensure_ascii=False, indent=2)
        self.customers = self._db.table("customers")
        self.orders = self._db.table("orders")

    def init_schema(self) -> None:
        return None

    def close(self) -> None:
        self._db.close()

    def add_customer(self, customer: Customer) -> int:
        new_id = customer.id if customer.id is not None else self._next_id(self.customers)
        if self.customer_exists(new_id):
            raise ValidationError("Клиент с id={0} уже есть".format(new_id))
        self.customers.insert(
            {
                "id": new_id,
                "name": customer.name,
                "phone": customer.phone,
                "address": customer.address,
            }
        )
        return new_id

    def update_customer(self, customer: Customer) -> None:
        updated = self.customers.update(
            {
                "name": customer.name,
                "phone": customer.phone,
                "address": customer.address,
            },
            Query().id == customer.id,
        )
        if not updated:
            raise NotFoundError("Клиент {0} не найден".format(customer.id))

    def delete_customer(self, customer_id: int) -> None:
        removed = self.customers.remove(Query().id == customer_id)
        if not removed:
            raise NotFoundError("Клиент {0} не найден".format(customer_id))

    def get_customer(self, customer_id: int) -> Customer:
        doc = self.customers.get(Query().id == customer_id)
        if doc is None:
            raise NotFoundError("Клиент {0} не найден".format(customer_id))
        return self._customer(doc)

    def list_customers(self) -> List[Customer]:
        rows = [self._customer(doc) for doc in self.customers.all()]
        rows.sort(key=lambda customer: customer.id or 0)
        return rows

    def customer_exists(self, customer_id: int) -> bool:
        return self.customers.get(Query().id == customer_id) is not None

    def count_orders_for_customer(self, customer_id: int) -> int:
        return len(self.orders.search(Query().customer_id == customer_id))

    def add_order(self, order: Order) -> int:
        new_id = order.id if order.id is not None else self._next_id(self.orders)
        if self.order_exists(new_id):
            raise ValidationError("Заказ с id={0} уже есть".format(new_id))
        order.id = new_id
        self.orders.insert(self._order_doc(order))
        return new_id

    def update_order(self, order: Order) -> None:
        updated = self.orders.update(self._order_doc(order), Query().id == order.id)
        if not updated:
            raise NotFoundError("Заказ {0} не найден".format(order.id))

    def delete_order(self, order_id: int) -> None:
        removed = self.orders.remove(Query().id == order_id)
        if not removed:
            raise NotFoundError("Заказ {0} не найден".format(order_id))

    def order_exists(self, order_id: int) -> bool:
        return self.orders.get(Query().id == order_id) is not None

    def get_order(self, order_id: int) -> Order:
        doc = self.orders.get(Query().id == order_id)
        if doc is None:
            raise NotFoundError("Заказ {0} не найден".format(order_id))
        return self._order(doc)

    def filter_orders(
        self,
        status: Optional[str] = None,
        on_date: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[Order]:
        orders = [self._order(doc) for doc in self.orders.all()]
        if status:
            orders = [order for order in orders if order.status == status]
        if on_date:
            orders = [order for order in orders if order.order_date == on_date]
        if date_from:
            orders = [order for order in orders if order.order_date >= date_from]
        if date_to:
            orders = [order for order in orders if order.order_date <= date_to]
        orders.sort(key=lambda order: (order.order_date, order.id or 0), reverse=True)
        return orders

    def _next_id(self, table) -> int:
        ids = [int(doc["id"]) for doc in table.all() if "id" in doc]
        return max(ids, default=0) + 1

    def _customer(self, doc) -> Customer:
        return Customer(int(doc["id"]), doc["name"], doc.get("phone") or "", doc.get("address") or "")

    def _order(self, doc) -> Order:
        items = [
            OrderItem(item["product_name"], int(item["quantity"]), float(item["price"]))
            for item in doc.get("items", [])
        ]
        return Order(
            id=int(doc["id"]),
            customer_id=int(doc["customer_id"]),
            order_date=doc["order_date"],
            status=doc["status"],
            items=items,
            total=float(doc["total"]),
        )

    def _order_doc(self, order: Order) -> dict:
        return {
            "id": order.id,
            "customer_id": order.customer_id,
            "order_date": order.order_date,
            "status": order.status,
            "total": order.total,
            "items": [
                {
                    "product_name": item.product_name,
                    "quantity": item.quantity,
                    "price": item.price,
                }
                for item in order.items
            ],
        }


class Database:
    """Единая точка работы с заказами независимо от выбранной базы."""

    def __init__(self, backend: str = "sqlite", path=None, seed: bool = True) -> None:
        if backend not in ("sqlite", "tinydb"):
            raise ValueError("Поддерживаются только базы sqlite и tinydb")
        self.backend = backend
        self.path = Path(path) if path is not None else default_path(backend)
        if backend == "sqlite":
            self._impl = SQLiteStorage(self.path)
        else:
            self._impl = TinyDBStorage(self.path)
        self._impl.init_schema()
        self._closed = False
        if seed and not self.list_customers() and not self.list_orders():
            seed_demo(self)
            logger.info("Добавлены демонстрационные данные в %s", self.path)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._impl.close()

    def add_customer(self, customer: Customer) -> Customer:
        customer.validate()
        new_id = self._impl.add_customer(customer)
        logger.info("Добавлен клиент id=%s, имя=%s", new_id, customer.name)
        return self.get_customer(new_id)

    def update_customer(self, customer: Customer) -> Customer:
        if customer.id is None:
            raise ValidationError("Не указан клиент")
        customer.validate()
        self._impl.update_customer(customer)
        logger.info("Изменён клиент id=%s", customer.id)
        return self.get_customer(customer.id)

    def delete_customer(self, customer_id: int) -> None:
        if not self._impl.customer_exists(customer_id):
            raise NotFoundError("Клиент {0} не найден".format(customer_id))
        if self._impl.count_orders_for_customer(customer_id) > 0:
            raise CustomerHasOrdersError("Нельзя удалить клиента, у которого есть заказы")
        self._impl.delete_customer(customer_id)
        logger.info("Удалён клиент id=%s", customer_id)

    def get_customer(self, customer_id: int) -> Customer:
        return self._impl.get_customer(customer_id)

    def list_customers(self) -> List[Customer]:
        return self._impl.list_customers()

    def add_order(self, order: Order) -> Order:
        self._prepare_order(order)
        new_id = self._impl.add_order(order)
        logger.info("Добавлен заказ id=%s, клиент=%s, сумма=%s", new_id, order.customer_id, order.total)
        return self.get_order(new_id)

    def update_order(self, order: Order) -> Order:
        if order.id is None:
            raise ValidationError("Не указан заказ")
        self._prepare_order(order)
        if not self._impl.order_exists(order.id):
            raise NotFoundError("Заказ {0} не найден".format(order.id))
        self._impl.update_order(order)
        logger.info("Изменён заказ id=%s", order.id)
        return self.get_order(order.id)

    def delete_order(self, order_id: int) -> None:
        self._impl.delete_order(order_id)
        logger.info("Удалён заказ id=%s", order_id)

    def get_order(self, order_id: int) -> Order:
        return self._impl.get_order(order_id)

    def list_orders(self) -> List[Order]:
        return self.filter_orders()

    def filter_orders(
        self,
        status: Optional[str] = None,
        on_date: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> List[Order]:
        if status is not None and status not in STATUSES:
            raise ValidationError("Неизвестный статус фильтра")
        return self._impl.filter_orders(status, on_date, date_from, date_to)

    def import_data(self, customers: List[Customer], orders: List[Order]) -> int:
        """Записывает проверенные данные. Повторный импорт обновляет те же id."""
        customer_ids = set()
        for customer in customers:
            customer.validate()
            if customer.id is None:
                raise ValidationError("У клиента в файле нет id")
            if customer.id in customer_ids:
                raise ValidationError("Повторяющийся id клиента {0}".format(customer.id))
            customer_ids.add(customer.id)

        order_ids = set()
        for order in orders:
            order.validate()
            if order.id is None:
                raise ValidationError("У заказа в файле нет id")
            if order.id in order_ids:
                raise ValidationError("Повторяющийся id заказа {0}".format(order.id))
            order_ids.add(order.id)

        known_customers = {customer.id for customer in self.list_customers()} | customer_ids
        for order in orders:
            if order.customer_id not in known_customers:
                raise ValidationError(
                    "Заказ {0} ссылается на несуществующего клиента {1}".format(
                        order.id, order.customer_id
                    )
                )

        for customer in customers:
            if self._impl.customer_exists(customer.id):
                self._impl.update_customer(customer)
            else:
                self._impl.add_customer(customer)
        for order in orders:
            if self._impl.order_exists(order.id):
                self._impl.update_order(order)
            else:
                self._impl.add_order(order)
        logger.info("Импортировано заказов: %s", len(orders))
        return len(orders)

    def _prepare_order(self, order: Order) -> None:
        order.total = order.calculated_total()
        order.validate()
        if not self._impl.customer_exists(order.customer_id):
            raise ValidationError("Клиент не найден")


def seed_demo(db: Database) -> None:
    """Несколько клиентов и заказов, чтобы отчёт и фильтры были на что показать."""
    today = date.today()
    month_start = today.replace(day=1)
    week_start = today - timedelta(days=today.weekday())
    earlier = today - timedelta(days=40)

    ivan = db.add_customer(Customer(None, "Иван Петров", "+79001111111", "ул. Ленина, 1"))
    maria = db.add_customer(Customer(None, "Мария Сидорова", "+79002222222", "пр. Мира, 10"))
    alex = db.add_customer(Customer(None, "Алексей Кузнецов", "+79003333333", "ул. Гагарина, 5"))
    olga = db.add_customer(Customer(None, "Ольга Новикова", "+79004444444", "ул. Пушкина, 7"))

    samples = [
        (ivan.id, today, "выполнен", [OrderItem("Пицца", 2, 750)]),
        (maria.id, today, "новый", [OrderItem("Суши", 1, 900)]),
        (ivan.id, week_start, "в доставке", [OrderItem("Бургер", 3, 300)]),
        (alex.id, month_start, "выполнен", [OrderItem("Салат", 4, 250), OrderItem("Сок", 1, 120)]),
        (olga.id, earlier, "отменён", [OrderItem("Паста", 1, 500)]),
        (alex.id, today, "в доставке", [OrderItem("Суп", 2, 200)]),
    ]
    seen = set()
    for customer_id, when, status, items in samples:
        key = (
            customer_id,
            when.isoformat(),
            status,
            tuple((item.product_name, item.quantity, item.price) for item in items),
        )
        if key in seen:
            continue
        seen.add(key)
        db.add_order(Order(customer_id, when.isoformat(), status, items))


def build_report(db: Database, period: str, today: Optional[date] = None) -> str:
    """Текст отчёта: статусы, топ-3 клиента и выручка за день, неделю или месяц."""
    kind = normalize_period(period)
    start, end = period_bounds(kind, today)
    orders = db.filter_orders(date_from=start, date_to=end)
    counts = {status: 0 for status in STATUSES}
    money = {}
    revenue = 0.0
    for order in orders:
        counts[order.status] += 1
        if order.status == "отменён":
            continue
        revenue += order.total
        money[order.customer_id] = money.get(order.customer_id, 0.0) + order.total
    revenue = round(revenue, 2)

    customers = {customer.id: customer for customer in db.list_customers()}
    ranking = sorted(
        money.items(),
        key=lambda pair: (-pair[1], customers.get(pair[0]).name if pair[0] in customers else ""),
    )[:3]

    lines = [
        "Отчёт за период: {0} ({1} — {2})".format(PERIOD_TITLES[kind], start, end),
        "Отменённые заказы в выручку и топ не входят.",
        "",
        "Количество заказов по статусам:",
    ]
    for status in STATUSES:
        lines.append("  {0}: {1}".format(status, counts[status]))
    lines.append("Всего: {0}".format(len(orders)))
    lines.append("")
    lines.append("Общая выручка: {0:.2f}".format(revenue))
    lines.append("")
    lines.append("Топ-3 клиента по сумме заказов:")
    if not ranking:
        lines.append("  нет данных")
    for index, (customer_id, total) in enumerate(ranking, start=1):
        customer = customers.get(customer_id)
        name = customer.name if customer else "Клиент {0}".format(customer_id)
        lines.append("  {0}. {1} — {2:.2f}".format(index, name, round(total, 2)))
    logger.info("Сформирован отчёт за %s", kind)
    return "\n".join(lines)
