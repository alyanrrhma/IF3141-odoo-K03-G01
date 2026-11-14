import base64
import csv
import io

from odoo import _, fields, models
from odoo.exceptions import UserError


class ElniExportWizard(models.TransientModel):
    _name = "elni.export.wizard"
    _description = "Ekspor Data untuk Accurate"

    export_type = fields.Selection(
        [("sales", "Penjualan (Invoice)"), ("purchase", "Pembelian")], string="Jenis Data", required=True, default="sales"
    )
    date_from = fields.Date(string="Dari", required=True, default=lambda self: fields.Date.context_today(self).replace(day=1))
    date_to = fields.Date(string="Sampai", required=True, default=fields.Date.context_today)
    only_new = fields.Boolean(string="Hanya yang belum pernah diekspor", default=True)
    file = fields.Binary(string="File CSV", readonly=True)
    filename = fields.Char(readonly=True)
    record_count = fields.Integer(readonly=True)

    def action_export(self):
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_("Tanggal awal tidak boleh melewati tanggal akhir."))
        buf = io.StringIO()
        writer = csv.writer(buf)
        if self.export_type == "sales":
            records = self.env["elni.invoice"].search(self._domain("invoice_date"))
            writer.writerow(["No Invoice", "Tanggal", "Pelanggan", "Jatuh Tempo", "Total", "Status"])
            for inv in records:
                writer.writerow([inv.name, inv.invoice_date, inv.partner_id.name, inv.due_date,
                                 inv.amount_total, inv.state])
        else:
            records = self.env["elni.purchase"].search(
                self._domain("date") + [("state", "in", ("confirmed", "received"))]
            )
            writer.writerow(["No Pembelian", "Tanggal", "Supplier", "Total", "Status"])
            for po in records:
                writer.writerow([po.name, po.date, po.supplier_id.name, po.amount_total, po.state])
        if not records:
            raise UserError(_("Tidak ada data yang cocok dengan filter."))
        records.write({"exported": True, "export_date": fields.Datetime.now()})
        self.write(
            {
                "file": base64.b64encode(buf.getvalue().encode("utf-8")),
                "filename": "accurate_%s_%s_%s.csv" % (self.export_type, self.date_from, self.date_to),
                "record_count": len(records),
            }
        )
        return self._reopen()

    def _domain(self, date_field):
        domain = [(date_field, ">=", self.date_from), (date_field, "<=", self.date_to)]
        if self.only_new:
            domain.append(("exported", "=", False))
        return domain

    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }


class ElniImportOpeningWizard(models.TransientModel):
    _name = "elni.import.opening.wizard"
    _description = "Impor Saldo Awal Piutang dari Accurate"

    file = fields.Binary(string="File CSV", required=True)
    filename = fields.Char()
    result = fields.Text(readonly=True)

    def action_import(self):
        self.ensure_one()
        try:
            text = base64.b64decode(self.file).decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise UserError(_("File harus berformat CSV UTF-8.")) from exc
        lines = text.splitlines()
        if not lines:
            raise UserError(_("File kosong."))
        delimiter = ";" if lines[0].count(";") > lines[0].count(",") else ","
        reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
        needed = {"pelanggan", "tanggal", "jatuh_tempo", "jumlah"}
        if not reader.fieldnames or not needed.issubset({f.strip().lower() for f in reader.fieldnames}):
            raise UserError(_("Kolom wajib: pelanggan, tanggal, jatuh_tempo, jumlah (format tanggal YYYY-MM-DD)."))
        partner_model = self.env["res.partner"]
        invoice_model = self.env["elni.invoice"]
        count = 0
        for line_no, raw in enumerate(reader, start=2):
            row = {k.strip().lower(): (v or "").strip() for k, v in raw.items() if k}
            try:
                amount = float(row["jumlah"])
                invoice_date = fields.Date.from_string(row["tanggal"])
                due_date = fields.Date.from_string(row["jatuh_tempo"])
            except (ValueError, TypeError) as exc:
                raise UserError(_("Baris %s tidak valid: %s", line_no, exc)) from exc
            if not row["pelanggan"] or not invoice_date or not due_date or amount <= 0:
                raise UserError(_("Baris %s tidak lengkap.", line_no))
            partner = partner_model.search([("name", "=", row["pelanggan"])], limit=1) or partner_model.create(
                {"name": row["pelanggan"]}
            )
            invoice_model.create(
                {
                    "partner_id": partner.id,
                    "amount_total": amount,
                    "invoice_date": invoice_date,
                    "due_date": due_date,
                    "is_opening": True,
                    "exported": True,
                }
            )
            count += 1
        self.result = _("%s saldo awal piutang berhasil diimpor.", count)
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
        }
