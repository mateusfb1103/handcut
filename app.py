from __future__ import annotations

import json
import queue
import shutil
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename


ROOT = Path(__file__).resolve().parent
DOWNLOAD_MAX_HEIGHT = 480  # qualidade máxima do download do YouTube (usada só para marcar os lances)
MEDIA_DIR = ROOT / "media"
EXPORT_DIR = ROOT / "exports"
TEMP_DIR = ROOT / "temp"
for directory in (MEDIA_DIR, EXPORT_DIR, TEMP_DIR):
    directory.mkdir(exist_ok=True)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 30 * 1024 * 1024 * 1024
jobs: dict[str, dict] = {}
jobs_lock = threading.Lock()
active_media: dict[str, Path] = {}
# Vídeos baixados do YouTube: guarda o link e a maior altura disponível, para a exportação
# poder baixar de novo só os trechos marcados em qualidade maior que a de edição (480p).
media_sources: dict[str, dict] = {}
MAX_REMOTE_HEIGHT = 1080
DOWNLOAD_TIMEOUT_SECONDS = 2 * 60 * 60
PROGRESS_LOG_INTERVAL_SECONDS = 30 


def run(command: list[str], *, timeout: int | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=True)


def probe(path: Path) -> dict:
    result = run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
        "-of", "json", str(path),
    ], timeout=60)
    data = json.loads(result.stdout)
    duration = float(data.get("format", {}).get("duration", 0))
    video = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"), {})
    if duration <= 0 or not video:
        raise ValueError("Não encontrei uma faixa de vídeo válida nesse arquivo.")
    return {"duration": duration, "width": video.get("width"), "height": video.get("height")}


def add_job(kind: str) -> str:
    job_id = uuid.uuid4().hex
    with jobs_lock:
        jobs[job_id] = {"id": job_id, "kind": kind, "status": "processing", "message": "Preparando…"}
    return job_id


def finish_job(job_id: str, **values) -> None:
    with jobs_lock:
        jobs[job_id].update(values)


def run_download_command(job_id: str, command: list[str]) -> None:
    """Run yt-dlp while forwarding its latest progress line to the browser UI."""
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    output: queue.Queue[str | None] = queue.Queue()

    def read_output() -> None:
        assert process.stdout is not None
        for line in process.stdout:
            output.put(line.rstrip())
        output.put(None)

    reader = threading.Thread(target=read_output, daemon=True)
    reader.start()
    deadline = time.monotonic() + DOWNLOAD_TIMEOUT_SECONDS
    recent_lines: list[str] = []
    while True:
        if time.monotonic() >= deadline:
            process.kill()
            process.wait()
            raise TimeoutError("O download excedeu o limite de 2 horas e foi encerrado.")
        try:
            line = output.get(timeout=0.5)
        except queue.Empty:
            if process.poll() is not None:
                break
            continue
        if line is None:
            break
        if not line:
            continue
        recent_lines.append(line)
        recent_lines = recent_lines[-30:]
        finish_job(job_id, message=line[:240])

    return_code = process.wait()
    reader.join(timeout=1)
    if return_code:
        raise RuntimeError("\n".join(recent_lines) or f"yt-dlp encerrou com código {return_code}.")


def best_available_height(info_files, fallback: int) -> int:
    """Maior altura de vídeo que o YouTube oferece (até MAX_REMOTE_HEIGHT), lida do info.json."""
    heights: list[int] = []
    for info_file in info_files:
        try:
            data = json.loads(info_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for item in data.get("formats") or []:
            height = item.get("height")
            if isinstance(height, int) and item.get("vcodec") not in (None, "none"):
                heights.append(height)
    return min(max(heights + [fallback]), MAX_REMOTE_HEIGHT)


def download_sections(job_id: str, url: str, plan: list[tuple[int, float, float]], height: int,
                      work_dir: Path) -> dict[int, Path]:
    """Baixa do YouTube só os trechos do plano, em até `height` p. Devolve {índice do lance: arquivo}."""
    output_template = str(work_dir / "sec-%(section_start)010.3f.%(ext)s")
    command = [sys.executable, "-m", "yt_dlp",
               "--no-playlist", "--newline", "--retries", "3", "--fragment-retries", "3",
               "--extractor-retries", "2", "--socket-timeout", "30", "-f",
               f"bv*[vcodec^=avc1][height<={height}]/bv*[height<={height}]",
               "-S", f"vcodec:h264,res:{height}", "-o", output_template]
    for _, start, end in plan:
        command += ["--download-sections", f"*{start:.3f}-{end:.3f}"]
    run_download_command(job_id, command + [url])
    files = {}
    for path in work_dir.glob("sec-*"):
        if path.suffix.lower() in {".mp4", ".webm", ".mkv"}:
            try:
                files[float(path.stem[4:])] = path
            except ValueError:
                continue
    result: dict[int, Path] = {}
    for index, start, _ in plan:
        near = min(files, key=lambda value: abs(value - start), default=None)
        if near is None or abs(near - start) > 0.5:
            raise RuntimeError(f"O yt-dlp não entregou o trecho do lance {index}.")
        result[index] = files[near]
    return result


def download_worker(job_id: str, url: str) -> None:
    try:
        prefix = [sys.executable, "-m", "yt_dlp"]
        # Nome só com ASCII (sem o título): acentos no caminho quebravam a junção no Windows.
        output_template = str(MEDIA_DIR / f"download-{job_id}-%(id)s.%(ext)s")
        # Só vídeo (sem áudio), no máximo 480p: download e edição mais rápidos.
        command = prefix + [
            "--no-playlist", "--newline", "--retries", "3", "--fragment-retries", "3",
            "--extractor-retries", "2", "--file-access-retries", "2", "--socket-timeout", "30",
            "--write-info-json", "-f",
            f"bv*[vcodec^=avc1][height<={DOWNLOAD_MAX_HEIGHT}]/bv*[height<={DOWNLOAD_MAX_HEIGHT}]",
            "-S", f"vcodec:h264,res:{DOWNLOAD_MAX_HEIGHT}",
            "-o", output_template, url,
        ]
        run_download_command(job_id, command)
        candidates = sorted(MEDIA_DIR.glob(f"download-{job_id}-*"), key=lambda item: item.stat().st_mtime, reverse=True)
        video = next((item for item in candidates if item.suffix.lower() in {".mp4", ".webm"}), None)
        if not video:
            raise RuntimeError("O download terminou, mas não encontrei o arquivo de vídeo.")
        info = probe(video)
        max_height = best_available_height(MEDIA_DIR.glob(f"download-{job_id}-*.info.json"), int(info.get("height") or 0))
        active_media[job_id] = video
        media_sources[job_id] = {"url": url, "max_height": max_height}
        finish_job(job_id, status="done", message="Vídeo baixado e pronto para marcar.", media_id=job_id,
                   name=video.name, max_height=max_height, **info)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()[-1200:]
        if "This video is not available" in detail:
            message = (
                "O YouTube não disponibilizou este vídeo para o download. Verifique se o link abre "
                "no navegador deste computador. Vídeos privados, restritos por idade ou região, "
                "ou que exigem login podem não ser acessíveis pelo link."
            )
        else:
            message = "Falha no download pelo yt-dlp. Confira o link e as mensagens de diagnóstico abaixo."
        finish_job(job_id, status="error", message=message, detail=detail)
    except TimeoutError as exc:
        finish_job(job_id, status="error", message=str(exc))
    except RuntimeError as exc:
        detail = str(exc).strip()[-1200:]
        if "This video is not available" in detail:
            message = (
                "O YouTube não disponibilizou este vídeo para o download. Verifique se o link abre "
                "no navegador deste computador. Vídeos privados, restritos por idade ou região, "
                "ou que exigem login podem não ser acessíveis pelo link."
            )
        else:
            message = "O yt-dlp encerrou o download com erro. Veja a última mensagem abaixo."
        finish_job(job_id, status="error", message=message, detail=detail)
    except Exception as exc:
        finish_job(job_id, status="error", message=str(exc))


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/upload")
def upload():
    uploaded = request.files.get("video")
    if not uploaded or not uploaded.filename:
        return jsonify(error="Selecione um arquivo .mp4 ou .webm."), 400
    suffix = Path(uploaded.filename).suffix.lower()
    if suffix not in {".mp4", ".webm"}:
        return jsonify(error="Formato não suportado. Use .mp4 ou .webm."), 400
    filename = secure_filename(Path(uploaded.filename).stem) or "video"
    path = MEDIA_DIR / f"{filename}-{uuid.uuid4().hex[:8]}{suffix}"
    uploaded.save(path)
    try:
        info = probe(path)
    except Exception as exc:
        path.unlink(missing_ok=True)
        return jsonify(error=f"Não consegui abrir esse vídeo: {exc}"), 400
    media_id = uuid.uuid4().hex
    active_media[media_id] = path
    return jsonify(media_id=media_id, name=path.name, **info)


@app.post("/api/download")
def download():
    url = (request.json or {}).get("url", "").strip()
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    youtube_host = host in {"youtu.be", "youtube.com", "youtube-nocookie.com"} or host.endswith(".youtube.com") or host.endswith(".youtube-nocookie.com")
    if parsed.scheme not in {"http", "https"} or not youtube_host:
        return jsonify(error="Informe um link válido do YouTube."), 400
    job_id = add_job("download")
    threading.Thread(target=download_worker, args=(job_id, url), daemon=True).start()
    return jsonify(job_id=job_id), 202


@app.get("/api/jobs/<job_id>")
def get_job(job_id: str):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify(error="Tarefa não encontrada."), 404
    return jsonify(job)


@app.get("/api/media/<media_id>")
def media(media_id: str):
    path = active_media.get(media_id)
    if not path or not path.exists():
        return jsonify(error="Vídeo não encontrado."), 404
    return send_file(path, conditional=True)


def fmt_time(seconds: float) -> str:
    seconds = int(round(seconds))
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def export_log(job_id: str, text: str) -> None:
    """Diagnostic line printed in the terminal that runs `python app.py`."""
    print(f"[export {job_id[:8]}] {text}", flush=True)


def run_ffmpeg(command: list[str], *, job_id: str, content_seconds: float, base_done: float,
               total_content: float, label: str, timeout: int = 60 * 60 * 4) -> float:
    """Run FFmpeg with live progress. Returns the elapsed wall-clock seconds.

    FFmpeg's `-progress` output tells how much video was produced so far. It feeds the
    progress bar (by seconds of video, not by number of lances) and a diagnostic line in
    the terminal at most every 30 s showing the current and the average speed.
    """
    command = command[:1] + ["-nostdin", "-progress", "pipe:1", "-nostats"] + command[1:]
    started = time.perf_counter()
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )
    error_lines: list[str] = []

    def read_errors() -> None:
        assert process.stderr is not None
        error_lines.extend(process.stderr)

    error_reader = threading.Thread(target=read_errors, daemon=True)
    error_reader.start()
    last_log_time, last_log_pos = started, 0.0
    assert process.stdout is not None
    for line in process.stdout:
        now = time.perf_counter()
        if now - started > timeout:
            process.kill()
            process.wait()
            raise TimeoutError("A exportação excedeu o tempo limite e foi encerrada.")
        key, _, value = line.strip().partition("=")
        if key not in {"out_time_us", "out_time_ms"} or not value.lstrip("-").isdigit():
            continue
        position = max(0.0, int(value) / 1_000_000)
        done = min(base_done + position, total_content)
        finish_job(job_id, message=f"Processando {label}… {fmt_time(done)} de {fmt_time(total_content)}",
                   progress=round(done / total_content * 90))
        if now - last_log_time >= PROGRESS_LOG_INTERVAL_SECONDS:
            current = (position - last_log_pos) / (now - last_log_time)
            average = position / (now - started)
            export_log(job_id, f"{label}: {fmt_time(position)} de {fmt_time(content_seconds)} | "
                               f"velocidade atual {current:.1f}x | média {average:.1f}x")
            last_log_time, last_log_pos = now, position
    return_code = process.wait()
    error_reader.join(timeout=2)
    if return_code:
        raise subprocess.CalledProcessError(return_code, command, stderr="".join(error_lines))
    return time.perf_counter() - started


def export_worker(job_id: str, media_path: Path, segments: list[dict], margin: float,
                  resolution: str = "original", source: dict | None = None) -> None:
    work_dir = TEMP_DIR / job_id
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        info = probe(media_path)
        duration = info["duration"]
        # "480" ou "720" reduz a altura do vídeo; "original" não mexe. Nunca amplia.
        target_height = int(resolution) if resolution.isdigit() else 0
        source_height = int(info.get("height") or 0)
        scale_args = ["-vf", f"scale=-2:{target_height}"] if 0 < target_height < source_height else []
        output_label = f"{target_height}p" if scale_args else f"original ({source_height}p)"
        # Vídeo do YouTube editado em 480p: se a saída pedida é maior, baixa de novo só os trechos.
        remote_height = 0
        if source:
            best = max(int(source["max_height"]), source_height)
            wanted = best if resolution == "original" else min(int(resolution), best)
            if wanted > source_height:
                remote_height, scale_args = wanted, []
                output_label = f"{wanted}p (trechos baixados de novo do YouTube)"
        plan: list[tuple[int, float, float]] = []
        for index, segment in enumerate(segments, 1):
            start = max(0.0, float(segment["start"]) - margin)
            end = min(duration, float(segment["end"]) + margin)
            if end > start:
                plan.append((index, start, end))
        if not plan:
            raise ValueError("Nenhum intervalo válido para exportar.")
        total_content = sum(end - start for _, start, end in plan)
        export_started = time.perf_counter()
        export_log(job_id, f"origem {media_path.name} ({info['width']}x{info['height']}), "
                           f"{len(plan)} lance(s), {fmt_time(total_content)} de vídeo")
        export_log(job_id, f"resolução da saída: {output_label}")
        section_files: dict[int, Path] = {}
        if remote_height:
            finish_job(job_id, message=f"Baixando os {len(plan)} lance(s) em {remote_height}p do YouTube…")
            download_started = time.perf_counter()
            section_files = download_sections(job_id, source["url"], plan, remote_height, work_dir)
            export_log(job_id, f"download dos trechos: {time.perf_counter() - download_started:.1f}s")
        segment_paths: list[Path] = []
        done_content = 0.0
        for number, (index, start, end) in enumerate(plan, 1):
            part = work_dir / f"part-{index:04d}.mp4"
            label = f"lance {number}/{len(plan)}"
            # Trecho já baixado: usa o arquivo inteiro. Caso contrário, corta do vídeo de origem.
            input_args = (["-i", str(section_files[index])] if remote_height
                          else ["-ss", f"{start:.3f}", "-i", str(media_path), "-t", f"{end - start:.3f}"])
            elapsed = run_ffmpeg([
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", *input_args,
                "-map", "0:v:0", "-map", "0:a?", *scale_args,
                "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(part),
            ], job_id=job_id, content_seconds=end - start, base_done=done_content,
                total_content=total_content, label=label)
            segment_paths.append(part)
            done_content += end - start
            export_log(job_id, f"{label}: {fmt_time(end - start)} de vídeo em {elapsed:.1f}s "
                               f"({(end - start) / max(elapsed, 0.001):.1f}x)")
        concat_started = time.perf_counter()
        list_file = work_dir / "concat.txt"
        list_file.write_text("".join(f"file '{path.as_posix()}'\n" for path in segment_paths), encoding="utf-8")
        output = EXPORT_DIR / f"lances-{job_id[:8]}.mp4"
        finish_job(job_id, message="Juntando os lances…", progress=95)
        run([
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0",
            "-i", str(list_file), "-c", "copy", "-movflags", "+faststart", str(output),
        ], timeout=60 * 60)
        total_elapsed = time.perf_counter() - export_started
        export_log(job_id, f"junção: {time.perf_counter() - concat_started:.1f}s | total: {total_elapsed:.1f}s "
                           f"para {fmt_time(total_content)} de vídeo ({total_content / max(total_elapsed, 0.001):.1f}x)")
        finish_job(job_id, status="done", message="Vídeo final pronto.", progress=100,
                   download_url=f"/api/exports/{output.name}", name=output.name)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()[-1200:]
        finish_job(job_id, status="error", message="O FFmpeg não conseguiu processar o vídeo.", detail=detail)
    except RuntimeError as exc:
        finish_job(job_id, status="error", detail=str(exc).strip()[-1200:],
                   message="Não consegui baixar os trechos em alta qualidade do YouTube. Tente exportar em 480p.")
    except Exception as exc:
        finish_job(job_id, status="error", message=str(exc))
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)


@app.post("/api/export")
def export():
    data = request.json or {}
    media_id = data.get("media_id")
    path = active_media.get(media_id)
    if not path or not path.exists():
        return jsonify(error="Carregue um vídeo antes de exportar."), 400
    resolution = str(data.get("resolution", "original"))
    if resolution not in {"original", "480", "720", "1080"}:
        return jsonify(error="Resolução de saída inválida."), 400
    segments = data.get("segments", [])
    if not isinstance(segments, list) or not segments:
        return jsonify(error="Marque pelo menos um lance antes de exportar."), 400
    try:
        margin = min(15.0, max(0.0, float(data.get("margin", 3))))
        duration = probe(path)["duration"]
        normalized = []
        for item in segments:
            start, end = float(item["start"]), float(item["end"])
            if start < 0 or end <= start or start > duration:
                raise ValueError("Um dos intervalos marcados é inválido.")
            normalized.append({"start": start, "end": min(end, duration)})
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify(error=f"Intervalos inválidos: {exc}"), 400
    job_id = add_job("export")
    threading.Thread(target=export_worker, args=(job_id, path, normalized, margin, resolution, media_sources.get(media_id)), daemon=True).start()
    return jsonify(job_id=job_id), 202


@app.get("/api/exports/<filename>")
def exported(filename: str):
    safe_name = secure_filename(filename)
    path = EXPORT_DIR / safe_name
    if not path.exists():
        return jsonify(error="Arquivo exportado não encontrado."), 404
    return send_file(path, as_attachment=True, download_name=safe_name)


@app.errorhandler(413)
def too_large(_error):
    return jsonify(error="O arquivo excede o limite de 30 GB."), 413


if __name__ == "__main__":
    print("Editor de Lances disponível em http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, threaded=True, debug=False)