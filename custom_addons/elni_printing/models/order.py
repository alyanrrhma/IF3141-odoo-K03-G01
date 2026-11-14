import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class ElniOrder(models.Model):
    _name = "elni.order"
    _description = "Pesanan Cetak"
    _inherit = ["mail.thread", "mail.activity.mixin", "elni.audit.mixin"]
    _order = "id desc"

    name = fields.Char(string="Nomor Pesanan", readonly=True, copy=False, default="Baru")
    partner_id = fields.Many2one("res.partner", string="Pelanggan", required=True, tracking=True)
    contact_name = fields.Char(string="Nama Kontak")
    contact_phone = fields.Char(string="Telepon / WhatsApp")
    order_date = fields.Date(string="Tanggal Pesanan", default=fields.Date.context_today)
    deadline = fields.Date(string="Deadline", required=True, tracking=True)
    location_id = fields.Many2one(
        "elni.location",
        string="Cabang Produksi",
        required=True,
        default=lambda self: self.env["elni.location"].search([], limit=1),
    )
    source = fields.Selection(
        [("internal", "Internal"), ("portal", "Portal Pelanggan")], default="internal", readonly=True
    )
    line_ids = fields.One2many("elni.order.line", "order_id", string="Produk")
    amount_total = fields.Float(string="Total (Rp)", compute="_compute_amount", store=True, digits=(16, 2))
    note = fields.Text(string="Catatan")
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("confirmed", "SPK Terkunci"),
            ("in_production", "Produksi"),
            ("ready", "Siap"),
            ("delivered", "Diserahkan"),
            ("cancelled", "Dibatalkan"),
        ],
        default="draft",
        required=True,
        tracking=True,
    )
    preview_ids = fields.One2many("elni.design.preview", "order_id", string="Preview Desain")
    revision_note_ids = fields.One2many("elni.revision.note", "order_id", string="Riwayat Revisi")
    preview_status = fields.Selection(
        [("none", "Belum ada preview"), ("pending", "Menunggu persetujuan"),
         ("approved", "Disetujui"), ("revision", "Perlu revisi")],
        compute="_compute_preview_status",
        store=True,
        tracking=True,
    )
    workorder_ids = fields.One2many("elni.work.order", "order_id", string="SPK")
    workorder_count = fields.Integer(compute="_compute_workorder_count")
    whatsapp_text = fields.Text(string="Teks WhatsApp", compute="_compute_whatsapp_text")
    email_sent = fields.Boolean(string="Email Notifikasi Terkirim", readonly=True, copy=False)
    wa_sent = fields.Boolean(string="WhatsApp Dikirim CSO", copy=False)

    @api.depends("line_ids.subtotal")
    def _compute_amount(self):
        for rec in self:
            rec.amount_total = sum(rec.line_ids.mapped("subtotal"))

    @api.depends("preview_ids.state")
    def _compute_preview_status(self):
        for rec in self:
            active = rec.preview_ids.filtered(lambda p: p.state != "superseded").sorted("id")
            rec.preview_status = active[-1].state if active else "none"

    def _compute_workorder_count(self):
        for rec in self:
            rec.workorder_count = len(rec.workorder_ids)

    @api.depends("name", "contact_name", "partner_id", "deadline")
    def _compute_whatsapp_text(self):
        for rec in self:
            rec.whatsapp_text = _(
                "Halo %(who)s, pesanan %(order)s di PT ELNI sudah selesai diproduksi dan siap "
                "diambil/dikirim. Mohon konfirmasi metode penyerahan. Terima kasih.",
                who=rec.contact_name or rec.partner_id.name or "",
                order=rec.name,
            )

    @api.constrains("deadline", "order_date")
    def _check_deadline(self):
        for rec in self:
            if rec.deadline and rec.order_date and rec.deadline < rec.order_date:
                raise ValidationError(_("Deadline tidak boleh lebih awal dari tanggal pesanan."))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Baru") == "Baru":
                vals["name"] = self.env["ir.sequence"].next_by_code("elni.order") or "Baru"
        return super().create(vals_list)

    # ------------------------------------------------------------------ aksi
    def action_confirm(self):
        for order in self:
            if order.state != "draft":
                raise UserError(_("Hanya pesanan Draft yang dapat dikonfirmasi."))
            if not order.line_ids:
                raise UserError(_("Pesanan harus memiliki minimal satu produk."))
        work_order = self.env["elni.work.order"]
        for order in self:
            work_order.create({"order_id": order.id})
            order.state = "confirmed"
            order._audit("Konfirmasi pesanan, SPK terbentuk (Terkunci)")
            order.message_post(body=_("Pesanan dikonfirmasi. SPK dibentuk dengan status Terkunci."))
        return True

    def action_demo_confirm_if_draft(self):
        """Allow demo data to be reloaded on an existing demo database."""
        self.filtered(lambda order: order.state == "draft").action_confirm()
        return True

    def action_cancel(self):
        for order in self:
            if order.state not in ("draft", "confirmed"):
                raise UserError(_("Pesanan yang sudah masuk produksi tidak dapat dibatalkan."))
            if order.workorder_ids.filtered(lambda w: w.state not in ("locked", "ready_to_start", "cancelled")):
                raise UserError(_("Ada SPK yang sudah dimulai; pesanan tidak dapat dibatalkan."))
            pending_wos = order.workorder_ids.filtered(lambda w: w.state in ("locked", "ready_to_start"))
            pending_wos.write({"cancel_reason": order.note or _("Pesanan dibatalkan")})
            pending_wos.action_cancel()
            order.state = "cancelled"
            order._audit("Pembatalan pesanan")
        return True

    def action_view_workorders(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("SPK"),
            "res_model": "elni.work.order",
            "view_mode": "tree,form",
            "domain": [("order_id", "=", self.id)],
        }

    def action_mark_wa_sent(self):
        self.write({"wa_sent": True})
        for order in self:
            order._audit("WhatsApp pesanan siap dikirim manual oleh CSO")
        return True

    def action_resend_ready_notification(self):
        for order in self:
            if order.state != "ready":
                raise UserError(_("Notifikasi hanya untuk pesanan berstatus Siap."))
            order._send_ready_notification()
        return True

    # ------------------------------------------------- dipanggil dari SPK/QC/penyerahan
    def _check_ready(self):
        """Pesanan siap jika semua SPK selesai dan sudah melewati QC (dipanggil via sudo)."""
        for order in self:
            if order.state not in ("confirmed", "in_production"):
                continue
            wos = order.workorder_ids.filtered(lambda w: w.state != "cancelled")
            if (
                wos
                and all(w.state == "done" and w.qc_state in ("passed", "failed") for w in wos)
                and any(w.qc_state == "passed" for w in wos)
            ):
                order._mark_ready()

    def _mark_ready(self):
        self.ensure_one()
        self.state = "ready"
        self._audit("Pesanan siap")
        self.env["elni.delivery"].create(
            {"order_id": self.id, "method": "pickup", "address": self.partner_id.contact_address or ""}
        )
        self._send_ready_notification()

    def _send_ready_notification(self):
        self.ensure_one()
        self.message_post(
            body=_("Teks WhatsApp untuk dikirim manual oleh CSO:<br/>%s", self.whatsapp_text),
            message_type="comment",
            subtype_xmlid="mail.mt_note",
        )
        template = self.env.ref("elni_printing.mail_template_order_ready", raise_if_not_found=False)
        if template and self.partner_id.email:
            try:
                template.send_mail(self.id, force_send=False)
                self.email_sent = True
            except Exception:  # pylint: disable=broad-except
                # Kegagalan email tidak boleh menggagalkan alur produksi; dicatat di chatter.
                _logger.exception("Gagal membuat email notifikasi pesanan %s", self.name)
                self.message_post(body=_("Email notifikasi gagal dibuat; kirim manual."))
        else:
            self.message_post(body=_("Email notifikasi tidak dikirim: pelanggan belum memiliki alamat email."))


class ElniOrderLine(models.Model):
    _name = "elni.order.line"
    _description = "Baris Pesanan"

    order_id = fields.Many2one("elni.order", required=True, ondelete="cascade")
    product_id = fields.Many2one(
        "elni.product", string="Produk", required=True, domain=[("kind", "=", "print")]
    )
    spec = fields.Text(string="Spesifikasi")
    qty = fields.Float(string="Jumlah", required=True, default=1.0)
    price_unit = fields.Float(string="Harga Satuan (Rp)", digits=(16, 2))
    subtotal = fields.Float(compute="_compute_subtotal", store=True, digits=(16, 2))

    _sql_constraints = [("qty_positive", "check(qty > 0)", "Jumlah harus lebih dari 0.")]

    @api.onchange("product_id")
    def _onchange_product_id(self):
        if self.product_id:
            self.price_unit = self.product_id.price

    @api.depends("qty", "price_unit")
    def _compute_subtotal(self):
        for rec in self:
            rec.subtotal = rec.qty * rec.price_unit
