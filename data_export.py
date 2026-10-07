"""Экспорт и импорт заказов в XML и JSON."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Tuple

from logger_config import get_logger
from models import Customer, Order, ValidationError, parse_customer, parse_order


logger = get_logger()


def export_to_file(customers: List[Customer], orders: List[Order], path: str) -> None:
    """Сохраняет всех клиентов и заказы. Формат берётся из расширения файла."""
    target = Path(path)
    suffix = target.suffix.lower()
    if suffix not in (".xml", ".json"):
        raise ValidationError("Формат определяется расширением файла: .xml или .json")
    if not target.parent.exists():
        raise ValidationError("Папка не найдена: {0}".format(target.parent))

    if suffix == ".json":
        _write_json(customers, orders, target)
    else:
        _write_xml(customers, orders, target)
    logger.info("Экспорт %s заказов в %s", len(orders), target)


def import_from_file(path: str) -> Tuple[List[Customer], List[Order]]:
    """Читает файл и проверяет корректность. В базу сам ничего не записывает."""
    source = Path(path)
    if not source.is_file():
        raise ValidationError("Файл не найден: {0}".format(source))
    suffix = source.suffix.lower()
    if suffix == ".json":
        raw = _read_json(source)
    elif suffix == ".xml":
        raw = _read_xml(source)
    else:
        raise ValidationError("Формат определяется расширением файла: .xml или .json")

    customers = _parse_section(raw.get("customers", []), parse_customer, "Клиент")
    orders = _parse_section(raw.get("orders", []), parse_order, "Заказ")
    logger.info("Прочитан файл %s: клиентов %s, заказов %s", source, len(customers), len(orders))
    return customers, orders


def _parse_section(rows: object, parser, title: str) -> list:
    if not isinstance(rows, list):
        raise ValidationError("Поле со списком записей имеет неверный тип")
    result = []
    for index, row in enumerate(rows, start=1):
        try:
            result.append(parser(row))
        except ValidationError as exc:
            raise ValidationError("{0} №{1}: {2}".format(title, index, exc)) from exc
    return result


def _write_json(customers: List[Customer], orders: List[Order], path: Path) -> None:
    payload = {
        "customers": [_customer_dict(customer) for customer in customers],
        "orders": [_order_dict(order) for order in orders],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path) -> Dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationError("Некорректный JSON: {0}".format(exc)) from exc
    return _require_document(raw)


def _write_xml(customers: List[Customer], orders: List[Order], path: Path) -> None:
    root = ET.Element("delivery")
    customers_node = ET.SubElement(root, "customers")
    for customer in customers:
        node = ET.SubElement(customers_node, "customer", id=str(customer.id))
        ET.SubElement(node, "name").text = customer.name
        ET.SubElement(node, "phone").text = customer.phone
        ET.SubElement(node, "address").text = customer.address

    orders_node = ET.SubElement(root, "orders")
    for order in orders:
        node = ET.SubElement(orders_node, "order", id=str(order.id))
        ET.SubElement(node, "customer_id").text = str(order.customer_id)
        ET.SubElement(node, "order_date").text = order.order_date
        ET.SubElement(node, "status").text = order.status
        ET.SubElement(node, "total").text = "{0:.2f}".format(order.total)
        items_node = ET.SubElement(node, "items")
        for item in order.items:
            item_node = ET.SubElement(items_node, "item")
            ET.SubElement(item_node, "product_name").text = item.product_name
            ET.SubElement(item_node, "quantity").text = str(item.quantity)
            ET.SubElement(item_node, "price").text = "{0:.2f}".format(item.price)

    _indent(root)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)


def _read_xml(path: Path) -> Dict:
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        raise ValidationError("Некорректный XML: {0}".format(exc)) from exc
    if root.tag != "delivery":
        raise ValidationError("Корневой элемент XML должен быть delivery")

    customers = []
    customers_node = root.find("customers")
    if customers_node is not None:
        for node in customers_node.findall("customer"):
            customers.append(
                {
                    "id": node.get("id"),
                    "name": _xml_text(node, "name"),
                    "phone": _xml_text(node, "phone"),
                    "address": _xml_text(node, "address"),
                }
            )

    orders_node = root.find("orders")
    if orders_node is None:
        raise ValidationError("В XML нет списка orders")
    orders = []
    for node in orders_node.findall("order"):
        items = []
        items_node = node.find("items")
        if items_node is not None:
            for item_node in items_node.findall("item"):
                items.append(
                    {
                        "product_name": _xml_text(item_node, "product_name"),
                        "quantity": _xml_text(item_node, "quantity"),
                        "price": _xml_text(item_node, "price"),
                    }
                )
        orders.append(
            {
                "id": node.get("id"),
                "customer_id": _xml_text(node, "customer_id"),
                "order_date": _xml_text(node, "order_date"),
                "status": _xml_text(node, "status"),
                "total": _xml_text(node, "total"),
                "items": items,
            }
        )
    return {"customers": customers, "orders": orders}


def _require_document(raw: object) -> Dict:
    if not isinstance(raw, dict):
        raise ValidationError("Файл должен содержать объект с полями customers и orders")
    if "orders" not in raw:
        raise ValidationError("В файле нет списка orders")
    if not isinstance(raw["orders"], list):
        raise ValidationError("Поле orders должно быть списком")
    customers = raw.get("customers", [])
    if not isinstance(customers, list):
        raise ValidationError("Поле customers должно быть списком")
    return {"customers": customers, "orders": raw["orders"]}


def _xml_text(node: ET.Element, tag: str):
    child = node.find(tag)
    if child is None or child.text is None:
        return None
    return child.text.strip()


def _indent(element: ET.Element, level: int = 0) -> None:
    pad = "\n" + "  " * level
    if len(element):
        if not element.text or not element.text.strip():
            element.text = pad + "  "
        for child in element:
            _indent(child, level + 1)
        if not child.tail or not child.tail.strip():
            child.tail = pad
    if level and (not element.tail or not element.tail.strip()):
        element.tail = pad


def _customer_dict(customer: Customer) -> Dict:
    return {
        "id": customer.id,
        "name": customer.name,
        "phone": customer.phone,
        "address": customer.address,
    }


def _order_dict(order: Order) -> Dict:
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
