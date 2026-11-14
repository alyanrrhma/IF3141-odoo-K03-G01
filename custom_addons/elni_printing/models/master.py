from odoo import api, fields, models


class ElniLocation(models.Model):
    _name = "elni.location"
    _description = "Lokasi / Cabang"
    _order = "name"

    name = fields.Char(string="Nama", required=True)
    code = fields.Char(string="Kode", required=True)
    address = fields.Char(string="Alamat")
    active = fields.Boolean(default=True)

    _sql_constraints = [("code_uniq", "unique(code)", "Kode lokasi harus unik.")]


class ElniProduct(models.Model):
    _name = "elni.product"
    _description = "Produk Cetak / Bahan Baku"
    _order = "kind, name"

    name = fields.Char(string="Nama", required=True)
    kind = fields.Selection(
        [("print", "Produk Cetak"), ("material", "Bahan Baku")], string="Jenis", required=True, default="print"
    )
    uom = fields.Char(string="Satuan", default="pcs", required=True)
    price = fields.Float(string="Harga Jual (Rp)", digits=(16, 2))
    cost = fields.Float(string="Harga Beli (Rp)", digits=(16, 2))
    min_stock = fields.Float(string="Batas Minimum Stok")
    supplier_id = fields.Many2one("res.partner", string="Supplier Utama")
    bom_ids = fields.One2many("elni.product.bom", "product_id", string="Kebutuhan Bahan")
    total_stock = fields.Float(string="Total Stok", compute="_compute_total_stock")
    active = fields.Boolean(default=True)

    _sql_constraints = [("name_uniq", "unique(name)", "Nama produk harus unik.")]

    def _compute_total_stock(self):
        quant = self.env["elni.stock.quant"]
        for rec in self:
            rec.total_stock = sum(quant.search([("product_id", "=", rec.id)]).mapped("qty"))


class ElniProductBom(models.Model):
    _name = "elni.product.bom"
    _description = "Kebutuhan Bahan per Unit Produk"

    product_id = fields.Many2one(
        "elni.product", string="Produk Cetak", required=True, ondelete="cascade", domain=[("kind", "=", "print")]
    )
    material_id = fields.Many2one(
        "elni.product", string="Bahan Baku", required=True, domain=[("kind", "=", "material")]
    )
    qty_per_unit = fields.Float(string="Qty per Unit", required=True, default=1.0, digits=(16, 4))
    uom = fields.Char(related="material_id.uom")

    _sql_constraints = [("qty_positive", "check(qty_per_unit > 0)", "Qty per unit harus lebih dari 0.")]
