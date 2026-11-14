"""Create/reset the two QC examples in an existing local Odoo demo database.

Run with:
    docker compose run --rm web odoo shell -d odoo_demo < scripts/seed_elni_qc_demo.py
"""

from datetime import timedelta

from odoo import fields


partner = env.ref("elni_printing.demo_customer", raise_if_not_found=False)
if not partner:
    partner = env["res.partner"].search(
        [("name", "=", "PT Maju Jaya (Demo B2B)")], limit=1
    )
if not partner:
    partner = env["res.partner"].create(
        {
            "name": "PT Maju Jaya (Demo B2B)",
            "email": "purchasing@majujaya.example",
            "is_company": True,
        }
    )

location = env.ref("elni_printing.loc_pasteur")
product = env.ref("elni_printing.prd_brosur")
image = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="

for scenario, marker, passed in (
    ("lolos", "[QC-DEMO:PASS]", True),
    ("cetak ulang", "[QC-DEMO:FAIL]", False),
):
    order = env["elni.order"].search([("note", "=", marker)], limit=1)
    if not order:
        order = env["elni.order"].create(
            {
                "partner_id": partner.id,
                "contact_name": "Budi Santoso",
                "contact_phone": "081234567890",
                "location_id": location.id,
                "deadline": fields.Date.today() + timedelta(days=3),
                "note": marker,
                "state": "in_production",
            }
        )
    if not order.line_ids:
        env["elni.order.line"].create(
            {
                "order_id": order.id,
                "product_id": product.id,
                "spec": "Demo QC " + scenario,
                "qty": 10,
                "price_unit": 3500,
            }
        )
    preview = order.preview_ids[:1]
    if not preview:
        preview = env["elni.design.preview"].create(
            {
                "order_id": order.id,
                "filename": "preview_qc_%s.png" % scenario.replace(" ", "_"),
                "file": image,
                "state": "approved",
                "decided_by": "Demo Pelanggan B2B",
                "decided_date": fields.Datetime.now(),
            }
        )
    else:
        preview.write(
            {
                "state": "approved",
                "decided_by": "Demo Pelanggan B2B",
                "decided_date": fields.Datetime.now(),
            }
        )

    work_order = order.workorder_ids[:1]
    if not work_order:
        work_order = env["elni.work.order"].create({"order_id": order.id})
    work_order.write(
        {
            "state": "waiting_qc",
            "schedule_approved": True,
            "planned_start": fields.Date.today(),
            "start_date": fields.Datetime.now(),
            "done_date": fields.Datetime.now(),
            "qc_state": "pending",
        }
    )

    qc = work_order.qc_ids[:1]
    qc_values = {
        "result": "pending",
        "check_size": True,
        "check_color": True,
        "check_finishing": True,
        "check_qty": passed,
        "reprint_reason": "" if passed else "Jumlah cetak tidak sesuai",
        "checked_by": False,
        "checked_date": False,
        "reprint_id": False,
    }
    if qc:
        qc.write(qc_values)
    else:
        env["elni.quality.check"].create(
            {"work_order_id": work_order.id, **qc_values}
        )

    print("QC demo %s siap: %s" % (scenario, work_order.name))


# Reuse the same demo customer and master data to populate the remaining screen mockups.
today = fields.Date.today()
supplier = env.ref("elni_printing.demo_supplier", raise_if_not_found=False) or partner
material = env.ref("elni_printing.mat_art_paper")


def screen_order(marker, state="ready"):
    order = env["elni.order"].search([("note", "=", marker)], limit=1)
    if not order:
        order = env["elni.order"].create(
            {
                "partner_id": partner.id,
                "contact_name": "Budi Santoso",
                "contact_phone": "081234567890",
                "location_id": location.id,
                "deadline": today + timedelta(days=2),
                "note": marker,
                "state": state,
            }
        )
    else:
        order.write({"state": state})
    if not order.line_ids:
        env["elni.order.line"].create(
            {
                "order_id": order.id,
                "product_id": product.id,
                "spec": "Demo layar operasional",
                "qty": 20,
                "price_unit": 3500,
            }
        )
    return order


# Layar Penyerahan: satu contoh per metode, termasuk resi dan status yang berbeda.
delivery_examples = (
    ("pickup", "draft", "[SCREEN-DEMO:DELIVERY:PICKUP]", ""),
    ("delivery", "shipped", "[SCREEN-DEMO:DELIVERY:DELIVERY]", "Jl. Pasteur No. 10, Bandung"),
    ("courier", "received", "[SCREEN-DEMO:DELIVERY:COURIER]", "Jl. Dago No. 25, Bandung"),
)
for method, state, marker, address in delivery_examples:
    order_state = "delivered" if state == "received" else "ready"
    order = screen_order(marker, order_state)
    delivery = env["elni.delivery"].search([("order_id", "=", order.id)], limit=1)
    values = {
        "order_id": order.id,
        "method": method,
        "state": state,
        "address": address,
        "tracking_ref": "JNE-DEMO-2026-001" if method == "courier" else False,
        "received_date": fields.Datetime.now() if state == "received" else False,
        "note": "Data contoh layar penyerahan",
    }
    if delivery:
        delivery.write(values)
    else:
        delivery = env["elni.delivery"].create(values)
    print("Penyerahan demo %s siap: %s" % (method, delivery.name))

# Layar Notifikasi: order siap untuk melihat status email dan template WhatsApp.
notification_order = screen_order("[SCREEN-DEMO:READY-NOTIFICATION]", "ready")
notification_order.write({"email_sent": True, "wa_sent": False})
print("Notifikasi pesanan siap demo: %s" % notification_order.name)

# Layar Piutang dan Ekspor: invoice bulan ini yang belum diekspor serta invoice lunas.
invoice_examples = (
    ("[SCREEN-DEMO:INVOICE-UNPAID]", "unpaid"),
    ("[SCREEN-DEMO:INVOICE-PAID]", "paid"),
)
for marker, state in invoice_examples:
    order = screen_order(marker, "delivered")
    invoice = env["elni.invoice"].search([("order_id", "=", order.id)], limit=1)
    due_date = today + timedelta(days=14) if state == "unpaid" else today - timedelta(days=2)
    values = {
        "order_id": order.id,
        "partner_id": partner.id,
        "amount_total": order.amount_total or 70000,
        "invoice_date": today,
        "due_date": due_date,
        "state": state,
        "payment_date": today if state == "paid" else False,
        "payment_ref": "TRF-DEMO-2026-001" if state == "paid" else False,
        "exported": False,
        "export_date": False,
    }
    if invoice:
        invoice.write(values)
    else:
        env["elni.invoice"].create(values)
    print("Invoice demo %s siap: %s" % (state, invoice.name if invoice else order.name))

# Layar KPI: completed SPK, material consumption, one on-time completion, and one reprint.
kpi_order = screen_order("[SCREEN-DEMO:KPI]", "delivered")
original = kpi_order.workorder_ids.filtered(lambda wo: not wo.is_reprint)[:1]
if not original:
    original = env["elni.work.order"].create({"order_id": kpi_order.id})
original.write(
    {
        "state": "done",
        "qc_state": "passed",
        "schedule_approved": True,
        "planned_start": today - timedelta(days=2),
        "start_date": fields.Datetime.to_datetime(today - timedelta(days=2)),
        "done_date": fields.Datetime.to_datetime(today - timedelta(days=1)),
    }
)
reprint = kpi_order.workorder_ids.filtered("is_reprint")[:1]
if not reprint:
    reprint = env["elni.work.order"].create(
        {
            "order_id": kpi_order.id,
            "is_reprint": True,
            "reprint_of_id": original.id,
        }
    )
reprint.write(
    {
        "state": "done",
        "qc_state": "passed",
        "schedule_approved": True,
        "planned_start": today - timedelta(days=1),
        "start_date": fields.Datetime.to_datetime(today - timedelta(days=1)),
        "done_date": fields.Datetime.to_datetime(today),
    }
)
for wo in original | reprint:
    wo.material_ids.write({"qty_used": 2.0})
print("Data KPI demo siap: %s" % kpi_order.name)

# Layar Pengaturan Pengguna: existing per-role demo users plus log and backup examples.
it_user = env.ref("elni_printing.demo_user_it", raise_if_not_found=False) or env.user
for label, status in (("Backup demo berhasil", "success"), ("Backup demo gagal", "failed")):
    backup = env["elni.backup.log"].search([("note", "=", label)], limit=1)
    values = {
        "backup_date": fields.Datetime.now(),
        "status": status,
        "storage": "/backup/demo/odoo_demo.zip",
        "note": label,
        "recorded_by": it_user.id,
    }
    if backup:
        backup.write(values)
    else:
        env["elni.backup.log"].create(values)

for label in ("Demo pengguna per jabatan siap diuji", "Demo hak akses per jabatan siap diuji"):
    audit = env["elni.audit.log"].search([("action", "=", label)], limit=1)
    if not audit:
        env["elni.audit.log"].create(
            {
                "user_id": it_user.id,
                "model": "res.users",
                "res_id": it_user.id,
                "record_name": it_user.name,
                "action": label,
            }
        )
print("Pengguna demo: %s akun per peran tersedia" % env["res.users"].search_count([("login", "ilike", "@elni.test")]))

# Layar Ekspor Accurate: one confirmed, current-period purchase not yet exported.
purchase = env["elni.purchase"].search([("supplier_ref", "=", "[SCREEN-DEMO:ACCURATE]")], limit=1)
if not purchase:
    purchase = env["elni.purchase"].create(
        {
            "supplier_id": supplier.id,
            "location_id": location.id,
            "date": today,
            "supplier_ref": "[SCREEN-DEMO:ACCURATE]",
            "state": "confirmed",
            "line_ids": [
                (0, 0, {"product_id": material.id, "qty": 50, "price_unit": material.cost or 1500})
            ],
        }
    )
else:
    purchase.write({"date": today, "state": "confirmed", "exported": False, "export_date": False})
print("Pembelian untuk ekspor demo siap: %s" % purchase.name)

env.cr.commit()
