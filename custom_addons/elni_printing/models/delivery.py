from datetime import timedelta

from odoo import _, fields, models
from odoo.exceptions import UserError


class ElniDelivery(models.Model):
    _name = "elni.delivery"
    _description = "Penyerahan Pesanan"
    _inherit = ["mail.thread", "elni.audit.mixin"]
    _order = "id desc"

    name = fields.Char(related="order_id.name", string="Pesanan", store=True)
    order_id = fields.Many2one("elni.order", string="Pesanan", required=True, ondelete="restrict")
    partner_id = fields.Many2one(related="order_id.partner_id", store=True)
    method = fields.Selection(
        [("pickup", "Diambil"), ("delivery", "Diantar"), ("courier", "Ekspedisi")],
        string="Metode Penyerahan",
        required=True,
        default="pickup",
        tracking=True,
    )
    address = fields.Text(string="Alamat")
    tracking_ref = fields.Char(string="No. Resi", tracking=True)
    state = fields.Selection(
        [("draft", "Disiapkan"), ("shipped", "Dikirim"), ("received", "Diterima")],
        default="draft",
        required=True,
        tracking=True,
    )
    received_date = fields.Datetime(readonly=True)
    note = fields.Char(string="Catatan")

    def action_dispatch(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Hanya penyerahan berstatus Disiapkan yang dapat dikirim."))
            if rec.method == "pickup":
                raise UserError(_("Pesanan yang diambil langsung dikonfirmasi diterima."))
            if not rec.address:
                raise UserError(_("Alamat wajib diisi untuk pengantaran/ekspedisi."))
            if rec.method == "courier" and not rec.tracking_ref:
                raise UserError(_("Nomor resi wajib diisi untuk ekspedisi."))
            rec.state = "shipped"
            rec._audit("Pesanan dikirim")
        return True

    def action_confirm_received(self):
        for rec in self:
            if rec.state == "received":
                raise UserError(_("Penerimaan sudah dikonfirmasi."))
            if rec.method != "pickup" and rec.state != "shipped":
                raise UserError(_("Kirim pesanan terlebih dahulu sebelum konfirmasi penerimaan."))
            if rec.order_id.state != "ready":
                raise UserError(_("Pesanan belum berstatus Siap."))
            rec.write({"state": "received", "received_date": fields.Datetime.now()})
            # sudo(): Sales/Logistik tidak memiliki hak ubah pesanan dan hak buat invoice;
            # invoice terbit otomatis oleh sistem saat penerimaan dikonfirmasi.
            order = rec.order_id.sudo()
            order.state = "delivered"
            rec._issue_invoice(order)
            rec._audit("Penerimaan dikonfirmasi")
        return True

    def _issue_invoice(self, order):
        invoice = self.env["elni.invoice"].sudo()
        if invoice.search_count([("order_id", "=", order.id)]):
            return
        today = fields.Date.context_today(self)
        term = self.env["elni.setting"]._get().payment_term_days
        invoice.create(
            {
                "order_id": order.id,
                "partner_id": order.partner_id.id,
                "amount_total": order.amount_total,
                "invoice_date": today,
                "due_date": today + timedelta(days=term),
            }
        )
