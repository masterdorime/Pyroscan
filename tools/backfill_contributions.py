"""
GitHub contribution backfill — commit kosong dengan tanggal yang ditentukan.

Pemakaian:
    python tools/backfill_contributions.py --dates 2026-11-13 2026-11-15
    python tools/backfill_contributions.py --range 2026-11-01 2026-11-16
    python tools/backfill_contributions.py --range 2026-11-01 2026-11-16 --skip-existing
    python tools/backfill_contributions.py --range ... --push

Default TIDAK push. Tanpa --push, commit dibuat lokal saja supaya bisa diperiksa
dulu. Hapus salah satu dengan: git rebase -i atau git reset --hard <sha sebelum>.

Catatan: commit ini kosong (--allow-empty) dan hanya mengisi grafik kontribusi.
Yang tercatat sebagai "kerja" di grafik adalah tanggal commit, bukan isinya.
"""

import argparse
import random
import subprocess
import sys
from datetime import date, datetime, timedelta


def run(args, env=None):
    r = subprocess.run(args, capture_output=True, text=True, env=env)
    if r.returncode != 0:
        print("GAGAL:", " ".join(args))
        print(r.stderr.strip())
        sys.exit(1)
    return r.stdout.strip()


def repo_commit_dates():
    """Tanggal (YYYY-MM-DD) yang sudah punya commit di repo ini."""
    out = run(["git", "log", "--pretty=%ad", "--date=short"])
    return set(out.splitlines())


def commit_on(day, count, offset_min=0):
    """Buat `count` commit kosong pada tanggal `day`."""
    import os
    made = []
    for i in range(count):
        hour = 9 + i * 3
        minute = random.randint(0, 59)
        stamp = f"{day}T{hour:02d}:{minute:02d}:{offset_min:+03d}:00"
        env = os.environ.copy()
        env["GIT_AUTHOR_DATE"] = stamp
        env["GIT_COMMITTER_DATE"] = stamp
        msg = f"chore: contribution {day}"
        run(["git", "commit", "--allow-empty", "-m", msg], env=env)
        made.append(stamp)
        print(f"  commit  {stamp}  {msg}")
    return made


def main():
    ap = argparse.ArgumentParser(description="Backfill grafik kontribusi GitHub.")
    ap.add_argument("--dates", nargs="+", help="Daftar tanggal YYYY-MM-DD")
    ap.add_argument("--range", nargs=2, metavar=("MULAI", "AKHIR"),
                    help="Rentang tanggal, inklusif")
    ap.add_argument("--per-day", type=int, default=1,
                    help="Jumlah commit per hari (default 1, maks 5)")
    ap.add_argument("--skip-existing", action="store_true",
                    help="Lewati tanggal yang sudah punya commit")
    ap.add_argument("--weekday-only", action="store_true",
                    help="Lewati Sabtu dan Minggu")
    ap.add_argument("--push", action="store_true",
                    help="Push ke origin setelah commit dibuat")
    ap.add_argument("--preview", action="store_true",
                    help="Tampilkan rencana saja, tidak membuat commit")
    ap.add_argument("--timezone", default="+07", help="Offset zona, default +07")
    args = ap.parse_args()

    if not args.dates and not args.range:
        ap.error("pakai --dates atau --range")

    # kumpulkan tanggal target
    targets = []
    if args.dates:
        targets += [date.fromisoformat(d) for d in args.dates]
    if args.range:
        start = date.fromisoformat(args.range[0])
        end = date.fromisoformat(args.range[1])
        if end < start:
            ap.error("tanggal akhir sebelum tanggal mulai")
        d = start
        while d <= end:
            targets.append(d)
            d += timedelta(days=1)

    targets.sort()

    # filter
    existing = repo_commit_dates() if args.skip_existing else set()
    plan = []
    for d in targets:
        iso = d.isoformat()
        if args.weekday_only and d.weekday() >= 5:
            print(f"  lewat   {iso}  (akhir pekan)")
            continue
        if iso in existing:
            print(f"  lewat   {iso}  (sudah ada commit)")
            continue
        if d > date.today():
            print(f"  lewat   {iso}  (masa depan)")
            continue
        plan.append(d)

    if not plan:
        print("\nTidak ada tanggal yang perlu diisi.")
        return

    n = max(1, min(5, args.per_day))
    tz = int(args.timezone)
    random.seed(42)

    if args.preview:
        print(f"\n[PREVIEW] Akan mengisi {len(plan)} tanggal, "
              f"{n} commit per hari:\n")
        for d in plan:
            print(f"  rencana  {d.isoformat()}")
        print("\nTidak ada commit dibuat. Jalankan tanpa --preview untuk eksekusi.")
        return

    print(f"\nMengisi {len(plan)} tanggal, {n} commit per hari:\n")
    for d in plan:
        commit_on(d.isoformat(), n, tz)

    print("\nSelesai. Periksa dengan: git log --pretty='%h %ad %s' --date=iso -20")

    if args.push:
        print("\nPush ke origin...")
        run(["git", "push", "origin", "HEAD"])
        print("Push selesai.")
    else:
        print("\nBelum di-push. Jalankan ulang dengan --push, "
              "atau: git push origin HEAD")


if __name__ == "__main__":
    main()
