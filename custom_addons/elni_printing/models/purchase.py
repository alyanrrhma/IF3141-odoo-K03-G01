from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ElniPurchase(models.Model):
    _name = "elni.purchase"
    _description = "RFQ / Pembelian"
    _inherit = ["mail.thread", "elni.audit.mixin"]
    _order = "id desc"

    name = fields.Char(string="Nomor", readonly=True, copy=False, default="Baru")
    supplier_id = fields.Many2one("res.partner", string="Supplier", required=True, tracking=True)
    location_id = fields.Many2one("elni.location", string="Lokasi Penerimaan", required=True)
    date = fields.Date(string="Tanggal", default=fields.Date.context_today)
    line_ids = fields.One2many("elni.purchase.line", "purchase_id", string="Bahan")
    amount_total = fields.Float(string="Total (Rp)", compute="_compute_amount", store=True, digits=(16, 2))
    needs_approval = fields.Boolean(string="Perlu Persetujuan", compute="_compute_needs_approval")
    supplier_ref = fields.Char(string="Referensi Penawaran Supplier")
    state = fields.Selection(
        [
            ("draft", "RFQ"),
            ("sent", "RFQ Terkirim"),
            ("to_approve", "To Approve"),
            ("confirmed", "Dikonfirmasi"),
            ("received", "Diterima"),
            ("rejected", "Ditolak"),
            ("cancelled", "Dibatalkan"),
        ],
        default="draft",
        required=True,
        tracking=True,
    )
    approver_id = fields.Many2one("res.users", string="Penyetuju", readonly=True, copy=False)
    approval_date = fields.Datetime(readonly=True, copy=False)
    reject_reason = fields.Text(string="Alasan Penolakan")
    exported = fields.Boolean(string="Sudah Diekspor", copy=False)
    export_date = fields.Datetime(copy=False, readonly=True)

    @api.depends("line_ids.subtotal")
    def _compute_amount(self):
        for rec in self:
            rec.amount_total = sum(rec.line_ids.mapped("subtotal"))

    @api.depends("amount_total")
    def _compute_needs_approval(self):
        limit = self.env["elni.setting"]._get().po_approval_limit
        for rec in self:
            rec.needs_approval = rec.amount_total > limit

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Baru") == "Baru":
                vals["name"] = self.env["ir.sequence"].next_by_code("elni.purchase") or "Baru"
        return super().create(vals_list)

    def action_send(self):
        for rec in self:
            if rec.state != "draft":
                raise UserError(_("Hanya RFQ berstatus draft yang dapat dikirim."))
            if not rec.line_ids:
                raise UserError(_("RFQ harus memiliki minimal satu baris bahan."))
            rec.state = "sent"
            rec.message_post(body=_("RFQ dikirim ke %s.", rec.supplier_id.name))
            rec._audit("RFQ dikirim")
        return True

    def action_demo_send_if_draft(self):
        """Allow demo data to be reloaded without resending an existing RFQ."""
        self.filtered(lambda purchase: purchase.state == "draft").action_send()
        return True

    def action_confirm(self):
        """Konfirmasi penawaran supplier; di atas batas nilai harus disetujui Manager Keuangan."""
        for rec in self:
            if rec.state != "sent":
                raise UserError(_("Konfirmasi hanya untuk RFQ yang sudah dikirim."))
            if rec.needs_approval:
                rec.state = "to_approve"
                rec._audit("Pembelian menunggu persetujuan")
            else:
                rec.state = "confirmed"
                rec._audit("Pembelian dikonfirmasi")
        return True

    def action_demo_confirm_if_sent(self):
        """Allow demo data to be reloaded without reconfirming an existing RFQ."""
        self.filtered(lambda purchase: purchase.state == "sent").action_confirm()
        return True

    def action_approve(self):
        self._require_group("elni_printing.group_elni_finance_manager", _("Manager Keuangan"))
        for rec in self:
            if rec.state != "to_approve":
                raise UserError(_("Pembelian ini tidak menunggu persetujuan."))
            rec.write(
                {"state": "confirmed", "approver_id": self.env.user.id, "approval_date": fields.Datetime.now()}
            )
            rec._audit("Pembelian disetujui")
        return True

    def action_reject(self):
        self._require_group("elni_printing.group_elni_finance_manager", _("Manager Keuangan"))
        for rec in self:
            if rec.state != "to_approve":
                raise UserError(_("Pembelian ini tidak menunggu persetujuan."))
            if not rec.reject_reason:
                raise UserError(_("Isi alasan penolakan terlebih dahulu."))
            rec.write(
                {"state": "rejected", "approver_id": self.env.user.id, "approval_date": fields.Datetime.now()}
            )
            rec._audit("Pembelian ditolak")
        return True

    def action_receive(self):
        move = self.env["elni.stock.move"]
        for rec in self:
            if rec.state != "confirmed":
                raise UserError(_("Hanya pembelian yang sudah dikonfirmasi yang dapat diterima."))
            for line in rec.line_ids:
                move.create(
                    {
                        "move_type": "receipt",
                        "product_id": line.product_id.id,
                        "location_id": rec.location_id.id,
                        "qty": line.qty,
                        "ref": rec.name,
                        "purchase_id": rec.id,
                    }
                )
            rec.state = "received"
            rec._audit("Barang diterima, stok bertambah")
        return True

    def action_cancel(self):
        for rec in self:
            if rec.state not in ("draft", "sent", "to_approve"):
                raise UserError(_("Pembelian pada status ini tidak dapat dibatalkan."))
            rec.state = "cancelled"
            rec._audit("Pembelian dibatalkan")
        return True


class ElniPurchaseLine(models.Model):
    _name = "elni.purchase.line"
    _description = "Baris Pembelian"

    purchase_id = fields.Many2one("elni.purchase", required=True, ondelete="cascade")
    product_id = fields.Many2one(
        "elni.product", string="Bahan", required=True, domain=[("kind", "=", "material")]
    )
    qty = fields.Float(string="Jumlah", required=True, default=1.0)
    price_unit = fields.Float(string="Harga Satuan (Rp)", digits=(16, 2))
    subtotal = fields.Float(compute="_compute_subtotal", store=True, digits=(16, 2))
    uom = fields.Char(related="product_id.uom")

    _sql_constraints = [("qty_positive", "check(qty > 0)", "Jumlah harus lebih dari 0.")]

    @api.onchange("product_id")
    def _onchange_product_id(self):
        if self.product_id:
            self.price_unit = self.product_id.cost

    @api.depends("qty", "price_unit")
    def _compute_subtotal(self):
        for rec in self:
            rec.subtotal = rec.qty * rec.price_unit
