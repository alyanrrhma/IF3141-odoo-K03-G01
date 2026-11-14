from datetime import timedelta

from odoo import api, fields, models
from odoo.tools import html_escape


class ElniKpiDashboard(models.TransientModel):
    _name = "elni.kpi.dashboard"
    _description = "Dasbor KPI"

    date_from = fields.Date(
        string="Dari", default=lambda self: fields.Date.context_today(self) - timedelta(days=90)
    )
    date_to = fields.Date(string="Sampai", default=fields.Date.context_today)
    location_id = fields.Many2one("elni.location", string="Lokasi")
    done_count = fields.Integer(string="SPK Selesai", compute="_compute_kpi")
    on_time_count = fields.Integer(string="SPK Tepat Waktu", compute="_compute_kpi")
    on_time_rate = fields.Float(string="Ketepatan Waktu (%)", compute="_compute_kpi")
    wo_count = fields.Integer(string="SPK Dibuat", compute="_compute_kpi")
    reprint_count = fields.Integer(string="Jumlah Reprint", compute="_compute_kpi")
    reprint_rate = fields.Float(string="Rasio Reprint (%)", compute="_compute_kpi")
    material_total = fields.Float(string="Total Pemakaian Bahan", compute="_compute_kpi")
    material_html = fields.Html(string="Pemakaian per Bahan", compute="_compute_kpi", sanitize=False)

    @api.depends("date_from", "date_to", "location_id")
    def _compute_kpi(self):
        wo_model = self.env["elni.work.order"]
        mat_model = self.env["elni.work.order.material"]
        for rec in self:
            start = fields.Datetime.to_datetime(rec.date_from) if rec.date_from else False
            end = fields.Datetime.to_datetime(rec.date_to) + timedelta(days=1) if rec.date_to else False
            loc = [("location_id", "=", rec.location_id.id)] if rec.location_id else []
            done_dom = [("state", "=", "done")] + loc
            created_dom = [("state", "!=", "cancelled")] + loc
            if start:
                done_dom.append(("done_date", ">=", start))
                created_dom.append(("create_date", ">=", start))
            if end:
                done_dom.append(("done_date", "<", end))
                created_dom.append(("create_date", "<", end))
            done = wo_model.search_count(done_dom)
            on_time = wo_model.search_count(done_dom + [("on_time", "=", True)])
            total = wo_model.search_count(created_dom)
            reprints = wo_model.search_count(created_dom + [("is_reprint", "=", True)])
            rec.done_count = done
            rec.on_time_count = on_time
            rec.on_time_rate = (on_time / done * 100.0) if done else 0.0
            rec.wo_count = total
            rec.reprint_count = reprints
            rec.reprint_rate = (reprints / total * 100.0) if total else 0.0
            mat_dom = [("work_order_id.state", "=", "done")] + loc
            if start:
                mat_dom.append(("done_date", ">=", start))
            if end:
                mat_dom.append(("done_date", "<", end))
            groups = mat_model.read_group(mat_dom, ["qty_used:sum"], ["product_id"])
            rec.material_total = sum(g["qty_used"] for g in groups)
            rows = "".join(
                "<tr><td>%s</td><td style='text-align:right'>%.2f</td></tr>"
                % (html_escape(g["product_id"][1]), g["qty_used"])
                for g in groups
                if g["product_id"]
            )
            rec.material_html = (
                "<table class='table table-sm'><thead><tr><th>Bahan</th><th>Terpakai</th></tr></thead>"
                "<tbody>%s</tbody></table>" % rows
            ) if rows else "<p>Belum ada pemakaian bahan pada periode ini.</p>"
