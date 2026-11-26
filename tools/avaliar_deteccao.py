"""Mede quanto a sugestão automática de lances (detector.py) acerta, usando as regras oficiais.

Uso (na pasta do projeto, com o ambiente virtual ativo):
    python tools/avaliar_deteccao.py VIDEO.mp4 GABARITO.txt --camisa clara

Formato do gabarito (tempos no PLAYER do vídeo; linhas com '#' são comentários):
    ataque  0:20 0:44
    defesa  0:45 0:52 opcional   # lance ambíguo: não conta no recall nem como erro
    ignorar 2:46 2:50            # encerramento, replay, intervalo...
    emenda  1:22.5               # corte entre trechos: exclui ±5 s ao redor

Use --inverter para avaliar o time adversário usando o mesmo gabarito, e --periodos para testar
recortes específicos com `detector.suggest_periods` (ex.: --periodos 0-80 85-166).
Use --cache para guardar a leitura do YOLO em um .json e testar regras sem rodar o YOLO de novo.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import detector  # noqa: E402
import metricas  # noqa: E402


def probe(video: Path) -> dict:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration",
         "-of", "json", str(video)], capture_output=True, text=True, check=True)
    data = json.loads(result.stdout)
    stream = data["streams"][0]
    return {"width": int(stream["width"]), "height": int(stream["height"]), "duration": float(data["format"]["duration"])}


def machine_info() -> str:
    """Resumo curto da máquina onde o teste rodou (para registrar junto com o tempo de CPU)."""
    cpu = platform.processor() or "CPU desconhecida"
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                cpu = winreg.QueryValueEx(key, "ProcessorNameString")[0].strip()
        except OSError:
            pass
    ram_gb = ""
    if os.name == "nt":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("sullAvailExtendedVirtual", ctypes.c_ulonglong)]

        status = MemoryStatus(dwLength=ctypes.sizeof(MemoryStatus))
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            ram_gb = f", {status.ullTotalPhys / 1024 ** 3:.1f} GB RAM"
    return f"{cpu} ({os.cpu_count() or '?'} núcleos lógicos{ram_gb}, {platform.system()} {platform.release()})"


def parse_periods(raw: list[str], duration: float) -> list[tuple[float, float]]:
    periods: list[tuple[float, float]] = []
    for item in raw:
        left, sep, right = item.partition("-")
        if not sep:
            raise ValueError(f"Período inválido '{item}'. Use INÍCIO-FIM (ex.: 0-80 ou 1:25-3:10).")
        start, end = max(0.0, metricas.parse_time(left)), min(duration, metricas.parse_time(right))
        if end <= start:
            raise ValueError(f"Período inválido '{item}': fim precisa ser maior que início.")
        periods.append((start, end))
    return periods


def fmt_ratio(value: float | None) -> str:
    if value is None:
        return "n/d"
    if value == float("inf"):
        return "inf"
    return f"{value:.2f}"


def fmt_ok(flag: bool | None) -> str:
    return "n/d" if flag is None else ("PASSA" if flag else "REPROVA")


def print_result(res: dict, analyzed_duration: float, elapsed: float | None) -> None:
    est = metricas.estimativa_revisao(res["sugestoes"], res["partidos"], analyzed_duration)
    tempo_rel = None if elapsed is None or analyzed_duration <= 0 else elapsed / analyzed_duration
    check = metricas.veredito(res, tempo_rel, est["segundos_por_jogo"])

    recall_txt = "n/d" if res["recall"] is None else f"{res['recall']:.0%} ({res['encontrados']}/{res['lances']})"
    print(f"\n=== Tipo: {res['tipo'].upper()} ===")
    print(f"  Recall (soma pedaços >=50%): {recall_txt} [{fmt_ok(check['recall'])}]")
    print(f"  Lances partidos (>=2 sug.):   {res['partidos']} de {res['encontrados']} encontrados")
    print(f"  Sugestões: {res['sugestoes']} total | {res['corretas']} corretas "
          f"(parcial <2s: {res['corretas_com_menos_de_2s']}) | {res['neutras']} neutras | "
          f"{res['erradas']} erradas (tipo trocado: {res['erradas_tipo_trocado']}, fora: {res['erradas_fora_de_lance']})")
    print(f"  Erradas / Corretas:           {fmt_ratio(res['erradas_por_correta'])} [{fmt_ok(check['erradas_por_correta'])}]")
    print(f"  Revisão estimada (p/ 60 min): ~{est['segundos_por_jogo'] / 60:.1f} min "
          f"(~{est['sugestoes_por_jogo']:.0f} sug./jogo) [{fmt_ok(check['revisao_estimada'])}]")
    for item in res["por_lance"]:
        status = "PARTIDO" if item["partido"] else ("OK     " if item["encontrado"] else "PERDIDO")
        print(f"    lance {item['start']:6.1f}s-{item['end']:6.1f}s  {status}  cob.{item['cobertura']:4.0%}  ({item['pedacos']} pedaço(s))")
    for item in res["por_sugestao"]:
        print(f"    sug.  {item['start']:6.1f}s-{item['end']:6.1f}s  {item['classe']:22s}  sobrep.={item['sobreposicao_mesmo_tipo']:.1f}s")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("video", type=Path)
    parser.add_argument("gabarito", type=Path)
    parser.add_argument("--camisa", choices=sorted(detector.ALLOWED_SHIRTS), required=True, help="camisa do SEU time")
    parser.add_argument("--tipo", choices=["ataque", "defesa", "ambos"], default="ambos")
    parser.add_argument("--inverter", action="store_true", help="inverte ataque/defesa do gabarito (avalia o outro time)")
    parser.add_argument("--periodos", nargs="+", help="faixas INÍCIO-FIM para testar suggest_periods (ex.: 0-80 85-166)")
    parser.add_argument("--piso-segundos", type=float, default=0.0, help="piso mínimo (s) para sugestão parcial contar")
    parser.add_argument("--piso-fracao", type=float, default=0.0, help="piso mínimo (fração do lance) para parcial contar")
    parser.add_argument("--cache", type=Path, help="arquivo .json para guardar/reaproveitar a leitura do YOLO")
    args = parser.parse_args()

    info = probe(args.video)
    periods = parse_periods(args.periodos, info["duration"]) if args.periodos else None
    gabarito = metricas.ler_gabarito(args.gabarito)
    if args.inverter:
        gabarito = gabarito.invertido()

    elapsed: float | None = None
    if args.cache and args.cache.is_file():
        cached = json.loads(args.cache.read_text(encoding="utf-8"))
        if isinstance(cached, list):
            period_samples = [(info["duration"], cached)] if not periods else None
            samples_flat = cached
        else:
            period_samples = [(float(end), s) for end, s in cached["period_samples"]]
            samples_flat = [s for _, items in period_samples for s in items]
        print(f"Leitura do YOLO reaproveitada de {args.cache} ({len(samples_flat)} quadros; tempo de CPU não medido neste run).")
        if period_samples is None:
            sys.exit("Cache antigo sem períodos; apague o cache ou rode sem --periodos.")
    else:
        print("Rodando o YOLO…")
        started = time.perf_counter()
        person_detector = detector.PersonDetector()
        targets = periods or [(0.0, info["duration"])]
        period_samples = []
        for idx, (start, end) in enumerate(targets, 1):
            samples = detector.extract_samples(
                args.video, info["duration"], info["width"], info["height"], start=start, end=end,
                detector=person_detector,
                progress=lambda v, n=idx, tot=len(targets): print(f"\r  período {n}/{tot}: {v:.0%}", end="", flush=True))
            print()
            period_samples.append((end, samples))
        elapsed = time.perf_counter() - started
        samples_flat = [s for _, items in period_samples for s in items]
        if args.cache:
            args.cache.write_text(json.dumps({"period_samples": period_samples}), encoding="utf-8")

    analyzed_duration = sum(e - s for s, e in (periods or [(0.0, info["duration"])]))
    t_rules = time.perf_counter()
    if periods:
        suggestions = detector.suggest_periods(period_samples, shirt=args.camisa)
    else:
        suggestions = detector.suggest(samples_flat, shirt=args.camisa, duration=info["duration"])
    if elapsed is not None:
        elapsed += time.perf_counter() - t_rules

    proto = detector.team_prototypes(samples_flat, shirt=args.camisa)
    print(f"\nMáquina: {machine_info()}")
    print(f"Vídeo:   {args.video.name} ({info['width']}x{info['height']}, analisado {analyzed_duration:.1f}s de {info['duration']:.1f}s)")
    print(f"Protótipos de cor ({proto['mode']}): meu={[round(float(v), 1) for v in proto['mine'][0]]} "
          f"vs adv={[round(float(v), 1) for v in proto['other']]} ({sum(len(s['people']) for s in samples_flat)} obs.)")
    if elapsed is not None:
        ratio = elapsed / max(analyzed_duration, 1e-6)
        print(f"Tempo de análise: {elapsed:.1f}s ({ratio:.2f}x a duração) "
              f"[{'PASSA' if ratio <= metricas.META_TEMPO_ANALISE else 'REPROVA'}]")

    kinds = [metricas.ATAQUE, metricas.DEFESA] if args.tipo == "ambos" else [args.tipo]
    for kind in kinds:
        res = metricas.avaliar(gabarito, suggestions[kind], kind,
                               piso_segundos=args.piso_segundos, piso_fracao=args.piso_fracao)
        print_result(res, analyzed_duration, elapsed)


if __name__ == "__main__":
    main()
