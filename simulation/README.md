# PyroScan 3D Payload Studio

Simulasi interaktif payload drone PyroScan. Satu file HTML mandiri: model 3D,
three.js, dan scene semuanya jalan dari satu dokumen yang bisa dibuka dengan
double-click.

**Buka:** `pyroscan_payload_studio.html`

---

## Kenapa ada build step

`file://` memblokir `fetch` ke berkas `.glb` di folder yang sama (CORS). Jadi
ketiga model harus ikut di dalam dokumen sebagai base64, dan menginjeksi ~1,8 MB
base64 dengan tangan tidak masuk akal.

```
assets/*.glb          model sumber (arsip, tidak dibaca saat runtime)
src/studio.html       template + placeholder __B64_*
build.py              injeksi base64 → satu file output
pyroscan_payload_studio.html   ← hasil, ini yang dibuka
```

```powershell
python simulation/build.py
```

Build gagal keras kalau ada placeholder yang tidak tergantikan atau aset hilang.
Jangan edit file hasil — edit `src/studio.html` lalu build ulang.

---

## Deep link

Berguna untuk share tampilan tertentu, dan dipakai untuk screenshot otomatis.

| Parameter | Nilai | Efek |
|---|---|---|
| `view` | `free` `payload` `posko` `laptop` `follow` `nadir` | Posisi kamera |
| `exploded` | `1` | Mode exploded view |
| `sim` | `1` | Langsung mulai simulasi terbang |
| `tab` | `sim` `inspect` `telemetry` | Tab panel kanan |
| `debug` | `1` | Panel diagnosa: mesh terdekat, radius, parent |

Contoh: `...html?view=payload&exploded=1`

---

## Aset 3D

| Model | Dipakai untuk | Perlakuan |
|---|---|---|
| `drone_low_poly.glb` | Frame drone | Bbox-normalisasi, rotor blur dari node `Cylinder*` |
| `smartphone.glb` | Payload kamera (Realme 3 Pro) | Digantung di bawah frame, terlihat lewat bukaan tray |
| `esp32.glb` | Modul radio | Diputar dari orientasi Z-up, diletakkan di tepi tray |

Semua lewat `fitObject()`: deteksi sumbu datar → rotasi ke Y-up → skala seragam
→ center di origin. Tidak ada angka rotasi hardcode, jadi menukar model dengan
versi lain tetap pas.

Kalau satu model gagal di-parse, bagian itu **kembali ke primitif prosedural**
dan status di kanan bawah menyebut jumlah yang gagal. Scene tidak pernah rusak
total.

---

## Catatan implementasi

Beberapa hal yang tidak kelihatan dari layar tapi menentukan hasilnya:

- **`renderer.outputEncoding = sRGB` + ACES.** Tanpa sRGB, tekstur GLB tampil
  pucat. Tapi begitu sRGB aktif, warna heksadesimal prosedural (yang ditulis
  dalam sRGB) harus dikonversi ke linear — kalau tidak, seluruh scene jadi putih
  susu. `tuneSceneMaterials()` yang mengurus itu, sebelum model GLB masuk.
- **`scene.environment`** menerangi semua `MeshStandardMaterial`. Intensitasnya
  diturunkan ke 0.22 untuk scene, 1.15 khusus model GLB.
- **Penanda waypoint** sekarang satu `Points` cloud. Sebelumnya 14 sphere
  `r=0.25`, dan yang pertama duduk tepat di posisi drone sehingga terbaca
  sebagai bola menggantung di payload.
- **Partikel api** butuh `map`; `PointsMaterial` tanpa tekstur merender kotak.
- **Scan volume** memakai gradien alfa vertikal. Kerucut solid membuat kamera
  yang berada di dalamnya melihat dinding terdekat sebagai cakram pekat.
- **Contact shadow** di-raycast ke terrain tiap frame, jadi tidak melayang di
  atas bukit.

---

## Verifikasi

Tidak ada test otomatis untuk tampilan. Yang dipakai:

```powershell
npx playwright screenshot --channel=msedge --viewport-size="1600,900" `
  --wait-for-timeout=9000 "file:///C:/.../pyroscan_payload_studio.html?view=payload" `
  "simulation/shots/check.png"
```

Status aset di kanan bawah adalah indikator utama: `ASET 3D: 3/3 · 21.682
TRIANGLES` berarti ketiga model termuat. Kalau ada `ERROR: ...` di situ, buka
`?debug=1` untuk melihat objek terdekat dengan payload.

Screenshot acuan ada di `shots/`.

---

## Berbeda dari file asli

Asli: `C:\Users\TRISTAN\Downloads\interactive_3d_simulation_environment.html`
(tidak diubah).

Yang berubah: tiga objek prosedural → model GLB, tray solid → frame dengan
bukaan kamera, pipeline warna diperbaiki, scan volume + footprint + contact
shadow + collision rotor blur ditambahkan, partikel api diperbaiki, dan teks
`WebODM`/`NNAPI`/`915 MHz` diselaraskan dengan PRD v1.3.1.
