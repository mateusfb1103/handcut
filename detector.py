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
from collections import Counter
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
MIN_PERSON_HEIGHT = 0.07   # pessoa menor que 7% da altura do quadro é torcida/fundo
MIN_FOOT_Y = 0.38          # pés acima de 38% da altura do quadro estão na arquibancada

# ---- Regras de ataque e defesa ----
MIN_PEOPLE = 6          # com menos pessoas em quadra o quadro não é avaliado (close, intervalo)
MIN_PER_TEAM = 2        # mínimo de jogadores de cada time visíveis no quadro
MARGIN = 0.03           # diferença mínima de distância ao gol entre os times (em tamanho de quadro)
SIDE_SMOOTH_SECONDS = 2.5   # o lado do gol é a mediana dos quadros nesta janela (para cada lado)
LABEL_SMOOTH_SECONDS = 1.0  # o estado de cada quadro é a maioria dos vizinhos nesta janela
MIN_SEGMENT_SECONDS = 4.0   # lance sugerido mais curto que isso é descartado
MERGE_GAP_SECONDS = 2.0     # intervalos do mesmo tipo separados por menos que isso viram um só

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
        # O tamanho da entrada é fixo e vem do próprio modelo (ex.: 384 x 640).
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


def read_frames(video: Path, duration: float, width: int, height: int, fps: float = SAMPLE_FPS):
    """Entrega (segundo, quadro BGR) a `fps` quadros por segundo, lidos pelo FFmpeg em 480p."""
    out_height = ANALYSIS_HEIGHT
    out_width = max(2, round(out_height * width / height / 2) * 2)  # largura par, como o FFmpeg exige
    command = [
        "ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error", "-i", str(video),
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
            yield index / fps, np.frombuffer(data, dtype=np.uint8).reshape(out_height, out_width, 3)
            index += 1
    finally:
        process.kill()
        process.wait()


def frame_features(frame: np.ndarray, detector: PersonDetector) -> dict:
    """O que interessa de um quadro: onde estão os jogadores, de que cor é a camisa e onde está o verde."""
    height, width = frame.shape[:2]
    people = []
    for x1, y1, x2, y2, _ in detector.detect(frame):
        person_height = y2 - y1
        if person_height < MIN_PERSON_HEIGHT * height or y2 < MIN_FOOT_Y * height:
            continue
        # Camisa = faixa do tronco (do ombro até a cintura), sem as bordas, onde entram braços e fundo.
        top, bottom = int(y1 + 0.15 * person_height), int(y1 + 0.50 * person_height)
        left, right = int(x1 + 0.25 * (x2 - x1)), int(x2 - 0.25 * (x2 - x1))
        torso = frame[top:bottom, left:right]
        if torso.size == 0:
            continue
        brightness = float(cv2.cvtColor(torso, cv2.COLOR_BGR2LAB)[..., 0].mean())  # 0 = preto, 255 = branco
        people.append((round(float((x1 + x2) / 2 / width), 4), round(float(y2 / height), 4), round(brightness, 1)))
    # Piso verde (área do gol e círculo central) na parte de baixo do quadro. A média da posição
    # horizontal dessa mancha mostra para que lado da quadra a câmera está virada.
    small = cv2.resize(frame[int(0.35 * height):], (width // 4, int(0.65 * height) // 4))
    green = cv2.inRange(cv2.cvtColor(small, cv2.COLOR_BGR2HSV), (40, 60, 40), (85, 255, 255))
    columns = np.where(green > 0)[1]
    green_x = float(columns.mean() / small.shape[1]) if columns.size > green.size * 0.01 else None
    return {"people": people, "green_x": None if green_x is None else round(green_x, 3)}


def extract_samples(video: Path, duration: float, width: int, height: int, *,
                    progress: Callable[[float], None] | None = None,
                    detector: PersonDetector | None = None, fps: float = SAMPLE_FPS) -> list[dict]:
    """Passo lento: roda o YOLO nos quadros amostrados. Devolve uma lista de {t, people, green_x}."""
    detector = detector or PersonDetector()
    samples = []
    for t, frame in read_frames(video, duration, width, height, fps):
        samples.append({"t": round(t, 3), **frame_features(frame, detector)})
        if progress and len(samples) % 10 == 0:
            progress(min(1.0, t / max(duration, 1.0)))
    if progress:
        progress(1.0)
    return samples


# =====================================================================================
# Passo 3: regras de ataque e defesa (rápidas; não usam o YOLO)
# =====================================================================================
def light_threshold(samples: list[dict]) -> float:
    """Brilho que separa camisa clara de escura, calculado pelo método de Otsu com todos os jogadores."""
    values = np.array([p[2] for s in samples for p in s["people"]], dtype=np.uint8)
    if values.size < 50:
        return 100.0
    threshold, _ = cv2.threshold(values.reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return float(threshold)


def goal_sides(samples: list[dict], fps: float = SAMPLE_FPS) -> list[float | None]:
    """Para cada quadro, o lado do gol: 0.0 = esquerda da imagem, 1.0 = direita, None = não sei."""
    radius = max(1, round(SIDE_SMOOTH_SECONDS * fps))
    raw = [s["green_x"] for s in samples]
    sides: list[float | None] = []
    for i in range(len(raw)):
        window = [x for x in raw[max(0, i - radius):i + radius + 1] if x is not None]
        sides.append(None if not window else (0.0 if float(np.median(window)) < 0.5 else 1.0))
    return sides


def label_samples(samples: list[dict], mine_is_light: bool, *, fps: float = SAMPLE_FPS,
                  threshold: float | None = None) -> list[str]:
    """Estado do seu time em cada quadro: "ataque", "defesa" ou "indef" (não deu para saber)."""
    threshold = light_threshold(samples) if threshold is None else threshold
    sides = goal_sides(samples, fps)
    raw: list[str] = []
    for sample, side in zip(samples, sides):
        people = sample["people"]
        mine = [p for p in people if (p[2] > threshold) == mine_is_light]
        other = [p for p in people if (p[2] > threshold) != mine_is_light]
        if side is None or len(people) < MIN_PEOPLE or len(mine) < MIN_PER_TEAM or len(other) < MIN_PER_TEAM:
            raw.append(INDEF)
            continue
        goal_x = 0.08 if side == 0.0 else 0.92  # posição aproximada do gol na imagem
        # Distância 2D (a profundidade da quadra pesa um pouco menos que o lado) até o gol.
        distance = lambda p: math.hypot(p[0] - goal_x, (p[1] - 0.35) * 0.9)
        d_mine = float(np.median([distance(p) for p in mine]))
        d_other = float(np.median([distance(p) for p in other]))
        raw.append(DEFESA if d_other - d_mine > MARGIN else ATAQUE if d_mine - d_other > MARGIN else INDEF)
    # Suaviza: cada quadro vira a maioria entre os vizinhos, para um quadro ruim não cortar o lance.
    radius = max(1, round(LABEL_SMOOTH_SECONDS * fps))
    votes_needed = math.ceil((2 * radius + 1) * 0.6)
    smooth: list[str] = []
    for i in range(len(raw)):
        window = [label for label in raw[max(0, i - radius):i + radius + 1] if label != INDEF]
        smooth.append(Counter(window).most_common(1)[0][0] if len(window) >= votes_needed else INDEF)
    return smooth


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
            segments.append([start, sample["t"]])
            start = None
    if start is not None and samples:
        segments.append([start, samples[-1]["t"] + 1 / fps])
    merged: list[list[float]] = []
    for item in segments:
        if merged and item[0] - merged[-1][1] <= merge_gap:
            merged[-1][1] = item[1]
        else:
            merged.append(item)
    limit = duration if duration else float("inf")
    return [{"start": round(a, 2), "end": round(min(b, limit), 2)} for a, b in merged if b - a >= min_seconds]


def suggest(samples: list[dict], mine_is_light: bool, *, fps: float = SAMPLE_FPS,
            duration: float | None = None) -> dict[str, list[dict]]:
    """Intervalos sugeridos de ataque e de defesa do time escolhido."""
    labels = label_samples(samples, mine_is_light, fps=fps)
    return {kind: labels_to_segments(samples, labels, kind, fps=fps, duration=duration)
            for kind in (ATAQUE, DEFESA)}
