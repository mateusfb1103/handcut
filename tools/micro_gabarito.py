"""Prepara e avalia o micro-gabarito por sinal (~30 quadros por vídeo) para os passos 1A, 1B e 1C.

Subcomandos:
    preparar VIDEO --saida TEMPLATE.json --grade GRADE.jpg [--passo 6.0] [--excluir INÍCIO-FIM ...]
        Extrai ~30 quadros espaçados, roda o detector de pessoas só neles (alguns segundos),
        desenha as caixas numeradas na grade e grava um JSON para preencher `lado_gol` (E/D/N)
        e `classe` de cada pessoa (meu / adv / fora).

    avaliar MICRO.json --pred PREDICOES.json
        Calcula acurácia de `lado_gol` (1A), acurácia de time (1B) e descarte de não jogadores (1C).
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

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


def read_frame_480p(video: Path, t: float, width: int, height: int) -> np.ndarray:
    out_h = detector.ANALYSIS_HEIGHT
    out_w = max(2, round(out_h * width / height / 2) * 2)
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(video), "-frames:v", "1",
         "-vf", f"scale={out_w}:{out_h}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        capture_output=True, check=True).stdout
    if len(raw) != out_w * out_h * 3:
        raise RuntimeError(f"Não consegui ler o quadro em t={t:.2f}s.")
    return np.frombuffer(raw, dtype=np.uint8).reshape(out_h, out_w, 3).copy()


def parse_exclusions(raw: list[str] | None) -> list[tuple[float, float]]:
    zones = []
    for item in raw or []:
        a, sep, b = item.partition("-")
        if not sep:
            raise ValueError(f"Faixa inválida '{item}'. Use INÍCIO-FIM.")
        zones.append((metricas.parse_time(a), metricas.parse_time(b)))
    return zones


def in_zones(t: float, zones: list[tuple[float, float]]) -> bool:
    return any(a <= t <= b for a, b in zones)


def cmd_preparar(args: argparse.Namespace) -> None:
    info = probe(args.video)
    zones = parse_exclusions(args.excluir)
    times = []
    t = args.inicio
    while t < info["duration"] - 1.0:
        if not in_zones(t, zones):
            times.append(round(t, 2))
        t += args.passo

    person_detector = detector.PersonDetector()
    frames_data = []
    tiles = []
    tile_w, tile_h = 568, 320
    for ts in times:
        frame = read_frame_480p(args.video, ts, info["width"], info["height"])
        h, w = frame.shape[:2]
        boxes = person_detector.detect(frame)
        people = []
        drawn = frame.copy()
        # Ordena da esquerda para a direita para facilitar localizar os números na imagem.
        ordered = sorted(boxes, key=lambda b: float((b[0] + b[2]) / 2))
        for idx, (x1, y1, x2, y2, conf) in enumerate(ordered):
            cx = round(float((x1 + x2) / 2 / w), 4)
            cy = round(float((y1 + y2) / 2 / h), 4)
            foot_y = round(float(y2 / h), 4)
            people.append({"id": idx, "cx": cx, "cy": cy, "foot_y": foot_y,
                           "box": [round(float(x1 / w), 4), round(float(y1 / h), 4),
                                   round(float(x2 / w), 4), round(float(y2 / h), 4)],
                           "conf": round(float(conf), 2), "classe": "?"})
            color = (0, 220, 255)
            cv2.rectangle(drawn, (int(x1), int(y1)), (int(x2), int(y2)), color, 2)
            cv2.putText(drawn, str(idx), (int(x1), max(14, int(y1) - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3)
            cv2.putText(drawn, str(idx), (int(x1), max(14, int(y1) - 4)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 1)
        frames_data.append({"t": ts, "lado_gol": "?", "pessoas": people})

        tile = cv2.resize(drawn, (tile_w, tile_h))
        cv2.rectangle(tile, (0, 0), (140, 26), (0, 0, 0), -1)
        cv2.putText(tile, f"t={ts:.0f}s ({int(ts // 60)}:{int(ts % 60):02d})", (5, 19),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2)
        tiles.append(tile)

    args.saida.parent.mkdir(parents=True, exist_ok=True)
    payload = {"video": args.video.name, "frames": frames_data}
    args.saida.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    if args.grade:
        cols = 3
        while len(tiles) % cols:
            tiles.append(np.zeros((tile_h, tile_w, 3), dtype=np.uint8))
        rows = [np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)]
        args.grade.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(args.grade), np.vstack(rows))
    print(f"Gerados {len(frames_data)} quadros em {args.saida}" +
          (f" e grade em {args.grade}" if args.grade else ""))


def match_predictions(truth_people: list[dict], pred_people: list[dict], max_dist: float = 0.05) -> list[tuple[dict, dict | None]]:
    """Casa cada pessoa anotada (cx, foot_y) à detecção mais próxima pelo centro/pé normalizado."""
    used: set[int] = set()
    pairs: list[tuple[dict, dict | None]] = []
    for gt in truth_people:
        best_i, best_d = None, max_dist
        for i, pr in enumerate(pred_people):
            if i in used:
                continue
            d = ((gt["cx"] - pr["cx"]) ** 2 + (gt["foot_y"] - pr["foot_y"]) ** 2) ** 0.5
            if d < best_d:
                best_i, best_d = i, d
        if best_i is not None:
            used.add(best_i)
            pairs.append((gt, pred_people[best_i]))
        else:
            pairs.append((gt, None))
    return pairs


def evaluate_signals(truth: dict, pred: dict) -> dict:
    """Avalia 1A (lado_gol), 1B (time) e 1C (descarte de 'fora') a partir de listas alinhadas por tempo `t`."""
    pred_by_t = {round(float(item["t"]), 2): item for item in pred["frames"]}
    goal_total = goal_ok = 0
    team_total = team_ok = 0
    fora_total = fora_discarded = 0
    jog_total = jog_kept = 0

    for tf in truth["frames"]:
        pf = pred_by_t.get(round(float(tf["t"]), 2))
        if tf.get("lado_gol") in {"E", "D"}:
            goal_total += 1
            if pf and pf.get("lado_gol") == tf["lado_gol"]:
                goal_ok += 1
        pairs = match_predictions(tf.get("pessoas", []), pf.get("pessoas", []) if pf else [])
        for gt, pr in pairs:
            cls = gt.get("classe")
            if cls == "fora":
                fora_total += 1
                if pr is None or pr.get("classe") == "fora":
                    fora_discarded += 1
            elif cls in {"meu", "adv"}:
                jog_total += 1
                if pr is not None and pr.get("classe") in {"meu", "adv"}:
                    jog_kept += 1
                if pr is not None and pr.get("classe") == cls:
                    team_ok += 1
                team_total += 1
    return {
        "lado_gol_ok": goal_ok, "lado_gol_total": goal_total,
        "lado_gol_acc": goal_ok / goal_total if goal_total else None,
        "time_ok": team_ok, "time_total": team_total,
        "time_acc": team_ok / team_total if team_total else None,
        "fora_descartados": fora_discarded, "fora_total": fora_total,
        "fora_taxa": fora_discarded / fora_total if fora_total else None,
        "jogadores_mantidos": jog_kept, "jogadores_total": jog_total,
        "jogadores_taxa": jog_kept / jog_total if jog_total else None,
    }


def cmd_avaliar(args: argparse.Namespace) -> None:
    truth = json.loads(args.micro.read_text(encoding="utf-8"))
    pred = json.loads(args.pred.read_text(encoding="utf-8"))
    res = evaluate_signals(truth, pred)
    fmt = lambda v: "n/d" if v is None else f"{v:.0%}"
    print(f"1A Lado do gol:      {res['lado_gol_ok']}/{res['lado_gol_total']} ({fmt(res['lado_gol_acc'])})")
    print(f"1B Time por jogador: {res['time_ok']}/{res['time_total']} ({fmt(res['time_acc'])})")
    print(f"1C Fora descartados: {res['fora_descartados']}/{res['fora_total']} ({fmt(res['fora_taxa'])})")
    print(f"1C Jog. mantidos:    {res['jogadores_mantidos']}/{res['jogadores_total']} ({fmt(res['jogadores_taxa'])})")


def cmd_1a(args: argparse.Namespace) -> None:
    """Mede o passo 1A (`detector.goal_sides`) contra um micro-gabarito."""
    truth = json.loads(args.micro.read_text(encoding="utf-8"))
    if args.cache and args.cache.is_file():
        samples = json.loads(args.cache.read_text(encoding="utf-8"))["samples"]
    else:
        info = probe(args.video)
        samples = detector.extract_samples(args.video, info["duration"], info["width"], info["height"])
        if args.cache:
            args.cache.parent.mkdir(parents=True, exist_ok=True)
            args.cache.write_text(json.dumps({"info": info, "samples": samples}), encoding="utf-8")

    sides = detector.goal_sides(samples)
    pred = {
        "frames": [
            {
                "t": s["t"],
                "lado_gol": "N" if side is None else ("E" if side == 0.0 else "D"),
                "pessoas": [],
            }
            for s, side in zip(samples, sides)
        ]
    }
    res = evaluate_signals(truth, pred)
    pct = "n/d" if res["lado_gol_acc"] is None else f"{res['lado_gol_acc']:.0%}"
    print(f"1A ({args.video.name}): {res['lado_gol_ok']}/{res['lado_gol_total']} ({pct})")
    by_t = {round(float(f["t"]), 2): f["lado_gol"] for f in pred["frames"]}
    for tf in truth["frames"]:
        gt = tf.get("lado_gol")
        if gt in {"E", "D"} and by_t.get(round(float(tf["t"]), 2)) != gt:
            print(f"  MISS t={tf['t']:5.1f}s gt={gt} pred={by_t.get(round(float(tf['t']), 2))}")


def cmd_1b(args: argparse.Namespace) -> None:
    """Mede o passo 1B (separação dos times em LAB/4D, 0 cliques e 2 cliques simulados)."""
    truth = json.loads(args.micro.read_text(encoding="utf-8"))
    samples, info = _load_or_extract_samples(args.video, args.cache)

    s_by_t = {round(float(s["t"]), 2): s for s in samples}

    def eval_proto(label: str, proto: dict) -> None:
        pred = {"frames": []}
        for tf in truth["frames"]:
            s = s_by_t.get(round(float(tf["t"]), 2), {"people": []})
            ppl = []
            for p in s["people"]:
                role = detector.person_role(p, proto)
                ppl.append({"cx": p[0], "foot_y": p[1], "classe": "fora" if role is None else role})
            pred["frames"].append({"t": tf["t"], "lado_gol": "N", "pessoas": ppl})
        res = evaluate_signals(truth, pred)
        kept = res["jogadores_mantidos"]
        acc_kept = res["time_ok"] / kept if kept else 0.0
        print(f"1B [{label}] ({args.video.name}): {res['time_ok']}/{kept} ({acc_kept:.1%}) dos mantidos "
              f"({res['time_ok']}/{res['time_total']} = {res['time_acc']:.1%} total, mantidos={kept}/{res['jogadores_total']})")

    proto_zero = detector.team_prototypes(samples, shirt=args.camisa)
    eval_proto(f"0-cliques {args.camisa}", proto_zero)

    meu_obs = []
    for tf in truth["frames"]:
        s = s_by_t.get(round(float(tf["t"]), 2), {"people": []})
        obs = [{"cx": p[0], "foot_y": p[1], "lab": tuple(p[2:5])} for p in s["people"] if len(p) >= 5]
        for gt, pr in match_predictions(tf["pessoas"], obs):
            if gt["classe"] == "meu" and pr is not None:
                meu_obs.append(pr["lab"])
    if len(meu_obs) >= 2:
        clicks = [meu_obs[len(meu_obs) // 4], meu_obs[(3 * len(meu_obs)) // 4]]
        proto_clicks = detector.team_prototypes(samples, mine_colors=clicks)
        eval_proto("2-cliques simulados", proto_clicks)


def _load_or_extract_samples(video: Path, cache: Path | None) -> tuple[list[dict], dict]:
    if cache and cache.is_file():
        cached = json.loads(cache.read_text(encoding="utf-8"))
        cached_samples = cached["samples"]
        if any(len(p) >= 6 for s in cached_samples for p in s["people"]):
            return cached_samples, cached["info"]
    info = probe(video)
    samples = detector.extract_samples(video, info["duration"], info["width"], info["height"])
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({"info": info, "samples": samples}), encoding="utf-8")
    return samples, info


def cmd_1c(args: argparse.Namespace) -> None:
    """Mede o passo 1C (filtro geométrico de quadra + descarte de árbitros/goleiros/fora)."""
    from collections import deque

    truth = json.loads(args.micro.read_text(encoding="utf-8"))
    samples, info = _load_or_extract_samples(args.video, args.cache)
    proto_zero = detector.team_prototypes(samples, shirt=args.camisa)

    person_detector = detector.PersonDetector()
    exact_frames: list[dict] = []
    meu_obs: list[tuple[float, float, float]] = []
    for tf in truth["frames"]:
        frame = read_frame_480p(args.video, tf["t"], info["width"], info["height"])
        feat = detector.frame_features(frame, person_detector, deque(maxlen=30))
        exact_frames.append({"t": tf["t"], "people": feat["people"]})
        obs = [{"cx": p[0], "foot_y": p[1], "lab": tuple(p[2:5])} for p in feat["people"] if len(p) >= 5]
        for gt, pr in match_predictions(tf["pessoas"], obs):
            if gt["classe"] == "meu" and pr is not None:
                meu_obs.append(pr["lab"])

    def eval_exact(label: str, proto: dict) -> None:
        pred = {"frames": []}
        for item in exact_frames:
            ppl = []
            for p in item["people"]:
                role = detector.person_role(p, proto)
                ppl.append({"cx": p[0], "foot_y": p[1], "classe": "fora" if role is None else role})
            pred["frames"].append({"t": item["t"], "lado_gol": "N", "pessoas": ppl})
        res = evaluate_signals(truth, pred)
        kept = res["jogadores_mantidos"]
        acc_kept = res["time_ok"] / kept if kept else 0.0
        print(f"1C [{label}] ({args.video.name}): "
              f"jog_mantidos={kept}/{res['jogadores_total']} ({res['jogadores_taxa']:.1%}) | "
              f"fora_desc={res['fora_descartados']}/{res['fora_total']} ({res['fora_taxa']:.1%}) | "
              f"1B_mantidos={res['time_ok']}/{kept} ({acc_kept:.1%})")

    eval_exact(f"0-cliques {args.camisa}", proto_zero)
    if len(meu_obs) >= 2:
        clicks = [meu_obs[len(meu_obs) // 4], meu_obs[(3 * len(meu_obs)) // 4]]
        proto_clicks = detector.team_prototypes(samples, mine_colors=clicks)
        eval_exact("2-cliques simulados", proto_clicks)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="cmd", required=True)

    prep = sub.add_parser("preparar", help="gera grade e JSON template para ~30 quadros")
    prep.add_argument("video", type=Path)
    prep.add_argument("--saida", type=Path, required=True)
    prep.add_argument("--grade", type=Path)
    prep.add_argument("--inicio", type=float, default=2.0)
    prep.add_argument("--passo", type=float, default=5.0)
    prep.add_argument("--excluir", nargs="*")

    ev = sub.add_parser("avaliar", help="avalia sinais 1A/1B/1C contra micro-gabarito")
    ev.add_argument("micro", type=Path)
    ev.add_argument("pred", type=Path)

    m1a = sub.add_parser("1a", help="mede passo 1A (`detector.goal_sides`) em um vídeo + micro-gabarito")
    m1a.add_argument("video", type=Path)
    m1a.add_argument("micro", type=Path)
    m1a.add_argument("--cache", type=Path)

    m1b = sub.add_parser("1b", help="mede passo 1B (separação LAB dos times) em um vídeo + micro-gabarito")
    m1b.add_argument("video", type=Path)
    m1b.add_argument("micro", type=Path)
    m1b.add_argument("--camisa", choices=sorted(detector.ALLOWED_SHIRTS), required=True)
    m1b.add_argument("--cache", type=Path)

    m1c = sub.add_parser("1c", help="mede passo 1C (quadra + descarte de não jogadores) em um vídeo + micro-gabarito")
    m1c.add_argument("video", type=Path)
    m1c.add_argument("micro", type=Path)
    m1c.add_argument("--camisa", choices=sorted(detector.ALLOWED_SHIRTS), required=True)
    m1c.add_argument("--cache", type=Path)

    args = parser.parse_args()
    if args.cmd == "preparar":
        cmd_preparar(args)
    elif args.cmd == "1a":
        cmd_1a(args)
    elif args.cmd == "1b":
        cmd_1b(args)
    elif args.cmd == "1c":
        cmd_1c(args)
    else:
        cmd_avaliar(args)


if __name__ == "__main__":
    main()
