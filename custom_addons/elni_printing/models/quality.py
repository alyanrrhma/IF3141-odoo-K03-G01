from odoo import _, fields, models
from odoo.exceptions import UserError


class ElniQualityCheck(models.Model):
    _name = "elni.quality.check"
    _description = "Quality Check"
    _inherit = ["mail.thread", "elni.audit.mixin"]
    _order = "id desc"

    work_order_id = fields.Many2one("elni.work.order", string="SPK", required=True, ondelete="cascade")
    order_id = fields.Many2one(related="work_order_id.order_id", store=True)
    result = fields.Selection(
        [("pending", "Menunggu"), ("pass", "Lolos"), ("fail", "Gagal")],
        default="pending",
        required=True,
        tracking=True,
    )
    check_size = fields.Boolean(string="Ukuran sesuai")
    check_color = fields.Boolean(string="Warna sesuai")
    check_finishing = fields.Boolean(string="Finishing rapi")
    check_qty = fields.Boolean(string="Jumlah sesuai")
    reprint_reason = fields.Text(string="Alasan Cetak Ulang")
    checked_by = fields.Many2one("res.users", readonly=True)
    checked_date = fields.Datetime(readonly=True)
    reprint_id = fields.Many2one("elni.work.order", string="SPK Cetak Ulang", readonly=True)

    def action_pass(self):
        for qc in self:
            if qc.result != "pending":
                raise UserError(_("QC ini sudah diputuskan."))
            if not (qc.check_size and qc.check_color and qc.check_finishing and qc.check_qty):
                raise UserError(_("Semua item checklist harus dicentang agar QC dinyatakan lolos."))
            qc.write({"result": "pass", "checked_by": self.env.user.id, "checked_date": fields.Datetime.now()})
            qc.work_order_id.qc_state = "passed"
            qc.work_order_id.action_close_after_qc(True)
            qc._audit("QC lolos")
            # sudo(): QA tidak memiliki hak ubah pada pesanan; sistem yang menyiapkan status Siap.
            qc.order_id.sudo()._check_ready()
        return True

    def action_fail(self):
        for qc in self:
            if qc.result != "pending":
                raise UserError(_("QC ini sudah diputuskan."))
            if not qc.reprint_reason:
                raise UserError(_("Alasan cetak ulang wajib diisi saat QC gagal."))
            qc.write({"result": "fail", "checked_by": self.env.user.id, "checked_date": fields.Datetime.now()})
            qc.work_order_id.qc_state = "failed"
            qc.work_order_id.action_close_after_qc(False)
            qc.reprint_id = qc.work_order_id._create_reprint()
            qc._audit("QC gagal, SPK cetak ulang dibentuk")
        return True
