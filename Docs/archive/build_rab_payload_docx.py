"""
RAB Payload PyroScan — dokumen terpisah, fokus HANYA payload + pasangan LoRa posko.
Jalankan: python Docs/build_rab_payload_docx.py
"""

from pathlib import Path
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

OUT = Path(__file__).resolve().parent / "RAB_Payload_PyroScan.docx"
FONT = "Arial"
HDR_BG = "D9D9D9"


def set_cell_bg(cell, hexcolor):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hexcolor)
    tcPr.append(shd)


def style_run(run, size=Pt(11), bold=False, italic=False):
    run.font.name = FONT
    run.font.size = size
    run.bold = bold
    run.italic = italic
    rpr = run._element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        rpr.append(rf)
    for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rf.set(qn(a), FONT)


def para(doc, text="", size=Pt(11), bold=False, italic=False, align=None,
         after=7, before=0):
    p = doc.add_paragraph()
    if align is not None:
        p.alignment = align
    p.paragraph_format.space_after = Pt(after)
    p.paragraph_format.space_before = Pt(before)
    if text:
        style_run(p.add_run(text), size=size, bold=bold, italic=italic)
    return p


def h1(doc, t):
    para(doc, t, size=Pt(15), bold=True, before=15, after=7)


def h2(doc, t):
    para(doc, t, size=Pt(13), bold=True, before=11, after=5)


def caption(doc, t):
    para(doc, t, size=Pt(9), italic=True, align=WD_ALIGN_PARAGRAPH.CENTER, after=12)


def table(doc, headers, rows, widths=None, numcols=()):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(headers):
        c = t.rows[0].cells[i]
        c.text = ""
        p = c.paragraphs[0]
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.space_before = Pt(2)
        style_run(p.add_run(h), size=Pt(9.5), bold=True)
        set_cell_bg(c, HDR_BG)
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            p = cells[i].paragraphs[0]
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.space_before = Pt(2)
            if i in numcols:
                p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            bold = str(v).startswith(("Rp", "SUBTOTAL", "TOTAL")) and i in numcols
            style_run(p.add_run(str(v)), size=Pt(9.5), bold=bold)
    if widths:
        for r in t.rows:
            for i, w in enumerate(widths):
                r.cells[i].width = Cm(w)
    para(doc, "", after=5)
    return t


def add_image(doc, rel_path, cap, width_cm=15.5):
    p = Path(__file__).resolve().parent / rel_path
    if not p.exists():
        caption(doc, f"{cap} — (berkas tidak ditemukan: {rel_path})")
        return
    doc.add_picture(str(p), width=Cm(width_cm))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    caption(doc, cap)


doc = Document()
s = doc.sections[0]
s.left_margin = Cm(2.0)
s.right_margin = Cm(2.0)
s.top_margin = Cm(1.8)
s.bottom_margin = Cm(1.8)
doc.styles["Normal"].font.name = FONT
doc.styles["Normal"].font.size = Pt(11)
doc.styles["Normal"]._element.rPr.rFonts.set(qn("w:eastAsia"), FONT)

para(doc, "RAB Payload PyroScan", size=Pt(20), bold=True,
     align=WD_ALIGN_PARAGRAPH.CENTER, after=3)
para(doc, "Rencana Anggaran Biaya Modul Payload dan Link LoRa",
     size=Pt(11), italic=True, align=WD_ALIGN_PARAGRAPH.CENTER, after=4)
para(doc, "Tanggal: 16 November 2026", size=Pt(9.5),
     align=WD_ALIGN_PARAGRAPH.CENTER, after=14)

para(doc,
     "Dokumen ini hanya menghitung komponen yang HARUS DIBELI untuk modul payload dan "
     "link telemetri LoRa. Perangkat yang sudah dimiliki (laptop, ponsel), perangkat lunak "
     "open source, drone, uji lapangan, dan dokumentasi TIDAK dihitung di sini. Semua angka "
     "adalah estimasi pasar per November 2026, bukan penawaran vendor, dan wajib divalidasi "
     "dengan penawaran nyata.", italic=True)

# ---------------------------------------------------------------- 1
h1(doc, "1. Ruang Lingkup")
add_image(doc, "rab_assets/fig5_sudah_ada_vs_beli.png",
          "Gambar 1. Perbandingan fungsi yang sudah tersedia di ponsel Realme 3 Pro dengan "
          "komponen yang harus dibeli. Ponsel menutup sebagian besar fungsi; radio jarak jauh "
          "menjadi satu-satunya celah yang benar-benar perlu diisi.")

para(doc, "Yang termasuk dalam RAB ini:")
para(doc, "Casing dan mekanik payload: filamen PETG untuk tray dan baffle kamera, "
          "rubber damper, velcro, sekrup dan insert.")
para(doc, "Link telemetri LoRa: dua node radio (satu di drone, satu di posko), antena, "
          "kabel jumper, kabel OTG, dan UBEC untuk catu daya.")
para(doc, "Yang TIDAK termasuk: laptop ground station, ponsel Realme 3 Pro, drone, sewa "
          "drone, biaya uji lapangan, dokumentasi, dan lisensi perangkat lunak.")

# ---------------------------------------------------------------- 2
h1(doc, "2. Asumsi")
para(doc,
     "Komponen yang sudah dimiliki dan karena itu tidak dibeli: ponsel Realme 3 Pro "
     "(termasuk kamera 16 MP, GNSS multi-sistem, CPU/GPU/DSP, baterai 4000 mAh, dan Wi-Fi), "
     "laptop Lenovo LOQ RTX 4060, serta seluruh perangkat lunak (NodeODM, Ollama, Qwen, "
     "CesiumJS, FastAPI, Python) yang berlisensi nol biaya.")
para(doc,
     "GPS eksternal tidak dibeli. Realme 3 Pro sudah memiliki GNSS multi-sistem yang cukup "
     "untuk geotagging EXIF. Pada spike Brighton Beach, posisi EXIF ponsel berhasil "
     "meng-align 18 dari 18 foto. Modul radio tidak memiliki GPS terintegrasi, dan itu "
     "disengaja: ponsel sudah menyediakan posisi, sehingga tidak perlu membayar GPS kedua.")
para(doc,
     "Dua node radio diperlukan karena satu link radio butuh dua ujung: satu terpasang di "
     "payload, satu terhubung ke laptop posko lewat USB. Modul yang dipilih adalah EBYTE "
     "E22-900T22D karena berinterface UART dengan pin header DIP, sehingga tidak memerlukan "
     "solder SMD dan hanya butuh empat kabel. Satu unit ESP32-S3-Zero sudah tersedia, "
     "sehingga hanya satu unit tambahan yang dibeli.")
para(doc,
     "Band frekuensi: Indonesia memakai wilayah AS923 pada 920 sampai 923 MHz. Modul dan "
     "antena WAJIB varian 923 MHz, bukan 433 MHz atau 868 MHz. Status verifikasi regulasi ke "
     "SDPPI masih terbuka dan menjadi decision gate tersendiri.", italic=True)

# ---------------------------------------------------------------- 3
h1(doc, "3. Daftar Belanja")
add_image(doc, "rab_assets/fig3_biaya_komponen.png",
          "Gambar 2. Rincian biaya per komponen. Modul radio adalah pos terbesar, disusul "
          "struktur payload dan kontingensi. Seluruh angka adalah estimasi pasar.")

COST_HDR = ["No", "Komponen", "Spesifikasi", "Qty", "Harga Satuan", "Subtotal",
            "Keterangan / Sumber"]
W = [1.0, 3.6, 4.4, 1.0, 2.2, 2.2, 3.2]
NC = (4, 5)

para(doc, "Kelompok A, Struktur dan Mekanik Payload", bold=True)
table(doc, COST_HDR,
      [["A1", "Filamen PETG", "1 kg, 1,75 mm, hitam", "1", "Rp 185.000", "Rp 185.000",
        "Tokopedia Nov 2026 (Rp 147.000-260.000)"],
       ["A2", "Rubber damper ball", "Anti-vibrasi 12x4x11,7 mm, paket 4", "1 set",
        "Rp 60.000", "Rp 60.000", "Tokopedia / toko drone"],
       ["A3", "Velcro / dual-lock tape", "3M Dual Lock atau velcro industri, 1 m", "1",
        "Rp 45.000", "Rp 45.000", "Estimasi toko bangunan"],
       ["A4", "Sekrup, heat insert, standoff", "M3 set + heat insert + standoff nilon",
        "1 set", "Rp 85.000", "Rp 85.000", "Estimasi online"],
       ["", "SUBTOTAL Kelompok A", "", "", "", "Rp 375.000", ""]],
      widths=W, numcols=NC)

para(doc, "Kelompok B, Link Telemetri LoRa (drone + posko)", bold=True)
para(doc,
     "Modul yang dipilih: EBYTE E22-900T22D, varian DIP dengan pin header dan interface "
     "UART. Dipilih karena tidak perlu solder SMD dan hanya butuh 4 kabel (TX, RX, VCC, GND) "
     "berbeda dari varian SPI yang butuh 8 kabel dan driver register SX1262.", italic=True)
table(doc, COST_HDR,
      [["B1", "EBYTE E22-900T22D", "SX1262, UART, 22 dBm, DIP header, 923 MHz",
        "2", "Rp 375.000", "Rp 750.000",
        "Tokopedia Nov 2026. Satu untuk drone, satu untuk posko"],
       ["B2", "ESP32-S3-Zero kedua", "ESP32-S3FH4R2, 4 MB flash, 2 MB PSRAM, 240 MHz",
        "1", "Rp 99.000", "Rp 99.000",
        "Hanya satu yang perlu dibeli, satu sudah dimiliki"],
       ["B3", "Antena LoRa 923 MHz", "SMA, 3 dBi, whip vertikal, band 920-923 MHz",
        "2", "Rp 45.000", "Rp 90.000",
        "Tokopedia. WAJIB band 923 MHz, bukan 433/868"],
       ["B4", "Kabel jumper Dupont", "Female-female, 20 cm, 1 set", "1", "Rp 20.000",
        "Rp 20.000", "Menghubungkan Zero ke E22 (4 kabel per node)"],
       ["B5", "UBEC 5V 3A", "Input 2-6S, output 5V 3A teregulasi", "1", "Rp 57.000",
        "Rp 57.000", "Tokopedia (BlueSky / BEC mini 3A)"],
       ["B6", "Kabel OTG USB-C", "USB-C ke USB-A female, dengan strain relief", "1",
        "Rp 40.000", "Rp 40.000", "Estimasi"],
       ["B7", "Konektor XT30, fuse, kabel silikon", "XT30, sekring, kabel AWG 20, heat shrink",
        "1 set", "Rp 75.000", "Rp 75.000", "Estimasi toko RC"],
       ["", "SUBTOTAL Kelompok B", "", "", "", "Rp 1.131.000", ""]],
      widths=W, numcols=NC)

para(doc, "Kelompok C, Opsional", bold=True)
table(doc, COST_HDR,
      [["C1", "Power bank 10.000 mAh", "5V/2A, untuk node posko", "1", "Rp 185.000",
        "Rp 185.000", "Hanya jika posko tidak punya daya listrik"],
       ["", "SUBTOTAL Kelompok C", "", "", "", "Rp 185.000", ""]],
      widths=W, numcols=NC)

# ---------------------------------------------------------------- 4
h1(doc, "4. Ringkasan Biaya")

para(doc, "a. Total belanja", bold=True)
table(doc, ["Kelompok", "Isi", "Subtotal"],
      [["A", "Struktur dan mekanik payload", "Rp 375.000"],
       ["B", "Link telemetri LoRa (2 node)", "Rp 1.131.000"],
       ["", "SUBTOTAL WAJIB", "Rp 1.506.000"],
       ["H", "Kontingensi 12 persen", "Rp 180.720"],
       ["", "TOTAL WAJIB DIBELI", "Rp 1.686.720"],
       ["C", "Opsional: power bank", "Rp 185.000"],
       ["", "TOTAL bila pakai power bank", "Rp 1.893.840"]],
      widths=[2.2, 8.5, 4.3], numcols=(2,))

para(doc, "b. Biaya per tahap", bold=True)
table(doc, ["Tahap", "Komponen", "Estimasi"],
      [["Tahap 1: struktur payload", "A1 sampai A4 (PETG, damper, velcro, sekrup)",
        "Rp 375.000"],
       ["Tahap 2: link LoRa", "B1 sampai B7 (2 modul E22, Zero kedua, antena, UBEC, kabel)",
        "Rp 1.131.000"],
       ["Kontingensi 12 persen", "Cadangan kenaikan harga", "Rp 180.720"],
       ["TOTAL", "", "Rp 1.686.720"]],
      widths=[3.6, 8.0, 3.4], numcols=(2,))
para(doc,
     "Tahap 1 bisa dikerjakan lebih dulu karena hanya perlu printer 3D dan damper. Tahap 2 "
     "menunggu keputusan DG-02 tentang regulasi frekuensi LoRa. Keduanya tidak saling "
     "mengunci.", italic=True)

para(doc, "c. Perbandingan pilihan modul LoRa", bold=True)
add_image(doc, "rab_assets/fig4_perbandingan.png",
          "Gambar 3. Perbandingan empat pilihan modul LoRa. Dua pilihan termurah memerlukan "
          "solder SMD. Yang dipilih adalah E22-900T22D: berheader DIP sehingga tidak perlu "
          "solder, dengan selisih biaya yang wajar dibanding Heltec.")
table(doc, ["Pilihan", "Interface", "Perlu solder?", "Subtotal 2 node", "Total + kontingensi"],
      [["ESP32-S3-Zero + E22-900T22D (DIP)  [DIPILIH]",
        "UART, 4 kabel", "Tidak", "Rp 1.131.000", "Rp 1.686.720"],
       ["Heltec LoRa32 V3 (LoRa + OLED satu board)",
        "UART internal", "Tidak", "Rp 1.292.000", "Rp 1.927.040"],
       ["ESP32-S3-Zero + E22-900T22S (SMD)",
        "UART, 4 kabel", "Ya, SMD", "Rp 956.000", "Rp 1.430.720"],
       ["ESP32-S3-Zero + E22-900M22S (SMD, SPI)",
        "SPI, 8 kabel + driver", "Ya, SMD", "Rp 774.000", "Rp 1.158.880"]],
      widths=[5.5, 2.6, 2.2, 2.4, 2.8])
para(doc,
     "Pilihan pertama diambil karena menyatukan dua keunggulan: ESP32-S3-Zero sudah dimiliki "
     "(hemat satu unit), dan E22-900T22D berheader DIP sehingga tidak perlu solder sama sekali. "
     "Hemat sekitar Rp 240.000 dibanding Heltec, dengan tingkat kesulitan yang sama rendah.",
     italic=True)

para(doc, "d. Barang yang tidak perlu dibeli", bold=True)
table(doc, ["Komponen", "Alasan tidak dibeli"],
      [["Ponsel Realme 3 Pro", "Sudah dimiliki. Sudah menyediakan kamera 16 MP, GNSS "
        "multi-sistem, pemroses untuk YOLOv8n, baterai, dan Wi-Fi"],
       ["ESP32-S3-Zero (unit pertama)", "Sudah dimiliki. Dipakai sebagai node"],
       ["GPS eksternal (u-blox NEO-M9N dan sejenisnya)",
        "GNSS ponsel sudah cukup untuk geotag EXIF. Bukti: 18/18 foto ter-align pada spike "
        "Brighton. Beli hanya jika uji lapangan membuktikan posisi EXIF gagal"],
       ["Laptop Lenovo LOQ RTX 4060", "Sudah dimiliki"],
       ["Drone dan sewa drone", "Di luar lingkup RAB payload ini"],
       ["NodeODM, Ollama, Qwen, CesiumJS, FastAPI, Python",
        "Open source, biaya lisensi nol"],
       ["Gateway dan network server LoRaWAN",
        "Berlebihan untuk satu drone. Cukup point-to-point"],
       ["Modul LoRa 433 MHz", "Band salah untuk Indonesia dan jangkauannya lebih buruk"],
       ["Pigtail U.FL ke SMA", "E22-900T22D sudah memakai konektor SMA langsung"]],
      widths=[5.5, 9.5])

# ---------------------------------------------------------------- 5
h1(doc, "5. Catatan Teknis yang Menentukan Keberhasilan")

add_image(doc, "rab_assets/fig1_alur_data.png",
          "Gambar 4. Alur data dari payload di udara sampai dashboard posko. Dua jalur "
          "berbeda: foto berukuran besar tetap di ponsel dan dipindah lewat Wi-Fi setelah "
          "mendarat, sedangkan metadata ringkas dikirim langsung lewat LoRa.")

add_image(doc, "rab_assets/fig2_paket_data.png",
          "Gambar 5. Isi paket LoRa dan alasan foto tidak bisa melewatinya. LoRa hanya "
          "membawa metadata terstruktur setiap 5 sampai 10 detik; satu misi 30 menit "
          "menghasilkan sekitar 900 foto atau 3 sampai 4 GB yang tetap tersimpan di ponsel.",
          width_cm=14.5)

para(doc, "a. Frekuensi dan regulasi", bold=True)
para(doc,
     "Indonesia memakai wilayah AS923 pada 920 sampai 923 MHz. Beli varian 923 MHz pada "
     "modul dan antena, karena antena harus tunning pada band yang sama. Status verifikasi ke "
     "SDPPI masih terbuka. Jangan cetak enclosure final atau pesan antena sebelum frekuensi "
     "dikonfirmasi.")

para(doc, "b. Pemasangan antena", bold=True)
para(doc,
     "Antena harus vertikal, di atas drone, dan jauh dari serat karbon serta pemancar video "
     "2,4 atau 5,8 GHz. Serat karbon memblokir sinyal radio.")

para(doc, "c. Catu daya", bold=True)
para(doc,
     "UBEC 5V 3A dengan ground bersama dan sekring. Puncak transmit LoRa sekitar 100 sampai "
     "120 mA. Beban terbesar tetap ponsel, bukan radio.")

para(doc, "d. Sambungan ke ponsel", bold=True)
para(doc,
     "Node payload tersusun dari ESP32-S3-Zero yang disambung ke E22-900T22D lewat empat "
     "kabel jumper (TX, RX, VCC 3,3V, GND). Zero kemudian tersambung ke Realme 3 Pro lewat "
     "kabel OTG USB-C sebagai perangkat serial. Karena aplikasi payload belum dibangun, sisi "
     "perangkat lunak ini adalah pekerjaan baru, bukan sekadar pembelian komponen. Sisi "
     "perangkat kerasnya justru sederhana: tanpa solder, tanpa driver register SPI.")
para(doc,
     "Catatan E22-900T22D: modul ini memakai UART dengan mode konfigurasi M0 dan M1. Kirim "
     "data lewat TX/RX, dan gunakan M0/M1 hanya saat mengubah parameter radio. Jangan hubung "
     "M0/M1 ke tegangan tetap, karena modul akan tersangkut di mode konfigurasi.", italic=True)

para(doc, "e. Ukuran paket data", bold=True)
para(doc,
     "LoRa lambat. Kirim JSON atau biner ringkas setiap 5 sampai 10 detik dan setiap ada "
     "deteksi. Isinya: node_id, mission_id, waktu, lat, lon, altitud, status fix, jumlah "
     "satelit, hdop, kelas, confidence, bbox, heading, pitch, roll. Gambar tetap disimpan di "
     "ponsel dan dipindah lewat Wi-Fi setelah mendarat.")

para(doc, "f. Koordinat api bukan koordinat drone", bold=True)
para(doc,
     "GPS memberi posisi drone atau ponsel. Koordinat api dihitung dengan memproyeksikan "
     "kotak deteksi YOLO melalui pose kamera ke permukaan tanah atau DSM, atau dari "
     "orthophoto. Jangan memberi label titik GPS drone sebagai titik api. LoRa hanya "
     "mengirimkan hasil, bukan menentukan lokasi api.")

para(doc, "g. Jangkauan", bold=True)
para(doc,
     "Perkiraan 2 sampai 10 km dengan pandangan langsung pada daya 20 dBm. Di dalam hutan "
     "atau perkotaan jauh lebih pendek. Gunakan spreading factor SF9 atau SF10 untuk "
     "keandalan, dan uji jangkauan sebelum penerbangan sebenarnya.")

# ---------------------------------------------------------------- 6
h1(doc, "6. Sumber Harga")
table(doc, ["Komponen", "Sumber dan rentang (November 2026)"],
      [["EBYTE E22-900T22D (UART, DIP)",
        "Tokopedia, sekitar Rp 375.000. Varian SPI (900M22S) sekitar Rp 109.000-250.000, "
        "varian UART SMD (900T22S) sekitar Rp 200.000"],
       ["ESP32-S3-Zero (Waveshare)",
        "Tokopedia Rp 99.000-377.000; Shopee Rp 377.000. Board asal Waveshare $6,49"],
       ["Filamen PETG 1 kg", "Tokopedia Rp 147.000-260.000; Indocart Rp 95.000"],
       ["UBEC 5V 3A", "Tokopedia, BlueSky 3A 5V Rp 37.490-57.000; HobbyWing 3A Rp 198.000"],
       ["Antena LoRa 923 MHz 3 dBi", "Tokopedia, Rp 14.000-45.000; pastikan band 923 MHz"],
       ["Rubber damper ball paket 4", "Tokopedia / toko drone, sekitar Rp 60.000"]],
      widths=[5.0, 10.0])
para(doc,
     "Semua angka adalah estimasi pasar, bukan penawaran resmi. Harga komponen elektronik "
     "dari luar negeri berfluktuasi mengikuti kurs dan ketersediaan stok.", italic=True)

doc.save(str(OUT))
print(f"OK -> {OUT}")
print(f"   ukuran: {OUT.stat().st_size/1024:.0f} KB  tabel: {len(doc.tables)}")
