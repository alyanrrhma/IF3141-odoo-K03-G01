from odoo import api, fields, models


class ElniSetting(models.Model):
    _name = "elni.setting"
    _description = "Pengaturan ELNI"

    name = fields.Char(default="Pengaturan ELNI", readonly=True)
    po_approval_limit = fields.Float(
        string="Batas Persetujuan Pembelian (Rp)", default=5000000.0, digits=(16, 2)
    )
    payment_term_days = fields.Integer(string="Jatuh Tempo Invoice (hari)", default=30)
    daily_capacity = fields.Integer(string="Kapasitas SPK per Hari", default=5)

    @api.model
    def _get(self):
        # sudo(): semua peran membaca konfigurasi; hanya Manajemen/IT yang boleh mengubahnya (lihat ACL).
        rec = self.sudo().search([], limit=1)
        return rec or self.sudo().create({})
