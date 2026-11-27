"""Baixa os binários Windows exigidos em vendor/ para empacotar o Handcut.

Uso:
    python tools/download_vendor.py
    python tools/download_vendor.py --update-ytdlp
    python tools/download_vendor.py --force
"""
from __future__ import annotations

import argparse
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = ROOT / "vendor"
USER_AGENT = "Handcut-Build/1.0"

FFMPEG_ZIP_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
DENO_ZIP_URL = "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip"
YTDLP_EXE_URL = "https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.exe"


def _download_file(url: str, destination: Path) -> None:
    print(f"Baixando {url} ...")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=300) as response, destination.open("wb") as out:
        shutil.copyfileobj(response, out, length=1024 * 1024)


def _extract_members(zip_path: Path, filenames: tuple[str, ...], dest_dir: Path) -> None:
    wanted = {name.lower(): name for name in filenames}
    found: set[str] = set()
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            base = Path(info.filename).name.lower()
            if base in wanted:
                target = dest_dir / wanted[base]
                with zf.open(info) as src, target.open("wb") as dst:
                    shutil.copyfileobj(src, dst, length=1024 * 1024)
                found.add(base)
                print(f"  extraído: {target.name} ({target.stat().st_size / 1024 / 1024:.1f} MB)")
    missing = [orig for low, orig in wanted.items() if low not in found]
    if missing:
        raise RuntimeError(f"Arquivos não encontrados em {zip_path.name}: {', '.join(missing)}")


def ensure_vendor(*, force: bool = False, update_ytdlp: bool = False) -> None:
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)

    need_ffmpeg = force or not (VENDOR_DIR / "ffmpeg.exe").is_file() or not (VENDOR_DIR / "ffprobe.exe").is_file()
    need_deno = force or not (VENDOR_DIR / "deno.exe").is_file()
    need_ytdlp = force or update_ytdlp or not (VENDOR_DIR / "yt-dlp.exe").is_file()

    with tempfile.TemporaryDirectory(prefix="handcut-vendor-") as tmp:
        tmp_dir = Path(tmp)

        if need_ffmpeg:
            zip_path = tmp_dir / "ffmpeg.zip"
            _download_file(FFMPEG_ZIP_URL, zip_path)
            _extract_members(zip_path, ("ffmpeg.exe", "ffprobe.exe"), VENDOR_DIR)
        else:
            print("ffmpeg.exe e ffprobe.exe já presentes em vendor/ (mantidos).")

        if need_deno:
            zip_path = tmp_dir / "deno.zip"
            _download_file(DENO_ZIP_URL, zip_path)
            _extract_members(zip_path, ("deno.exe",), VENDOR_DIR)
        else:
            print("deno.exe já presente em vendor/ (mantido).")

        if need_ytdlp:
            target = VENDOR_DIR / "yt-dlp.exe"
            tmp_exe = tmp_dir / "yt-dlp.exe"
            _download_file(YTDLP_EXE_URL, tmp_exe)
            shutil.move(str(tmp_exe), str(target))
            print(f"  salvo: {target.name} ({target.stat().st_size / 1024 / 1024:.1f} MB)")
        else:
            print("yt-dlp.exe já presente em vendor/ (mantido).")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Baixa ffmpeg, ffprobe, deno e yt-dlp (Windows) para vendor/.")
    parser.add_argument("--force", action="store_true", help="Baixa novamente todos os binários.")
    parser.add_argument(
        "--update-ytdlp",
        action="store_true",
        help="Atualiza sempre o yt-dlp.exe mesmo quando já existe em cache.",
    )
    args = parser.parse_args(argv)
    ensure_vendor(force=args.force, update_ytdlp=args.update_ytdlp)


if __name__ == "__main__":
    main()
