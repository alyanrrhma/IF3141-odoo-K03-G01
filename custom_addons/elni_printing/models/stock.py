from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class ElniStockQuant(models.Model):
    _name = "elni.stock.quant"
    _description = "Stok per Lokasi"
    _order = "location_id, product_id"

    product_id = fields.Many2one(
        "elni.product", string="Bahan", required=True, ondelete="restrict", domain=[("kind", "=", "material")]
    )
    location_id = fields.Many2one("elni.location", string="Lokasi", required=True, ondelete="restrict")
    qty = fields.Float(string="Stok", default=0.0)
    uom = fields.Char(related="product_id.uom")
    min_stock = fields.Float(related="product_id.min_stock", string="Batas Minimum")
    is_low = fields.Boolean(string="Di Bawah Minimum", compute="_compute_is_low", store=True)

    _sql_constraints = [
        ("product_location_uniq", "unique(product_id, location_id)", "Stok bahan per lokasi harus unik."),
    ]

    @api.depends("qty", "product_id.min_stock")
    def _compute_is_low(self):
        for rec in self:
            rec.is_low = rec.qty < rec.product_id.min_stock

    @api.model
    def _update_qty(self, product, location, delta):
        quant = self.search([("product_id", "=", product.id), ("location_id", "=", location.id)], limit=1)
        if not quant:
            quant = self.create({"product_id": product.id, "location_id": location.id, "qty": 0.0})
        new_qty = quant.qty + delta
        if new_qty < -1e-9:
            raise UserError(
                _(
                    "Stok %(product)s di %(location)s tidak cukup (tersedia %(have)s, dibutuhkan %(need)s).",
                    product=product.name,
                    location=location.name,
                    have=quant.qty,
                    need=-delta,
                )
            )
        quant.qty = new_qty
        return quant

    def action_create_rfq(self):
        low = self.filtered("is_low")
        if not low:
            raise UserError(_("Pilih stok yang berada di bawah batas minimum."))
        groups = {}
        for quant in low:
            supplier = quant.product_id.supplier_id
            if not supplier:
                raise UserError(_("Bahan %s belum memiliki supplier utama.", quant.product_id.name))
            groups.setdefault((supplier, quant.location_id), self.browse())
            groups[(supplier, quant.location_id)] |= quant
        rfqs = self.env["elni.purchase"]
        for (supplier, location), quants in groups.items():
            rfqs |= rfqs.create(
                {
                    "supplier_id": supplier.id,
                    "location_id": location.id,
                    "line_ids": [
                        (
                            0,
                            0,
                            {
                                "product_id": q.product_id.id,
                                "qty": max(q.min_stock * 2 - q.qty, 1.0),
                                "price_unit": q.product_id.cost,
                            },
                        )
                        for q in quants
                    ],
                }
            )
        return {
            "type": "ir.actions.act_window",
            "name": _("RFQ"),
            "res_model": "elni.purchase",
            "view_mode": "tree,form",
            "domain": [("id", "in", rfqs.ids)],
        }


class ElniStockMove(models.Model):
    _name = "elni.stock.move"
    _description = "Pergerakan Stok"
    _order = "date desc, id desc"

    date = fields.Datetime(default=fields.Datetime.now, required=True)
    move_type = fields.Selection(
        [("receipt", "Bahan Masuk"), ("transfer", "Transfer Antarcabang"), ("consume", "Pemakaian Produksi")],
        string="Jenis",
        required=True,
        default="receipt",
    )
    product_id = fields.Many2one(
        "elni.product", string="Bahan", required=True, domain=[("kind", "=", "material")]
    )
    location_id = fields.Many2one(
        "elni.location", string="Lokasi (Tujuan / Asal)", required=True,
        help="Bahan masuk: lokasi tujuan. Transfer dan pemakaian: lokasi asal.",
    )
    dest_location_id = fields.Many2one("elni.location", string="Lokasi Tujuan Transfer")
    qty = fields.Float(string="Jumlah", required=True)
    uom = fields.Char(related="product_id.uom")
    ref = fields.Char(string="Referensi")
    purchase_id = fields.Many2one("elni.purchase", string="Pembelian", ondelete="set null")
    work_order_id = fields.Many2one("elni.work.order", string="SPK", ondelete="set null")
    user_id = fields.Many2one("res.users", default=lambda self: self.env.user, readonly=True)
    note = fields.Char(string="Catatan")

    _sql_constraints = [("qty_positive", "check(qty > 0)", "Jumlah harus lebih dari 0.")]

    @api.constrains("move_type", "location_id", "dest_location_id")
    def _check_transfer(self):
        for rec in self:
            if rec.move_type == "transfer":
                if not rec.dest_location_id:
                    raise ValidationError(_("Transfer harus memiliki lokasi tujuan."))
                if rec.dest_location_id == rec.location_id:
                    raise ValidationError(_("Lokasi asal dan tujuan transfer tidak boleh sama."))

    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        quant = self.env["elni.stock.quant"]
        for move in moves:
            if move.move_type == "receipt":
                quant._update_qty(move.product_id, move.location_id, move.qty)
            elif move.move_type == "consume":
                quant._update_qty(move.product_id, move.location_id, -move.qty)
            else:
                quant._update_qty(move.product_id, move.location_id, -move.qty)
                quant._update_qty(move.product_id, move.dest_location_id, move.qty)
        locations = moves.mapped("location_id") | moves.mapped("dest_location_id")
        self.env["elni.work.order"].search([
            ("state", "in", ("locked", "ready_to_start")),
            ("location_id", "in", locations.ids),
        ])._refresh_readiness()
        return moves
