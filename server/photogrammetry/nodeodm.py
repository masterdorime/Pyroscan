"""NodeODM REST client. One door to photogrammetry."""
from __future__ import annotations

import json
import shutil
import time
import zipfile
from pathlib import Path

import requests

from .. import config


def _images(images_dir: Path) -> list[Path]:
    return sorted(
        p for p in Path(images_dir).iterdir()
        if p.is_file() and p.suffix.lower() in (".jpg", ".jpeg", ".png", ".tif", ".tiff")
    )


def create_task(images: list[Path], options: list[dict], host: str = config.NODEODM) -> str:
    handles = []
    files = []
    try:
        for p in images:
            fh = open(p, "rb")
            handles.append(fh)
            files.append(("images", (p.name, fh, "image/jpeg")))
        r = requests.post(
            f"{host}/task/new",
            files=files,
            data={"options": json.dumps(options)},
            timeout=900,
        )
        r.raise_for_status()
        return r.json()["uuid"]
    finally:
        for fh in handles:
            fh.close()


def wait(uuid: str, timeout: int = 3600, poll: int = 5,
         host: str = config.NODEODM, on_update=None) -> dict:
    end = time.time() + timeout
    while time.time() < end:
        r = requests.get(f"{host}/task/{uuid}/info", timeout=30)
        r.raise_for_status()
        info = r.json()
        if on_update:
            on_update(info)
        code = info.get("status", {}).get("code")
        if code == 40:
            return info
        if code in (30, 50):
            raise RuntimeError(f"ODM task {uuid} ended with code {code}: {info.get('status')}")
        time.sleep(poll)
    raise TimeoutError(f"ODM task {uuid} exceeded {timeout}s")


def download(uuid: str, out_zip: Path, host: str = config.NODEODM) -> None:
    r = requests.get(f"{host}/task/{uuid}/download/all.zip", stream=True, timeout=900)
    r.raise_for_status()
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with open(out_zip, "wb") as f:
        for chunk in r.iter_content(1024 * 256):
            if chunk:
                f.write(chunk)


def run(images_dir: Path | str, work_dir: Path | str, options: list[dict],
        on_update=None) -> tuple[Path, str]:
    images = _images(Path(images_dir))
    if not images:
        raise FileNotFoundError(f"no images in {images_dir}")
    uuid = create_task(images, options)
    wait(uuid, on_update=on_update)
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    zip_path = work / "odm.zip"
    download(uuid, zip_path)
    task_dir = work / "odm"
    if task_dir.exists():
        shutil.rmtree(task_dir)
    task_dir.mkdir(parents=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(task_dir)
    return task_dir, uuid
