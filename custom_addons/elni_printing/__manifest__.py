{
    "name": "PT ELNI Printing",
    "summary": "Sistem informasi percetakan PT ELNI: pesanan, SPK, QC, stok, pembelian, piutang, KPI",
    "version": "17.0.1.0.0",
    "license": "LGPL-3",
    "author": "IF3141 K03 G01",
    "category": "Manufacturing",
    "depends": ["base", "mail", "portal"],
    "application": True,
    # Urutan penting: security dahulu, lalu data dasar, view, dan menu terakhir.
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/sequences.xml",
        "data/seed_data.xml",
        "data/mail_template.xml",
        "views/master_views.xml",
        "views/order_views.xml",
        "views/production_views.xml",
        "views/stock_views.xml",
        "views/finance_views.xml",
        "views/report_admin_views.xml",
        "views/portal_templates.xml",
        "views/menus.xml",
    ],
    # Hanya dimuat jika DB dibuat tanpa --without-demo.
    "demo": ["demo/demo.xml"],
}
