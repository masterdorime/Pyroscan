"""
Build Docs/Proposal_PyroScan.docx — proposal lengkap dengan tabel asli dan gambar.

Sumber isi: Docs/proposal_sections_id.md (draf teks, sudah direview).
Jalankan:  python Docs/build_proposal_docx.py
"""

from pathlib import Path
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "Docs"
OUT = DOCS / "Proposal_PyroScan.docx"

FONT = "Arial"
BODY_SIZE = Pt(12)
H1_SIZE = Pt(16)
H2_SIZE = Pt(14)
CAP_SIZE = Pt(10)

TABLE_HEADER_BG = "D9D9D9"


# ---------------------------------------------------------------- helpers

def set_cell_bg(cell, hexcolor):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), hexcolor)
    tcPr.append(shd)


def style_run(run, size=BODY_SIZE, bold=False, italic=False, color=None):
    run.font.name = FONT
    run.font.size = size
    run.bold = bold
    run.italic = italic
    if color:
        run.font.color.rgb = RGBColor.from_string(color)
    rpr = run._element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        rpr.append(rf)
    for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
        rf.set(qn(a), FONT)


def para(doc, text="", size=BODY_SIZE, bold=False, italic=False,
         align=None, space_after=8, space_before=0):
    p = doc.add_paragraph()
    if align is not None:
        p.alignment = align
    pf = p.paragraph_format
    pf.space_after = Pt(space_after)
    pf.space_before = Pt(space_before)
    if text:
        style_run(p.add_run(text), size=size, bold=bold, italic=italic)
    return p


def h1(doc, text):
    para(doc, text, size=H1_SIZE, bold=True, space_before=16, space_after=8)


def h2(doc, text):
    para(doc, text, size=H2_SIZE, bold=True, space_before=12, space_after=6)


def caption(doc, text):
    para(doc, text, size=CAP_SIZE, italic=True,
         align=WD_ALIGN_PARAGRAPH.CENTER, space_after=14)


def add_table(doc, headers, rows, widths=None):
    t = doc.add_table(rows=1, cols=len(headers))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER

    hdr = t.rows[0].cells
    for i, htext in enumerate(headers):
        hdr[i].text = ""
        p = hdr[i].paragraphs[0]
        p.paragraph_format.space_after = Pt(2)
        p.paragraph_format.space_before = Pt(2)
        style_run(p.add_run(htext), size=Pt(10), bold=True)
        set_cell_bg(hdr[i], TABLE_HEADER_BG)

    for row in rows:
        cells = t.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = ""
            p = cells[i].paragraphs[0]
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.space_before = Pt(2)
            right = str(val).strip().endswith(("0", "IDR", "GB", "t/s", "s")) and i >= 1 and _is_numcol(headers, i)
            if right:
                p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            style_run(p.add_run(str(val)), size=Pt(10))

    if widths:
        for r in t.rows:
            for i, w in enumerate(widths):
                r.cells[i].width = Cm(w)
    para(doc, "", space_after=6)
    return t


def _is_numcol(headers, i):
    return headers[i] in ("Qty", "Harga Satuan", "Subtotal", "Decode (t/s)",
                          "Wall dingin (s)", "VRAM puncak", "Estimasi", "Total")


def add_image(doc, rel_path, cap, width_cm=15.5, missing_label=""):
    p = ROOT / rel_path
    if not p.exists():
        caption(doc, f"{cap} — (berkas tidak ditemukan: {missing_label or rel_path})")
        return
    doc.add_picture(str(p), width=Cm(width_cm))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    caption(doc, cap)


# ---------------------------------------------------------------- content

doc = Document()
sec = doc.sections[0]
sec.left_margin = Cm(2.2)
sec.right_margin = Cm(2.2)
sec.top_margin = Cm(2.0)
sec.bottom_margin = Cm(2.0)

normal = doc.styles["Normal"]
normal.font.name = FONT
normal.font.size = BODY_SIZE
normal._element.rPr.rFonts.set(qn("w:eastAsia"), FONT)

# Title block
para(doc, "PyroScan", size=Pt(22), bold=True,
     align=WD_ALIGN_PARAGRAPH.CENTER, space_after=4)
para(doc,
     "Modul Payload IoT Ekstensi Berbiaya Rendah untuk Pemetaan Lahan Hangus "
     "& Prediksi Jalur Rambatan Api",
     size=Pt(12), italic=True, align=WD_ALIGN_PARAGRAPH.CENTER, space_after=18)

# ---- 1. Pokok Masalah
h1(doc, "1. Pokok Masalah")
para(doc,
     "Kebakaran hutan dan lahan sering kali meluas dengan cepat karena keterbatasan "
     "pemantauan udara secara menyeluruh dan sulitnya memperkirakan arah pergerakan api "
     "di lapangan. Di sisi lain, merancang dan membangun wahana drone dari nol dalam "
     "proyek rekayasa membutuhkan biaya tinggi, waktu pengerjaan yang lama, serta risiko "
     "kegagalan mekanik yang besar.")
para(doc,
     "Padahal, banyak instansi maupun tim tanggap darurat sudah memiliki unit drone "
     "komersial, namun belum memiliki perangkat tambahan berbiaya rendah yang mampu "
     "memetakan batas area terbakar secara otomatis sekaligus memprediksi jalur rambatan "
     "api berikutnya berdasarkan kondisi cuaca lokal.")

# ---- 2. Ide Solusi
h1(doc, "2. Ide Solusi")
para(doc,
     "PyroScan adalah modul perangkat keras IoT berkonsep modular payload (ekstensi "
     "tambahan) yang dirancang khusus untuk dipasang pada drone yang sudah ada tanpa perlu "
     "memodifikasi sistem kendali penerbangan drone tersebut.")
para(doc,
     "Untuk menekan biaya agar sesuai dengan anggaran prototipe mahasiswa tanpa mengurangi "
     "fungsi utamanya, PyroScan menerapkan arsitektur lightweight edge-capture:")
para(doc,
     "Di Udara (Modul Ekstensi): Modul hanya bertugas mengambil citra udara area terdampak "
     "secara berkala beserta titik koordinatnya dengan bobot total di bawah 100 gram.")
para(doc,
     "Di Darat (Ground Station): Setelah drone mendarat, hasil foto diunduh ke laptop untuk "
     "digabungkan (image stitching) menjadi satu peta digital utuh, lalu dipadukan dengan "
     "data meteorologi terbuka dari BMKG (arah angin, kecepatan angin, dan kelembapan udara) "
     "menggunakan model Machine Learning untuk memprediksi arah rambatan api.")

# ---- 3. Rancangan Sistem
h1(doc, "3. Rancangan Sistem")
para(doc,
     "Bagian ini menjelaskan sistem yang benar-benar dibangun, batasan kerasnya, dan bukti "
     "pengukuran yang sudah ada.")
para(doc,
     "Catatan konsistensi: bagian 2 menyebut bobot payload di bawah 100 gram, sumber cuaca "
     "BMKG, dan model Machine Learning. Hasil kerja teknis terbaru memakai batas bobot 190 "
     "gram, sumber cuaca Open-Meteo dengan cache offline, dan simulation engine deterministik, "
     "sedangkan LLM hanya menulis laporan naratif. Bagian 3 mengikuti hasil kerja teknis "
     "terbaru; bagian 2 perlu diselaraskan menyusul.", italic=True)

# 3.1
h2(doc, "3.1. Ringkasan Sistem")
para(doc,
     "PyroScan adalah sistem pemantauan, pemetaan tiga dimensi, dan prediksi rambatan "
     "kebakaran hutan yang beroperasi penuh tanpa koneksi internet. Sistem ini tidak "
     "membangun drone dari nol, melainkan modul ekstensi yang dipasang di perut drone "
     "komersial milik instansi tanpa mengubah sistem kendali penerbangannya.")
para(doc,
     "Penggunanya ada dua: komandan posko bencana atau tim SAR yang butuh keputusan cepat "
     "soal rute evakuasi dan titik pemutus vegetasi, serta operator drone lapangan yang "
     "butuh modul ringkas dan otomatis.")
para(doc, "Alur sistem terdiri dari tiga lapisan berurutan:")
para(doc,
     "Payload di udara. Smartphone Android bekas Realme 3 Pro di dalam tray PETG cetak 3D, "
     "dipasang nadir. Mengambil foto 12 MP ber-EXIF GPS secara berkala dan mendeteksi api "
     "atau asap di on-device.")
para(doc,
     "Ground Station di darat. Laptop Lenovo LOQ dengan RTX 4060 8 GB. Menjalankan NodeODM "
     "via CUDA, verifikasi YOLO, fusi raster spasial, simulasi rambatan, dan LLM advisory lokal.")
para(doc,
     "Dashboard untuk operator. Antarmuka 3D CesiumJS yang membaca data dari SQLite lewat "
     "FastAPI, menampilkan medan rekonstruksi, hotspot, prediksi rambat, dan panel rekomendasi.")

add_image(doc, "Docs/references/ref-photogrammetry-process.png",
          "Gambar 1. Rantai pemrosesan fotogrametri digital (SfM/MVS) yang menjadi acuan "
          "tahapan di Ground Station. Sumber: gambar referensi proses fotogrametri digital "
          "(bukan hasil pengukuran PyroScan).")

para(doc,
     "Sistem mendukung dua mode misi yang berbagi satu payload, satu pipeline, dan satu "
     "basis data:")
add_table(doc,
          ["Mode", "Kapan dipakai", "Sumber data", "Yang dihasilkan"],
          [["MODE-A: Pre-Fire Monitoring",
            "Sebelum atau di depan api, area belum terbakar",
            "Foto kanopi hidup + YOLO + DEM",
            "Peta bahan bakar, lereng, vektor arah rambat"],
           ["MODE-B: Burn-Scar Mapping",
            "Pasca-kebakaran",
            "Foto permukaan hangus + DEM",
            "Luas terbakar, batas api terakhir, topografi bekas bakar"]],
          widths=[3.6, 4.0, 3.6, 4.8])

para(doc,
     "Alasan mode ganda bersifat teknis. Kanopi hutan hidup adalah subjek terburuk untuk "
     "feature matching SfM karena teksturnya berulang, homogen, dan bergerak tertiup angin. "
     "Permukaan hangus justru kaya tekstur dan statis. Dengan MODE-B, proyek tetap punya "
     "jalur sukses meski MODE-A gagal di lapangan, dan luas terbakar dari MODE-B menjadi "
     "angka validasi untuk MODE-A berikutnya.")
para(doc,
     "Batasan keras yang membentuk seluruh rancangan: offline penuh tanpa cloud, CDN, atau "
     "API berbayar; VRAM 8 GB sehingga fotogrametri dan LLM tidak boleh berbarengan; satu "
     "operator dengan SQLite dan FastAPI saja; dua bahasa saja, Python untuk pipeline dan "
     "TypeScript untuk antarmuka; bobot payload maksimum 190 gram; dan tanpa biaya berulang.")

# 3.2
h2(doc, "3.2. Arsitektur Payload")
para(doc,
     "Payload adalah Realme 3 Pro tanpa penutup belakang dengan baterai asli, dipasang pada "
     "tray PETG cetak 3D dengan empat peredam getaran karet.")
add_table(doc,
          ["Komponen", "Spesifikasi", "Fungsi"],
          [["Realme 3 Pro (RMX1851)", "Snapdragon 710, Adreno 616, Hexagon 685",
            "Unit pemrosesan: kamera, GPS, inferensi on-device"],
           ["Sensor kamera", "Sony IMX519, 16 MP (default 12 MP)",
            "Pengambilan citra nadir ber-EXIF"],
           ["GNSS", "Multi-GNSS (GPS, GLONASS, Galileo, BeiDou)",
            "Geotagging EXIF per citra"],
           ["Casing tray", "PETG cetak 3D, infill 30%, 2 perimeter",
            "Struktur pemasangan ke perut drone"],
           ["Peredam getaran", "4 buah rubber damper ball, rating 300 g",
            "Menekan getaran rotor agar citra tidak blur"],
           ["Baffle kamera", "PETG hitam 5 mm sekeliling jendela lensa",
            "Memblokir flare matahari langsung"],
           ["Sekrup, insert, velcro", "Standar", "Pengikat modul"],
           ["ESP32-WROOM-32 + SX1262", "+22 dBm, antena 3 dBi",
            "Fase 2: transmisi telemetri 16 byte"]],
          widths=[4.2, 5.6, 6.2])

para(doc,
     "Alur kerja aplikasi payload: berjalan sebagai foreground service bertipe camera dengan "
     "resolusi default 12 MP (maksimum 16 MP) dan interval 2 sampai 4 detik; menyuntikkan "
     "koordinat GPS dan waktu GNSS ke metadata EXIF setiap citra; menjalankan inferensi "
     "YOLOv8n TFLite INT8 dengan rantai delegasi yang diukur, yaitu NNAPI lalu GPU delegate "
     "FP16 lalu XNNPACK CPU INT8, di mana delegasi tercepat yang stabil saat startup dipilih "
     "dan dicatat di log; menyimpan seluruh hasil deteksi ke log lokal; dan menyediakan layar "
     "panduan karena ColorOS membunuh background service secara agresif.")
para(doc,
     "NNAPI tidak wajib berhasil. Pada Snapdragon 710, NNAPI sering memecah graf dan justru "
     "lebih lambat dari XNNPACK. Fase 1 berjalan tanpa radio, sehingga tidak ada kabel "
     "eksternal dan tidak ada titik gagal mekanis tambahan. Tray sudah dicetak dengan pocket "
     "kosong untuk modul radio agar Fase 2 tidak perlu cetak ulang.")
para(doc,
     "Bobot Fase 1 diperkirakan 186 sampai 192 gram terhadap batas keras 190 gram, artinya "
     "masih mepet dan berpotensi lewat. Setiap komponen wajib ditimbang dengan timbangan "
     "dapur 0,1 gram sebelum enclosure final dicetak. Untuk Fase 2, dengan tambahan ESP32, "
     "modul LoRa, antena, dan kabel OTG, bobot naik ke 215 sampai 221 gram dan melampaui batas.")
para(doc,
     "Beban capture 12 MP setiap 2 detik ditambah inferensi kontinu memanaskan sensor dan ISP, "
     "dengan throttling diperkirakan muncul setelah 8 sampai 12 menit. Karena mode host OTG "
     "tidak bisa mengisi daya, batas misi per baterai diperkirakan 35 sampai 45 menit. Aturan "
     "operasional: layar dimatikan, airplane mode aktif kecuali saat sinkronisasi, dan jeda 30 "
     "detik setiap 5 menit bila suhu baterai melewati 42 derajat Celsius.")

# 3.3
h2(doc, "3.3. Arsitektur Ground Station")
para(doc,
     "Ground Station adalah laptop Lenovo LOQ yang menjalankan seluruh pemrosesan berat "
     "secara lokal. Alur dimulai dari directory watcher yang mendeteksi folder foto baru, "
     "membuat baris mission di basis data, lalu memicu NodeODM.")
para(doc,
     "PyroScan memakai NodeODM langsung lewat REST API, bukan WebODM. WebODM tidak dipakai "
     "di jalur kritis karena hanya sekitar 10 persen kemampuannya yang dibutuhkan, sementara "
     "ia menjadi titik gagal tambahan di lapangan. Penggantinya adalah halaman Photogrammetry "
     "Manager di dashboard.")
para(doc, "Seluruh opsi ODM dikirim eksplisit dari kode, tidak mengandalkan default container:")
add_table(doc,
          ["Opsi ODM", "Nilai", "Alasan"],
          [["use-exif", "true", "Memakai geotag GPS ponsel sebagai titik kontrol awal"],
           ["gps-accuracy", "15", "Menoleransi ketidakpastian GNSS ponsel single-band"],
           ["resize-to", "2000", "Membatasi biaya komputasi ekstraksi fitur"],
           ["feature-quality", "medium", "Keseimbangan akurasi dan waktu pada 8 GB VRAM"],
           ["pc-quality", "medium", "Membatasi kedalaman point cloud padat"],
           ["orthophoto-resolution", "2", "Orthophoto 2 cm per piksel"],
           ["dem-resolution", "2", "DEM 2 cm per piksel"],
           ["dsm", "true", "Wajib. Tanpa ini ODM 3.6.2 tidak menghasilkan DEM"]],
          widths=[5.0, 2.4, 8.6])

para(doc, "Tahapan pipeline lengkap:")
add_table(doc,
          ["Tahap", "Pemroses", "Input", "Output"],
          [["Capture", "Payload Realme 3 Pro", "Interval 2 sampai 4 detik",
            "Foto JPEG 12 MP + EXIF GPS"],
           ["Deteksi tepi", "YOLOv8n TFLite", "Foto", "Log hotspot lokal"],
           ["Sinkronisasi", "Wi-Fi lokal posko", "Folder foto", "Foto di SSD laptop"],
           ["Deteksi misi", "Watcher + Mode Resolver", "Folder foto baru",
            "Baris mission, mode PRE_FIRE atau BURN_SCAR"],
           ["Fotogrametri", "NodeODM Docker CUDA", "Foto + opsi eksplisit",
            "ortho.tif, dem.tif, mesh.glb"],
           ["Verifikasi visual", "YOLO sisi server", "Foto atau orthophoto",
            "Daftar hotspot terverifikasi"],
           ["Fusi spasial", "Python rasterio dan numpy", "DEM + hotspot",
            "spatial_fusion.json v1.1.0"],
           ["Simulasi rambat", "Python numpy", "Fusi + cuaca",
            "Vektor prediksi 30 sampai 60 menit (MODE-A)"],
           ["Metrik bakar", "Python rasterio", "Orthophoto",
            "Luas, keliling, bbox (MODE-B)"],
           ["Advisory", "Ollama qwen3.5:4b-q4_K_M", "Subset spatial_fusion.json",
            "Advisory JSON + audit trail"],
           ["Penyajian", "FastAPI + SSE ke CesiumJS", "SQLite + aset misi",
            "Dashboard 3D"]],
          widths=[3.4, 4.2, 4.2, 4.2])

para(doc,
     "Fusi raster membaca elevasi, kelandaian, dan arah lereng dari DEM pada titik hotspot. "
     "Simulasi rambat memproyeksikan posisi api 30 sampai 60 menit ke depan dari vektor angin "
     "dan dorongan lereng, dengan slope_weight dan wind_weight yang wajib konfigurabel. Burn "
     "metrics menghitung luas, keliling, dan bounding box area terbakar.")
para(doc,
     "Serialisasi GPU wajib. Alurnya ODM selesai, LLM dimuat, advisory dihasilkan, model "
     "dilepas. OLLAMA_KEEP_ALIVE diset 0. VRAM efektif hanya sekitar 7,2 GB dari 8 GB, "
     "sehingga 3,97 GB untuk LLM ditambah 2 sampai 4 GB untuk ODM hanya muat bila berurutan. "
     "Seluruh state disimpan di SQLite (pyroscan.db), dan FastAPI menyajikan REST serta SSE "
     "tanpa Redis dan tanpa Celery.")

# 3.4
h2(doc, "3.4. Kontrak Data")
para(doc, "Kontrak data adalah satu-satunya jembatan antara pipeline dan antarmuka.")
para(doc,
     "spatial_fusion.json versi 1.1.0 adalah berkas pertukaran internal setelah fotogrametri, "
     "YOLO, dan cuaca selesai, dan satu-satunya masukan bagi simulation engine serta LLM "
     "advisory. Field wajib: schema_version, session_id, mission_mode, timestamp. Struktur "
     "turunannya:")
add_table(doc,
          ["Field", "Isi", "Catatan"],
          [["photogrammetry",
            "images_submitted, images_aligned, align_ratio, rmse_reprojection_px",
            "Bukti kualitas rekonstruksi"],
           ["hotspots",
            "lat, lon, elevation_m, slope_deg, aspect_deg, fire_confidence, smoke_confidence",
            "Daftar titik api"],
           ["environmental_data",
            "wind_speed_kmh, wind_direction_deg, humidity_pct, temperature_c, source, "
            "observed_at, age_minutes",
            "Cuaca + penanda usia"],
           ["spread_prediction",
            "predicted_lat, predicted_lon, estimated_arrival_minutes, risk_level, "
            "slope_weight, wind_weight",
            "Hanya MODE-A"],
           ["burn_scar", "area_m2, perimeter_m, bbox, geojson_path", "Hanya MODE-B"]],
          widths=[4.0, 7.4, 4.6])

para(doc,
     "Jebakan yang harus dihindari: wind_direction_deg memakai konvensi meteorologis FROM, "
     "yaitu arah dari mana angin bertiup. Vektor rambat api adalah arah TO, yaitu "
     "wind_direction_deg ditambah 180. Salah tanda membalik seluruh prediksi.")
para(doc,
     "Advisory LLM punya tiga aturan yang dipaksakan oleh kode. Pertama, severity berasal "
     "dari simulation engine yang deterministik dan diteruskan apa adanya; LLM tidak pernah "
     "ditanya dan tidak boleh menimpanya, karena pada benchmark qwen3.5:4b menaikkan HIGH "
     "dari mesin menjadi CRITICAL sehingga dua misi dengan data identik bisa memberi tingkat "
     "ancaman berbeda. Kedua, aksi dipilih dari katalog tertutup berisi enam id: "
     "EVAC_IMMEDIATE, EVAC_ROUTE, FIREBREAK, AERIAL, PATROL, EARLY_WARNING; model hanya "
     "mengembalikan action_ids dan teksnya dirender dari katalog, sedangkan id di luar "
     "katalog dibuang dan dicatat di dropped_ids. Ketiga, setiap advisory menyimpan audit "
     "trail berupa model, seed, prompt_sha, dan dropped_ids, serta selalu tampil dengan "
     "label draf, verifikasi lapangan.")
para(doc,
     "Kontrak heightmap Cesium adalah pengganti tileset quantized-mesh, satu payload per "
     "misi, dengan field mission_id, width, height, west, south, east, north, height_scale_m, "
     "geoid_offset_m, dan heights_m.")
para(doc,
     "Field geoid_offset_m wajib diisi. ODM menghasilkan tinggi di atas permukaan laut "
     "dengan acuan EGM96, sementara CustomHeightmapTerrainProvider Cesium menginterpretasikan "
     "tinggi di atas ellipsoid. Tanpa offset ini, terrain tampak bergeser vertikal beberapa "
     "meter dan pin hotspot tidak menempel di permukaan.")
para(doc, "Skema SQLite utama:")
add_table(doc,
          ["Tabel", "Isi pokok", "Kunci"],
          [["mission", "Mode misi, waktu, luas, status pipeline, jalur DEM, ortho, mesh",
            "id seperti FLIGHT_20261114_001"],
           ["hotspot",
            "Koordinat, elevasi, slope, aspect, confidence api dan asap, sumber",
            "id, relasi ke mission"],
           ["prediction",
            "Horizon menit, koordinat prediksi, risk_level, bobot slope dan wind",
            "auto increment, relasi ke hotspot"],
           ["weather_obs", "Angin, kelembapan, suhu, sumber, penanda cache",
            "auto increment, relasi ke mission"],
           ["advisory",
            "severity dari engine, narasi, action_ids_json, model, prompt_sha, seed",
            "id seperti ADV-20261114-01"]],
          widths=[3.0, 8.0, 5.0])
para(doc,
     "severity di tabel advisory berasal dari engine, bukan model. action_ids_json disimpan "
     "sebagai id, bukan teks, agar kalimat bisa diubah tanpa migrasi data.")

# 3.5
h2(doc, "3.5. Dashboard 3D")
para(doc,
     "Dashboard adalah konsol 3D: medan hasil rekonstruksi menjadi antarmukanya, dan panel "
     "berfungsi mengendalikan serta menjelaskan medan tersebut.")
para(doc,
     "Media utama adalah 3D dengan orbit bebas, mode 2D hanya tombol alih. Komposisinya "
     "adegan penuh dengan rel kanan yang bisa dilipat. Basemap berupa citra satelit yang "
     "di-cache lokal sejauh 2 sampai 5 km tanpa permintaan jaringan saat runtime.")
para(doc, "Mode dasar: Ortho, Elevation, dan Burn severity.")
para(doc,
     "Overlay: Heat, Wind, Prediction, Hotspots, dan Flight path. Masing-masing punya kotak "
     "centang dan penggeser opasitas, plus legenda.")
para(doc,
     "Rel kanan: tab Layers, Mission, Advisory, dan Weather, dengan lencana severity yang "
     "selalu tampil di atasnya. LOW hijau, MEDIUM kuning, HIGH oranye, CRITICAL merah, selalu "
     "teks dan warna, tidak pernah warna saja.")
para(doc,
     "Forecast strip: garis waktu now sampai +60 menit, luas terbakar, laju rambat, dan "
     "peristiwa kunci.")
para(doc,
     "Kejujuran data: setiap lapisan yang masih fixture diberi penanda SIMULASI di legenda "
     "sampai pipeline benar-benar memproduksinya. Saat ini orthophoto, DSM/mesh, dan basemap "
     "sudah nyata, sedangkan heat, wind, severity, prediksi, cuaca, dan advisory masih "
     "fixture. P95 frame time terukur sekitar 28 ms pada 1600x900 dengan seluruh lapisan "
     "aktif dan tanpa permintaan eksternal.")

add_image(doc, "Docs/references/ref-pyroscan-live.png",
          "Gambar 2. Dashboard PyroScan berjalan dengan data misi nyata dari dataset Brighton "
          "Beach: orthophoto dan mesh DSM hasil NodeODM, dibaca dari SQLite lewat FastAPI. "
          "Lapisan heat, wind, severity, prediksi, cuaca, dan advisory masih berstatus fixture "
          "(SIMULASI). Sumber: tangkapan layar sistem PyroScan (nyata, sebagian fixture).")

para(doc,
     "Satu koreksi teknis dari spike: CustomHeightmapTerrainProvider Cesium menutup tepi "
     "petak ke ellipsoid sehingga tampak seperti menara pada skala 100 m. Solusinya merender "
     "DEM sebagai mesh primitive dengan globe disembunyikan, yang justru selaras dengan "
     "rencana mesh.glb di PRD.")

# 3.6
h2(doc, "3.6. Kecerdasan Buatan dan Guardrail")
para(doc,
     "Sistem memakai dua model berbeda peran yang tidak boleh tertukar. YOLOv8n di on-device "
     "mendeteksi api dan asap secara langsung di udara sebagai preview cepat, lalu verifikasi "
     "kedua berjalan di sisi server setelah foto sampai di posko.")
para(doc,
     "Qwen3.5-4B via Ollama di Ground Station menghasilkan laporan naratif berbahasa "
     "Indonesia dari konteks spasial JSON. Hasil benchmark pada RTX 4060 Laptop 8 GB:")
add_table(doc,
          ["Model", "Decode (t/s)", "Wall dingin (s)", "VRAM puncak", "JSON valid", "Status"],
          [["qwen3.5:4b-q4_K_M", "67,1 terukur", "11,4 terukur", "3,97 GB terukur", "3/3",
            "Default produksi"],
           ["gemma4:e4b", "55,9 terukur", "16,2 terukur", "4,41 GB terukur", "1/1",
            "Tidak dipilih"],
           ["qwen3.5:9b", "belum terukur", "belum terukur", "belum terukur", "belum terukur",
            "Unduhan gagal"],
           ["qwen3-vl:4b", "belum terukur", "belum terukur", "belum terukur", "belum terukur",
            "Unduhan gagal"]],
          widths=[3.4, 2.6, 2.6, 2.8, 2.4, 3.2])
para(doc,
     "Target latency advisory adalah di bawah 90 detik dari status ODM DONE sampai advisory "
     "tersimpan. Angka terukur 11,4 detik berarti lolos dengan margin 7,9 kali. Model 4B "
     "sudah jauh melewati target, dan model 9B bukan syarat agar sistem berjalan melainkan "
     "peningkatan kualitas.")
para(doc,
     "Guardrail yang tidak boleh dilonggarkan ada empat: severity dari engine, bukan LLM; "
     "aksi dari katalog tertutup, bukan teks bebas; JSON tidak terbaca memicu fallback dua "
     "aksi prioritas tertinggi dengan penanda error sehingga advisory tidak pernah kosong; "
     "dan risk_level tidak dikenal dipetakan ke MEDIUM, tidak pernah diam-diam turun ke LOW. "
     "Kegagalan LLM tidak boleh menggagalkan misi.")
para(doc,
     "Keputusan DG-03 soal pemilihan model berstatus sebagian tertutup: model 4B terukur dan "
     "dipilih sebagai default, dua kandidat lain belum dapat diukur karena unduhan gagal.")

# 3.7
h2(doc, "3.7. Operasi Offline, Keamanan, dan Keandalan")
para(doc,
     "Tidak ada internet di jalur kritis. Data cuaca dari Open-Meteo diambil lewat cache "
     "offline terakhir dengan penanda usia data di antarmuka; bila usia melewati ambang, "
     "muncul banner peringatan.")
para(doc,
     "Tanpa Cesium ion dan tanpa CDN. Terrain dan orthophoto dibaca dari berkas lokal, dan "
     "Cesium di-mask ke area coverage misi agar tidak merender seluruh globe.")
para(doc,
     "Keamanan API: API LAN posko saat ini tanpa autentikasi karena hanya untuk prototipe. "
     "Rekomendasi produksi adalah menambahkan token bersama sebelum API diekspos ke jaringan "
     "lebih luas.")
para(doc,
     "Integritas data: data GPS dan flight log disimpan paralel di memori internal ponsel "
     "dan SSD laptop, sehingga tidak hilang bila drone mengalami musibah.")
para(doc,
     "Ketahanan kegagalan: ODM gagal menghasilkan status FAILED dengan pesan; DEM belum siap "
     "membuat dashboard jatuh ke basemap 2D dengan pin hotspot dan banner status; advisory "
     "gagal memicu fallback dengan penanda error.")

# 3.8
h2(doc, "3.8. Pengujian, KPI, dan Risiko")
para(doc,
     "Hanya metrik dengan prosedur ukur jelas dan sumber data yang benar-benar ada yang "
     "dipertahankan.")
add_table(doc,
          ["Indikator", "Prosedur ukur", "Target MVP", "Status"],
          [["Deteksi api dan asap YOLOv8", "mAP50 pada validation set lapangan",
            "di atas 80 persen", "Uji belum dijalankan"],
           ["Foto ter-align (SfM)", "num_reconstructed dibagi num_images",
            "di atas 80 persen MODE-B, 60 persen MODE-A",
            "100 persen pada spike Brighton, permukaan bukan kanopi"],
           ["Waktu proses end-to-end",
            "Pemicu watcher sampai artefak tersedia di SQLite",
            "di bawah 4 menit untuk 30 foto", "Belum teruji di GPU"],
           ["Akurasi relatif orthophoto", "RMSE antar minimal 3 checkpoint GCP",
            "di bawah 2 m", "Belum diukur"],
           ["Error posisi hotspot", "Jarak pin terhadap posisi api ground-truth",
            "di bawah 15 m", "Belum diukur"],
           ["Frame time dashboard", "p95 frame time 1080p, 60 detik sampling",
            "di bawah 33 ms", "sekitar 28 ms pada 1600x900, terukur"],
           ["Latency advisory", "Status ODM DONE sampai advisory tersimpan",
            "di bawah 90 s", "11,4 s terukur"]],
          widths=[3.8, 4.6, 3.8, 3.8])

para(doc,
     "Status spike harus dinyatakan jujur. Pada dataset Brighton Beach, yaitu permukaan "
     "pantai dan bukan kanopi hutan, 18 dari 18 foto ter-align dengan reprojection error 1,08 "
     "piksel dan GSD 1,64 cm, diproses 8,5 menit pada CPU. Angka ini adalah spike pada "
     "permukaan, bukan uji kanopi hutan hidup. Uji SfM di atas kanopi masih menjadi decision "
     "gate yang menentukan apakah MODE-A layak diterapkan.")
para(doc, "Risiko dan decision gate:")
add_table(doc,
          ["Kode", "Risiko", "Dampak", "Status", "Mitigasi"],
          [["R-01", "SfM gagal di atas kanopi hutan hidup", "Fatal untuk MODE-A",
            "DG-01 blocking",
            "Jika gagal, MODE-B jadi mode utama dan MODE-A jadi fitur eksperimental berlabel"],
           ["R-02", "Target waktu proses tidak tercapai", "Tinggi", "Terbuka",
            "Turunkan resolusi atau quality ODM, ukur nyata, revisi target"],
           ["R-03", "VRAM 8 GB tidak cukup saat ODM dan LLM", "Tinggi", "Termitigasi",
            "Serialisasi pipeline dan OLLAMA_KEEP_ALIVE 0"],
           ["R-04", "ColorOS membunuh background service", "Tinggi", "Terbuka",
            "SOP onboarding dan verifikasi lapangan"],
           ["R-05", "NNAPI lebih lambat dari CPU", "Sedang", "Termitigasi",
            "Rantai fallback terukur"],
           ["R-06", "GNSS ponsel tidak mencapai akurasi absolut tinggi", "Sedang",
            "Termitigasi", "Ukur akurasi relatif dan GCP, jangan menjanjikan absolut"],
           ["R-07", "Regulasi frekuensi LoRa Indonesia", "Sedang", "DG-02",
            "Relevan hanya bila Fase 2 dijalankan"],
           ["R-08", "Dataset YOLO tidak tersedia atau lisensi AGPL", "Tinggi", "Terbuka",
            "Verifikasi dataset dan lisensi sebelum menulis kode inferensi"],
           ["R-09", "Termal payload saat capture kontinu", "Sedang", "Terbuka",
            "Interval 2 sampai 4 detik, 12 MP, uji 10 menit kontinu"],
           ["R-10", "Rolling shutter digabung getaran menyebabkan motion blur", "Sedang",
            "Terbuka", "Shutter minimal 1/1000 s, peredam karet, uji ketajaman"],
           ["R-11", "Scope creep karena dua mode", "Sedang", "Terbuka",
            "Satu pipeline dan satu basis data, beda hanya lapisan metrik dan label"],
           ["R-12", "Thermal throttling laptop saat ODM panjang", "Sedang", "Terbuka",
            "Ukur suhu dan clock, atur power mode Windows"]],
          widths=[1.4, 4.2, 2.0, 2.2, 6.2])

para(doc,
     "Decision gate yang mengontrol pengembangan: DG-01 kelayakan SfM, lulus jika minimal 80 "
     "persen align pada MODE-B atau 60 persen pada MODE-A; DG-02 aktivasi LoRa, hanya bila "
     "drone tidak punya telemetry link dan frekuensi sudah diverifikasi; DG-03 pemilihan "
     "model LLM, sebagian tertutup; DG-04 kontrak advisory, sudah tertutup dan terverifikasi.")

# 3.9
h2(doc, "3.9. Roadmap Bertahap")
add_table(doc,
          ["Fase", "Fokus", "Keluaran", "Gate"],
          [["Fase 0 Technical Spike", "Uji kelayakan sebelum kode produksi",
            "SfM kanopi, Camera2 level, benchmark delegate TFLite, benchmark LLM, verifikasi "
            "dataset YOLO",
            "DG-01. Status sebagian selesai: ODM Brighton dan benchmark LLM sudah jalan, SfM "
            "kanopi, delegate TFLite, dan dataset YOLO belum"],
           ["Fase 1 MVP Core", "Sistem jalan ujung ke ujung",
            "Aplikasi Android capture, pipeline Python, SQLite dengan FastAPI dan SSE, "
            "dashboard React dan CesiumJS, Photogrammetry Manager",
            "KPI tervalidasi pada hardware nyata"],
           ["Fase 2 Integrasi Hardware dan LoRa", "Radio dan enclosure final",
            "Serial USB OTG ke ESP32/SX1262, receiver posko, enclosure final terverifikasi bobot",
            "DG-02 harus lulus lebih dulu"],
           ["Fase 3 Uji Lapangan dan Kalibrasi", "Penerbangan nyata dan penyetelan",
            "Uji MODE-A dan MODE-B, kalibrasi slope_weight dan wind_weight, kalibrasi "
            "gps-accuracy dan penempatan GCP",
            "Hasil kalibrasi menggantikan angka estimasi"]],
          widths=[3.6, 3.4, 4.6, 4.4])

# ---- 4. Rencana Anggaran Biaya
h1(doc, "4. Rencana Anggaran Biaya")
VZ = ROOT / "Docs/rab_assets"
if (VZ / "fig1_alur_data.png").exists():
    doc.add_picture(str(VZ / "fig1_alur_data.png"), width=Cm(15.5))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    caption(doc, "Gambar 3. Alur data dari payload di udara sampai dashboard posko. "
                 "Foto berpindah lewat Wi-Fi setelah mendarat; metadata ringkas lewat LoRa.")

para(doc,
     "Seluruh angka di bagian ini adalah estimasi pasar per November 2026, bukan penawaran "
     "vendor. Setiap angka harus divalidasi dengan penawaran nyata sebelum diajukan sebagai "
     "komitmen.", italic=True)

# 4.1
h2(doc, "4.1. Asumsi Biaya")
para(doc,
     "Aset yang sudah tersedia, bukan biaya baru tetapi dicatat sebagai nilai aset, adalah "
     "laptop Lenovo LOQ RTX 4060 8 GB dan ponsel Realme 3 Pro. Keduanya dianggap sudah "
     "dimiliki sehingga tidak dihitung sebagai pengeluaran.")
para(doc,
     "Drone belum tersedia, sehingga perlu diputuskan antara menyewa atau meminjam dan "
     "membeli unit bekas. Kedua skenario dihitung terpisah.")
para(doc,
     "Perangkat lunak open source berbiaya lisensi nol: NodeODM dan OpenDroneMap, Ollama, "
     "Qwen, CesiumJS, FastAPI, dan Python. Catatan lisensi: ODM berlisensi AGPL-3.0, sehingga "
     "bila perangkat lunak didistribusikan sebagai layanan jaringan, kewajiban AGPL ikut "
     "berlaku. Ultralytics YOLOv8 juga AGPL-3.0, dan lisensi komersialnya hanya diperlukan "
     "bila produk dikomersialkan.")
para(doc,
     "Tidak ada biaya cloud atau API berulang karena seluruh pemrosesan lokal. Harga dicari "
     "dari sumber lokal maupun online dan dicantumkan sumber serta tanggalnya pada tabel.")
para(doc, "Sumber harga yang dipakai (semua diakses November 2026):", bold=True)
add_table(doc,
          ["Komponen", "Sumber dan rentang harga"],
          [["SSD NVMe 1 TB", "Blibli, Kingston NV2 1TB Rp 1.035.000; Midasforce 1TB Rp 984.000"],
           ["Router Wi-Fi 6 portable",
            "Tokopedia, GL.iNet GL-MT3000 (Beryl AX) Rp 2.490.000; TP-Link TL-WR3002X "
            "Rp 2.680.000"],
           ["Drone bekas",
            "OLX, DJI Mavic 2 Pro combo 3 baterai Rp 9.300.000; Shopee Rp 15.658.000 "
            "(kondisi lebih baik)"],
           ["Sewa drone",
            "Pondok Lensa, Rp 1.500.000/hari atau Rp 3.000.000/3 hari (tanpa pilot); "
            "rentkamera.com Rp 1.250.000/hari"],
           ["Filamen PETG", "Tokopedia, Rp 147.000-260.000 per kg; Indocart Rp 95.000"],
           ["Modul LoRa SX1262",
            "Tokopedia, Heltec LoRa32 V3 (ESP32-S3 + SX1262) sekitar Rp 500.000"],
           ["Rubber damper ball", "Tokopedia dan toko drone, paket 4 sekitar Rp 60.000"]],
          widths=[4.5, 11.5])
para(doc,
     "Semua angka adalah estimasi pasar, bukan penawaran resmi. Wajib divalidasi dengan "
     "penawaran vendor sebelum diajukan sebagai komitmen.", italic=True)

# 4.2
h2(doc, "4.2. Tabel Biaya per Komponen")
COST_HDR = ["No", "Komponen", "Spesifikasi", "Qty", "Harga Satuan", "Subtotal", "Keterangan"]
COST_W = [1.2, 3.6, 4.2, 1.0, 2.4, 2.2, 2.8]

para(doc, "Kelompok A, Payload. Semua item di bawah ini WAJIB DIBELI.", bold=True)
add_table(doc, COST_HDR,
          [["A1", "Filamen PETG", "1 kg, 1,75 mm, warna hitam", "1", "185.000", "185.000",
            "Tokopedia, Nov 2026 (kisaran Rp 147.000-260.000)"],
           ["A2", "Rubber damper ball", "Anti-vibrasi, 12x4x11,7 mm, paket 4", "1 set",
            "60.000", "60.000", "Tokopedia / toko drone, Nov 2026"],
           ["A3", "Baffle kamera", "Dicetak dari filamen PETG A1", "1", "0", "0",
            "Tidak beli terpisah, pakai sisa A1"],
           ["A4", "Sekrup, mur, insert, velcro", "Set M3 + heat insert + velcro", "1 set",
            "85.000", "85.000", "Estimasi toko bangunan / online"],
           ["A5", "Kabel dan konektor", "Kabel OTG USB-C, header, jumper", "1 set", "75.000",
            "75.000", "Estimasi"],
           ["A6", "Power bank", "10.000 mAh, output 5V/2A", "1", "185.000", "185.000",
            "Untuk misi panjang, opsional"],
           ["A7", "Realme 3 Pro", "RMX1851 bekas", "1", "0", "0",
            "SUDAH DIMILIKI (aset). Harga pasar bekas sekitar Rp 700.000-1.100.000"]],
          widths=COST_W)

para(doc, "Kelompok B, Ground Station. Semua item WAJIB DIBELI kecuali B6.", bold=True)
add_table(doc, COST_HDR,
          [["B1", "SSD NVMe", "1 TB, M.2 PCIe Gen3/Gen4", "1", "1.035.000", "1.035.000",
            "Blibli Nov 2026 (Kingston NV2 1TB Rp 1.035.000)"],
           ["B2", "Router Wi-Fi 6 portable", "GL.iNet GL-MT3000 atau AX3000 travel router",
            "1", "2.490.000", "2.490.000",
            "Tokopedia Nov 2026. WAJIB Fase 1, satu-satunya jalur transfer foto"],
           ["B3", "MicroSD", "64 GB, kelas U3 / V30", "1", "130.000", "130.000",
            "Estimasi Nov 2026"],
           ["B4", "Kabel dan konektor", "Kabel LAN, USB, adaptor", "1 set", "150.000",
            "150.000", "Estimasi"],
           ["B5", "Tas pelindung laptop", "Tahan air, berlapis busa", "1", "250.000", "250.000",
            "Untuk mobilitas posko, opsional"],
           ["B6", "Lenovo LOQ RTX 4060", "i7-HX, 8 GB VRAM, 16/32 GB RAM", "1", "0", "0",
            "SUDAH DIMILIKI (aset). Harga pasar baru sekitar Rp 14.000.000-17.000.000"]],
          widths=COST_W)

para(doc, "Kelompok C, Drone. Pilih SALAH SATU skenario. Drone belum dimiliki.", bold=True)
add_table(doc,
          ["Skenario", "Komponen", "Spesifikasi", "Qty", "Harga Satuan", "Subtotal",
           "Keterangan / Sumber"],
          [["C-1 Sewa", "Sewa drone + pilot", "3 hari, unit kelas Mavic 3, termasuk operator",
            "1 paket", "1.500.000", "4.500.000",
            "Pondok Lensa Nov 2026: Rp 1.500.000/hari, Rp 3.000.000/3 hari tanpa pilot"],
           ["C-2 Beli", "Drone bekas", "DJI Mavic 2 Pro, baterai 2-3 buah", "1 unit",
            "9.300.000", "9.300.000",
            "OLX Nov 2026: Rp 9.300.000 (combo 3 baterai, kondisi mulus)"],
           ["C-2 Beli", "Baterai cadangan", "Baterai Mavic 2 tambahan", "1", "1.200.000",
            "1.200.000", "Estimasi Nov 2026"],
           ["C-2 Beli", "Kartu memori drone", "64 GB V30", "1", "130.000", "130.000",
            "Estimasi"]],
          widths=COST_W)

para(doc, "Kelompok D, Software dan Lisensi. DIBAWA GRATIS, tidak ada pembelian.", bold=True)
add_table(doc, COST_HDR,
          [["D1", "NodeODM dan OpenDroneMap", "AGPL-3.0", "-", "0", "0",
            "Unduh gratis. Kewajiban AGPL bila didistribusikan sebagai layanan"],
           ["D2", "Ollama dan Qwen", "Apache 2.0", "-", "0", "0", "Unduh gratis, model lokal"],
           ["D3", "CesiumJS", "Apache 2.0", "-", "0", "0",
            "Unduh gratis. Tidak memakai Cesium ion berbayar"],
           ["D4", "FastAPI, Python, dan pustaka lain", "Open source", "-", "0", "0",
            "Unduh gratis"],
           ["D5", "Ultralytics YOLOv8", "AGPL-3.0", "-", "0", "0",
            "Gratis untuk riset. Lisensi komersial hanya bila produk dijual"]],
          widths=COST_W)

para(doc, "Tambahan Fase 2, LoRa (hanya jika DG-02 lulus).", bold=True)
add_table(doc, COST_HDR,
          [["I1", "Modul LoRa", "Heltec LoRa32 V3, ESP32-S3 + SX1262, 923 MHz", "2",
            "500.000", "1.000.000", "Tokopedia Nov 2026. Satu untuk drone, satu untuk posko"],
           ["I2", "Antena LoRa", "3 dBi dipole, konektor SMA", "2", "75.000", "150.000",
            "Estimasi"],
           ["I3", "Kabel OTG USB-C", "Dengan strain relief", "2", "35.000", "70.000",
            "Estimasi"],
           ["I4", "Baterai LiPo / holder", "Untuk modul LoRa di drone", "1", "120.000",
            "120.000", "Estimasi"]],
          widths=COST_W)

para(doc, "Kelompok E, Pengujian Lapangan.", bold=True)
add_table(doc, COST_HDR,
          [["E1", "Transportasi", "Menuju lokasi uji, pulang pergi", "1 paket",
            "1.000.000", "1.000.000", "Estimasi dalam Jawa"],
           ["E2", "Akomodasi", "3 hari, 2 orang", "6 malam", "300.000", "1.800.000",
            "Estimasi penginapan sederhana"],
           ["E3", "Konsumsi lapangan", "3 hari, 3 orang", "9 hari-orang", "75.000", "675.000",
            "Estimasi"],
           ["E4", "Perizinan", "Izin lokasi / instansi", "1", "500.000", "500.000",
            "Jika diperlukan"],
           ["E5", "GCP (ground control point)", "Target mark + patok, 3 unit", "1 set",
            "600.000", "600.000", "Untuk validasi akurasi relatif"],
           ["E6", "Sewa lahan atau akses", "Bila diperlukan", "1", "500.000", "500.000",
            "Estimasi"]],
          widths=COST_W)

para(doc, "Kelompok F, Dokumentasi dan Diseminasi.", bold=True)
add_table(doc, COST_HDR,
          [["F1", "Desain grafis", "Proposal, poster, dan slide", "1 paket", "1.500.000",
            "1.500.000", "Estimasi jasa desain"],
           ["F2", "Video dokumentasi", "Editing dan produksi 3 menit", "1", "2.000.000",
            "2.000.000", "Estimasi jasa videografer"],
           ["F3", "Publikasi", "Biaya publikasi / cetak", "1", "1.000.000", "1.000.000",
            "Estimasi"]],
          widths=COST_W)

para(doc, "Kelompok G, Tenaga Kerja.", bold=True)
para(doc,
     "Tenaga kerja dihitung sebagai in-kind, yaitu nilai kontribusi yang tidak dibayar tunai. "
     "Dengan demikian kelompok ini tidak menambah pengeluaran kas, tetapi tetap dicatat agar "
     "nilai proyek terbaca utuh. Bila nanti diputuskan dibiayai, angkanya masuk ke total.",
     italic=True)
add_table(doc, COST_HDR,
          [["G1", "Kerja mahasiswa", "Pengembangan + uji, 400 jam", "400 jam", "50.000",
            "20.000.000", "IN-KIND, bukan pengeluaran tunai"],
           ["G2", "Teknisi lapangan", "Pendamping uji, bila dibiayai", "6 hari", "300.000",
            "1.800.000", "Opsional, dibiayai"]],
          widths=COST_W)

para(doc, "Kelompok H, Kontingensi.", bold=True)
add_table(doc, COST_HDR,
          [["H1", "Kontingensi", "12 persen dari subtotal. Skenario minimum: 12% x Rp 18.285.000",
            "1", "2.194.200", "2.194.200",
            "Cadangan kenaikan harga atau komponen gagal"],
           ["H2", "Kontingensi (skenario penuh)",
            "12 persen dari subtotal. Skenario penuh: 12% x Rp 27.555.000",
            "1", "3.306.600", "3.306.600", "Pakai salah satu sesuai skenario"]],
          widths=COST_W)

# 4.3
h2(doc, "4.3. Ringkasan Biaya")
para(doc,
     "Ringkasan berikut memisahkan barang yang SUDAH DIMILIKI (tidak dibeli) dari barang "
     "yang WAJIB DIBELI, agar angka pengeluaran kas terlihat jelas.", bold=True)

if (VZ / "fig3_biaya_komponen.png").exists():
    doc.add_picture(str(VZ / "fig3_biaya_komponen.png"), width=Cm(15.5))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    caption(doc, "Gambar 4. Rincian biaya per komponen proyek, dari payload sampai drone. "
                 "Seluruh angka adalah estimasi pasar per November 2026.")

para(doc, "a. Rekapitulasi per kelompok", bold=True)
add_table(doc,
          ["Kelompok", "Isi", "Skenario minimum", "Skenario penuh"],
          [["A", "Payload (wajib beli)", "Rp 405.000", "Rp 405.000"],
           ["B", "Ground Station (wajib beli)", "Rp 3.805.000", "Rp 3.805.000"],
           ["C-1", "Drone: SEWA 3 hari", "Rp 4.500.000", "-"],
           ["C-2", "Drone: BELI bekas + baterai", "-", "Rp 10.630.000"],
           ["D", "Software dan lisensi", "Rp 0", "Rp 0"],
           ["I", "LoRa Fase 2 (opsional)", "-", "Rp 1.340.000"],
           ["E", "Pengujian lapangan", "Rp 5.075.000", "Rp 5.075.000"],
           ["F", "Dokumentasi dan diseminasi", "Rp 4.500.000", "Rp 4.500.000"],
           ["G1", "Tenaga kerja mahasiswa (in-kind)", "Rp 0", "Rp 0"],
           ["G2", "Teknisi lapangan (opsional)", "-", "Rp 1.800.000"],
           ["H", "Kontingensi 12 persen", "Rp 2.194.200", "Rp 3.306.600"],
           ["", "SUBTOTAL sebelum kontingensi", "Rp 18.285.000", "Rp 27.555.000"],
           ["", "TOTAL", "Rp 20.479.200", "Rp 30.861.600"]],
          widths=[2.0, 6.0, 4.0, 4.0])

para(doc,
     "Catatan: G1 (kerja mahasiswa 400 jam, setara Rp 20.000.000) dihitung sebagai in-kind, "
     "sehingga TIDAK menambah pengeluaran kas. Bila nanti diputuskan dibiayai, tambahkan "
     "Rp 20.000.000 ke total.", italic=True)

para(doc, "b. Daftar belanja yang benar-benar harus dibeli", bold=True)
para(doc, "Skenario minimum (drone disewa):")
add_table(doc,
          ["No", "Barang yang harus dibeli", "Qty", "Subtotal"],
          [["1", "Filamen PETG 1 kg", "1", "Rp 185.000"],
           ["2", "Rubber damper ball (paket 4)", "1 set", "Rp 60.000"],
           ["3", "Sekrup, mur, heat insert, velcro", "1 set", "Rp 85.000"],
           ["4", "Kabel OTG, header, jumper", "1 set", "Rp 75.000"],
           ["5", "SSD NVMe 1 TB", "1", "Rp 1.035.000"],
           ["6", "Router Wi-Fi 6 portable (GL.iNet GL-MT3000)", "1", "Rp 2.490.000"],
           ["7", "MicroSD 64 GB V30", "1", "Rp 130.000"],
           ["8", "Kabel LAN, USB, adaptor", "1 set", "Rp 150.000"],
           ["9", "Sewa drone + pilot 3 hari", "1 paket", "Rp 4.500.000"],
           ["10", "Pengujian lapangan (transport, akomodasi, izin, GCP)", "1 paket",
            "Rp 5.075.000"],
           ["11", "Dokumentasi dan diseminasi", "1 paket", "Rp 4.500.000"],
           ["", "SUBTOTAL sebelum kontingensi", "", "Rp 18.285.000"],
           ["12", "Kontingensi 12 persen dari subtotal", "1", "Rp 2.194.200"],
           ["", "TOTAL BELANJA (skenario minimum)", "", "Rp 20.479.200"]],
          widths=[1.5, 8.0, 2.5, 4.0])
para(doc, "Item opsional di luar subtotal: power bank 10.000 mAh (Rp 185.000) dan tas "
          "pelindung laptop (Rp 250.000). Tambahkan jika diperlukan.", italic=True)

para(doc, "Skenario penuh (drone dibeli, LoRa Fase 2 disertakan):")
add_table(doc,
          ["No", "Barang yang harus dibeli", "Qty", "Subtotal"],
          [["1", "Payload: PETG, damper, sekrup, kabel", "1 paket", "Rp 405.000"],
           ["2", "Ground Station: SSD NVMe 1 TB, router Wi-Fi 6, microSD, kabel",
            "1 paket", "Rp 3.805.000"],
           ["3", "Drone bekas DJI Mavic 2 Pro (combo 3 baterai)", "1 unit", "Rp 9.300.000"],
           ["4", "Baterai drone tambahan", "1", "Rp 1.200.000"],
           ["5", "Kartu memori drone 64 GB V30", "1", "Rp 130.000"],
           ["6", "Modul LoRa Heltec LoRa32 V3 (ESP32-S3 + SX1262)", "2", "Rp 1.000.000"],
           ["7", "Antena LoRa 3 dBi SMA", "2", "Rp 150.000"],
           ["8", "Kabel OTG USB-C (2 buah)", "1 set", "Rp 70.000"],
           ["9", "Baterai LiPo + holder untuk LoRa", "1", "Rp 120.000"],
           ["10", "Pengujian lapangan (transport, akomodasi, izin, GCP)", "1 paket",
            "Rp 5.075.000"],
           ["11", "Dokumentasi dan diseminasi", "1 paket", "Rp 4.500.000"],
           ["12", "Teknisi lapangan 6 hari (opsional)", "6 hari", "Rp 1.800.000"],
           ["", "SUBTOTAL sebelum kontingensi", "", "Rp 27.555.000"],
           ["13", "Kontingensi 12 persen dari subtotal", "1", "Rp 3.306.600"],
           ["", "TOTAL BELANJA (skenario penuh)", "", "Rp 30.861.600"]],
          widths=[1.5, 8.0, 2.5, 4.0])
para(doc,
     "Kelompok Drone Rp 10.630.000 pada rekap adalah gabungan baris 3, 4, dan 5. Ground "
     "Station Rp 3.805.000 pada rekap termasuk tas pelindung laptop Rp 250.000 yang tidak "
     "dihitung di baris 2 karena bersifat opsional.", italic=True)

para(doc, "c. Barang yang TIDAK perlu dibeli (sudah tersedia)", bold=True)
add_table(doc,
          ["Komponen", "Status", "Nilai aset (estimasi)"],
          [["Laptop Lenovo LOQ RTX 4060 8 GB", "Sudah dimiliki", "Rp 14.000.000 - 17.000.000"],
           ["Ponsel Realme 3 Pro", "Sudah dimiliki",
            "Rp 700.000 - 1.100.000 (bekas)"],
           ["NodeODM, Ollama, Qwen, CesiumJS, FastAPI, Python", "Open source, gratis",
            "Rp 0"],
           ["Drone (pada skenario minimum)", "Disewa, bukan dibeli", "Rp 0"]],
          widths=[6.5, 4.5, 5.0])
para(doc,
     "Total nilai aset yang sudah tersedia sekitar Rp 15.000.000 - 18.000.000. Nilai ini tidak "
     "masuk sebagai pengeluaran, tetapi menunjukkan modal yang sudah tertanam di proyek.",
     italic=True)

para(doc, "d. Biaya per fase", bold=True)
add_table(doc,
          ["Fase", "Cakupan belanja", "Estimasi"],
          [["Fase 0", "Technical Spike. Semua aset sudah ada, tanpa belanja baru",
            "Rp 0"],
           ["Fase 1", "Payload (A) + Ground Station (B) + drone sewa (C-1), sebelum kontingensi",
            "Rp 8.710.000"],
           ["Fase 2", "Modul LoRa dan antenna (I) + enclosure final", "Rp 1.340.000"],
           ["Fase 3", "Uji lapangan (E) + dokumentasi (F), sebelum kontingensi",
            "Rp 9.575.000"]],
          widths=[3.0, 9.5, 3.5])

para(doc, "e. Biaya berulang per misi", bold=True)
add_table(doc,
          ["Komponen berulang", "Per misi", "Catatan"],
          [["Transportasi ke lokasi", "Rp 200.000 - 500.000", "Bergantung jarak"],
           ["Komponen habis pakai (kabel, pengikat, velcro)", "Rp 50.000", "Penggantian berkala"],
           ["Listrik pengisian", "Rp 5.000", "Diabaikan, dalam operasional posko"],
           ["Langganan cloud, API, tile hosting", "Rp 0", "Tidak ada, seluruh proses lokal"],
           ["TOTAL BERULANG PER MISI", "Rp 255.000 - 555.000",
            "Mendekati nol dibanding alternatif berlangganan"]],
          widths=[6.5, 4.5, 5.0])

para(doc, "f. Tabel sensitivitas: bila harga drone naik 20 persen", bold=True)
add_table(doc,
          ["Skenario", "Harga drone", "Subtotal", "Kontingensi 12%", "Total"],
          [["Dasar", "Rp 10.630.000", "Rp 27.555.000", "Rp 3.306.600", "Rp 30.861.600"],
           ["Drone naik 20 persen", "Rp 12.756.000", "Rp 29.681.000", "Rp 3.561.720",
            "Rp 33.242.720"],
           ["Drone turun 20 persen", "Rp 8.504.000", "Rp 25.429.000", "Rp 3.051.480",
            "Rp 28.480.480"]],
          widths=[4.0, 3.4, 3.2, 3.2, 3.2])
para(doc,
     "Kenaikan harga drone 20 persen hanya menambah sekitar Rp 2.381.120, atau 7,7 persen "
     "dari total. Artinya total anggaran cukup tahan terhadap gejolak harga drone. Yang paling "
     "memengaruhi total justru keputusan menyewa atau membeli drone (selisih Rp 10.225.000) "
     "dan keputusan membiayai tenaga kerja (tambahan Rp 20.000.000).", italic=True)

# 4.4
h2(doc, "4.4. Justifikasi Nilai")
para(doc,
     "Biaya PyroScan rendah karena tiga keputusan sadar. Pertama, memakai ponsel bekas "
     "sebagai payload, bukan kamera khusus, karena Realme 3 Pro sudah punya sensor 16 MP, "
     "GNSS multi-sistem, dan GPU serta DSP yang bisa menjalankan TFLite. Kedua, memakai "
     "perangkat lunak open source sehingga biaya lisensi nol, sementara alternatif komersial "
     "seperti Metashape atau Pix4D berbayar per tahun dan layanan cloud menambah biaya "
     "berulang per misi. Ketiga, memproses secara lokal sehingga tidak ada biaya compute atau "
     "penyimpanan cloud berulang.")
add_table(doc, ["Alternatif", "Mengapa berbeda dari PyroScan"],
          [["Drone RTK dengan kamera multispektral",
            "Presisi absolut jauh lebih tinggi, tetapi biaya perangkat berkali-kali lipat dan "
            "operatornya terspesialisasi"],
           ["Lisensi perangkat lunak fotogrametri komersial",
            "Berbiaya berulang per tahun, sedangkan PyroScan memakai ODM yang open source"],
           ["Layanan pemrosesan cloud",
            "Membutuhkan internet, bertentangan langsung dengan batasan operasi offline"]],
          widths=[5.5, 10.5])
para(doc,
     "Batasan yang harus dinyatakan jujur: PyroScan tidak mengklaim akurasi absolut, karena "
     "GNSS ponsel single-band sambil bergerak tidak bisa menjamin akurasi di bawah 5 meter; "
     "yang diukur adalah akurasi relatif antar checkpoint GCP. Biaya validasi GCP atau RTK "
     "dihitung terpisah. Harga drone bekas sangat bergantung pada kondisi unit dan "
     "ketersediaan pasar lokal, sehingga perlu diverifikasi langsung.")

# ---- Lampiran gambar referensi
h1(doc, "Lampiran. Gambar Referensi")
para(doc,
     "Gambar berikut adalah referensi visual pendukung. Label menunjukkan statusnya: nyata "
     "(hasil sistem), referensi (acuan desain, bukan hasil PyroScan), atau simulasi.")

add_image(doc, "spike/shots/dashboard-live.png",
          "Gambar 5. Tampilan live dashboard PyroScan dengan orthophoto dan mesh hasil "
          "rekonstruksi NodeODM. Sumber: spike/shots/dashboard-live.png (nyata).")
add_image(doc, "Docs/references/ref-elevation.png",
          "Gambar 6. Permukaan elevasi / point cloud: bentuk medan sebagai data, "
          "memperlihatkan kanopi, lereng, dan potongan jalan. Sumber: "
          "Docs/references/ref-elevation.png (referensi visual).")
add_image(doc, "Docs/references/ref-burn-severity.png",
          "Gambar 7. Pita kelas burn severity di atas dasar grayscale, acuan untuk lapisan "
          "Burn severity pada MODE-B. Sumber: Docs/references/ref-burn-severity.png "
          "(referensi visual).")
add_image(doc, "simulation/shots/FINAL-default.png",
          "Gambar 8. Studio payload 3D: tray cetak 3D, ponsel, dan modul radio, dipakai "
          "untuk memeriksa pemasangan dan ruang bebas. Sumber: "
          "simulation/shots/FINAL-default.png (simulasi).")

doc.save(str(OUT))
print(f"OK -> {OUT}")
print(f"   ukuran: {OUT.stat().st_size/1024:.0f} KB")
print(f"   paragraf: {len(doc.paragraphs)}  tabel: {len(doc.tables)}")
