"""Окно учёта заказов на Tkinter."""

from __future__ import annotations

import tkinter as tk
from datetime import date
from tkinter import filedialog, messagebox, ttk

from data_export import export_to_file, import_from_file
from database import DATA_DIR, Database, build_report
from logger_config import get_logger
from models import STATUSES, Customer, CustomerHasOrdersError, Order, OrderItem, ValidationError


logger = get_logger()


class DeliveryApp(tk.Tk):
    def __init__(self, backend: str = "sqlite", db: Database = None) -> None:
        super().__init__()
        self.title("Быстрая доставка — учёт заказов")
        self.geometry("980x560")
        self.minsize(860, 480)
        self.db = db if db is not None else Database(backend, seed=True)
        self.data_paths = {
            "sqlite": DATA_DIR / "delivery.db",
            "tinydb": DATA_DIR / "tinydb.json",
        }
        if db is not None:
            self.data_paths[self.db.backend] = self.db.path
        self._customers_window = None
        self._build()
        self.reload_orders()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        logger.info("Открыто окно, база %s", self.db.backend)

    def _build(self) -> None:
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="База:").pack(side="left")
        self.backend_var = tk.StringVar(value=self.db.backend)
        ttk.Combobox(
            top,
            textvariable=self.backend_var,
            values=("sqlite", "tinydb"),
            state="readonly",
            width=12,
        ).pack(side="left", padx=(4, 8))
        ttk.Button(top, text="Сменить базу", command=self.change_backend).pack(side="left")
        ttk.Button(top, text="Клиенты", command=self.open_customers).pack(side="left", padx=8)
        self.path_label = ttk.Label(top, text=str(self.db.path))
        self.path_label.pack(side="left", padx=8)

        filters = ttk.Frame(self, padding=(8, 0, 8, 8))
        filters.pack(fill="x")
        ttk.Label(filters, text="Статус:").pack(side="left")
        self.status_var = tk.StringVar(value="Все")
        ttk.Combobox(
            filters,
            textvariable=self.status_var,
            values=("Все",) + STATUSES,
            state="readonly",
            width=16,
        ).pack(side="left", padx=(4, 12))
        ttk.Label(filters, text="Дата (ГГГГ-ММ-ДД):").pack(side="left")
        self.date_var = tk.StringVar()
        ttk.Entry(filters, textvariable=self.date_var, width=14).pack(side="left", padx=(4, 8))
        ttk.Button(filters, text="Применить", command=self.apply_filter).pack(side="left")
        ttk.Button(filters, text="Сбросить", command=self.reset_filter).pack(side="left", padx=4)

        table = ttk.Frame(self, padding=(8, 0, 8, 0))
        table.pack(fill="both", expand=True)
        columns = ("id", "date", "customer", "status", "total")
        self.tree = ttk.Treeview(table, columns=columns, show="headings", height=14)
        headings = {
            "id": ("ID", 50),
            "date": ("Дата", 110),
            "customer": ("Клиент", 240),
            "status": ("Статус", 130),
            "total": ("Сумма", 100),
        }
        for name, (title, width) in headings.items():
            self.tree.heading(name, text=title)
            anchor = "e" if name == "total" else "w"
            self.tree.column(name, width=width, anchor=anchor)
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda _event: self.edit_order())

        buttons = ttk.Frame(self, padding=8)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Добавить", command=self.add_order).pack(side="left")
        ttk.Button(buttons, text="Редактировать", command=self.edit_order).pack(side="left", padx=4)
        ttk.Button(buttons, text="Удалить", command=self.delete_order).pack(side="left")
        ttk.Button(buttons, text="Показать отчёт", command=self.show_report).pack(side="left", padx=12)
        ttk.Label(buttons, text="Формат:").pack(side="left")
        self.format_var = tk.StringVar(value="JSON")
        ttk.Combobox(
            buttons,
            textvariable=self.format_var,
            values=("JSON", "XML"),
            state="readonly",
            width=8,
        ).pack(side="left", padx=4)
        ttk.Button(buttons, text="Экспорт", command=self.export_orders).pack(side="left")
        ttk.Button(buttons, text="Импорт", command=self.import_orders).pack(side="left", padx=4)

        self.count_label = ttk.Label(self, padding=(8, 0, 8, 8))
        self.count_label.pack(fill="x")

    def change_backend(self) -> None:
        backend = self.backend_var.get()
        if backend != self.db.backend:
            if self._customers_window is not None and self._customers_window.winfo_exists():
                self._customers_window.destroy()
            self.db.close()
            self.db = Database(backend, self.data_paths[backend], seed=True)
            logger.info("Выбрана база %s: %s", backend, self.db.path)
        self.path_label.configure(text=str(self.db.path))
        self.reload_orders()

    def reload_orders(self) -> None:
        self._fill_orders(self.db.list_orders())

    def apply_filter(self) -> None:
        status = self.status_var.get()
        if status == "Все":
            status = None
        date_text = self.date_var.get().strip()
        on_date = None
        if date_text:
            try:
                date.fromisoformat(date_text)
            except ValueError:
                messagebox.showerror("Фильтр", "Дата должна быть в формате ГГГГ-ММ-ДД", parent=self)
                return
            on_date = date_text
        self._fill_orders(self.db.filter_orders(status=status, on_date=on_date))

    def reset_filter(self) -> None:
        self.status_var.set("Все")
        self.date_var.set("")
        self.reload_orders()

    def _fill_orders(self, orders) -> None:
        self.tree.delete(*self.tree.get_children())
        names = {customer.id: customer.name for customer in self.db.list_customers()}
        for order in orders:
            self.tree.insert(
                "",
                "end",
                iid=str(order.id),
                values=(
                    order.id,
                    order.order_date,
                    names.get(order.customer_id, ""),
                    order.status,
                    "{0:.2f}".format(order.total),
                ),
            )
        self.count_label.configure(text="Заказов в списке: {0}".format(len(orders)))

    def selected_order_id(self):
        selected = self.tree.selection()
        if not selected:
            return None
        return int(selected[0])

    def add_order(self):
        if not self.db.list_customers():
            messagebox.showerror("Заказ", "Сначала добавьте клиента", parent=self)
            return None
        return OrderDialog(self, self.db, on_saved=self.reload_orders)

    def edit_order(self):
        order_id = self.selected_order_id()
        if order_id is None:
            messagebox.showerror("Заказ", "Выберите заказ в списке", parent=self)
            return None
        return OrderDialog(self, self.db, self.db.get_order(order_id), on_saved=self.reload_orders)

    def delete_order(self) -> None:
        order_id = self.selected_order_id()
        if order_id is None:
            messagebox.showerror("Заказ", "Выберите заказ в списке", parent=self)
            return
        if not messagebox.askyesno("Удаление", "Удалить выбранный заказ?", parent=self):
            return
        self.db.delete_order(order_id)
        self.reload_orders()

    def show_report(self):
        return ReportWindow(self, self.db)

    def export_orders(self) -> None:
        extension = ".json" if self.format_var.get() == "JSON" else ".xml"
        path = filedialog.asksaveasfilename(
            parent=self,
            defaultextension=extension,
            initialfile="orders_backup{0}".format(extension),
            filetypes=[("JSON", "*.json"), ("XML", "*.xml")],
        )
        if not path:
            return
        try:
            export_to_file(self.db.list_customers(), self.db.list_orders(), path)
        except (ValidationError, OSError) as exc:
            messagebox.showerror("Экспорт", str(exc), parent=self)
            return
        messagebox.showinfo("Экспорт", "Заказы сохранены в {0}".format(path), parent=self)

    def import_orders(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            filetypes=[("JSON и XML", "*.json *.xml"), ("JSON", "*.json"), ("XML", "*.xml")],
        )
        if not path:
            return
        try:
            customers, orders = import_from_file(path)
            count = self.db.import_data(customers, orders)
        except (ValidationError, OSError) as exc:
            messagebox.showerror("Импорт", str(exc), parent=self)
            return
        self.reload_orders()
        messagebox.showinfo("Импорт", "Импортировано заказов: {0}".format(count), parent=self)

    def open_customers(self):
        if self._customers_window is not None and self._customers_window.winfo_exists():
            self._customers_window.lift()
            return self._customers_window
        self._customers_window = CustomersWindow(self, self.db)
        return self._customers_window

    def _on_close(self) -> None:
        try:
            self.db.close()
        finally:
            self.destroy()


class CustomersWindow(tk.Toplevel):
    def __init__(self, master: DeliveryApp, db: Database) -> None:
        super().__init__(master)
        self.db = db
        self.title("Клиенты")
        self.geometry("720x420")
        self.transient(master)
        columns = ("id", "name", "phone", "address")
        self.tree = ttk.Treeview(self, columns=columns, show="headings", height=12)
        for name, title, width in (
            ("id", "ID", 50),
            ("name", "Имя", 200),
            ("phone", "Телефон", 150),
            ("address", "Адрес", 260),
        ):
            self.tree.heading(name, text=title)
            self.tree.column(name, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=8, pady=8)
        buttons = ttk.Frame(self, padding=8)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="Добавить", command=self.add_customer).pack(side="left")
        ttk.Button(buttons, text="Редактировать", command=self.edit_customer).pack(side="left", padx=4)
        ttk.Button(buttons, text="Удалить", command=self.delete_customer).pack(side="left")
        self.reload()

    def reload(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for customer in self.db.list_customers():
            self.tree.insert(
                "",
                "end",
                iid=str(customer.id),
                values=(customer.id, customer.name, customer.phone, customer.address),
            )
        if hasattr(self.master, "reload_orders"):
            self.master.reload_orders()

    def selected_customer_id(self):
        selected = self.tree.selection()
        if not selected:
            return None
        return int(selected[0])

    def add_customer(self):
        return CustomerDialog(self, self.db, on_saved=self.reload)

    def edit_customer(self):
        customer_id = self.selected_customer_id()
        if customer_id is None:
            messagebox.showerror("Клиент", "Выберите клиента", parent=self)
            return None
        return CustomerDialog(self, self.db, self.db.get_customer(customer_id), on_saved=self.reload)

    def delete_customer(self) -> None:
        customer_id = self.selected_customer_id()
        if customer_id is None:
            messagebox.showerror("Клиент", "Выберите клиента", parent=self)
            return
        if not messagebox.askyesno("Удаление", "Удалить выбранного клиента?", parent=self):
            return
        try:
            self.db.delete_customer(customer_id)
        except CustomerHasOrdersError as exc:
            messagebox.showerror("Клиент", str(exc), parent=self)
            return
        self.reload()


class CustomerDialog(tk.Toplevel):
    def __init__(self, master, db: Database, customer: Customer = None, on_saved=None) -> None:
        super().__init__(master)
        self.db = db
        self.customer = customer
        self.on_saved = on_saved
        self.title("Редактирование клиента" if customer else "Новый клиент")
        self.resizable(False, False)
        self.transient(master)
        self.name_var = tk.StringVar(value=customer.name if customer else "")
        self.phone_var = tk.StringVar(value=customer.phone if customer else "")
        self.address_var = tk.StringVar(value=customer.address if customer else "")
        form = ttk.Frame(self, padding=12)
        form.pack(fill="both", expand=True)
        self._row(form, 0, "Имя", self.name_var)
        self._row(form, 1, "Телефон", self.phone_var)
        self._row(form, 2, "Адрес", self.address_var)
        buttons = ttk.Frame(form)
        buttons.grid(row=3, column=0, columnspan=2, pady=(12, 0))
        ttk.Button(buttons, text="Сохранить", command=self.save).pack(side="left")
        ttk.Button(buttons, text="Отмена", command=self.destroy).pack(side="left", padx=4)

    def _row(self, form, row: int, label: str, variable: tk.StringVar) -> None:
        ttk.Label(form, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(form, textvariable=variable, width=40).grid(row=row, column=1, pady=4)

    def save(self) -> bool:
        try:
            customer = Customer(
                self.customer.id if self.customer else None,
                self.name_var.get(),
                self.phone_var.get(),
                self.address_var.get(),
            )
            if self.customer:
                self.db.update_customer(customer)
            else:
                self.db.add_customer(customer)
        except ValidationError as exc:
            messagebox.showerror("Клиент", str(exc), parent=self)
            return False
        if self.on_saved:
            self.on_saved()
        self.destroy()
        return True


class OrderDialog(tk.Toplevel):
    def __init__(self, master, db: Database, order: Order = None, on_saved=None) -> None:
        super().__init__(master)
        self.db = db
        self.order = order
        self.on_saved = on_saved
        self.items = list(order.items) if order else []
        self.title("Редактирование заказа" if order else "Новый заказ")
        self.geometry("560x460")
        self.transient(master)

        self.customers = self.db.list_customers()
        labels = ["{0}: {1}".format(customer.id, customer.name) for customer in self.customers]
        self.date_var = tk.StringVar(value=order.order_date if order else date.today().isoformat())
        self.customer_var = tk.StringVar()
        self.status_var = tk.StringVar(value=order.status if order else "новый")
        self.product_var = tk.StringVar()
        self.qty_var = tk.StringVar(value="1")
        self.price_var = tk.StringVar()
        self.total_var = tk.StringVar(value="0.00")

        form = ttk.Frame(self, padding=12)
        form.pack(fill="both", expand=True)
        ttk.Label(form, text="Дата").grid(row=0, column=0, sticky="w", pady=3)
        ttk.Entry(form, textvariable=self.date_var, width=20).grid(row=0, column=1, sticky="w")
        ttk.Label(form, text="Клиент").grid(row=1, column=0, sticky="w", pady=3)
        self.customer_combo = ttk.Combobox(
            form, textvariable=self.customer_var, values=labels, state="readonly", width=36
        )
        self.customer_combo.grid(row=1, column=1, columnspan=3, sticky="w")
        if order:
            for label in labels:
                if label.startswith("{0}:".format(order.customer_id)):
                    self.customer_var.set(label)
                    break
        elif labels:
            self.customer_var.set(labels[0])
        ttk.Label(form, text="Статус").grid(row=2, column=0, sticky="w", pady=3)
        ttk.Combobox(
            form, textvariable=self.status_var, values=STATUSES, state="readonly", width=18
        ).grid(row=2, column=1, sticky="w")

        ttk.Label(form, text="Товар").grid(row=3, column=0, sticky="w", pady=(10, 3))
        ttk.Entry(form, textvariable=self.product_var, width=22).grid(row=3, column=1, sticky="w")
        ttk.Label(form, text="Кол-во").grid(row=4, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.qty_var, width=8).grid(row=4, column=1, sticky="w")
        ttk.Label(form, text="Цена").grid(row=5, column=0, sticky="w")
        ttk.Entry(form, textvariable=self.price_var, width=10).grid(row=5, column=1, sticky="w")
        ttk.Button(form, text="Добавить товар", command=self.add_item).grid(row=5, column=2, padx=6)
        ttk.Button(form, text="Удалить товар", command=self.remove_item).grid(row=5, column=3)

        self.items_tree = ttk.Treeview(
            form,
            columns=("name", "qty", "price", "sum"),
            show="headings",
            height=6,
        )
        for name, title, width in (
            ("name", "Товар", 180),
            ("qty", "Кол-во", 70),
            ("price", "Цена", 80),
            ("sum", "Сумма", 80),
        ):
            self.items_tree.heading(name, text=title)
            self.items_tree.column(name, width=width)
        self.items_tree.grid(row=6, column=0, columnspan=4, pady=8, sticky="nsew")
        ttk.Label(form, text="Итого").grid(row=7, column=0, sticky="w")
        ttk.Label(form, textvariable=self.total_var).grid(row=7, column=1, sticky="w")
        buttons = ttk.Frame(form)
        buttons.grid(row=8, column=0, columnspan=4, pady=(8, 0), sticky="w")
        ttk.Button(buttons, text="Сохранить", command=self.save).pack(side="left")
        ttk.Button(buttons, text="Отмена", command=self.destroy).pack(side="left", padx=4)
        form.columnconfigure(1, weight=1)
        self._refresh_items()

    def add_item(self) -> None:
        try:
            quantity = int(self.qty_var.get().strip())
            price = float(self.price_var.get().strip().replace(",", "."))
            item = OrderItem(self.product_var.get(), quantity, price)
            item.validate()
        except ValueError:
            messagebox.showerror(
                "Товар",
                "Количество должно быть целым числом, цена — числом",
                parent=self,
            )
            return
        except ValidationError as exc:
            messagebox.showerror("Товар", str(exc), parent=self)
            return
        self.items.append(item)
        self.product_var.set("")
        self.qty_var.set("1")
        self.price_var.set("")
        self._refresh_items()

    def remove_item(self) -> None:
        selected = self.items_tree.selection()
        if not selected:
            return
        del self.items[int(selected[0])]
        self._refresh_items()

    def _refresh_items(self) -> None:
        self.items_tree.delete(*self.items_tree.get_children())
        for index, item in enumerate(self.items):
            self.items_tree.insert(
                "",
                "end",
                iid=str(index),
                values=(
                    item.product_name,
                    item.quantity,
                    "{0:.2f}".format(item.price),
                    "{0:.2f}".format(item.line_total),
                ),
            )
        total = round(sum(item.line_total for item in self.items), 2)
        self.total_var.set("{0:.2f}".format(total))

    def save(self) -> bool:
        label = self.customer_var.get()
        try:
            if ":" not in label:
                raise ValidationError("Выберите клиента")
            customer_id = int(label.split(":", 1)[0])
            order = Order(
                id=self.order.id if self.order else None,
                customer_id=customer_id,
                order_date=self.date_var.get(),
                status=self.status_var.get(),
                items=list(self.items),
            )
            if self.order:
                self.db.update_order(order)
            else:
                self.db.add_order(order)
        except (ValidationError, ValueError) as exc:
            messagebox.showerror("Заказ", str(exc), parent=self)
            return False
        if self.on_saved:
            self.on_saved()
        self.destroy()
        return True


class ReportWindow(tk.Toplevel):
    def __init__(self, master: DeliveryApp, db: Database) -> None:
        super().__init__(master)
        self.db = db
        self.title("Отчёт")
        self.geometry("640x460")
        self.transient(master)
        self.period_labels = {"день": "day", "неделя": "week", "месяц": "month"}
        top = ttk.Frame(self, padding=8)
        top.pack(fill="x")
        ttk.Label(top, text="Период:").pack(side="left")
        self.period_var = tk.StringVar(value="месяц")
        ttk.Combobox(
            top,
            textvariable=self.period_var,
            values=tuple(self.period_labels),
            state="readonly",
            width=12,
        ).pack(side="left", padx=4)
        ttk.Button(top, text="Сформировать", command=self.generate).pack(side="left")

        frame = ttk.Frame(self, padding=8)
        frame.pack(fill="both", expand=True)
        self.text = tk.Text(frame, wrap="word", font="TkFixedFont")
        scroll = ttk.Scrollbar(frame, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.generate()

    def generate(self) -> None:
        try:
            report = build_report(self.db, self.period_labels[self.period_var.get()])
        except (ValidationError, KeyError) as exc:
            messagebox.showerror("Отчёт", str(exc), parent=self)
            return
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.insert("1.0", report)
        self.text.configure(state="disabled")


def main() -> None:
    app = DeliveryApp()
    app.mainloop()


if __name__ == "__main__":
    main()
