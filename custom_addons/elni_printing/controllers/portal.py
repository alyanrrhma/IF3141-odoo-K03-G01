from odoo import _, fields, http
from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.exceptions import AccessError, MissingError, UserError, ValidationError
from odoo.http import request


class ElniCustomerPortal(CustomerPortal):
    def _prepare_home_portal_values(self, counters):
        values = super()._prepare_home_portal_values(counters)
        if "elni_order_count" in counters:
            order = request.env["elni.order"]
            values["elni_order_count"] = (
                order.search_count([]) if order.check_access_rights("read", raise_exception=False) else 0
            )
        return values

    def _elni_get_order(self, order_id):
        order = request.env["elni.order"].browse(order_id).exists()
        if not order:
            return None
        try:
            order.check_access_rights("read")
            order.check_access_rule("read")
        except (AccessError, MissingError):
            return None
        return order

    @http.route("/my/elni-orders", type="http", auth="user", website=True)
    def elni_orders(self, **kw):
        orders = request.env["elni.order"].search([])
        return request.render("elni_printing.portal_elni_orders", {"orders": orders, "page_name": "elni_orders"})

    @http.route("/my/elni-orders/<int:order_id>", type="http", auth="user", website=True)
    def elni_order_detail(self, order_id, **kw):
        order = self._elni_get_order(order_id)
        if not order:
            return request.redirect("/my")
        return request.render(
            "elni_printing.portal_elni_order_detail",
            {"order": order, "page_name": "elni_orders", "error": kw.get("error")},
        )

    def _elni_decide(self, order_id, preview_id, action, note=None):
        order = self._elni_get_order(order_id)
        if not order:
            return request.redirect("/my")
        preview = order.preview_ids.filtered(lambda p: p.id == preview_id)
        error = ""
        if preview:
            try:
                # sudo(): pelanggan portal hanya boleh membaca preview; kepemilikan pesanan
                # sudah diverifikasi lewat record rule pada _elni_get_order.
                if action == "approve":
                    preview.sudo().action_portal_approve()
                else:
                    preview.sudo().action_portal_revision(note)
            except UserError as exc:
                error = exc.args[0]
        url = "/my/elni-orders/%s" % order.id
        return request.redirect(url + ("?error=%s" % error if error else ""))

    @http.route(
        "/my/elni-orders/<int:order_id>/preview/<int:preview_id>/approve",
        type="http", auth="user", methods=["POST"], website=True,
    )
    def elni_preview_approve(self, order_id, preview_id, **kw):
        return self._elni_decide(order_id, preview_id, "approve")

    @http.route(
        "/my/elni-orders/<int:order_id>/preview/<int:preview_id>/revision",
        type="http", auth="user", methods=["POST"], website=True,
    )
    def elni_preview_revision(self, order_id, preview_id, note="", **kw):
        return self._elni_decide(order_id, preview_id, "revision", note=(note or "").strip())

    @http.route("/my/elni-orders/new", type="http", auth="user", methods=["GET", "POST"], website=True)
    def elni_order_new(self, **post):
        products = request.env["elni.product"].search([("kind", "=", "print")])
        values = {"products": products, "page_name": "elni_orders", "error": None, "post": post}
        if request.httprequest.method == "POST":
            try:
                product = products.filtered(lambda p: p.id == int(post.get("product_id") or 0))
                qty = float(post.get("qty") or 0)
                deadline = fields.Date.from_string(post.get("deadline"))
                if not product or qty <= 0 or not deadline:
                    raise ValidationError(_("Produk, jumlah, dan deadline wajib diisi dengan benar."))
                partner = request.env.user.partner_id.commercial_partner_id
                # sudo(): pelanggan portal tidak memiliki hak buat pada pesanan; data dibatasi
                # ke partner milik pengguna yang sedang login dan produk yang lolos record rule.
                order = request.env["elni.order"].sudo().create(
                    {
                        "partner_id": partner.id,
                        "contact_name": request.env.user.name,
                        "contact_phone": request.env.user.partner_id.phone or "",
                        "deadline": deadline,
                        "source": "portal",
                        "note": post.get("note") or "",
                        "line_ids": [
                            (0, 0, {"product_id": product.id, "qty": qty,
                                    "price_unit": product.price, "spec": post.get("spec") or ""})
                        ],
                    }
                )
                return request.redirect("/my/elni-orders/%s" % order.id)
            except (ValueError, TypeError):
                values["error"] = _("Format jumlah atau tanggal tidak valid.")
            except (ValidationError, UserError) as exc:
                values["error"] = exc.args[0]
        return request.render("elni_printing.portal_elni_order_new", values)
