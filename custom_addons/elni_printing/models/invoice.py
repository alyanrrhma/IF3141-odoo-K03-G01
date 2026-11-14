from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ElniInvoice(models.Model):
    _name = "elni.invoice"
    _description = "Invoice / Piutang"
    _inherit = ["mail.thread", "elni.audit.mixin"]
    _order = "id desc"

    name = fields.Char(string="Nomor Invoice", readonly=True, copy=False, default="Baru")
    order_id = fields.Many2one("elni.order", string="Pesanan", ondelete="restrict")
    partner_id = fields.Many2one("res.partner", string="Pelanggan", required=True)
    amount_total = fields.Float(string="Total (Rp)", digits=(16, 2), required=True)
    invoice_date = fields.Date(string="Tanggal Invoice", default=fields.Date.context_today, required=True)
    due_date = fields.Date(string="Jatuh Tempo", required=True)
    state = fields.Selection(
        [("unpaid", "Not Paid"), ("paid", "Paid")], default="unpaid", required=True, tracking=True
    )
    payment_date = fields.Date(string="Tanggal Bayar", copy=False)
    payment_ref = fields.Char(string="Referensi Pembayaran", copy=False)
    is_opening = fields.Boolean(string="Saldo Awal", readonly=True)
    days_overdue = fields.Integer(string="Hari Terlambat", compute="_compute_days_overdue")
    exported = fields.Boolean(string="Sudah Diekspor", copy=False)
    export_date = fields.Datetime(copy=False, readonly=True)

    @api.depends("due_date", "state")
    def _compute_days_overdue(self):
        today = fields.Date.context_today(self)
        for rec in self:
            rec.days_overdue = (
                (today - rec.due_date).days if rec.state == "unpaid" and rec.due_date and rec.due_date < today else 0
            )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Baru") == "Baru":
                vals["name"] = self.env["ir.sequence"].next_by_code("elni.invoice") or "Baru"
        return super().create(vals_list)

    def action_register_payment(self):
        for rec in self:
            if rec.state == "paid":
                raise UserError(_("Invoice %s sudah dibayar; pembayaran hanya dicatat satu kali.", rec.name))
            rec.write({"state": "paid", "payment_date": rec.payment_date or fields.Date.context_today(self)})
            rec._audit("Pembayaran dicatat")
        return True
