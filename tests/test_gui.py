from datetime import date

import pytest

from database import Database


def test_gui_orders_customers_report_and_files(tmp_path, monkeypatch):
    pytest.importorskip("tkinter")
    import main_gui

    errors = []
    monkeypatch.setattr(main_gui.messagebox, "showerror", lambda *args, **kwargs: errors.append(args))
    monkeypatch.setattr(main_gui.messagebox, "showinfo", lambda *args, **kwargs: None)
    monkeypatch.setattr(main_gui.messagebox, "askyesno", lambda *args, **kwargs: True)

    database = Database("sqlite", tmp_path / "gui.db", seed=True)
    app = main_gui.DeliveryApp(db=database)
    app.withdraw()
    try:
        assert len(app.tree.get_children()) >= 4
        app.tree.selection_remove(app.tree.selection())
        app.edit_order()
        app.delete_order()
        assert errors

        all_rows = app.tree.get_children()
        app.status_var.set("выполнен")
        app.apply_filter()
        assert 0 < len(app.tree.get_children()) < len(all_rows)
        app.status_var.set("Все")
        app.date_var.set(date.today().isoformat())
        app.apply_filter()
        assert len(app.tree.get_children()) >= 1
        app.date_var.set("вчера")
        app.apply_filter()
        assert errors
        app.reset_filter()
        assert app.status_var.get() == "Все"
        assert len(app.tree.get_children()) == len(all_rows)

        customers = app.open_customers()
        assert app.open_customers() is customers
        dialog = customers.add_customer()
        dialog.name_var.set("   ")
        assert dialog.save() is False
        dialog.name_var.set("Тестовый Клиент")
        dialog.phone_var.set("+7000")
        dialog.address_var.set("ул. Тестовая, 1")
        assert dialog.save()

        created = None
        for item_id in customers.tree.get_children():
            if customers.tree.item(item_id, "values")[1] == "Тестовый Клиент":
                created = item_id
        customers.tree.selection_set(created)
        customers.delete_customer()
        names = [customers.tree.item(item_id, "values")[1] for item_id in customers.tree.get_children()]
        assert "Тестовый Клиент" not in names

        busy = customers.tree.get_children()[0]
        customers.tree.selection_set(busy)
        editor = customers.edit_customer()
        editor.phone_var.set("+7999")
        assert editor.save()
        customers.tree.selection_set(customers.tree.get_children()[0])
        customers.delete_customer()
        assert any("Нельзя удалить" in str(item) for item in errors)

        order_dialog = app.add_order()
        assert order_dialog.save() is False
        order_dialog.product_var.set("Чай")
        order_dialog.qty_var.set("2")
        order_dialog.price_var.set("50")
        order_dialog.add_item()
        assert order_dialog.total_var.get() == "100.00"
        order_dialog.items_tree.selection_set("0")
        order_dialog.remove_item()
        assert order_dialog.total_var.get() == "0.00"
        order_dialog.remove_item()
        order_dialog.product_var.set("")
        order_dialog.add_item()
        order_dialog.product_var.set("Чай")
        order_dialog.qty_var.set("2")
        order_dialog.price_var.set("50")
        order_dialog.add_item()
        assert order_dialog.save()

        app.tree.selection_set(app.tree.get_children()[0])
        editor = app.edit_order()
        editor.status_var.set("отменён")
        assert editor.save()

        before = len(app.db.list_orders())
        app.tree.selection_set(app.tree.get_children()[0])
        app.delete_order()
        assert len(app.db.list_orders()) == before - 1

        report = app.show_report()
        assert "Топ-3" in report.text.get("1.0", "end")
        report.period_var.set("день")
        report.generate()
        assert "день" in report.text.get("1.0", "end")
        report.destroy()

        json_path = tmp_path / "orders_backup.json"
        xml_path = tmp_path / "orders_backup.xml"
        monkeypatch.setattr(main_gui.filedialog, "asksaveasfilename", lambda **kwargs: str(json_path))
        app.format_var.set("JSON")
        app.export_orders()
        monkeypatch.setattr(main_gui.filedialog, "asksaveasfilename", lambda **kwargs: str(xml_path))
        app.format_var.set("XML")
        app.export_orders()
        assert json_path.exists() and xml_path.exists()

        monkeypatch.setattr(main_gui.filedialog, "askopenfilename", lambda **kwargs: str(json_path))
        app.import_orders()
        broken = tmp_path / "bad.json"
        broken.write_text("{", encoding="utf-8")
        monkeypatch.setattr(main_gui.filedialog, "askopenfilename", lambda **kwargs: str(broken))
        app.import_orders()
        monkeypatch.setattr(main_gui.filedialog, "asksaveasfilename", lambda **kwargs: "")
        app.export_orders()
        monkeypatch.setattr(main_gui.filedialog, "askopenfilename", lambda **kwargs: "")
        app.import_orders()

        app.data_paths["tinydb"] = tmp_path / "gui.json"
        app.backend_var.set("tinydb")
        app.change_backend()
        assert app.db.backend == "tinydb"
        assert app.tree.get_children()
        app.backend_var.set("tinydb")
        app.change_backend()
    finally:
        app._on_close()
