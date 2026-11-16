"""
Buat visual (flowchart, diagram, chart) untuk RAB Payload PyroScan.
Output: Docs/rab_assets/*.png
Jalankan: python Docs/build_rab_visuals.py
"""

from pathlib import Path
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle
import numpy as np

OUT = Path(__file__).resolve().parent / "rab_assets"
OUT.mkdir(exist_ok=True)

plt.rcParams["font.family"] = "Arial"

# palette
OBS = "#0d0d12"
INK = "#1a1a22"
BOX = "#1f1f2a"
LINE = "#3a3a48"
TEXT = "#e8e8ea"
MUTED = "#9a9aa8"
AMBER = "#e5a954"
FLAME = "#ff6b35"
TEAL = "#4fb5a8"
BLUE = "#4f8fd6"
GREEN = "#6fbf8f"
RED = "#e5443b"
PURPLE = "#9b7fd4"


def box(ax, x, y, w, h, label, sub="", color=BOX, edge=LINE,
        tc=TEXT, sc=MUTED, lw=1.6, fs=11, round_=True):
    style = "round,pad=0.02,rounding_size=0.12" if round_ else "square,pad=0.0"
    p = FancyBboxPatch((x, y), w, h, boxstyle=style,
                       linewidth=lw, edgecolor=edge, facecolor=color, zorder=2)
    ax.add_patch(p)
    cy = y + h / 2
    if sub:
        ax.text(x + w/2, cy + h*0.16, label, ha="center", va="center",
                color=tc, fontsize=fs, fontweight="bold", zorder=3)
        ax.text(x + w/2, cy - h*0.20, sub, ha="center", va="center",
                color=sc, fontsize=fs-2.5, zorder=3)
    else:
        ax.text(x + w/2, cy, label, ha="center", va="center",
                color=tc, fontsize=fs, fontweight="bold", zorder=3)
    return (x, y, w, h)


def arrow(ax, p1, p2, color=MUTED, lw=1.7, style="-|>", ls="-", rad=0.0):
    a = FancyArrowPatch(p1, p2, arrowstyle=style, mutation_scale=14,
                        linewidth=lw, color=color, linestyle=ls,
                        connectionstyle=f"arc3,rad={rad}", zorder=1,
                        shrinkA=2, shrinkB=2)
    ax.add_patch(a)


def blank(w, h):
    fig, ax = plt.subplots(figsize=(w, h), dpi=200)
    fig.patch.set_facecolor(OBS)
    ax.set_facecolor(OBS)
    ax.set_xlim(0, 10)
    ax.set_ylim(0, 10)
    ax.axis("off")
    return fig, ax


def save(fig, name):
    p = OUT / name
    fig.savefig(p, facecolor=OBS, bbox_inches="tight", pad_inches=0.18)
    plt.close(fig)
    print("  wrote", p.name)


# ---------------------------------------------------------- 1. alur data
def fig_dataflow():
    fig, ax = blank(13.5, 8.2)

    ax.text(5, 9.72, "Alur Data Payload → Link LoRa → Posko",
            ha="center", va="center", color=TEXT, fontsize=16, fontweight="bold")
    ax.text(5, 9.30, "Foto lewat Wi-Fi, metadata lewat LoRa",
            ha="center", va="center", color=AMBER, fontsize=10.5)

    # Kolom 1: drone
    ax.add_patch(Rectangle((0.15, 1.30), 3.5, 7.30, facecolor="#14141c",
                           edgecolor=LINE, linewidth=1.2, zorder=0,
                           linestyle=(0, (5, 4))))
    ax.text(1.9, 8.28, "DI UDARA", ha="center", color=AMBER,
            fontsize=10, fontweight="bold")

    box(ax, 0.5, 7.05, 2.8, 0.95, "Realme 3 Pro",
        "Kamera 16 MP + GNSS\nYOLOv8n TFLite INT8", color="#232333", fs=10.5)
    box(ax, 0.5, 5.45, 2.8, 0.95, "ESP32-S3-Zero",
        "Format paket, 4 kabel UART", color="#1f2b33", edge=TEAL, fs=10.5)
    box(ax, 0.5, 3.85, 2.8, 0.95, "E22-900T22D",
        "SX1262 · UART · 923 MHz\ndaya 22 dBm", color="#2b2333", edge=PURPLE, fs=10.5)
    box(ax, 0.5, 2.25, 2.8, 0.95, "Antena 923 MHz",
        "3 dBi, vertikal, atas drone", color="#232333", fs=10.5)

    arrow(ax, (1.9, 7.05), (1.9, 6.40), color=TEAL)
    ax.text(2.05, 6.72, "USB-C OTG serial", ha="left", color=TEAL, fontsize=7.8)
    arrow(ax, (1.9, 5.45), (1.9, 4.80), color=TEAL)
    ax.text(2.05, 5.12, "TX / RX / VCC / GND", ha="left", color=TEAL, fontsize=7.8)
    arrow(ax, (1.9, 3.85), (1.9, 3.20), color=PURPLE)

    # tengah: radio link
    ax.annotate("", xy=(6.35, 4.32), xytext=(3.35, 4.32),
                arrowprops=dict(arrowstyle="<|-|>", color=FLAME, linewidth=2.6))
    ax.text(4.85, 5.05, "LINK LoRa 923 MHz", ha="center", color=FLAME,
            fontsize=11, fontweight="bold")
    ax.text(4.85, 4.68, "point-to-point · 2–10 km LOS", ha="center",
            color=MUTED, fontsize=8.2)
    ax.text(4.85, 3.90, "metadata saja, tanpa gambar", ha="center",
            color=MUTED, fontsize=8.2, style="italic")

    # Kolom 2: posko
    ax.add_patch(Rectangle((6.35, 1.30), 3.5, 7.30, facecolor="#14141c",
                           edgecolor=LINE, linewidth=1.2, zorder=0,
                           linestyle=(0, (5, 4))))
    ax.text(8.1, 8.28, "DI POSKO", ha="center", color=AMBER,
            fontsize=10, fontweight="bold")

    box(ax, 6.7, 7.05, 2.8, 0.95, "Antena 923 MHz",
        "3 dBi, boleh ditinggikan", color="#232333", fs=10.5)
    box(ax, 6.7, 5.45, 2.8, 0.95, "E22-900T22D",
        "SX1262, penerima", color="#2b2333", edge=PURPLE, fs=10.5)
    box(ax, 6.7, 3.85, 2.8, 0.95, "ESP32-S3-Zero",
        "Parse paket metadata", color="#1f2b33", edge=TEAL, fs=10.5)
    box(ax, 6.7, 2.25, 2.8, 0.95, "Laptop LOQ",
        "pyserial → FastAPI\n→ SQLite → dashboard", color="#232333", fs=10.5)

    arrow(ax, (8.1, 7.05), (8.1, 6.40), color=PURPLE)
    arrow(ax, (8.1, 5.45), (8.1, 4.80), color=TEAL)
    arrow(ax, (8.1, 3.85), (8.1, 3.20), color=TEAL)
    ax.text(8.25, 3.52, "USB", ha="left", color=TEAL, fontsize=7.8)

    # catatan bawah
    ax.text(5, 0.92,
            "Ditransmisikan:  node_id · mission_id · waktu · lat · lon · alt · fix · sats · hdop",
            ha="center", va="center", color=MUTED, fontsize=8.4)
    ax.text(5, 0.50,
            "class · confidence · bbox · heading · pitch · roll",
            ha="center", va="center", color=MUTED, fontsize=8.4)

    save(fig, "fig1_alur_data.png")


# ---------------------------------------------------------- 2. rincian paket
def fig_packet():
    fig, ax = blank(12.5, 5.2)
    ax.text(5, 9.3, "Isi Paket LoRa vs Yang Tetap di Ponsel",
            ha="center", color=TEXT, fontsize=15, fontweight="bold")
    ax.text(5, 8.75, "LoRa lambat: hanya metadata ringkas setiap 5–10 detik",
            ha="center", color=AMBER, fontsize=10)

    fields = [
        ("node_id", "ID node (1–2 byte)", BLUE),
        ("mission_id", "ID misi", BLUE),
        ("t", "timestamp GNSS", BLUE),
        ("lat / lon", "posisi (int32, 1e-7°)", GREEN),
        ("alt", "ketinggian (int16)", GREEN),
        ("fix / sats", "kualitas GPS", GREEN),
        ("hdop", "akurasi horizontal", GREEN),
        ("class", "api / asap / bukan", FLAME),
        ("conf", "0–100", FLAME),
        ("bbox", "kotak deteksi", FLAME),
        ("heading/pitch/roll", "sikap kamera", PURPLE),
    ]

    y = 7.75
    for i, (name, desc, col) in enumerate(fields):
        yy = 7.75 - i * 0.62
        ax.add_patch(FancyBboxPatch((1.0, yy - 0.20), 3.4, 0.42,
                                    boxstyle="round,pad=0.01,rounding_size=0.08",
                                    facecolor="#1c1c26", edgecolor=col, linewidth=1.3))
        ax.text(1.2, yy, name, ha="left", va="center", color=col,
                fontsize=9.5, fontweight="bold", family="monospace")
        ax.text(4.55, yy, desc, ha="left", va="center", color=MUTED, fontsize=9)

    # kanan: gambar tetap di ponsel
    ax.add_patch(FancyBboxPatch((6.0, 1.15), 3.6, 6.55,
                                boxstyle="round,pad=0.02,rounding_size=0.12",
                                facecolor="#2a1a1a", edgecolor=RED, linewidth=2.0))
    ax.text(7.8, 7.05, "TETAP DI PONSEL", ha="center", color=RED,
            fontsize=11, fontweight="bold")
    ax.text(7.8, 6.45, "Foto JPEG 12 MP", ha="center", color=TEXT,
            fontsize=12, fontweight="bold")
    ax.text(7.8, 5.95, "+ EXIF GPS", ha="center", color=TEXT,
            fontsize=12, fontweight="bold")
    ax.plot([6.4, 9.2], [5.55, 5.55], color=RED, linewidth=1, alpha=0.45)
    ax.text(7.8, 4.95, "Satu misi 30 menit", ha="center", color=MUTED, fontsize=9.5)
    ax.text(7.8, 4.45, "≈ 900 foto", ha="center", color=TEXT,
            fontsize=11, fontweight="bold")
    ax.text(7.8, 3.95, "≈ 3–4 GB", ha="center", color=TEXT,
            fontsize=11, fontweight="bold")
    ax.plot([6.4, 9.2], [3.50, 3.50], color=RED, linewidth=1, alpha=0.45)
    ax.text(7.8, 2.90, "Tidak bisa lewat LoRa.",
            ha="center", va="center", color=AMBER, fontsize=9.8, fontweight="bold")
    ax.text(7.8, 2.15, "Dipindah via Wi-Fi",
            ha="center", va="center", color=AMBER, fontsize=9.8, fontweight="bold")
    ax.text(7.8, 1.68, "setelah drone mendarat.",
            ha="center", va="center", color=AMBER, fontsize=9.8, fontweight="bold")

    save(fig, "fig2_paket_data.png")


# ---------------------------------------------------------- 3. chart biaya
def fig_cost():
    fig, ax = plt.subplots(figsize=(12.5, 5.6), dpi=200)
    fig.patch.set_facecolor(OBS)
    ax.set_facecolor(OBS)

    labels = ["Struktur\npayload", "Modul radio\nE22 ×2", "ESP32-S3-Zero\n(1 tambahan)",
              "Antena\n×2", "UBEC +\nkabel", "Kontingensi\n12%"]
    vals = [375000, 750000, 99000, 90000, 192000, 180720]
    colors = ["#4f8fd6", "#9b7fd4", "#4fb5a8", "#e5a954", "#6fbf8f", "#ff6b35"]

    bars = ax.bar(range(len(vals)), vals, color=colors, width=0.62,
                  edgecolor=OBS, linewidth=1.5, zorder=3)
    for i, (b, v) in enumerate(zip(bars, vals)):
        ax.text(b.get_x() + b.get_width()/2, v + 16000,
                f"Rp {v:,.0f}".replace(",", "."),
                ha="center", color=TEXT, fontsize=9.5, fontweight="bold", zorder=4)

    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, color=TEXT, fontsize=9.5)
    ax.tick_params(axis="y", colors=MUTED, labelsize=9)
    ax.set_ylabel("Rupiah", color=MUTED, fontsize=10)
    ax.set_ylim(0, max(vals) * 1.22)
    ax.yaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(lambda v, p: f"{v/1000:.0f}rb"))
    ax.grid(axis="y", color="#26262f", linewidth=0.8, zorder=0)
    for s in ax.spines.values():
        s.set_color(LINE)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    total = sum(vals)
    ax.text(0.98, 0.94, f"TOTAL  Rp {total:,.0f}".replace(",", "."),
            transform=ax.transAxes, ha="right", va="top",
            color=OBS, fontsize=13, fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.55", facecolor=AMBER, edgecolor="none"))

    ax.set_title("Rincian Biaya Payload — Belanja per Komponen",
                 color=TEXT, fontsize=14, fontweight="bold", pad=14)
    save(fig, "fig3_biaya_komponen.png")


# ---------------------------------------------------------- 4. chart perbandingan
def fig_compare():
    fig, ax = plt.subplots(figsize=(12.5, 5.4), dpi=200)
    fig.patch.set_facecolor(OBS)
    ax.set_facecolor(OBS)

    opsi = ["Zero + E22-900M22S\n(SPI, SMD)",
            "Zero + E22-900T22S\n(UART, SMD)",
            "Zero + E22-900T22D\n(UART, DIP) ← dipilih",
            "2× Heltec LoRa32 V3\n(satu board)"]
    total = [1158880, 1430720, 1686720, 1927040]
    need_solder = [True, True, False, False]
    cols = [RED, AMBER, GREEN, BLUE]

    bars = ax.barh(range(len(total)), total, color=cols, height=0.55,
                   edgecolor=OBS, linewidth=1.5, zorder=3)
    for i, (b, v, solder) in enumerate(zip(bars, total, need_solder)):
        ax.text(v + 22000, b.get_y() + b.get_height()/2,
                f"Rp {v:,.0f}".replace(",", "."),
                va="center", color=TEXT, fontsize=10, fontweight="bold", zorder=4)
        tag = "perlu solder SMD" if solder else "tanpa solder"
        ax.text(v + 22000, b.get_y() + b.get_height()/2 - 0.30,
                tag, va="center", color=(RED if solder else GREEN), fontsize=8.2)

    ax.set_yticks(range(len(opsi)))
    ax.set_yticklabels(opsi, color=TEXT, fontsize=9.5)
    ax.invert_yaxis()
    ax.set_xlabel("Total termasuk kontingensi 12% (Rupiah)", color=MUTED, fontsize=10)
    ax.tick_params(axis="x", colors=MUTED, labelsize=9)
    ax.set_xlim(0, max(total) * 1.34)
    ax.xaxis.set_major_formatter(
        matplotlib.ticker.FuncFormatter(lambda v, p: f"{v/1_000_000:.1f}jt"))
    ax.set_xticks([0, 500000, 1000000, 1500000, 2000000])
    ax.grid(axis="x", color="#26262f", linewidth=0.8, zorder=0)
    for s in ax.spines.values():
        s.set_color(LINE)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    ax.set_title("Perbandingan Pilihan Modul LoRa",
                 color=TEXT, fontsize=14, fontweight="bold", pad=14)
    ax.text(0.99, 1.02, "Yang dipilih: termurah kedua TANPA solder",
            transform=ax.transAxes, ha="right", va="bottom",
            color=GREEN, fontsize=9.5, fontweight="bold")
    save(fig, "fig4_perbandingan.png")


# ---------------------------------------------------------- 5. fungsi vs biaya
def fig_fungsi():
    fig, ax = blank(12.5, 6.4)
    ax.text(5, 9.5, "Sudah Ada di Realme vs Yang Harus Dibeli",
            ha="center", color=TEXT, fontsize=15, fontweight="bold")
    ax.text(5, 8.95, "Ponsel menutup sebagian besar fungsi — radio jarak jauh satu-satunya celah",
            ha="center", color=AMBER, fontsize=10)

    ax.add_patch(Rectangle((0.15, 0.5), 4.5, 7.9, facecolor="#14141c",
                           edgecolor=GREEN, linewidth=1.6, zorder=0))
    ax.text(2.4, 7.95, "SUDAH ADA · Rp 0", ha="center", color=GREEN,
            fontsize=11.5, fontweight="bold")

    punya = [
        ("Kamera 16 MP", "Sony IMX519, inti payload"),
        ("GNSS multi-sistem", "GPS+GLONASS+Galileo+BeiDou"),
        ("Pemroses AI", "Snapdragon 710, Adreno 616"),
        ("Baterai 4000 mAh", "35–45 menit terbang"),
        ("Wi-Fi", "transfer foto pasca-mendarat"),
        ("IMU + kompas", "sikap kamera untuk proyeksi"),
        ("ESP32-S3-Zero", "1 unit sudah dimiliki"),
    ]
    for i, (n, d) in enumerate(punya):
        yy = 7.20 - i * 0.90
        ax.add_patch(FancyBboxPatch((0.55, yy - 0.32), 3.9, 0.66,
                                    boxstyle="round,pad=0.01,rounding_size=0.09",
                                    facecolor="#16241c", edgecolor=GREEN, linewidth=1.2))
        ax.text(0.75, yy + 0.10, n, ha="left", va="center", color=TEXT,
                fontsize=9.8, fontweight="bold")
        ax.text(0.75, yy - 0.16, d, ha="left", va="center", color=MUTED, fontsize=8)

    ax.add_patch(Rectangle((5.35, 0.5), 4.5, 7.9, facecolor="#1f1616",
                           edgecolor=FLAME, linewidth=1.6, zorder=0))
    ax.text(7.6, 7.95, "HARUS DIBELI · Rp 1.686.720", ha="center", color=FLAME,
            fontsize=11.5, fontweight="bold")

    beli = [
        ("Modul radio LoRa", "E22-900T22D × 2 — Rp 750.000"),
        ("ESP32-S3-Zero kedua", "node satunya — Rp 99.000"),
        ("Antena 923 MHz", "× 2 — Rp 90.000"),
        ("UBEC + kabel + OTG", "catu daya & sambungan — Rp 192.000"),
        ("Struktur payload", "PETG, damper, velcro, sekrup — Rp 375.000"),
        ("Kontingensi 12%", "cadangan harga — Rp 180.720"),
    ]
    for i, (n, d) in enumerate(beli):
        yy = 7.20 - i * 0.90
        ax.add_patch(FancyBboxPatch((5.75, yy - 0.32), 3.9, 0.66,
                                    boxstyle="round,pad=0.01,rounding_size=0.09",
                                    facecolor="#2a1c18", edgecolor=FLAME, linewidth=1.2))
        ax.text(5.95, yy + 0.10, n, ha="left", va="center", color=TEXT,
                fontsize=9.8, fontweight="bold")
        ax.text(5.95, yy - 0.16, d, ha="left", va="center", color=MUTED, fontsize=8)

    save(fig, "fig5_sudah_ada_vs_beli.png")


print("Membuat visual...")
fig_dataflow()
fig_packet()
fig_cost()
fig_compare()
fig_fungsi()
print(f"\nSelesai. Output di: {OUT}")
