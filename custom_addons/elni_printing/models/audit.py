from odoo import _, fields, models
from odoo.exceptions import AccessError


class ElniAuditMixin(models.AbstractModel):
    _name = "elni.audit.mixin"
    _description = "Mixin log aktivitas dan cek peran"

    def _audit(self, action):
        # sudo(): semua peran harus bisa menulis log, tetapi tidak boleh mengubah/menghapusnya.
        log = self.env["elni.audit.log"].sudo()
        for rec in self:
            log.create(
                {
                    "user_id": self.env.user.id,
                    "model": rec._name,
                    "res_id": rec.id,
                    "record_name": rec.display_name,
                    "action": action,
                }
            )

    def _require_group(self, xmlid, label):
        if not self.env.user.has_group(xmlid):
            raise AccessError(_("Hanya peran %s yang dapat melakukan tindakan ini.", label))


class ElniAuditLog(models.Model):
    _name = "elni.audit.log"
    _description = "Log Aktivitas"
    _order = "id desc"

    date = fields.Datetime(default=fields.Datetime.now, readonly=True)
    user_id = fields.Many2one("res.users", string="Pengguna", readonly=True)
    model = fields.Char(string="Model", readonly=True)
    res_id = fields.Integer(readonly=True)
    record_name = fields.Char(string="Dokumen", readonly=True)
    action = fields.Char(string="Aktivitas", readonly=True)


class ElniBackupLog(models.Model):
    _name = "elni.backup.log"
    _description = "Status Backup"
    _order = "backup_date desc"

    backup_date = fields.Datetime(string="Waktu Backup", default=fields.Datetime.now, required=True)
    status = fields.Selection(
        [("success", "Berhasil"), ("failed", "Gagal")], default="success", required=True
    )
    storage = fields.Char(string="Lokasi Penyimpanan")
    note = fields.Text(string="Catatan")
    recorded_by = fields.Many2one("res.users", default=lambda self: self.env.user, readonly=True)
