const $ = (selector) => document.querySelector(selector);
const player = $("#player");
const clipEditorPlayer = $("#clip-editor-player");
const CLIP_EDIT_PAD_SECONDS = 30;
const CLIP_MIN_DURATION_SECONDS = 0.5;
let mediaId = null;
let mediaDuration = 0;
let clips = [];
let pendingStart = null;
let pendingMarkTarget = null;
let markingMode = "clip";
let analysisPeriods = [];
let busy = false;
let autoResult = null; // última análise automática: { mediaId, shirtKey, periodsKey, suggestions }
let pickingShirt = false;
let pickedShirtColors = []; // [[r, g, b], ...] clicadas na camisa de jogadores do meu time
let editingClip = null;
let editWinStart = 0;
let editWinEnd = 0;
let editDraftStart = 0;
let editDraftEnd = 0;
let activeTrimDrag = null;

function formatTime(seconds) {
  const value = Math.max(0, Math.floor(Number(seconds) || 0));
  const hours = Math.floor(value / 3600);
  const minutes = Math.floor((value % 3600) / 60);
  const secs = value % 60;
  return hours
    ? `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`
    : `${minutes}:${String(secs).padStart(2, "0")}`;
}
function setStatus(target, message, type = "") {
  target.textContent = message;
  target.className = `status ${type}`;
}
async function readError(response) {
  const data = await response.json().catch(() => ({}));
  if (!response.ok)
    throw new Error(data.error || "Não foi possível concluir a operação.");
  return data;
}
function updateResolutionOptions(sourceHeight, maxHeight) {
  // Nunca amplia o vídeo. Em vídeos do YouTube, a edição é em 480p, mas a exportação pode
  // baixar de novo os trechos marcados em qualquer altura até maxHeight.
  const select = $("#resolution");
  const best = Math.max(sourceHeight || 0, maxHeight || 0);
  for (const option of select.options) {
    if (option.value === "original") {
      option.textContent = best ? `Original (${best}p)` : "Original";
      continue;
    }
    const target = Number(option.value);
    const unavailable =
      best > 0 &&
      (target > best || (target === best && target === sourceHeight));
    const note = target === best ? "igual à origem" : "maior que a origem";
    option.disabled = unavailable;
    option.textContent = unavailable ? `${target}p (${note})` : `${target}p`;
  }
  if (select.selectedOptions[0]?.disabled) select.value = "original";
}

function setSourceCollapsed(collapsed) {
  const source = $("#source-panel");
  source.classList.toggle("collapsed", collapsed);
  $("#source-toggle").setAttribute("aria-expanded", String(!collapsed));
  $("#source-toggle").setAttribute(
    "aria-label",
    collapsed ? "Abrir escolha da gravação" : "Recolher escolha da gravação",
  );
}

$("#source-toggle").addEventListener("click", (event) => {
  event.stopPropagation();
  setSourceCollapsed(!$("#source-panel").classList.contains("collapsed"));
});

$("#source-panel").addEventListener("click", (event) => {
  if (!$("#source-panel").classList.contains("collapsed")) return;
  if (event.target.closest("#source-toggle")) return;
  setSourceCollapsed(false);
});

function setMarkingCollapsed(collapsed) {
  const main = $("#editor-main");
  if (!main) return;
  main.classList.toggle("collapsed", collapsed);
  $("#marking-toggle").setAttribute("aria-expanded", String(!collapsed));
  $("#marking-toggle").setAttribute(
    "aria-label",
    collapsed ? "Abrir marcação de lances" : "Recolher marcação de lances",
  );
}

$("#marking-toggle").addEventListener("click", (event) => {
  event.stopPropagation();
  setMarkingCollapsed(!$("#editor-main").classList.contains("collapsed"));
  event.currentTarget.blur();
});

$("#editor-main").addEventListener("click", (event) => {
  if (!$("#editor-main").classList.contains("collapsed")) return;
  if (event.target.closest("#marking-toggle")) return;
  setMarkingCollapsed(false);
});

function enterEditor(data) {
  mediaId = data.media_id;
  mediaDuration = Number(data.duration) || 0;
  clips = [];
  pendingStart = null;
  pendingMarkTarget = null;
  markingMode = "clip";
  analysisPeriods = [];
  autoResult = null;
  pickedShirtColors = [];
  setPickingShirt(false);
  renderShirtPicks();
  setStatus($("#auto-status"), "", "");
  clipEditorPlayer.pause();
  clipEditorPlayer.removeAttribute("src");
  clipEditorPlayer.removeAttribute("data-media-id");
  clipEditorPlayer.load();
  closeClipEditor();
  $("#editor").classList.remove("hidden");
  $(".shell").classList.add("editor-layout");
  setSourceCollapsed(true);
  $("#loaded-name").textContent = data.name;
  $("#video-dimensions").textContent =
    `${data.width} × ${data.height} · ${formatTime(data.duration)}`;
  $("#total-time").textContent = formatTime(data.duration);
  updateResolutionOptions(Number(data.height), Number(data.max_height));
  player.src = `/api/media/${mediaId}`;
  renderClips();
  renderAnalysisPeriods();
  updateMarkingMode();
  $("#editor").scrollIntoView({ behavior: "smooth", block: "start" });
}

$("#video-file").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  $("#file-name").textContent = file.name;
  setStatus(
    $("#source-status"),
    "Carregando e verificando o vídeo…",
    "working",
  );
  const body = new FormData();
  body.append("video", file);
  try {
    const data = await readError(
      await fetch("/api/upload", { method: "POST", body }),
    );
    setStatus(
      $("#source-status"),
      "Vídeo carregado. Já pode marcar os lances.",
      "success",
    );
    enterEditor(data);
  } catch (error) {
    setStatus($("#source-status"), error.message, "error");
  }
});

try {
  $("#youtube-cookies").value = localStorage.getItem("handcut-cookies") || "";
} catch (_) {}
$("#youtube-cookies").addEventListener("change", (event) => {
  try {
    localStorage.setItem("handcut-cookies", event.target.value);
  } catch (_) {}
});

$("#youtube-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button");
  button.disabled = true;
  setStatus($("#source-status"), "Iniciando download…", "working");
  try {
    const { job_id } = await readError(
      await fetch("/api/download", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url: $("#youtube-url").value,
          cookies: $("#youtube-cookies").value,
        }),
      }),
    );
    await pollJob(
      job_id,
      (job) => {
        setStatus(
          $("#source-status"),
          job.message,
          job.status === "error" ? "error" : "working",
        );
        if (job.detail)
          setStatus(
            $("#source-status"),
            `${job.message} ${job.detail}`,
            "error",
          );
      },
      (job) => {
        setStatus($("#source-status"), job.message, "success");
        enterEditor({
          media_id: job.media_id,
          name: job.name,
          duration: job.duration,
          width: job.width,
          height: job.height,
          max_height: job.max_height,
        });
      },
    );
  } catch (error) {
    setStatus($("#source-status"), error.message, "error");
  } finally {
    button.disabled = false;
  }
});

// ---- Seletor de arquivos nativo (janela pywebview): lê o vídeo onde ele está, sem copiar ----
function hasNativePicker() {
  return Boolean(
    window.pywebview &&
    window.pywebview.api &&
    window.pywebview.api.choose_video,
  );
}
$("#video-file").addEventListener("click", async (event) => {
  if (!hasNativePicker()) return; // no navegador comum, vale o seletor padrão (envia uma cópia)
  event.preventDefault();
  const path = await window.pywebview.api.choose_video();
  if (!path) return;
  $("#file-name").textContent = path.split(/[\\/]/).pop();
  setStatus($("#source-status"), "Verificando o vídeo…", "working");
  try {
    const data = await readError(
      await fetch("/api/open-path", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      }),
    );
    setStatus(
      $("#source-status"),
      "Vídeo aberto. Já pode marcar os lances.",
      "success",
    );
    enterEditor(data);
  } catch (error) {
    setStatus($("#source-status"), error.message, "error");
  }
});

function markStart() {
  if (!mediaId || !Number.isFinite(player.currentTime)) return;
  pendingStart = player.currentTime;
  pendingMarkTarget = markingMode;
  const target = markingMode === "analysis" ? "período de análise" : "lance";
  $("#pending-text").textContent =
    `Início do ${target} em ${formatTime(pendingStart)} · marque o fim com O`;
  $(".pending-dot").classList.add("active");
}
function markEnd() {
  if (pendingStart === null) {
    setStatus(
      $("#export-status"),
      "Marque o início com I antes de marcar o fim.",
      "error",
    );
    return;
  }
  const end = player.currentTime;
  if (end <= pendingStart) {
    setStatus(
      $("#export-status"),
      "O fim precisa estar depois do início. Volte a reproduzir e tente novamente.",
      "error",
    );
    return;
  }
  if (pendingMarkTarget === "analysis") {
    analysisPeriods.push({ start: pendingStart, end });
    analysisPeriods.sort((a, b) => a.start - b.start);
    autoResult = null;
    renderAnalysisPeriods();
  } else {
    clips.push({ start: pendingStart, end });
    clips.sort((a, b) => a.start - b.start);
    renderClips();
  }
  pendingStart = null;
  pendingMarkTarget = null;
  $("#pending-text").textContent = "Nenhum início marcado";
  $(".pending-dot").classList.remove("active");
  setStatus($("#export-status"), "", "");
}
$("#mark-start").addEventListener("click", markStart);
$("#mark-end").addEventListener("click", markEnd);

function resetPendingMark() {
  pendingStart = null;
  pendingMarkTarget = null;
  $("#pending-text").textContent = "Nenhum início marcado";
  $(".pending-dot").classList.remove("active");
}

function updateMarkingMode() {
  const isAnalysis = markingMode === "analysis";
  $("#analysis-mode-toggle").textContent = isAnalysis
    ? "Marcando períodos de análise"
    : "Marcar períodos de análise";
  $("#analysis-mode-toggle").classList.toggle("active", isAnalysis);
  $("#analysis-mode-toggle").setAttribute("aria-pressed", String(isAnalysis));
  $("#mark-start-detail").textContent = isAnalysis
    ? "do período de análise"
    : "do lance";
  $("#mark-end-detail").textContent = isAnalysis
    ? "do período de análise"
    : "do lance";
}

$("#analysis-mode-toggle").addEventListener("click", (event) => {
  markingMode = markingMode === "analysis" ? "clip" : "analysis";
  resetPendingMark();
  updateMarkingMode();
  event.currentTarget.blur();
});

function renderAnalysisPeriods() {
  const list = $("#analysis-period-list");
  list.replaceChildren();
  $("#analysis-period-count").textContent = analysisPeriods.length;
  $("#analysis-period-empty").classList.toggle(
    "hidden",
    analysisPeriods.length > 0,
  );
  analysisPeriods.forEach((period, index) => {
    const item = document.createElement("li");
    item.className = "analysis-period-item";
    const play = document.createElement("button");
    play.className = "clip-play";
    play.textContent = "▶";
    play.title = "Ir para o início deste período";
    play.addEventListener("click", () => {
      player.currentTime = period.start;
      player.play();
    });
    const label = document.createElement("span");
    label.className = "clip-label";
    label.textContent = `Período ${String(index + 1).padStart(2, "0")}`;
    const time = document.createElement("span");
    time.className = "clip-time";
    time.textContent = `${formatTime(period.start)} — ${formatTime(period.end)} · ${formatTime(period.end - period.start)}`;
    const remove = document.createElement("button");
    remove.className = "clip-remove";
    remove.textContent = "Remover";
    remove.addEventListener("click", () => {
      analysisPeriods.splice(index, 1);
      autoResult = null;
      renderAnalysisPeriods();
    });
    item.append(play, label, time, remove);
    list.append(item);
  });
}

function analysisPeriodsKey(periods = analysisPeriods) {
  return periods
    .map((period) => `${period.start.toFixed(3)}:${period.end.toFixed(3)}`)
    .join("|");
}

function computeClipEditWindow(
  allClips,
  targetClip,
  totalDuration,
  padSeconds = CLIP_EDIT_PAD_SECONDS,
) {
  const maxDur = Math.max(Number(totalDuration) || 0, targetClip.end);
  let winStart = Math.max(0, targetClip.start - padSeconds);
  let winEnd = Math.min(maxDur, targetClip.end + padSeconds);

  for (const other of allClips) {
    if (other === targetClip) continue;
    if (other.end <= targetClip.start && other.end >= winStart) {
      winStart = Math.max(winStart, Math.min(targetClip.start, other.end + 1));
    } else if (other.start >= targetClip.end && other.start <= winEnd) {
      winEnd = Math.min(winEnd, Math.max(targetClip.end, other.start - 1));
    } else {
      if (other.start < targetClip.start && other.end > targetClip.start) {
        winStart = Math.max(winStart, targetClip.start);
      }
      if (other.start < targetClip.end && other.end > targetClip.end) {
        winEnd = Math.min(winEnd, targetClip.end);
      }
    }
  }

  winStart = Math.min(winStart, targetClip.start);
  winEnd = Math.max(winEnd, targetClip.end);
  return { winStart, winEnd };
}

function createSvgIcon(pathD) {
  const svgNs = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(svgNs, "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(svgNs, "path");
  path.setAttribute("d", pathD);
  svg.append(path);
  return svg;
}

function createPencilIcon() {
  return createSvgIcon(
    "M11.8 2.2a1.4 1.4 0 0 1 2 2L5.3 12.7l-3 .8.8-3z",
  );
}

function createCloseIcon() {
  return createSvgIcon("M4 4l8 8M12 4l-8 8");
}

function renderClipTrimUI() {
  if (!editingClip) return;
  const span = Math.max(0.01, editWinEnd - editWinStart);
  const startPct = ((editDraftStart - editWinStart) / span) * 100;
  const endPct = ((editDraftEnd - editWinStart) / span) * 100;
  const curRaw = Number.isFinite(clipEditorPlayer.currentTime)
    ? clipEditorPlayer.currentTime
    : editDraftStart;
  const cur = Math.min(editWinEnd, Math.max(editWinStart, curRaw));
  const curPct = ((cur - editWinStart) / span) * 100;

  $("#clip-trim-range").style.left = `${startPct}%`;
  $("#clip-trim-range").style.width = `${Math.max(0, endPct - startPct)}%`;
  $("#clip-trim-handle-start").style.left = `${startPct}%`;
  $("#clip-trim-handle-end").style.left = `${endPct}%`;
  $("#clip-trim-handle-start").setAttribute(
    "aria-valuenow",
    String(Math.round(editDraftStart)),
  );
  $("#clip-trim-handle-end").setAttribute(
    "aria-valuenow",
    String(Math.round(editDraftEnd)),
  );
  $("#clip-trim-playhead").style.left = `${curPct}%`;

  $("#clip-editor-win-start").textContent = formatTime(editWinStart);
  $("#clip-editor-win-end").textContent = formatTime(editWinEnd);
  $("#clip-editor-window-info").textContent =
    `Janela do editor: ${formatTime(editWinStart)} — ${formatTime(editWinEnd)}`;
  $("#clip-editor-range-info").textContent =
    `Lance: ${formatTime(editDraftStart)} — ${formatTime(editDraftEnd)} · ${formatTime(editDraftEnd - editDraftStart)}`;
  $("#clip-editor-current").textContent = `Posição: ${formatTime(cur)}`;
  $("#clip-editor-play").textContent = clipEditorPlayer.paused ? "▶" : "⏸";
}

function seekClipEditor(targetTime) {
  const clamped = Math.min(editWinEnd, Math.max(editWinStart, targetTime));
  if (clipEditorPlayer.readyState >= 1) {
    clipEditorPlayer.currentTime = clamped;
  } else {
    clipEditorPlayer.addEventListener(
      "loadedmetadata",
      () => {
        if (editingClip) clipEditorPlayer.currentTime = clamped;
      },
      { once: true },
    );
  }
}

function openClipEditor(clip) {
  if (!mediaId) return;
  if (!player.paused) player.pause();
  setPickingShirt(false);
  editingClip = clip;
  const knownDuration =
    mediaDuration ||
    (Number.isFinite(player.duration) ? player.duration : clip.end + 30);
  const { winStart, winEnd } = computeClipEditWindow(
    clips,
    clip,
    knownDuration,
  );
  editWinStart = winStart;
  editWinEnd = winEnd;
  editDraftStart = clip.start;
  editDraftEnd = clip.end;

  setMarkingCollapsed(true);
  $("#clip-editor-panel").classList.remove("hidden");
  const idx = clips.indexOf(clip);
  $("#clip-editor-title").textContent =
    `Editar Lance ${String(idx + 1).padStart(2, "0")}`;

  if (clipEditorPlayer.dataset.mediaId !== String(mediaId)) {
    clipEditorPlayer.dataset.mediaId = String(mediaId);
    clipEditorPlayer.src = `/api/media/${mediaId}`;
  }
  clipEditorPlayer.pause();
  seekClipEditor(editDraftStart);
  renderClips();
  renderClipTrimUI();
  $("#clip-editor-panel").scrollIntoView({
    behavior: "smooth",
    block: "nearest",
  });
}

function closeClipEditor() {
  if (clipEditorPlayer && !clipEditorPlayer.paused) clipEditorPlayer.pause();
  editingClip = null;
  activeTrimDrag = null;
  $("#clip-trim-handle-start")?.classList.remove("dragging");
  $("#clip-trim-handle-end")?.classList.remove("dragging");
  $("#clip-editor-panel")?.classList.add("hidden");
  setMarkingCollapsed(false);
  renderClips();
}

function toggleClipEditorPlay() {
  if (!editingClip) return;
  if (clipEditorPlayer.paused) {
    if (
      clipEditorPlayer.currentTime < editWinStart ||
      clipEditorPlayer.currentTime >= editWinEnd - 0.15
    ) {
      clipEditorPlayer.currentTime = editDraftStart;
    }
    clipEditorPlayer.play().catch(() => {});
  } else {
    clipEditorPlayer.pause();
  }
}

function renderClips() {
  const list = $("#clips-list");
  list.replaceChildren();
  $("#clip-count").textContent = clips.length;
  $("#empty-clips").classList.toggle("hidden", clips.length > 0);
  clips.forEach((clip, index) => {
    const item = document.createElement("li");
    item.className = clip === editingClip ? "clip-item editing" : "clip-item";
    const play = document.createElement("button");
    play.className = "clip-play";
    play.textContent = "▶";
    play.title = "Reproduzir este intervalo";
    play.addEventListener("click", () => {
      if (clip === editingClip) {
        seekClipEditor(editDraftStart);
        clipEditorPlayer.play().catch(() => {});
        return;
      }
      if (!clipEditorPlayer.paused) clipEditorPlayer.pause();
      setMarkingCollapsed(false);
      player.currentTime = clip.start;
      player.play();
    });
    const label = document.createElement("span");
    label.className = "clip-label";
    label.textContent = `Lance ${String(index + 1).padStart(2, "0")}`;
    const tag = document.createElement("span");
    tag.className = "clip-tag";
    tag.textContent = "sugerido";
    tag.hidden = !clip.auto;
    const time = document.createElement("span");
    time.className = "clip-time";
    time.textContent = `${formatTime(clip.start)} — ${formatTime(clip.end)} · ${formatTime(clip.end - clip.start)}`;

    const actions = document.createElement("div");
    actions.className = "clip-actions";

    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "clip-icon-btn clip-edit";
    edit.title = "Editar início e fim deste lance";
    edit.setAttribute("aria-label", `Editar Lance ${String(index + 1).padStart(2, "0")}`);
    edit.append(createPencilIcon());
    edit.addEventListener("click", () => {
      openClipEditor(clip);
    });

    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "clip-icon-btn clip-delete";
    remove.title = "Remover este lance";
    remove.setAttribute("aria-label", `Remover Lance ${String(index + 1).padStart(2, "0")}`);
    remove.append(createCloseIcon());
    remove.addEventListener("click", () => {
      const removed = clips.splice(index, 1)[0];
      if (removed === editingClip) {
        closeClipEditor();
        return;
      }
      if (editingClip) {
        const knownDuration =
          mediaDuration ||
          (Number.isFinite(player.duration) ? player.duration : editingClip.end + 30);
        const win = computeClipEditWindow(clips, editingClip, knownDuration);
        editWinStart = win.winStart;
        editWinEnd = win.winEnd;
        editDraftStart = Math.max(editWinStart, editDraftStart);
        editDraftEnd = Math.min(editWinEnd, editDraftEnd);
        renderClipTrimUI();
      }
      renderClips();
    });

    actions.append(edit, remove);
    item.append(play, label, tag, time, actions);
    list.append(item);
  });
  $("#export-button").disabled = clips.length === 0 || busy;
}

clipEditorPlayer.addEventListener("click", toggleClipEditorPlay);
$("#clip-editor-play").addEventListener("click", (event) => {
  toggleClipEditorPlay();
  event.currentTarget.blur();
});
clipEditorPlayer.addEventListener("play", renderClipTrimUI);
clipEditorPlayer.addEventListener("pause", renderClipTrimUI);
clipEditorPlayer.addEventListener("timeupdate", () => {
  if (!editingClip) return;
  if (clipEditorPlayer.currentTime < editWinStart) {
    clipEditorPlayer.currentTime = editWinStart;
  } else if (clipEditorPlayer.currentTime >= editWinEnd) {
    clipEditorPlayer.pause();
    clipEditorPlayer.currentTime = editWinEnd;
  }
  renderClipTrimUI();
});

function timeFromTrimPointer(clientX) {
  const rect = $("#clip-trim-bar").getBoundingClientRect();
  const frac = Math.min(
    1,
    Math.max(0, (clientX - rect.left) / Math.max(1, rect.width)),
  );
  return editWinStart + frac * (editWinEnd - editWinStart);
}

function applyTrimDrag(clientX) {
  if (!editingClip || !activeTrimDrag) return;
  const target = timeFromTrimPointer(clientX);
  if (activeTrimDrag === "start") {
    editDraftStart = Math.min(
      target,
      editDraftEnd - CLIP_MIN_DURATION_SECONDS,
    );
    editDraftStart = Math.max(editWinStart, editDraftStart);
    clipEditorPlayer.currentTime = editDraftStart;
  } else if (activeTrimDrag === "end") {
    editDraftEnd = Math.max(
      target,
      editDraftStart + CLIP_MIN_DURATION_SECONDS,
    );
    editDraftEnd = Math.min(editWinEnd, editDraftEnd);
    clipEditorPlayer.currentTime = editDraftEnd;
  } else {
    clipEditorPlayer.currentTime = target;
  }
  renderClipTrimUI();
}

$("#clip-trim-handle-start").addEventListener("pointerdown", (event) => {
  if (!editingClip) return;
  event.preventDefault();
  event.stopPropagation();
  activeTrimDrag = "start";
  clipEditorPlayer.pause();
  event.currentTarget.classList.add("dragging");
  $("#clip-trim-bar").setPointerCapture(event.pointerId);
});

$("#clip-trim-handle-end").addEventListener("pointerdown", (event) => {
  if (!editingClip) return;
  event.preventDefault();
  event.stopPropagation();
  activeTrimDrag = "end";
  clipEditorPlayer.pause();
  event.currentTarget.classList.add("dragging");
  $("#clip-trim-bar").setPointerCapture(event.pointerId);
});

$("#clip-trim-bar").addEventListener("pointerdown", (event) => {
  if (!editingClip || event.target.closest(".clip-trim-handle")) return;
  event.preventDefault();
  activeTrimDrag = "seek";
  $("#clip-trim-bar").setPointerCapture(event.pointerId);
  applyTrimDrag(event.clientX);
});

$("#clip-trim-bar").addEventListener("pointermove", (event) => {
  if (!activeTrimDrag) return;
  applyTrimDrag(event.clientX);
});

function stopTrimDrag() {
  if (!activeTrimDrag) return;
  activeTrimDrag = null;
  $("#clip-trim-handle-start").classList.remove("dragging");
  $("#clip-trim-handle-end").classList.remove("dragging");
}
$("#clip-trim-bar").addEventListener("pointerup", stopTrimDrag);
$("#clip-trim-bar").addEventListener("pointercancel", stopTrimDrag);

function nudgeTrimHandle(edge, event) {
  if (!editingClip || (event.key !== "ArrowLeft" && event.key !== "ArrowRight"))
    return;
  event.preventDefault();
  event.stopPropagation();
  const step = (event.shiftKey ? 0.5 : 1.0) * (event.key === "ArrowRight" ? 1 : -1);
  clipEditorPlayer.pause();
  if (edge === "start") {
    editDraftStart = Math.max(
      editWinStart,
      Math.min(editDraftEnd - CLIP_MIN_DURATION_SECONDS, editDraftStart + step),
    );
    clipEditorPlayer.currentTime = editDraftStart;
  } else {
    editDraftEnd = Math.min(
      editWinEnd,
      Math.max(editDraftStart + CLIP_MIN_DURATION_SECONDS, editDraftEnd + step),
    );
    clipEditorPlayer.currentTime = editDraftEnd;
  }
  renderClipTrimUI();
}
$("#clip-trim-handle-start").addEventListener("keydown", (e) =>
  nudgeTrimHandle("start", e),
);
$("#clip-trim-handle-end").addEventListener("keydown", (e) =>
  nudgeTrimHandle("end", e),
);

$("#clip-editor-cancel").addEventListener("click", closeClipEditor);
$("#clip-editor-confirm").addEventListener("click", () => {
  if (!editingClip) return;
  editingClip.start = Number(editDraftStart.toFixed(2));
  editingClip.end = Number(editDraftEnd.toFixed(2));
  clips.sort((a, b) => a.start - b.start);
  closeClipEditor();
});

// Depois de um clique nos controles nativos do player, o teclado passa a valer só para eles
// (as setas pulam outro valor e I, O e espaço deixam de funcionar). Tirar o foco do player
// devolve os atalhos do app.
player.addEventListener("focus", () => player.blur());

player.addEventListener("timeupdate", () => {
  $("#current-time").textContent = formatTime(player.currentTime);
  if (Number.isFinite(player.duration) && player.duration > 0)
    $("#seek").value = Math.round(
      (player.currentTime / player.duration) * 1000,
    );
});
$("#seek").addEventListener("input", (event) => {
  if (Number.isFinite(player.duration))
    player.currentTime = (Number(event.target.value) / 1000) * player.duration;
});
function isShortcutInput(target) {
  // A barra de progresso (input range) fica de fora: depois de clicar nela, os atalhos
  // continuam valendo e as setas não movem a barra por conta própria.
  return (
    target instanceof Element &&
    target.matches(
      'input:not([type="range"]),textarea,select,button,[contenteditable="true"]',
    )
  );
}

function handlePlayerShortcut(event) {
  if (!mediaId) return;
  if (editingClip) {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      if (event.type === "keydown") closeClipEditor();
      return;
    }
    if (event.target instanceof Element && event.target.closest(".clip-trim-handle"))
      return;
    if (isShortcutInput(event.target)) return;
    const isNav =
      event.code === "Space" ||
      event.key === "ArrowLeft" ||
      event.key === "ArrowRight";
    if (!isNav) return;
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation();
    if (event.type === "keyup" || event.repeat) return;
    if (event.code === "Space") {
      toggleClipEditorPlay();
    } else if (event.key === "ArrowLeft") {
      clipEditorPlayer.currentTime = Math.max(
        editWinStart,
        clipEditorPlayer.currentTime - 5,
      );
      renderClipTrimUI();
    } else if (event.key === "ArrowRight") {
      clipEditorPlayer.currentTime = Math.min(
        editWinEnd,
        clipEditorPlayer.currentTime + 5,
      );
      renderClipTrimUI();
    }
    return;
  }
  if (isShortcutInput(event.target)) return;
  const isPlayerShortcut =
    event.code === "Space" ||
    event.key === "ArrowLeft" ||
    event.key === "ArrowRight" ||
    event.key.toLowerCase() === "i" ||
    event.key.toLowerCase() === "o";
  if (!isPlayerShortcut) return;

  // Capture before native video controls so they don't also seek or toggle
  // playback on keydown/keyup when the player has focus.
  event.preventDefault();
  event.stopPropagation();
  event.stopImmediatePropagation();

  if (event.type === "keyup" || event.repeat) return;
  if (event.code === "Space") {
    if (player.paused) player.play().catch(() => {});
    else player.pause();
  } else if (event.key === "ArrowLeft") {
    player.currentTime = Math.max(0, player.currentTime - 5);
  } else if (event.key === "ArrowRight") {
    player.currentTime = Math.min(
      player.duration || Infinity,
      player.currentTime + 5,
    );
  } else if (event.key.toLowerCase() === "i") {
    markStart();
  } else if (event.key.toLowerCase() === "o") {
    markEnd();
  }
}

window.addEventListener("keydown", handlePlayerShortcut, { capture: true });
window.addEventListener("keyup", handlePlayerShortcut, { capture: true });

async function pollJob(jobId, onProgress, onDone) {
  while (true) {
    const job = await readError(await fetch(`/api/jobs/${jobId}`));
    onProgress(job);
    if (job.status === "error")
      throw new Error(
        job.detail ? `${job.message} ${job.detail}` : job.message,
      );
    if (job.status === "done") {
      onDone(job);
      return job;
    }
    await new Promise((resolve) => setTimeout(resolve, 1200));
  }
}

$("#export-button").addEventListener("click", async () => {
  busy = true;
  renderClips();
  const button = $("#export-button");
  button.textContent = "Montando…";
  setStatus($("#export-status"), "Preparando os cortes no FFmpeg…", "working");
  try {
    const { job_id } = await readError(
      await fetch("/api/export", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          media_id: mediaId,
          segments: clips,
          margin: $("#margin").value,
          resolution: $("#resolution").value,
        }),
      }),
    );
    await pollJob(
      job_id,
      (job) =>
        setStatus(
          $("#export-status"),
          job.message,
          job.status === "error" ? "error" : "working",
        ),
      (job) => {
        const link = document.createElement("a");
        link.href = job.download_url;
        link.className = "download-result";
        link.textContent = `Baixar ${job.name}`;
        setStatus($("#export-status"), "", "success");
        $("#export-status").append("Vídeo final pronto. ", link);
      },
    );
  } catch (error) {
    setStatus($("#export-status"), error.message, "error");
  } finally {
    busy = false;
    button.innerHTML = "Exportar vídeo <span>→</span>";
    renderClips();
  }
});

// ---- Sugestão automática (Fase 2) ----
function medianChannel(values) {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)] || 0;
}

function samplePlayerColor(event) {
  if (!player.videoWidth || !player.videoHeight) return null;
  const rect = player.getBoundingClientRect();
  // Ignora cliques na barra inferior de controles nativos do player.
  if (event.clientY > rect.bottom - 44) return null;
  const videoRatio = player.videoWidth / player.videoHeight;
  const boxRatio = rect.width / rect.height;
  let drawW = rect.width;
  let drawH = rect.height;
  let offsetX = 0;
  let offsetY = 0;
  if (boxRatio > videoRatio) {
    drawW = rect.height * videoRatio;
    offsetX = (rect.width - drawW) / 2;
  } else {
    drawH = rect.width / videoRatio;
    offsetY = (rect.height - drawH) / 2;
  }
  const relX = (event.clientX - rect.left - offsetX) / drawW;
  const relY = (event.clientY - rect.top - offsetY) / drawH;
  if (relX < 0 || relX > 1 || relY < 0 || relY > 1) return null;

  const canvas = document.createElement("canvas");
  const scale = Math.min(1, 854 / player.videoWidth);
  canvas.width = Math.max(1, Math.round(player.videoWidth * scale));
  canvas.height = Math.max(1, Math.round(player.videoHeight * scale));
  const ctx = canvas.getContext("2d", { willReadFrequently: true });
  ctx.drawImage(player, 0, 0, canvas.width, canvas.height);

  const cx = Math.min(canvas.width - 1, Math.max(0, Math.round(relX * canvas.width)));
  const cy = Math.min(canvas.height - 1, Math.max(0, Math.round(relY * canvas.height)));
  const x0 = Math.max(0, cx - 3);
  const y0 = Math.max(0, cy - 3);
  const w = Math.min(canvas.width - x0, 7);
  const h = Math.min(canvas.height - y0, 7);
  const pixels = ctx.getImageData(x0, y0, w, h).data;
  const rs = [];
  const gs = [];
  const bs = [];
  for (let i = 0; i < pixels.length; i += 4) {
    rs.push(pixels[i]);
    gs.push(pixels[i + 1]);
    bs.push(pixels[i + 2]);
  }
  return [medianChannel(rs), medianChannel(gs), medianChannel(bs)];
}

function setPickingShirt(active) {
  pickingShirt = Boolean(active);
  if (pickingShirt && !player.paused) player.pause();
  player.classList.toggle("picking-shirt", pickingShirt);
  const toggle = $("#pick-shirt-toggle");
  toggle.classList.toggle("active", pickingShirt);
  toggle.setAttribute("aria-pressed", String(pickingShirt));
  toggle.textContent = pickingShirt
    ? "Concluir seleção no vídeo"
    : "Clicar na camisa no vídeo";
  renderShirtPicks();
}

function renderShirtPicks() {
  const bar = $("#shirt-picker-bar");
  const swatches = $("#shirt-swatches");
  const hint = $("#pick-shirt-hint");
  const clear = $("#clear-shirt-picks");
  const hasPicks = pickedShirtColors.length > 0;
  bar.classList.toggle("hidden", !pickingShirt && !hasPicks);
  hint.hidden = !pickingShirt && hasPicks;
  clear.hidden = !hasPicks;
  clear.classList.toggle("hidden", !hasPicks);
  swatches.replaceChildren();
  pickedShirtColors.forEach((rgb, index) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "shirt-swatch";
    chip.style.backgroundColor = `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`;
    chip.title = `Amostra ${index + 1} (clique para remover)`;
    chip.textContent = "×";
    chip.addEventListener("click", () => {
      pickedShirtColors.splice(index, 1);
      autoResult = null;
      renderShirtPicks();
    });
    swatches.append(chip);
  });
  if (hasPicks && !pickingShirt) {
    const note = document.createElement("span");
    note.className = "shirt-swatch-note";
    note.textContent = `${pickedShirtColors.length} amostra(s) clicada(s) — têm prioridade sobre "Meu time veste"`;
    swatches.append(note);
  }
}

$("#pick-shirt-toggle").addEventListener("click", (event) => {
  if (!mediaId) return;
  setPickingShirt(!pickingShirt);
  event.currentTarget.blur();
});

$("#clear-shirt-picks").addEventListener("click", (event) => {
  pickedShirtColors = [];
  autoResult = null;
  renderShirtPicks();
  event.currentTarget.blur();
});

player.addEventListener(
  "click",
  (event) => {
    if (!pickingShirt || !mediaId) return;
    const rgb = samplePlayerColor(event);
    if (!rgb) return;
    event.preventDefault();
    event.stopPropagation();
    if (pickedShirtColors.length >= 10) pickedShirtColors.shift();
    pickedShirtColors.push(rgb);
    autoResult = null;
    renderShirtPicks();
  },
  { capture: true },
);

function shirtConfigKey(shirt, shirtColors) {
  if (shirtColors.length) {
    return "clicks:" + shirtColors.map((c) => c.join(",")).join(";");
  }
  return `select:${shirt}`;
}

function addSuggestedClips(kind, suggestions) {
  let added = 0;
  for (const item of suggestions[kind] || []) {
    // Não repete um trecho que já está na lista (por exemplo, ao pedir a sugestão duas vezes).
    if (clips.some((clip) => clip.start < item.end && item.start < clip.end))
      continue;
    clips.push({ start: item.start, end: item.end, auto: true });
    added += 1;
  }
  clips.sort((a, b) => a.start - b.start);
  renderClips();
  return added;
}

$("#auto-button").addEventListener("click", async () => {
  if (!mediaId) return;
  setPickingShirt(false);
  const button = $("#auto-button");
  const status = $("#auto-status");
  const analyzed = mediaId;
  const shirt = $("#auto-shirt").value;
  const shirtColors = pickedShirtColors.map((c) => [...c]);
  const shirtKey = shirtConfigKey(shirt, shirtColors);
  const kind = $("#auto-kind").value;
  const periods = analysisPeriods.map((period) => ({ ...period }));
  const periodsKey = analysisPeriodsKey(periods);
  button.disabled = true;
  button.blur(); // devolve os atalhos do teclado (I, O, espaço, setas) ao player
  try {
    // A análise é a parte lenta e serve para ataques e defesas. Se já foi feita para este
    // vídeo e esta cor de camisa, só reaproveita o resultado.
    if (
      !autoResult ||
      autoResult.mediaId !== analyzed ||
      autoResult.shirtKey !== shirtKey ||
      autoResult.periodsKey !== periodsKey
    ) {
      setStatus(status, "Iniciando a análise…", "working");
      const { job_id } = await readError(
        await fetch("/api/suggest", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            media_id: analyzed,
            shirt,
            shirt_colors: shirtColors,
            periods,
          }),
        }),
      );
      const job = await pollJob(
        job_id,
        (job) =>
          setStatus(
            status,
            job.message,
            job.status === "error" ? "error" : "working",
          ),
        () => {},
      );
      autoResult = {
        mediaId: analyzed,
        shirtKey,
        periodsKey,
        suggestions: job.suggestions,
        warnings: job.warnings || [],
      };
    }
    if (mediaId !== analyzed) return; // a pessoa trocou de vídeo durante a análise
    if (analysisPeriodsKey() !== periodsKey) {
      setStatus(
        status,
        "Os períodos foram alterados durante a análise. Clique em sugerir novamente.",
        "working",
      );
      return;
    }
    const found = (autoResult.suggestions[kind] || []).length;
    const added = addSuggestedClips(kind, autoResult.suggestions);
    const name = kind === "ataque" ? "ataque(s)" : "defesa(s)";
    const warnings = autoResult.warnings || [];
    const warnSuffix = warnings.length ? ` Aviso: ${warnings.join(" ")}` : "";
    if (added) {
      setStatus(
        status,
        `${added} ${name} sugerido(s) e adicionado(s) à lista. Confira cada um no ▶ antes de exportar.${warnSuffix}`,
        warnings.length ? "working" : "success",
      );
    } else if (found) {
      setStatus(
        status,
        `Os ${found} ${name} encontrado(s) já estão na lista.${warnSuffix}`,
        warnings.length ? "working" : "success",
      );
    } else if (warnings.length) {
      setStatus(
        status,
        `Não encontrei ${name} neste trecho. ${warnings.join(" ")}`,
        "error",
      );
    } else {
      setStatus(
        status,
        `Não encontrei ${name} neste vídeo. Confira se a cor da camisa está certa.`,
        "error",
      );
    }
  } catch (error) {
    setStatus(status, error.message, "error");
  } finally {
    button.disabled = false;
  }
});

// Tira o foco do seletor para os atalhos I, O, espaço e setas voltarem a funcionar.
$("#resolution").addEventListener("change", (event) => event.target.blur());
$("#auto-shirt").addEventListener("change", (event) => {
  autoResult = null;
  if (pickedShirtColors.length) {
    setStatus(
      $("#auto-status"),
      `Você ainda tem ${pickedShirtColors.length} amostra(s) clicada(s) no vídeo (têm prioridade). Clique em "Limpar amostras" se quiser usar só o seletor.`,
      "working",
    );
  }
  event.target.blur();
});
$("#auto-kind").addEventListener("change", (event) => event.target.blur());

$("#change-video").addEventListener("click", () => {
  player.pause();
  player.removeAttribute("src");
  player.load();
  clipEditorPlayer.pause();
  clipEditorPlayer.removeAttribute("src");
  clipEditorPlayer.removeAttribute("data-media-id");
  clipEditorPlayer.load();
  mediaId = null;
  mediaDuration = 0;
  clips = [];
  closeClipEditor();
  resetPendingMark();
  markingMode = "clip";
  analysisPeriods = [];
  autoResult = null;
  pickedShirtColors = [];
  setPickingShirt(false);
  renderShirtPicks();
  setStatus($("#auto-status"), "", "");
  renderAnalysisPeriods();
  updateMarkingMode();
  $("#editor").classList.add("hidden");
  $(".shell").classList.remove("editor-layout");
  setSourceCollapsed(false);
  $("#video-file").value = "";
  $("#file-name").textContent = "Nenhum arquivo selecionado";
  window.scrollTo({ top: 0, behavior: "smooth" });
});

// ---- Manutenção: versão do yt-dlp, atualização e limpeza ----
async function refreshMaintenance() {
  try {
    const data = await readError(await fetch("/api/maintenance"));
    $("#ytdlp-version").textContent =
      `yt-dlp ${data.ytdlp_version} · ${data.used} em uso`;
  } catch {
    $("#ytdlp-version").textContent = "";
  }
}

async function runMaintenance(button, start) {
  const status = $("#maintenance-status");
  button.disabled = true;
  try {
    await start(status);
  } catch (error) {
    setStatus(status, error.message, "error");
  } finally {
    button.disabled = false;
    refreshMaintenance();
  }
}

$("#update-ytdlp").addEventListener("click", (event) =>
  runMaintenance(event.currentTarget, async (status) => {
    setStatus(status, "Procurando atualização do yt-dlp…", "working");
    const { job_id } = await readError(
      await fetch("/api/update-ytdlp", { method: "POST" }),
    );
    await pollJob(
      job_id,
      (job) =>
        setStatus(
          status,
          job.message,
          job.status === "error" ? "error" : "working",
        ),
      (job) => setStatus(status, job.message, "success"),
    );
  }),
);

$("#cleanup").addEventListener("click", (event) => {
  const message =
    "Apagar os vídeos baixados do YouTube, os arquivos temporários e os vídeos exportados? " +
    "Exportações que você ainda não baixou serão perdidas. " +
    "O vídeo aberto agora e os arquivos escolhidos no seu computador não serão apagados.";
  if (!window.confirm(message)) return;
  runMaintenance(event.currentTarget, async (status) => {
    const result = await readError(
      await fetch("/api/cleanup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ keep_media_id: mediaId }),
      }),
    );
    setStatus(
      status,
      `Limpeza concluída: ${result.removed} item(ns), ${result.freed} liberados.`,
      "success",
    );
  });
});

refreshMaintenance();
