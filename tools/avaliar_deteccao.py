"""Mede quanto a sugestão automática de lances (detector.py) acerta, comparando com o seu gabarito.

Uso (na pasta do projeto, com o ambiente virtual ativo):
    python tools/avaliar_deteccao.py VIDEO.mp4 GABARITO.txt --camisa clara

O gabarito é um arquivo de texto com uma linha por lance, no tempo do PLAYER do vídeo (não do
relógio do jogo):
    ataque  0:12  0:42
    defesa  0:42  0:52
    ataque  1:07  1:17
Tempos como M:SS ou H:MM:SS. Linhas começando com # são ignoradas. "ataque" e "defesa" são do
SEU time. Quanto mais lances você anotar (inclusive os que o programa deve ignorar), mais
confiável é a nota.

A primeira passada (YOLO) é lenta; use --cache para guardar o resultado em um arquivo e testar
outros ajustes das regras em segundos.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import detector  # noqa: E402


def parse_time(text: str) -> float:
    seconds = 0.0
    for part in text.strip().split(":"):
        seconds = seconds * 60 + float(part)
    return seconds


def read_truth(path: Path) -> list[tuple[str, float, float]]:
    truth = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.split("#")[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) != 3 or parts[0].lower() not in {detector.ATAQUE, detector.DEFESA}:
            sys.exit(f"{path.name}, linha {number}: use 'ataque ou defesa  início  fim' (ex.: ataque 0:12 0:42).")
        truth.append((parts[0].lower(), parse_time(parts[1]), parse_time(parts[2])))
    return truth


def overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def probe(video: Path) -> dict:
    import subprocess
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration",
         "-of", "json", str(video)], capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    stream = data["streams"][0]
    return {"width": int(stream["width"]), "height": int(stream["height"]), "duration": float(data["format"]["duration"])}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video", type=Path)
    parser.add_argument("gabarito", type=Path)
    parser.add_argument("--camisa", choices=["clara", "escura"], required=True, help="camisa do SEU time")
    parser.add_argument("--cache", type=Path, help="arquivo .json para guardar/reaproveitar a leitura do YOLO")
    args = parser.parse_args()

    info = probe(args.video)
    if args.cache and args.cache.is_file():
        samples = json.loads(args.cache.read_text(encoding="utf-8"))
        print(f"Leitura do YOLO reaproveitada de {args.cache} ({len(samples)} quadros).")
    else:
        print("Rodando o YOLO (pode demorar)…")
        samples = detector.extract_samples(
            args.video, info["duration"], info["width"], info["height"],
            progress=lambda value: print(f"\r  {value:.0%}", end="", flush=True))
        print()
        if args.cache:
            args.cache.write_text(json.dumps(samples), encoding="utf-8")

    suggestions = detector.suggest(samples, args.camisa == "clara", duration=info["duration"])
    truth = read_truth(args.gabarito)
    other = {detector.ATAQUE: detector.DEFESA, detector.DEFESA: detector.ATAQUE}

    print(f"\nLimiar claro/escuro (Otsu): {detector.light_threshold(samples):.0f}")
    print("\nPor lance do gabarito (quanto do tempo a sugestão cobriu):")
    for kind, start, end in truth:
        same = sum(overlap(start, end, s["start"], s["end"]) for s in suggestions[kind])
        wrong = sum(overlap(start, end, s["start"], s["end"]) for s in suggestions[other[kind]])
        length = end - start
        print(f"  {kind:6s} {start:7.1f}s-{end:7.1f}s  certo {same / length:4.0%}  tipo trocado {wrong / length:4.0%}"
              f"  sem sugestão {max(0.0, 1 - (same + wrong) / length):4.0%}")

    print("\nPor sugestão (o que o programa propôs):")
    for kind in (detector.ATAQUE, detector.DEFESA):
        total = sum(s["end"] - s["start"] for s in suggestions[kind])
        right = sum(overlap(s["start"], s["end"], a, b) for s in suggestions[kind] for k, a, b in truth if k == kind)
        wrong = sum(overlap(s["start"], s["end"], a, b) for s in suggestions[kind] for k, a, b in truth if k == other[kind])
        print(f"  {kind:6s} {len(suggestions[kind])} trecho(s), {total:.0f}s: dentro do mesmo tipo no gabarito "
              f"{right:.0f}s, no tipo oposto {wrong:.0f}s, fora do gabarito {max(0.0, total - right - wrong):.0f}s")


if __name__ == "__main__":
    main()
