"""Gera o programa para distribuir: dist/Handcut/ (pasta do programa) e dist/Handcut.zip.

Uso (com o ambiente virtual ativo):
    pip install -r requirements-dev.txt
    python build.py

Antes de rodar, a pasta vendor/ precisa ter os programas que vão dentro do pacote:
ffmpeg, ffprobe, deno e yt-dlp (no Windows, com ".exe").
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_NAME = "Handcut"
SUFFIX = ".exe" if os.name == "nt" else ""
REQUIRED_TOOLS = [f"{name}{SUFFIX}" for name in ("ffmpeg", "ffprobe", "deno", "yt-dlp")]
ICON_PATH = ROOT / "handcut.ico"

def check_vendor() -> None:
    vendor = ROOT / "vendor"

    if not ICON_PATH.is_file():
        sys.exit(f"Ícone não encontrado: {ICON_PATH}")
        
    missing = [name for name in REQUIRED_TOOLS if not (vendor / name).is_file()]
    if missing:
        sys.exit(f"Faltam arquivos em {vendor}:\n  " + "\n  ".join(missing))


def main() -> None:
    check_vendor()
    for folder in ("build", "dist"):
        shutil.rmtree(ROOT / folder, ignore_errors=True)
    separator = os.pathsep  # o PyInstaller usa ";" no Windows e ":" nos outros sistemas
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--windowed",                      # sem janela de terminal
        "--name", APP_NAME,
        "--specpath", "build",             # mantém o arquivo .spec dentro de build/
        "--add-data", f"{ROOT / 'templates'}{separator}templates",
        "--add-data", f"{ROOT / 'static'}{separator}static",
        "--add-data", f"{ROOT / 'vendor'}{separator}vendor",
        "--icon", str(ICON_PATH),
        str(ROOT / "launcher.py"),
    ]
    subprocess.run(command, cwd=ROOT, check=True)
    archive = shutil.make_archive(str(ROOT / "dist" / APP_NAME), "zip", ROOT / "dist", APP_NAME)
    size = Path(archive).stat().st_size / 1024 / 1024
    print(f"\nPronto:\n  pasta: {ROOT / 'dist' / APP_NAME}\n  ZIP:   {archive} ({size:.0f} MB)")


if __name__ == "__main__":
    main()