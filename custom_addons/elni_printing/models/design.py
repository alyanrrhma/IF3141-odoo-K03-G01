from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class ElniDesignPreview(models.Model):
    _name = "elni.design.preview"
    _description = "Preview Desain"
    _inherit = ["elni.audit.mixin"]
    _order = "order_id, version desc"

    order_id = fields.Many2one("elni.order", string="Pesanan", required=True, ondelete="cascade")
    version = fields.Integer(string="Versi", readonly=True, default=1)
    file = fields.Binary(string="File Preview", attachment=True)
    filename = fields.Char(string="Nama File")
    note = fields.Text(string="Catatan Revisi")
    state = fields.Selection(
        [("pending", "Menunggu persetujuan"), ("approved", "Disetujui"),
         ("revision", "Perlu revisi"), ("superseded", "Digantikan versi baru")],
        default="pending",
        required=True,
    )
    uploaded_by = fields.Many2one("res.users", default=lambda self: self.env.user, readonly=True)
    decided_by = fields.Char(string="Diputuskan Oleh", readonly=True)
    decided_date = fields.Datetime(string="Waktu Keputusan", readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            order = self.env["elni.order"].browse(vals.get("order_id"))
            vals["version"] = max(order.preview_ids.mapped("version") or [0]) + 1
        records = super().create(vals_list)
        for rec in records:
            # versi baru menggantikan versi lama yang belum disetujui
            (rec.order_id.preview_ids - rec).filtered(
                lambda p: p.state in ("pending", "revision")
            ).write({"state": "superseded"})
            rec._audit("Unggah preview desain v%s" % rec.version)
        return records

    @api.constrains("file")
    def _check_file(self):
        for rec in self:
            if not rec.file:
                raise ValidationError(_("File preview wajib diunggah."))

    def _decide(self, state, note=None):
        for rec in self:
            if rec.state != "pending":
                raise UserError(_("Hanya preview berstatus Menunggu persetujuan yang dapat diputuskan."))
            vals = {"state": state, "decided_by": self.env.user.name, "decided_date": fields.Datetime.now()}
            if note:
                vals["note"] = note
            rec.write(vals)
            if state == "revision":
                self.env["elni.revision.note"].create({
                    "order_id": rec.order_id.id,
                    "preview_id": rec.id,
                    "kind": "revision",
                    "note": note or rec.note,
                })
                # A revision before production invalidates preview approval and locks the SPK again.
                rec.order_id.workorder_ids.filtered(
                    lambda wo: wo.state in ("locked", "ready_to_start")
                ).write({"state": "locked"})
            else:
                rec.order_id.workorder_ids._refresh_readiness()
            label = "disetujui" if state == "approved" else "diminta revisi"
            rec.order_id.message_post(body=_("Preview v%(v)s %(s)s oleh %(u)s.", v=rec.version, s=label, u=self.env.user.name))
            rec._audit("Preview %s" % label)

    def action_approve(self):
        self._decide("approved")

    def action_request_revision(self):
        for rec in self:
            if not rec.note:
                raise UserError(_("Isi catatan revisi terlebih dahulu."))
        self._decide("revision")

    def action_portal_approve(self):
        # Dipanggil controller portal via sudo() setelah kepemilikan pesanan diverifikasi.
        self._decide("approved")

    def action_portal_revision(self, note):
        if not note:
            raise UserError(_("Isi catatan revisi terlebih dahulu."))
        self._decide("revision", note=note)


class ElniRevisionNote(models.Model):
    _name = "elni.revision.note"
    _description = "Catatan Revisi Pesanan"
    _order = "create_date desc, id desc"

    order_id = fields.Many2one("elni.order", string="Pesanan", required=True, ondelete="cascade")
    preview_id = fields.Many2one("elni.design.preview", string="Preview", ondelete="set null")
    kind = fields.Selection([("revision", "Revisi"), ("complaint", "Komplain")], required=True, default="revision")
    note = fields.Text(string="Isi", required=True)
    recorded_by = fields.Many2one("res.users", string="Dicatat Oleh", default=lambda self: self.env.user, readonly=True)
    recorded_at = fields.Datetime(string="Waktu", default=fields.Datetime.now, readonly=True)
