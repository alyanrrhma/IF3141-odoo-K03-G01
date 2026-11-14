import base64
from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError
from odoo.tests.common import TransactionCase

PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n")


class TestElniFlow(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.admin = cls.env.ref("base.user_admin")  # anggota semua group ELNI
        cls.pasteur = cls.env.ref("elni_printing.loc_pasteur")
        cls.paper = cls.env.ref("elni_printing.mat_art_paper")
        cls.ink = cls.env.ref("elni_printing.mat_ink")
        cls.brosur = cls.env.ref("elni_printing.prd_brosur")
        cls.partner = cls.env["res.partner"].create({"name": "Pelanggan Test"})
        cls.supplier = cls.env["res.partner"].create({"name": "Supplier Test"})
        move = cls.env["elni.stock.move"]
        move.create({"move_type": "receipt", "product_id": cls.paper.id, "location_id": cls.pasteur.id, "qty": 1000})
        move.create({"move_type": "receipt", "product_id": cls.ink.id, "location_id": cls.pasteur.id, "qty": 10})

    def _order(self, qty=100):
        order = self.env["elni.order"].with_user(self.admin).create(
            {
                "partner_id": self.partner.id,
                "location_id": self.pasteur.id,
                "deadline": fields.Date.today() + timedelta(days=7),
                "line_ids": [(0, 0, {"product_id": self.brosur.id, "qty": qty, "price_unit": 3500})],
            }
        )
        order.action_confirm()
        return order

    def _ready_wo(self, order):
        wo = order.workorder_ids
        self.env["elni.design.preview"].create(
            {"order_id": order.id, "file": PNG, "filename": "p.png"}
        ).action_approve()
        wo.sequence_no = 1
        wo.with_user(self.admin).action_approve_schedule()
        return wo

    def _quant(self, product):
        return self.env["elni.stock.quant"].search(
            [("product_id", "=", product.id), ("location_id", "=", self.pasteur.id)]
        ).qty

    def test_confirm_creates_locked_wo(self):
        order = self._order()
        self.assertEqual(order.state, "confirmed")
        self.assertEqual(order.workorder_ids.state, "locked")
        self.assertEqual(len(order.workorder_ids.material_ids), 2)

    def test_start_blocked_until_conditions_met(self):
        order = self._order()
        wo = order.workorder_ids
        with self.assertRaises(UserError):
            wo.action_start()
        self._ready_wo(order)
        wo.action_start()
        self.assertEqual(wo.state, "in_progress")

    def test_start_blocked_when_stock_short(self):
        order = self._order(qty=999999)
        wo = self._ready_wo(order)
        self.assertFalse(wo.cond_stock)
        with self.assertRaises(UserError):
            wo.action_start()

    def test_full_flow_ready_and_consumption(self):
        order = self._order()
        wo = self._ready_wo(order)
        wo.action_start()
        wo.action_done()
        self.assertEqual(self._quant(self.paper), 900)
        qc = wo.qc_ids
        with self.assertRaises(UserError):
            qc.action_pass()  # checklist belum lengkap
        qc.write({"check_size": True, "check_color": True, "check_finishing": True, "check_qty": True})
        qc.action_pass()
        self.assertEqual(order.state, "ready")
        delivery = self.env["elni.delivery"].search([("order_id", "=", order.id)])
        delivery.action_confirm_received()
        self.assertEqual(order.state, "delivered")
        invoice = self.env["elni.invoice"].search([("order_id", "=", order.id)])
        self.assertEqual(invoice.amount_total, 350000)
        invoice.action_register_payment()
        with self.assertRaises(UserError):
            invoice.action_register_payment()

    def test_qc_fail_creates_reprint(self):
        order = self._order()
        wo = self._ready_wo(order)
        wo.action_start()
        wo.action_done()
        qc = wo.qc_ids
        with self.assertRaises(UserError):
            qc.action_fail()  # alasan wajib
        qc.reprint_reason = "Warna pudar"
        qc.action_fail()
        self.assertTrue(qc.reprint_id.is_reprint)
        self.assertNotEqual(order.state, "ready")

    def test_cancel_only_before_start(self):
        order = self._order()
        wo = self._ready_wo(order)
        wo.action_start()
        with self.assertRaises(UserError):
            wo.action_cancel()

    def test_schedule_priority(self):
        near = self._order()
        far = self._order()
        far.deadline = fields.Date.today() + timedelta(days=30)
        self.env["elni.work.order"].action_recommend_queue()
        self.assertLess(near.workorder_ids.sequence_no, far.workorder_ids.sequence_no)

    def test_stock_cannot_go_negative(self):
        with self.assertRaises(UserError):
            self.env["elni.stock.move"].create(
                {"move_type": "consume", "product_id": self.ink.id, "location_id": self.pasteur.id, "qty": 999}
            )

    def test_purchase_approval_threshold(self):
        po = self.env["elni.purchase"].with_user(self.admin).create(
            {
                "supplier_id": self.supplier.id,
                "location_id": self.pasteur.id,
                "line_ids": [(0, 0, {"product_id": self.paper.id, "qty": 10000, "price_unit": 1500})],
            }
        )
        self.assertTrue(po.needs_approval)
        po.action_send()
        po.action_confirm()
        self.assertEqual(po.state, "to_approve")
        po.action_approve()
        self.assertEqual(po.state, "confirmed")
        po.action_receive()
        self.assertEqual(self._quant(self.paper), 11000)

    def test_small_purchase_skips_approval(self):
        po = self.env["elni.purchase"].create(
            {
                "supplier_id": self.supplier.id,
                "location_id": self.pasteur.id,
                "line_ids": [(0, 0, {"product_id": self.paper.id, "qty": 10, "price_unit": 1500})],
            }
        )
        po.action_send()
        po.action_confirm()
        self.assertEqual(po.state, "confirmed")

    def test_approve_requires_role(self):
        user = self.env["res.users"].create(
            {"name": "Op", "login": "op_t", "groups_id": [(6, 0, [self.env.ref("elni_printing.group_elni_operator").id])]}
        )
        po = self.env["elni.purchase"].create(
            {
                "supplier_id": self.supplier.id,
                "location_id": self.pasteur.id,
                "state": "to_approve",
                "line_ids": [(0, 0, {"product_id": self.paper.id, "qty": 1, "price_unit": 1})],
            }
        )
        with self.assertRaises(AccessError):
            po.with_user(user).action_approve()
