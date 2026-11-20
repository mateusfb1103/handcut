"""Fase 2: sugestão automática de lances (ataque e defesa) com YOLO.

Como funciona, em 3 passos:

1. O FFmpeg lê o vídeo em 480p e entrega poucos quadros por segundo (SAMPLE_FPS).
2. Em cada quadro, um modelo YOLO (formato ONNX, roda na CPU) acha as pessoas em quadra. A cor
   da camisa separa os dois times e a mancha verde do piso mostra de que lado está o gol.
3. O time mais perto do gol está defendendo e o outro está atacando. Os quadros seguidos com o
   mesmo estado viram intervalos (os "lances" sugeridos).

O trabalho lento (passo 2) fica em `extract_samples`. As regras (passo 3) ficam em funções
separadas e rápidas, para dar para ajustar os parâmetros sem rodar o YOLO de novo
(ver tools/avaliar_deteccao.py).
"""
from __future__ import annotations

import math
import os
import subprocess
import sys
from collections import Counter, deque
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
MODEL_FILE = RESOURCE_DIR / "models" / "yolo11n.onnx"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# ---- Leitura do vídeo ----
SAMPLE_FPS = 2.0        # quadros analisados por segundo de vídeo
ANALYSIS_HEIGHT = 480   # os quadros são reduzidos para esta altura (o mesmo do download do YouTube)

# ---- Detecção de pessoas ----
PERSON_CLASS = 0        # "pessoa" na lista de 80 classes do YOLO
CONF_MIN = 0.20         # confiança mínima de uma detecção
NMS_IOU = 0.45          # caixas que se sobrepõem mais que isso são tratadas como a mesma pessoa
MIN_PERSON_HEIGHT = 0.06   # pessoa menor que 6% da altura do quadro é ruído/torcida distante
MIN_FOOT_Y = 0.24          # piso duro superior quando a máscara da quadra ainda não isolou a linha
MAX_PERSON_AR = 0.90       # caixas muito largas em relação à altura (ex.: mãos na frente da câmera)
FOREGROUND_AR = 0.72       # mãos/braços próximos à câmera na borda inferior
FOREGROUND_FOOT_Y = 0.93
TEAM_Z_MAX = 4.5           # z-score máximo (por MAD de cada time) antes de virar outlier cromático
OUTLIER_Z_MAX = 3.6        # raio máximo ao redor de um cluster de árbitro/goleiro descoberto
OUTLIER_RATIO = 1.10       # prefere outlier quando z_out < ratio * z_team

# ---- Regras de ataque e defesa ----
MIN_PEOPLE = 6          # com menos pessoas em quadra o quadro não é avaliado (close, intervalo)
MIN_PER_TEAM = 2        # mínimo de jogadores de cada time visíveis no quadro
MIN_PROTOTYPE_PEOPLE = 50         # abaixo disso faltam amostras para separar cores com segurança
MIN_RECOMMENDED_PERIOD_SECONDS = 15.0  # períodos menores sofrem mais com a janela das bordas
MARGIN = 0.03           # diferença mínima de distância ao gol entre os times (em tamanho de quadro)
SIDE_SMOOTH_SECONDS = 2.5   # o lado do gol é a mediana dos quadros nesta janela (para cada lado)
LABEL_SMOOTH_SECONDS = 1.0  # o estado de cada quadro é a maioria dos vizinhos nesta janela
MIN_SEGMENT_SECONDS = 4.0   # lance sugerido mais curto que isso é descartado
MERGE_GAP_SECONDS = 3.5     # breves quedas (< MIN_SEGMENT_SECONDS) dentro do mesmo lance são unidas

ATAQUE, DEFESA, INDEF = "ataque", "defesa", "indef"


# =====================================================================================
# Passo 1 e 2: ler o vídeo e achar as pessoas
# =====================================================================================
class PersonDetector:
    """Acha pessoas em um quadro BGR (OpenCV) com um modelo YOLO em ONNX, só na CPU."""

    def __init__(self, model_file: Path = MODEL_FILE, threads: int | None = None):
        import onnxruntime as ort  # importado aqui para o app abrir rápido se a Fase 2 não for usada

        options = ort.SessionOptions()
        # Deixa um núcleo livre para o resto do computador (e para a janela do app) não travar.
        options.intra_op_num_threads = threads or max(1, (os.cpu_count() or 2) - 1)
        self.session = ort.InferenceSession(str(model_file), options, providers=["CPUExecutionProvider"])
        model_input = self.session.get_inputs()[0]
        self.input_name = model_input.name
        # O tamanho da entrada é fixo e vem do próprio modelo (no yolo11n.onnx atual: 544 x 960).
        self.input_height, self.input_width = int(model_input.shape[2]), int(model_input.shape[3])

    def detect(self, frame: np.ndarray) -> np.ndarray:
        """Devolve um array (N, 5) com x1, y1, x2, y2 e confiança de cada pessoa, em pixels do quadro."""
        frame_height, frame_width = frame.shape[:2]
        # Redimensiona mantendo a proporção e completa as bordas com cinza (o formato que o YOLO espera).
        ratio = min(self.input_width / frame_width, self.input_height / frame_height)
        new_width, new_height = round(frame_width * ratio), round(frame_height * ratio)
        pad_x, pad_y = (self.input_width - new_width) // 2, (self.input_height - new_height) // 2
        canvas = np.full((self.input_height, self.input_width, 3), 114, dtype=np.uint8)
        canvas[pad_y:pad_y + new_height, pad_x:pad_x + new_width] = cv2.resize(
            frame, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
        blob = canvas[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0  # BGR -> RGB
        output = self.session.run(None, {self.input_name: np.ascontiguousarray(blob)})[0][0]  # (84, N)

        scores = output[4 + PERSON_CLASS]
        keep = scores >= CONF_MIN
        if not keep.any():
            return np.zeros((0, 5), dtype=np.float32)
        scores = scores[keep]
        cx, cy, w, h = output[0][keep], output[1][keep], output[2][keep], output[3][keep]
        boxes = np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], axis=1)
        chosen = nms(boxes, scores, NMS_IOU)
        boxes, scores = boxes[chosen], scores[chosen]
        # Volta para os pixels do quadro original (desfaz o redimensionamento e as bordas).
        boxes[:, [0, 2]] = np.clip((boxes[:, [0, 2]] - pad_x) / ratio, 0, frame_width)
        boxes[:, [1, 3]] = np.clip((boxes[:, [1, 3]] - pad_y) / ratio, 0, frame_height)
        return np.concatenate([boxes, scores[:, None]], axis=1)


def nms(boxes: np.ndarray, scores: np.ndarray, iou_limit: float) -> list[int]:
    """Supressão de não-máximos: de várias caixas sobre a mesma pessoa, fica a de maior confiança."""
    order = scores.argsort()[::-1]
    keep: list[int] = []
    areas = (boxes[:, 2] - boxes[:, 0]) * (boxes[:, 3] - boxes[:, 1])
    while order.size:
        i = int(order[0])
        keep.append(i)
        rest = order[1:]
        inter_w = np.maximum(0, np.minimum(boxes[i, 2], boxes[rest, 2]) - np.maximum(boxes[i, 0], boxes[rest, 0]))
        inter_h = np.maximum(0, np.minimum(boxes[i, 3], boxes[rest, 3]) - np.maximum(boxes[i, 1], boxes[rest, 1]))
        inter = inter_w * inter_h
        iou = inter / (areas[i] + areas[rest] - inter + 1e-9)
        order = rest[iou <= iou_limit]
    return keep


def read_frames(video: Path, duration: float, width: int, height: int, fps: float = SAMPLE_FPS,
                *, start: float = 0.0, end: float | None = None):
    """Entrega (segundo, quadro BGR) de uma faixa do vídeo, em `fps` quadros por segundo.

    `start` e `end` preservam o relógio original do vídeo nos valores devolvidos. Isso permite
    analisar só alguns períodos sem perder as posições corretas das sugestões.
    """
    start = max(0.0, float(start))
    end = min(duration, float(end)) if end is not None else duration
    if end <= start:
        return
    out_height = ANALYSIS_HEIGHT
    out_width = max(2, round(out_height * width / height / 2) * 2)  # largura par, como o FFmpeg exige
    command = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-ss", f"{start:.3f}",
        "-t", f"{end - start:.3f}", "-i", str(video),
        "-vf", f"fps={fps},scale={out_width}:{out_height}", "-an", "-f", "rawvideo", "-pix_fmt", "bgr24", "-",
    ]
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               creationflags=NO_WINDOW)
    frame_bytes = out_width * out_height * 3
    index = 0
    try:
        while True:
            data = process.stdout.read(frame_bytes)
            if len(data) < frame_bytes:
                break
            yield start + index / fps, np.frombuffer(data, dtype=np.uint8).reshape(out_height, out_width, 3)
            index += 1
    finally:
        process.kill()
        process.wait()


def _court_top_profile(mask: np.ndarray) -> np.ndarray:
    """Estima o limite superior `top_y(x)` da quadra (0..1) por coluna, fechando oclusões locais."""
    sh, sw = mask.shape
    m = mask.copy()
    m[:int(0.22 * sh), :] = 0
    closed = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 15), np.uint8))
    num, labels, stats, _ = cv2.connectedComponentsWithStats(closed)
    if num > 1:
        best = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        clean = (labels == best).astype(np.uint8)
    else:
        clean = closed
    top_y = np.ones(sw, dtype=np.float32)
    for x in range(sw):
        ys = np.where(clean[:, x] > 0)[0]
        if ys.size >= 3:
            top_y[x] = ys[0] / sh
    valid = top_y < 0.99
    if not valid.any():
        return np.full(sw, MIN_FOOT_Y, dtype=np.float32)
    xs = np.arange(sw)
    interp = np.interp(xs, xs[valid], top_y[valid]).astype(np.float32)
    pad = 4
    padded = np.pad(interp, pad, mode="edge")
    return np.array([float(np.percentile(padded[i:i + 2 * pad + 1], 25)) for i in range(sw)], dtype=np.float32)


def _analyze_court(frame: np.ndarray, floor_history: deque[np.ndarray]) -> tuple[float, float | None, np.ndarray, np.ndarray]:
    """Extrai `(cov_diff, end_score, floor_lab, top_y)` a partir da cor dominante do piso em LAB."""
    height, width = frame.shape[:2]
    small = cv2.resize(frame, (max(16, width // 4), max(16, height // 4)))
    sh, sw = small.shape[:2]
    lab = cv2.cvtColor(small, cv2.COLOR_BGR2LAB).astype(np.float32)

    # Aprende em streaming a cor dominante do piso pela faixa central inferior da imagem.
    patch = lab[int(0.55 * sh):int(0.85 * sh), int(0.30 * sw):int(0.70 * sw)].reshape(-1, 3)
    if patch.size:
        floor_history.append(np.median(patch, axis=0))
    floor_lab = np.median(floor_history, axis=0) if floor_history else np.array([128.0, 128.0, 128.0], dtype=np.float32)

    dist = np.linalg.norm((lab - floor_lab) * np.array([0.4, 1.0, 1.0], dtype=np.float32), axis=2)
    mask = (dist < 24.0).astype(np.uint8)
    court_region = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    top_y = _court_top_profile(mask)

    band = mask[int(0.25 * sh):int(0.70 * sh), :]
    cov_diff = float(band[:, :sw // 2].mean() - band[:, sw // 2:].mean()) if band.size else 0.0

    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    court_dil = cv2.dilate(court_region, np.ones((3, 3), np.uint8))
    edges = cv2.Canny(gray, 40, 120) & (court_dil * 255)
    edges[:int(0.28 * sh), :] = 0
    edges[int(0.75 * sh):, :] = 0

    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=18, minLineLength=max(8, sw // 6), maxLineGap=8)
    score_d = score_e = 0.0
    if lines is not None:
        for x1, y1, x2, y2 in lines.reshape(-1, 4):
            if abs(x2 - x1) < 5:
                continue
            ang = float(np.degrees(np.arctan2(y2 - y1, x2 - x1)))
            length = float(np.hypot(x2 - x1, y2 - y1))
            xm = (x1 + x2) / 2.0 / sw
            ym = (y1 + y2) / 2.0 / sh
            if 10.0 <= ang <= 55.0 and xm > 0.45 and ym < 0.70:
                score_d += length
            elif -55.0 <= ang <= -10.0 and xm < 0.55 and ym < 0.70:
                score_e += length
    total_lines = score_d + score_e
    end_score = (score_d - score_e) / total_lines if total_lines > 0 else None
    return cov_diff, end_score, floor_lab.astype(np.float32), top_y


def _court_side_features(frame: np.ndarray, floor_history: deque[np.ndarray]) -> tuple[float, float | None]:
    """Estima, sem depender de piso verde, de que lado está o gol.

    Devolve `(cov_diff, end_score)`:
    - `cov_diff`: diferença entre cobertura de piso dominante na metade esquerda e na direita
      (valores grandes em módulo indicam área de gol pintada com outra cor).
    - `end_score`: saldo normalizado das linhas de fundo dentro da região da quadra (`< 0` = gol à
      esquerda, `> 0` = gol à direita, `None` = sem linhas confiáveis).
    """
    cov_diff, end_score, _, _ = _analyze_court(frame, floor_history)
    return cov_diff, end_score


def frame_features(frame: np.ndarray, detector: PersonDetector,
                   floor_history: deque[np.ndarray] | None = None) -> dict:
    """O que interessa de um quadro: jogadores na quadra (geometria + cor limpa do tronco) e lado do gol."""
    height, width = frame.shape[:2]
    history = floor_history if floor_history is not None else deque(maxlen=30)
    cov_diff, end_score, floor_lab, top_y = _analyze_court(frame, history)
    sw = len(top_y)
    people = []
    for x1, y1, x2, y2, _ in detector.detect(frame):
        person_height = y2 - y1
        person_width = x2 - x1
        ph = person_height / height
        fy = y2 / height
        cx = (x1 + x2) / 2.0 / width
        ar = person_width / max(1.0, person_height)
        if ph < MIN_PERSON_HEIGHT or ar > MAX_PERSON_AR or (ar > FOREGROUND_AR and fy > FOREGROUND_FOOT_Y):
            continue
        sx = min(sw - 1, max(0, int(cx * sw)))
        if fy < max(MIN_FOOT_Y, float(top_y[sx]) + 0.005):
            continue

        # Camisa = miolo do tronco sem braços nem píxeis do piso/fundo local.
        top, bottom = int(y1 + 0.16 * person_height), int(y1 + 0.44 * person_height)
        left, right = int(x1 + 0.32 * person_width), int(x2 - 0.32 * person_width)
        torso = frame[max(0, top):max(1, bottom), max(0, left):max(1, right)]
        if torso.size == 0:
            continue
        lab_px = cv2.cvtColor(torso, cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float32)
        hsv_px = cv2.cvtColor(torso, cv2.COLOR_BGR2HSV).reshape(-1, 3).astype(np.float32)

        bg_refs = [floor_lab]
        pad_px = max(4, int(0.15 * person_width))
        for bx1, bx2 in ((max(0, int(x1) - pad_px), max(0, int(x1) - 1)),
                         (min(width, int(x2) + 1), min(width, int(x2) + pad_px))):
            if bx2 > bx1 and bottom > top:
                strip = frame[max(0, top):max(1, bottom), bx1:bx2]
                if strip.size:
                    strip_lab = cv2.cvtColor(strip, cv2.COLOR_BGR2LAB).reshape(-1, 3).astype(np.float32)
                    bg_refs.append(np.median(strip_lab, axis=0))
        bg_w = np.array([0.45, 1.0, 1.0], dtype=np.float32)
        min_bg_d = np.min([np.linalg.norm((lab_px - bg) * bg_w, axis=1) for bg in bg_refs], axis=0)
        keep = min_bg_d > 18.0
        if int(keep.sum()) >= max(6, int(0.25 * len(lab_px))):
            lab_use, hsv_use = lab_px[keep], hsv_px[keep]
        else:
            lab_use, hsv_use = lab_px, hsv_px

        lab = np.median(lab_use, axis=0)
        hsv = np.median(hsv_use, axis=0)
        sat = float(hsv[1]) * min(1.0, max(0.0, (float(hsv[2]) - 35.0) / 35.0))
        people.append((
            round(float(cx), 4),
            round(float(fy), 4),
            round(float(lab[0]), 1),
            round(float(lab[1]), 1),
            round(float(lab[2]), 1),
            round(sat, 1),
        ))
    return {
        "people": people,
        "cov_diff": round(cov_diff, 4),
        "end_score": None if end_score is None else round(end_score, 4),
    }


def extract_samples(video: Path, duration: float, width: int, height: int, *,
                    progress: Callable[[float], None] | None = None,
                    detector: PersonDetector | None = None, fps: float = SAMPLE_FPS,
                    start: float = 0.0, end: float | None = None) -> list[dict]:
    """Roda o YOLO em uma faixa do vídeo e devolve {t, people, cov_diff, end_score}.

    Quando `start`/`end` são informados, apenas aquela faixa é decodificada e enviada ao YOLO.
    """
    detector = detector or PersonDetector()
    start = max(0.0, float(start))
    end = min(duration, float(end)) if end is not None else duration
    section_duration = max(end - start, 0.0)
    floor_history: deque[np.ndarray] = deque(maxlen=30)
    samples = []
    for t, frame in read_frames(video, duration, width, height, fps, start=start, end=end):
        samples.append({"t": round(t, 3), **frame_features(frame, detector, floor_history)})
        if progress and len(samples) % 10 == 0:
            progress(min(1.0, (t - start) / max(section_duration, 1.0)))
    if progress:
        progress(1.0)
    return samples


# =====================================================================================
# Passo 3: regras de ataque e defesa (rápidas; não usam o YOLO)
# =====================================================================================
def light_threshold(samples: list[dict]) -> float:
    """Brilho que separa camisa clara de escura, calculado pelo método de Otsu com todos os jogadores.

    Com menos de `MIN_PROTOTYPE_PEOPLE` (50) observações de pessoas nos quadros analisados, devolve
    o valor fixo 100.0 (fallback; avisado pelo diagnóstico em `diagnose_periods`).
    """
    values = np.array([p[2] for s in samples for p in s["people"]], dtype=np.uint8)
    if values.size < MIN_PROTOTYPE_PEOPLE:
        return 100.0
    threshold, _ = cv2.threshold(values.reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return float(threshold)


def goal_sides(samples: list[dict], fps: float = SAMPLE_FPS) -> list[float | None]:
    """Para cada quadro, o lado do gol: 0.0 = esquerda da imagem, 1.0 = direita, None = não sei.

    Quando chamada por `suggest_periods`, recebe as amostras de um período por vez (via
    `label_samples`), evitando que o fim de um período contamine o início do próximo.
    """
    radius = max(1, round(SIDE_SMOOTH_SECONDS * fps))
    if samples and "cov_diff" in samples[0]:
        cov_vals = [abs(float(s["cov_diff"])) for s in samples]
        has_painted_area = len(cov_vals) >= 6 and float(np.percentile(cov_vals, 90)) > 0.16

        # Alinha automaticamente o sinal de `cov_diff` pela correlação com `end_score`
        # (a inclinação em perspectiva das linhas de fundo é um invariante geométrico).
        cov_sign = 1.0
        if has_painted_area:
            pairs = [
                (float(s["cov_diff"]), float(s["end_score"]))
                for s in samples
                if s.get("end_score") is not None
                and abs(float(s["end_score"])) >= 0.25
                and abs(float(s["cov_diff"])) >= 0.08
            ]
            if len(pairs) >= 6:
                corr = sum(c * e for c, e in pairs) / (sum(abs(c * e) for c, e in pairs) + 1e-9)
                if corr < -0.25:
                    cov_sign = -1.0

        raw: list[float | None] = []
        for s in samples:
            end_score = s.get("end_score")
            if has_painted_area:
                raw.append(cov_sign * float(s["cov_diff"]) * 4.0 + (float(end_score) if end_score is not None else 0.0) * 0.5)
            else:
                raw.append(None if end_score is None else float(end_score))
        dead_zone = 0.10 if has_painted_area else 0.05
        sides: list[float | None] = []
        for i in range(len(raw)):
            window = [x for x in raw[max(0, i - radius):i + radius + 1] if x is not None]
            if not window:
                sides.append(None)
            else:
                med = float(np.median(window))
                sides.append(None if abs(med) < dead_zone else (0.0 if med < 0.0 else 1.0))
        return sides

    # Compatibilidade com amostras antigas ou sintéticas que só informam `green_x`.
    raw_green = [s.get("green_x") for s in samples]
    sides_green: list[float | None] = []
    for i in range(len(raw_green)):
        window = [x for x in raw_green[max(0, i - radius):i + radius + 1] if x is not None]
        sides_green.append(None if not window else (0.0 if float(np.median(window)) < 0.5 else 1.0))
    return sides_green


ALLOWED_SHIRTS = {"clara", "escura", "amarela", "vermelha", "azul", "verde"}
LAB_WEIGHTS = np.array([0.7, 1.0, 1.0], dtype=np.float32)
SHIRT_COLOR_REFS = {
    "amarela": np.array([170.0, 125.0, 185.0], dtype=np.float32),
    "vermelha": np.array([120.0, 185.0, 155.0], dtype=np.float32),
    "azul": np.array([100.0, 130.0, 80.0], dtype=np.float32),
    "verde": np.array([130.0, 80.0, 155.0], dtype=np.float32),
}


def rgb_to_lab(rgb: tuple[int, int, int] | list[int]) -> tuple[float, float, float]:
    """Converte uma amostra RGB (0..255) clicada no vídeo para (L, a, b) do OpenCV."""
    pixel = np.uint8([[[int(rgb[0]), int(rgb[1]), int(rgb[2])]]])
    lab = cv2.cvtColor(pixel, cv2.COLOR_RGB2LAB)[0, 0]
    return float(lab[0]), float(lab[1]), float(lab[2])


def _person_lab(person: tuple) -> np.ndarray:
    if len(person) >= 5:
        return np.array([person[2], person[3], person[4]], dtype=np.float32)
    return np.array([person[2], 128.0, 128.0], dtype=np.float32)


def _person_feat4(person: tuple) -> np.ndarray:
    if len(person) >= 6:
        return np.array([person[2], person[3], person[4], person[5]], dtype=np.float32)
    if len(person) >= 5:
        chroma = math.hypot(float(person[3]) - 128.0, float(person[4]) - 128.0) * 1.5
        return np.array([person[2], person[3], person[4], chroma], dtype=np.float32)
    return np.array([person[2], 128.0, 128.0, 0.0], dtype=np.float32)


def _kmeans2_lab(points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Agrupa observações (L, a, b) em 2 uniformes dominantes de forma determinística."""
    scaled = points * LAB_WEIGHTS
    centered = scaled - scaled.mean(axis=0)
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    proj = centered @ vt[0]
    c0 = scaled[int(np.argmin(proj))].copy()
    c1 = scaled[int(np.argmax(proj))].copy()
    for _ in range(20):
        d0 = np.linalg.norm(scaled - c0, axis=1)
        d1 = np.linalg.norm(scaled - c1, axis=1)
        mask = d0 <= d1
        if mask.all() or (~mask).all():
            break
        c0 = np.median(scaled[mask], axis=0)
        c1 = np.median(scaled[~mask], axis=0)
    return c0 / LAB_WEIGHTS, c1 / LAB_WEIGHTS


def _fit_teams_and_outliers_4d(pts: np.ndarray) -> tuple[list[tuple[np.ndarray, np.ndarray]], list[tuple[np.ndarray, np.ndarray]]]:
    """Ajusta 2 protótipos de time aparados (sem árbitros/goleiros) e até 2 clusters de outliers na cauda."""
    w_team = np.array([0.65, 1.0, 1.0, 0.15], dtype=np.float32)
    wpts = pts * w_team
    centered = wpts - wpts.mean(axis=0)
    _, _, vt = np.linalg.svd(centered, full_matrices=False)
    proj = centered @ vt[0]
    med_proj = float(np.median(proj))
    m_low = proj <= med_proj
    m_high = ~m_low
    if m_low.any() and m_high.any():
        c0 = np.median(pts[m_low], axis=0)
        c1 = np.median(pts[m_high], axis=0)
    else:
        c0 = pts[int(np.argmin(proj))].copy()
        c1 = pts[int(np.argmax(proj))].copy()
    for _ in range(20):
        d0 = np.linalg.norm((pts - c0) * w_team, axis=1)
        d1 = np.linalg.norm((pts - c1) * w_team, axis=1)
        dm = np.minimum(d0, d1)
        inliers = dm <= np.quantile(dm, 0.72)
        m0 = inliers & (d0 <= d1)
        m1 = inliers & (d1 < d0)
        nc0 = np.median(pts[m0], axis=0) if m0.any() else c0
        nc1 = np.median(pts[m1], axis=0) if m1.any() else c1
        if np.allclose(nc0, c0, atol=0.1) and np.allclose(nc1, c1, atol=0.1):
            break
        c0, c1 = nc0, nc1

    d0 = np.linalg.norm((pts - c0) * w_team, axis=1)
    d1 = np.linalg.norm((pts - c1) * w_team, axis=1)
    lbl = d0 <= d1
    sf_team = np.array([22.0, 3.0, 3.0, 15.0], dtype=np.float32)
    team_stats: list[tuple[np.ndarray, np.ndarray]] = []
    for mask, dc in ((lbl, d0), (~lbl, d1)):
        if not mask.any():
            team_stats.append((c0 if len(team_stats) == 0 else c1, sf_team.copy()))
            continue
        sub, sd = pts[mask], dc[mask]
        core = sub[sd <= np.quantile(sd, 0.68)]
        med = np.median(core, axis=0)
        mad = np.median(np.abs(core - med), axis=0) * 1.4826
        team_stats.append((med, np.maximum(mad, sf_team)))

    zb_all = np.minimum(
        np.linalg.norm((pts - team_stats[0][0]) / team_stats[0][1], axis=1),
        np.linalg.norm((pts - team_stats[1][0]) / team_stats[1][1], axis=1),
    )
    tail = pts[zb_all >= np.quantile(zb_all, 0.85)]
    out_models: list[tuple[np.ndarray, np.ndarray]] = []
    if len(tail) >= 20:
        w_out = 1.0 / np.minimum(team_stats[0][1], team_stats[1][1])
        tw = tail * w_out
        tc = tw - tw.mean(axis=0)
        _, _, tvt = np.linalg.svd(tc, full_matrices=False)
        tp = tc @ tvt[0]
        med_tp = float(np.median(tp))
        o_low = tp <= med_tp
        o_high = ~o_low
        if o_low.any() and o_high.any():
            o0 = np.median(tail[o_low], axis=0)
            o1 = np.median(tail[o_high], axis=0)
        else:
            o0 = tail[int(np.argmin(tp))].copy()
            o1 = tail[int(np.argmax(tp))].copy()
        for _ in range(15):
            do0 = np.linalg.norm((tail - o0) * w_out, axis=1)
            do1 = np.linalg.norm((tail - o1) * w_out, axis=1)
            m0 = do0 <= do1
            no0 = np.median(tail[m0], axis=0) if m0.any() else o0
            no1 = np.median(tail[~m0], axis=0) if (~m0).any() else o1
            if np.allclose(no0, o0, atol=0.1) and np.allclose(no1, o1, atol=0.1):
                break
            o0, o1 = no0, no1
        do0 = np.linalg.norm((tail - o0) * w_out, axis=1)
        do1 = np.linalg.norm((tail - o1) * w_out, axis=1)
        sf_out = np.array([20.0, 3.0, 3.0, 14.0], dtype=np.float32)
        min_support = max(8, int(0.02 * len(pts)))
        for m in (do0 <= do1, do1 < do0):
            if int(m.sum()) < min_support:
                continue
            sub = tail[m]
            ds = np.linalg.norm((sub - np.median(sub, axis=0)) * w_out, axis=1)
            core = sub[ds <= np.quantile(ds, 0.70)]
            oc = np.median(core, axis=0)
            omad = np.maximum(np.median(np.abs(core - oc), axis=0) * 1.4826, sf_out)
            # Rejeita nuvens difusas (ex.: ruído de rede/fundo) para não engolir um time real;
            # uniformes de árbitro/goleiro formam clusters compactos.
            if float(omad[0]) > 35.0 or float(omad[3]) > 35.0:
                continue
            if min(float(np.linalg.norm((oc - tm) / ts)) for tm, ts in team_stats) >= 2.0:
                out_models.append((oc, omad))
    return team_stats, out_models


def _pick_cluster(c0: np.ndarray, c1: np.ndarray, shirt: str) -> tuple[np.ndarray, np.ndarray]:
    if shirt == "clara":
        return (c0, c1) if c0[0] >= c1[0] else (c1, c0)
    if shirt == "escura":
        return (c0, c1) if c0[0] <= c1[0] else (c1, c0)
    ref = SHIRT_COLOR_REFS.get(shirt, SHIRT_COLOR_REFS["amarela"])
    chroma_w = np.array([0.35, 1.0, 1.0], dtype=np.float32)
    return (c0, c1) if np.linalg.norm((c0 - ref) * chroma_w) <= np.linalg.norm((c1 - ref) * chroma_w) else (c1, c0)


def _pick_cluster_by_clicks(c0_lab: np.ndarray, c1_lab: np.ndarray,
                            mine_colors: list[tuple[float, float, float]], shirt: str) -> int:
    """Escolhe qual centróide é o meu time por voto dos cliques válidos (descarta cliques no piso/fundo)."""
    votes = [0, 0]
    for raw_c in mine_colors:
        c = np.array(raw_c, dtype=np.float32)
        d0 = float(np.linalg.norm((c - c0_lab) * LAB_WEIGHTS))
        d1 = float(np.linalg.norm((c - c1_lab) * LAB_WEIGHTS))
        if min(d0, d1) > 45.0:
            continue
        votes[0 if d0 <= d1 else 1] += 1
    if votes[0] != votes[1]:
        return 0 if votes[0] > votes[1] else 1
    # Em empate (ou se todos os cliques erraram as camisas), desempata pela mediana dos cliques
    # quando há separação clara, ou pelo seletor `shirt` como proteção.
    click_med = np.median(np.array(mine_colors, dtype=np.float32), axis=0)
    d0 = float(np.linalg.norm((click_med - c0_lab) * LAB_WEIGHTS))
    d1 = float(np.linalg.norm((click_med - c1_lab) * LAB_WEIGHTS))
    if abs(d0 - d1) >= 12.0 and min(d0, d1) <= 45.0:
        return 0 if d0 <= d1 else 1
    picked_mine, _ = _pick_cluster(c0_lab, c1_lab, shirt)
    return 0 if np.allclose(picked_mine, c0_lab) else 1


def team_prototypes(samples: list[dict], shirt: str = "clara", *,
                    mine_colors: list[tuple[float, float, float]] | None = None,
                    mine_is_light: bool | None = None) -> dict:
    """Define os protótipos de cor dos times e clusters de outliers (árbitros/goleiros)."""
    if mine_is_light is not None and not mine_colors:
        shirt = "clara" if mine_is_light else "escura"
    people = [p for s in samples for p in s["people"]]
    has_lab = any(len(p) >= 5 for p in people)

    if len(people) >= MIN_PROTOTYPE_PEOPLE and (has_lab or mine_colors):
        pts4 = np.array([_person_feat4(p) for p in people], dtype=np.float32)
        team_stats, out_models = _fit_teams_and_outliers_4d(pts4)
        c0_lab, c1_lab = team_stats[0][0][:3], team_stats[1][0][:3]
        if mine_colors:
            mine_idx = _pick_cluster_by_clicks(c0_lab, c1_lab, mine_colors, shirt)
        else:
            picked_mine, _ = _pick_cluster(c0_lab, c1_lab, shirt)
            mine_idx = 0 if np.allclose(picked_mine, c0_lab) else 1
        mine_stat = team_stats[mine_idx]
        other_stat = team_stats[1 - mine_idx]
        return {
            "mode": "team_outlier_4d",
            "mine": [mine_stat[0][:3]],
            "other": other_stat[0][:3],
            "mine_stat": mine_stat,
            "other_stat": other_stat,
            "out_models": out_models,
            "obs_count": len(people),
        }

    if mine_colors:
        mine_protos = [np.array(c, dtype=np.float32) for c in mine_colors]
        click_med = np.median(mine_protos, axis=0)
        if len(people) >= 10:
            pts = np.array([_person_lab(p) for p in people], dtype=np.float32)
            dists = np.linalg.norm((pts - click_med) * LAB_WEIGHTS, axis=1)
            far = pts[dists > np.percentile(dists, 50)]
            other_proto = np.median(far if len(far) else pts, axis=0)
        else:
            other_proto = np.array([200.0 if click_med[0] < 128.0 else 50.0, 128.0, 128.0], dtype=np.float32)
        return {"mode": "clicks", "mine": mine_protos, "other": other_proto, "obs_count": len(people)}

    if not has_lab or len(people) < MIN_PROTOTYPE_PEOPLE:
        if shirt in {"clara", "escura"}:
            return {
                "mode": "fallback_1d",
                "threshold": light_threshold(samples),
                "mine_is_light": shirt == "clara",
                "obs_count": len(people),
            }
        ref = SHIRT_COLOR_REFS.get(shirt, SHIRT_COLOR_REFS["amarela"])
        other = np.array([200.0 if ref[0] < 128.0 else 50.0, 128.0, 128.0], dtype=np.float32)
        return {"mode": "clicks", "mine": [ref], "other": other, "obs_count": len(people)}

    pts = np.array([_person_lab(p) for p in people], dtype=np.float32)
    c0, c1 = _kmeans2_lab(pts)
    c_mine, c_other = _pick_cluster(c0, c1, shirt)
    return {"mode": "kmeans_lab", "mine": [c_mine], "other": c_other, "obs_count": len(people)}


def person_role(person: tuple, proto: dict) -> str | None:
    """Classifica uma pessoa em `'meu'`, `'adv'` ou `None` (outlier: árbitro/goleiro/fora)."""
    mode = proto["mode"]
    if mode == "fallback_1d":
        return "meu" if (person[2] > proto["threshold"]) == proto["mine_is_light"] else "adv"
    if mode == "team_outlier_4d":
        x = _person_feat4(person)
        m_med, m_scale = proto["mine_stat"]
        o_med, o_scale = proto["other_stat"]
        zm = float(np.linalg.norm((x - m_med) / m_scale))
        zo_team = float(np.linalg.norm((x - o_med) / o_scale))
        zb = min(zm, zo_team)
        if zb > TEAM_Z_MAX:
            return None
        out_models = proto["out_models"]
        if out_models:
            zo = min(float(np.linalg.norm((x - oc) / os)) for oc, os in out_models)
            if zo < OUTLIER_RATIO * zb and zo <= OUTLIER_Z_MAX:
                return None
        d_mine = float(np.linalg.norm((x[:3] - m_med[:3]) * LAB_WEIGHTS))
        d_other = float(np.linalg.norm((x[:3] - o_med[:3]) * LAB_WEIGHTS))
        return "meu" if d_mine <= d_other else "adv"

    v = _person_lab(person)
    d_mine = min(float(np.linalg.norm((v - m) * LAB_WEIGHTS)) for m in proto["mine"])
    d_other = float(np.linalg.norm((v - proto["other"]) * LAB_WEIGHTS))
    return "meu" if d_mine <= d_other else "adv"


def classify_person(person: tuple, proto: dict) -> bool:
    """True se a pessoa pertence ao meu time segundo os protótipos calculados."""
    return person_role(person, proto) == "meu"


def _infer_half_attack_sides(sides: list[float | None], pol: np.ndarray,
                             valid: np.ndarray, fps: float) -> list[float | None] | None:
    """Estima qual lado do gol (0.0=E ou 1.0=D) é o ataque do meu time em cada tempo.

    Em handebol, durante um mesmo tempo, o time sempre ataca para um gol e defende o outro;
    se o vídeo juntar 1º e 2º tempo sem marcação de períodos, aceita até 1 virada de polaridade
    exclusivamente entre visitas contíguas ao gol (nunca cortando um lance no meio).
    """
    n = len(sides)
    total_v = int(valid.sum())
    if total_v == 0:
        return None

    max_gap = max(1, round(2.0 * fps))
    visits: list[tuple[int, int]] = []
    i = 0
    while i < n:
        if sides[i] is None or not valid[i]:
            i += 1
            continue
        cur_side = sides[i]
        start = i
        last_ok = i
        j = i + 1
        gap = 0
        while j < n:
            if sides[j] == cur_side and valid[j]:
                last_ok = j
                gap = 0
            elif sides[j] is not None and sides[j] != cur_side:
                break
            else:
                gap += 1
                if gap > max_gap:
                    break
            j += 1
        visits.append((start, last_ok + 1))
        i = j

    total_sum = float(pol.sum())
    base_score = abs(total_sum)
    best_split_score = base_score
    best_split: int | None = None
    default_sign = 1.0 if total_sum >= 0.0 else -1.0
    best_signs = (default_sign, default_sign)

    prefix = np.concatenate([[0.0], np.cumsum(pol)])
    v_prefix = np.concatenate([[0], np.cumsum(valid.astype(np.int32))])
    min_half_valid = max(12, int(0.15 * total_v))

    for _, k in visits[:-1]:
        vl = int(v_prefix[k])
        vr = int(v_prefix[n] - v_prefix[k])
        if vl < min_half_valid or vr < min_half_valid:
            continue
        sl = float(prefix[k])
        sr = float(prefix[n] - prefix[k])
        if sl * sr < 0.0 and abs(sl) / vl >= 0.02 and abs(sr) / vr >= 0.02:
            sc = abs(sl) + abs(sr)
            if sc > base_score * 1.15 and sc > best_split_score:
                best_split_score = sc
                best_split = k
                best_signs = (1.0 if sl > 0.0 else -1.0, 1.0 if sr > 0.0 else -1.0)

    if best_split_score / total_v < 0.015:
        return None
    return [
        1.0 if (best_signs[0] if (best_split is None or idx < best_split) else best_signs[1]) > 0.0 else 0.0
        for idx in range(n)
    ]


def label_samples(samples: list[dict], mine_is_light: bool | None = None, *, fps: float = SAMPLE_FPS,
                  threshold: float | None = None, shirt: str = "clara",
                  mine_colors: list[tuple[float, float, float]] | None = None,
                  proto: dict | None = None) -> list[str]:
    """Estado do seu time em cada quadro: "ataque", "defesa" ou "indef" (não deu para saber)."""
    if proto is None:
        if threshold is not None:
            is_light = True if mine_is_light is None else mine_is_light
            proto = {"mode": "fallback_1d", "threshold": threshold, "mine_is_light": is_light}
        else:
            proto = team_prototypes(samples, shirt=shirt, mine_colors=mine_colors, mine_is_light=mine_is_light)
    sides = goal_sides(samples, fps)
    n = len(samples)
    pol = np.zeros(n, dtype=np.float32)
    raw_diffs: list[float | None] = [None] * n
    valid = np.zeros(n, dtype=bool)

    for i, (sample, side) in enumerate(zip(samples, sides)):
        if side is None:
            continue
        people = sample["people"]
        roles = [person_role(p, proto) for p in people]
        mine = [p for p, r in zip(people, roles) if r == "meu"]
        other = [p for p, r in zip(people, roles) if r == "adv"]
        if len(mine) + len(other) < MIN_PEOPLE or len(mine) < MIN_PER_TEAM or len(other) < MIN_PER_TEAM:
            continue
        goal_x = 0.08 if side == 0.0 else 0.92  # posição aproximada do gol na imagem
        # Distância 2D em perspectiva (gol fica na parte superior da imagem em quadra vista da lateral).
        distance = lambda p: math.hypot(p[0] - goal_x, (p[1] - 0.35) * 0.9)
        d_mine = float(np.median([distance(p) for p in mine]))
        d_other = float(np.median([distance(p) for p in other]))
        diff = d_mine - d_other
        raw_diffs[i] = diff
        pol[i] = float(np.clip(diff if side == 1.0 else -diff, -0.20, 0.20))
        valid[i] = True

    attack_sides = _infer_half_attack_sides(sides, pol, valid, fps)
    raw: list[str] = []
    for i in range(n):
        if not valid[i]:
            raw.append(INDEF)
        elif attack_sides is not None:
            raw.append(ATAQUE if sides[i] == attack_sides[i] else DEFESA)
        else:
            diff = raw_diffs[i]
            assert diff is not None
            raw.append(DEFESA if -diff > MARGIN else ATAQUE if diff > MARGIN else INDEF)
    # Suaviza: cada quadro vira a maioria entre os vizinhos, para um quadro ruim não cortar o lance.
    # Nos 2 primeiros e 2 últimos quadros (fps=2.0 -> radius=2) a janela ainda exige `votes_needed` (3);
    # por isso lances que começam ou terminam colados no corte do período podem encolher (recomenda-se folga ~5 s).
    radius = max(1, round(LABEL_SMOOTH_SECONDS * fps))
    votes_needed = math.ceil((2 * radius + 1) * 0.6)
    smooth: list[str] = []
    for i in range(len(raw)):
        window = [label for label in raw[max(0, i - radius):i + radius + 1] if label != INDEF]
        smooth.append(Counter(window).most_common(1)[0][0] if len(window) >= votes_needed else INDEF)
    return smooth


def diagnose_periods(period_samples: list[tuple[float, list[dict]]], proto: dict,
                     suggestions: dict[str, list[dict]], *, fps: float = SAMPLE_FPS) -> dict:
    """Resume diagnóstico e avisos explícitos (poucos jogadores, fallback 1D e períodos curtos)."""
    obs_count = int(proto.get("obs_count", sum(len(s["people"]) for _, samples in period_samples for s in samples)))
    used_fallback = proto.get("mode") != "team_outlier_4d"
    total_frames = 0
    valid_frames = 0
    short_periods: list[float] = []

    for _, samples in period_samples:
        total_frames += len(samples)
        duration_s = (samples[-1]["t"] - samples[0]["t"] + 1.0 / fps) if samples else 0.0
        if duration_s < MIN_RECOMMENDED_PERIOD_SECONDS:
            short_periods.append(round(float(duration_s), 1))
        sides = goal_sides(samples, fps)
        for sample, side in zip(samples, sides):
            roles = [person_role(p, proto) for p in sample["people"]]
            mine_n = sum(1 for r in roles if r == "meu")
            other_n = sum(1 for r in roles if r == "adv")
            if side is not None and mine_n + other_n >= MIN_PEOPLE and mine_n >= MIN_PER_TEAM and other_n >= MIN_PER_TEAM:
                valid_frames += 1

    warnings: list[str] = []
    if obs_count < MIN_PROTOTYPE_PEOPLE:
        warnings.append(
            f"Poucos jogadores detectados ({obs_count} observações; mínimo recomendado: {MIN_PROTOTYPE_PEOPLE}). "
            "A separação automática das camisas ficou limitada; selecione um trecho maior ou clique na camisa no vídeo."
        )
    elif proto.get("mode") == "fallback_1d":
        warnings.append("Análise usou apenas brilho (fallback 1D) por falta de amostras de cor completas.")

    if short_periods:
        warnings.append(
            f"Há {len(short_periods)} período(s) curto(s) (< {int(MIN_RECOMMENDED_PERIOD_SECONDS)} s). "
            "Deixe cerca de 5 s de folga antes e depois dos lances nas bordas."
        )

    if total_frames > 0 and valid_frames < max(1, int(0.15 * total_frames)) and obs_count >= MIN_PROTOTYPE_PEOPLE:
        warnings.append(
            f"Poucos quadros com times completos em quadra aberta ({valid_frames}/{total_frames}); "
            "verifique câmera fechada, intervalo ou mínimo de jogadores."
        )
    elif not suggestions.get(ATAQUE) and not suggestions.get(DEFESA) and obs_count >= MIN_PROTOTYPE_PEOPLE:
        warnings.append(
            "Nenhum lance completo atingiu 4 s com jogadores suficientes nos dois times e lado do gol definido."
        )

    return {
        "obs_count": obs_count,
        "proto_mode": proto.get("mode"),
        "used_fallback": used_fallback,
        "short_periods": short_periods,
        "valid_frames": valid_frames,
        "total_frames": total_frames,
        "warnings": warnings,
    }


def labels_to_segments(samples: list[dict], labels: list[str], wanted: str, *, fps: float = SAMPLE_FPS,
                       duration: float | None = None, min_seconds: float = MIN_SEGMENT_SECONDS,
                       merge_gap: float = MERGE_GAP_SECONDS) -> list[dict]:
    """Junta os quadros seguidos com o estado `wanted` em intervalos {start, end} (em segundos)."""
    segments: list[list[float]] = []
    start = None
    for sample, label in zip(samples, labels):
        if label == wanted and start is None:
            start = sample["t"]
        elif label != wanted and start is not None:
            segments.append([start, sample["t"], sample["t"] - start])
            start = None
    if start is not None and samples:
        end_t = samples[-1]["t"] + 1 / fps
        segments.append([start, end_t, end_t - start])
    merged: list[list[float]] = []
    for a, b, active in segments:
        if merged and a - merged[-1][1] <= merge_gap:
            merged[-1][1] = b
            merged[-1][2] += active
        else:
            merged.append([a, b, active])
    limit = duration if duration else float("inf")
    return [{"start": round(a, 2), "end": round(min(b, limit), 2)}
            for a, b, active in merged if active >= min_seconds]


def suggest(samples: list[dict], mine_is_light: bool | None = None, *, fps: float = SAMPLE_FPS,
            duration: float | None = None, shirt: str = "clara",
            mine_colors: list[tuple[float, float, float]] | None = None) -> dict[str, list[dict]]:
    """Intervalos sugeridos de ataque e de defesa do time escolhido."""
    labels = label_samples(samples, mine_is_light, fps=fps, shirt=shirt, mine_colors=mine_colors)
    return {kind: labels_to_segments(samples, labels, kind, fps=fps, duration=duration)
            for kind in (ATAQUE, DEFESA)}


def suggest_periods(period_samples: list[tuple[float, list[dict]]], mine_is_light: bool | None = None, *,
                    fps: float = SAMPLE_FPS, shirt: str = "clara",
                    mine_colors: list[tuple[float, float, float]] | None = None,
                    diagnostics_out: dict | None = None) -> dict[str, list[dict]]:
    """Sugere lances para períodos independentes, sem unir um ao outro.

    As cores dos times são estimadas com todos os períodos selecionados, mas a suavização
    do lado do gol, dos rótulos e a conversão em segmentos acontecem período a período.
    """
    all_samples = [sample for _, samples in period_samples for sample in samples]
    proto = team_prototypes(all_samples, shirt=shirt, mine_colors=mine_colors, mine_is_light=mine_is_light)
    result = {ATAQUE: [], DEFESA: []}
    for end, samples in period_samples:
        labels = label_samples(samples, mine_is_light, fps=fps, shirt=shirt, mine_colors=mine_colors, proto=proto)
        for kind in result:
            result[kind].extend(labels_to_segments(samples, labels, kind, fps=fps, duration=end))
    if diagnostics_out is not None:
        diagnostics_out.update(diagnose_periods(period_samples, proto, result, fps=fps))
    return result
