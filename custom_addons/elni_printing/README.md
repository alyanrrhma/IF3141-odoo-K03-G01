# elni_printing

Modul Odoo 17 (Community) untuk sistem informasi PT ELNI
Install: `docker compose run --rm web odoo -d odoo_app -i elni_printing --stop-after-init`.

## Akun uji

Akun berikut didefinisikan di `demo/demo.xml`; semua memakai kata sandi `demo` dan hanya untuk database lokal pengujian. Data demo mencakup pesanan, stok, RFQ, serta pelanggan portal.

| Peran | Login |
| --- | --- |
| Sales / CSO | `sales@elni.test` |
| Designer | `designer@elni.test` |
| Operator | `operator@elni.test` |
| Quality Assurance | `qa@elni.test` |
| Logistik & Pembelian | `logistik@elni.test` |
| Manager Keuangan | `fm@elni.test` |
| A/R Staff | `ar@elni.test` |
| Chief Akunting | `akunting@elni.test` |
| Manajemen | `manajemen@elni.test` |
| IT & Tech | `it@elni.test` |
| Pelanggan B2B (portal) | `pelanggan@elni.test` |

Untuk database baru, pasang modul dengan demo data aktif. Jalankan perintah ini dari root proyek:

```bash
docker compose run --rm web odoo -d odoo_demo -i elni_printing --stop-after-init
```

Perintah `web` normal pada `docker-compose.yml` memakai `--without-demo=all`, jadi perintah di atas sengaja menggantinya. Setelah instalasi selesai, jalankan Odoo terhadap database yang dipilih dan login memakai akun di atas.