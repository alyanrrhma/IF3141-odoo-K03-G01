from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ElniWorkOrder(models.Model):
    _name = "elni.work.order"
    _description = "SPK / Work Order"
    _inherit = ["mail.thread", "elni.audit.mixin"]
    _order = "sequence_no, id"

    name = fields.Char(string="Nomor SPK", readonly=True, copy=False, default="Baru")
    order_id = fields.Many2one("elni.order", string="Pesanan", required=True, ondelete="restrict")
    partner_id = fields.Many2one(related="order_id.partner_id", store=True)
    deadline = fields.Date(related="order_id.deadline", store=True)
    location_id = fields.Many2one(related="order_id.location_id", store=True)
    state = fields.Selection(
        [("locked", "Terkunci"), ("ready_to_start", "Siap dimulai"),
         ("in_progress", "Dalam pengerjaan"), ("waiting_qc", "Menunggu QC"),
         ("done", "Selesai"), ("cancelled", "Dibatalkan")],
        default="locked",
        required=True,
        tracking=True,
    )
    sequence_no = fields.Integer(string="No. Urut", default=0, tracking=True)
    planned_start = fields.Date(string="Rencana Mulai")
    schedule_approved = fields.Boolean(string="Jadwal Disetujui", tracking=True, copy=False)
    cancel_reason = fields.Text(string="Alasan Pembatalan", copy=False)
    approved_by = fields.Many2one("res.users", string="Disetujui Oleh", readonly=True, copy=False)
    cond_preview = fields.Boolean(string="Preview Disetujui", compute="_compute_conditions")
    cond_schedule = fields.Boolean(string="Jadwal Disetujui", compute="_compute_conditions")
    cond_stock = fields.Boolean(string="Stok Cukup", compute="_compute_conditions")
    missing_text = fields.Text(string="Syarat Belum Terpenuhi", compute="_compute_conditions")
    material_ids = fields.One2many("elni.work.order.material", "work_order_id", string="Bahan")
    qc_ids = fields.One2many("elni.quality.check", "work_order_id", string="Quality Check")
    qc_state = fields.Selection(
        [("none", "-"), ("pending", "Menunggu QC"), ("passed", "Lolos"), ("failed", "Gagal")],
        default="none",
        tracking=True,
    )
    is_reprint = fields.Boolean(string="SPK Cetak Ulang", readonly=True, copy=False)
    reprint_of_id = fields.Many2one("elni.work.order", string="Cetak Ulang dari", readonly=True, copy=False)
    start_date = fields.Datetime(readonly=True, copy=False)
    done_date = fields.Datetime(readonly=True, copy=False)
    on_time = fields.Boolean(string="Tepat Waktu", compute="_compute_on_time", store=True)

    @api.depends("done_date", "deadline")
    def _compute_on_time(self):
        for rec in self:
            rec.on_time = bool(rec.done_date and rec.deadline and rec.done_date.date() <= rec.deadline)

    @api.depends("order_id.preview_status", "schedule_approved", "material_ids.qty_planned",
                 "material_ids.product_id", "location_id")
    def _compute_conditions(self):
        quant = self.env["elni.stock.quant"]
        for rec in self:
            rec.cond_preview = rec.order_id.preview_status == "approved"
            rec.cond_schedule = rec.schedule_approved
            short = []
            for mat in rec.material_ids:
                have = sum(
                    quant.search(
                        [("product_id", "=", mat.product_id.id), ("location_id", "=", rec.location_id.id)]
                    ).mapped("qty")
                )
                if have < mat.qty_planned:
                    short.append("%s (butuh %s, tersedia %s)" % (mat.product_id.name, mat.qty_planned, have))
            rec.cond_stock = not short
            missing = []
            if not rec.cond_preview:
                missing.append(_("Preview desain belum disetujui pelanggan."))
            if not rec.cond_schedule:
                missing.append(_("Jadwal produksi belum disetujui Manajemen."))
            if short:
                missing.append(_("Stok bahan tidak cukup: %s.", "; ".join(short)))
            rec.missing_text = "\n".join(missing)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", "Baru") == "Baru":
                vals["name"] = self.env["ir.sequence"].next_by_code("elni.work.order") or "Baru"
        records = super().create(vals_list)
        for rec in records:
            if not rec.material_ids:
                rec._generate_materials()
        return records

    def _generate_materials(self):
        for rec in self:
            needs = {}
            for line in rec.order_id.line_ids:
                for bom in line.product_id.bom_ids:
                    needs[bom.material_id] = needs.get(bom.material_id, 0.0) + bom.qty_per_unit * line.qty
            rec.write(
                {
                    "material_ids": [
                        (0, 0, {"product_id": mat.id, "qty_planned": qty, "qty_used": qty})
                        for mat, qty in needs.items()
                    ]
                }
            )

    # --------------------------------------------------------------- jadwal
    @api.model
    def action_recommend_queue(self):
        """Urutan prioritas: cetak ulang dahulu, lalu deadline terdekat, lalu pesanan lebih lama."""
        wos = self.search([("state", "in", ("locked", "ready_to_start", "in_progress"))])
        today = fields.Date.context_today(self)
        wos = wos.sorted(key=lambda w: (not w.is_reprint, w.deadline or today, w.id))
        capacity = max(self.env["elni.setting"]._get().daily_capacity, 1)
        for idx, wo in enumerate(wos):
            wo.write(
                {
                    "sequence_no": idx + 1,
                    "planned_start": today + timedelta(days=idx // capacity),
                    "schedule_approved": False,
                    "approved_by": False,
                }
            )
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Rekomendasi jadwal"),
                "message": _("%s SPK diurutkan. Jadwal menunggu persetujuan Manajemen.", len(wos)),
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def action_approve_schedule(self):
        self._require_group("elni_printing.group_elni_management", _("Manajemen"))
        for wo in self:
            if wo.state not in ("locked", "ready_to_start", "in_progress"):
                raise UserError(_("SPK %s tidak dapat dijadwalkan.", wo.name))
            if not wo.sequence_no:
                raise UserError(_("SPK %s belum memiliki nomor urut. Jalankan rekomendasi urutan.", wo.name))
        self.write({"schedule_approved": True, "approved_by": self.env.user.id})
        for wo in self:
            wo._audit("Jadwal disetujui")
        self._refresh_readiness()
        return True

    # ------------------------------------------------------------ produksi
    def _missing_conditions(self):
        self.ensure_one()
        return [m for m in (self.missing_text or "").split("\n") if m]

    def _refresh_readiness(self):
        """Keep the explicit STD state synchronized when a start condition changes."""
        self.invalidate_recordset(["cond_preview", "cond_schedule", "cond_stock", "missing_text"])
        for wo in self:
            if wo.state in ("locked", "ready_to_start"):
                wo.state = "ready_to_start" if not wo._missing_conditions() else "locked"

    def action_start(self):
        self._refresh_readiness()
        for wo in self:
            if wo.state not in ("locked", "ready_to_start"):
                raise UserError(_("SPK %s tidak berstatus Terkunci atau Siap dimulai.", wo.name))
            missing = wo._missing_conditions()
            if missing:
                raise UserError(
                    _("SPK %(name)s belum dapat dimulai:\n- %(why)s", name=wo.name, why="\n- ".join(missing))
                )
        self.write({"state": "in_progress", "start_date": fields.Datetime.now()})
        for wo in self:
            wo._audit("SPK dimulai")
            # sudo(): operator tidak memiliki hak ubah pada pesanan; transisi status dilakukan sistem.
            order = wo.order_id.sudo()
            if order.state == "confirmed":
                order.state = "in_production"
        return True

    def action_done(self):
        stock_move = self.env["elni.stock.move"]
        for wo in self:
            if wo.state != "in_progress":
                raise UserError(_("Hanya SPK berstatus Berjalan yang dapat diselesaikan."))
            for mat in wo.material_ids.filtered(lambda m: m.qty_used > 0):
                stock_move.create(
                    {
                        "move_type": "consume",
                        "product_id": mat.product_id.id,
                        "location_id": wo.location_id.id,
                        "qty": mat.qty_used,
                        "ref": wo.name,
                        "work_order_id": wo.id,
                    }
                )
            wo.write({"state": "waiting_qc", "done_date": fields.Datetime.now(), "qc_state": "pending"})
            self.env["elni.quality.check"].create({"work_order_id": wo.id})
            wo._audit("SPK selesai, menunggu QC")
        return True

    def action_cancel(self):
        for wo in self:
            if wo.state not in ("locked", "ready_to_start"):
                raise UserError(_("SPK yang sudah dimulai tidak dapat dibatalkan."))
            if not wo.cancel_reason:
                raise UserError(_("Alasan pembatalan wajib diisi."))
            wo.state = "cancelled"
            wo._audit("SPK dibatalkan")
        return True

    def _create_reprint(self):
        self.ensure_one()
        # Cetak ulang mewarisi persetujuan jadwal agar tidak menunggu antrean persetujuan baru.
        reprint = self.create(
            {
                "order_id": self.order_id.id,
                "is_reprint": True,
                "reprint_of_id": self.id,
                "sequence_no": 1,
                "planned_start": fields.Date.context_today(self),
                "schedule_approved": True,
                "approved_by": self.approved_by.id,
            }
        )
        reprint._audit("SPK cetak ulang dibentuk dari %s" % self.name)
        return reprint

    def action_close_after_qc(self, passed):
        """Close a work order after QC, regardless of result; failures get a reprint."""
        for wo in self:
            if wo.state != "waiting_qc":
                raise UserError(_("SPK harus berstatus Menunggu QC untuk ditutup."))
            wo.state = "done"
            wo._audit("SPK ditutup setelah QC %s" % (_("lolos") if passed else _("gagal")))
        return True


class ElniWorkOrderMaterial(models.Model):
    _name = "elni.work.order.material"
    _description = "Bahan SPK"

    work_order_id = fields.Many2one("elni.work.order", required=True, ondelete="cascade")
    product_id = fields.Many2one(
        "elni.product", string="Bahan", required=True, domain=[("kind", "=", "material")]
    )
    qty_planned = fields.Float(string="Rencana")
    qty_used = fields.Float(string="Terpakai")
    uom = fields.Char(related="product_id.uom")
    location_id = fields.Many2one(related="work_order_id.location_id", store=True)
    done_date = fields.Datetime(related="work_order_id.done_date", store=True)
