from models import Customer, Order, OrderItem


def add_sample(database):
    ivan = database.add_customer(Customer(None, "Иван Петров", "+7900", "ул. Ленина, 1"))
    maria = database.add_customer(Customer(None, "Мария Сидорова", "+7901", "пр. Мира, 10"))
    database.add_order(Order(ivan.id, "2026-10-07", "выполнен", [OrderItem("Пицца", 2, 100)]))
    database.add_order(Order(ivan.id, "2026-10-07", "отменён", [OrderItem("Суп", 1, 50)]))
    database.add_order(Order(maria.id, "2026-10-01", "новый", [OrderItem("Чай", 1, 80)]))
    database.add_order(Order(maria.id, "2026-09-01", "выполнен", [OrderItem("Кофе", 1, 70)]))
    return ivan, maria
