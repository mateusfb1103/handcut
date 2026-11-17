const $ = (selector) => document.querySelector(selector);
const player = $("#player");
let mediaId = null;
let clips = [];
let pendingStart = null;
let pendingMarkTarget = null;
let markingMode = "clip";
let analysisPeriods = [];
let busy = false;
let autoResult = null; // última análise automática: { mediaId, shirt, suggestions }

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

function enterEditor(data) {
  mediaId = data.media_id;
  clips = [];
  pendingStart = null;
  pendingMarkTarget = null;
  markingMode = "clip";
  analysisPeriods = [];
  autoResult = null;
  setStatus($("#auto-status"), "", "");
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

function renderClips() {
  const list = $("#clips-list");
  list.replaceChildren();
  $("#clip-count").textContent = clips.length;
  $("#empty-clips").classList.toggle("hidden", clips.length > 0);
  clips.forEach((clip, index) => {
    const item = document.createElement("li");
    item.className = "clip-item";
    const play = document.createElement("button");
    play.className = "clip-play";
    play.textContent = "▶";
    play.title = "Reproduzir este intervalo";
    play.addEventListener("click", () => {
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
    const remove = document.createElement("button");
    remove.className = "clip-remove";
    remove.textContent = "Remover";
    remove.addEventListener("click", () => {
      clips.splice(index, 1);
      renderClips();
    });
    item.append(play, label, tag, time, remove);
    list.append(item);
  });
  $("#export-button").disabled = clips.length === 0 || busy;
}

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
  if (!mediaId || isShortcutInput(event.target)) return;
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
  const button = $("#auto-button");
  const status = $("#auto-status");
  const analyzed = mediaId;
  const shirt = $("#auto-shirt").value;
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
      autoResult.shirt !== shirt ||
      autoResult.periodsKey !== periodsKey
    ) {
      setStatus(status, "Iniciando a análise…", "working");
      const { job_id } = await readError(
        await fetch("/api/suggest", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ media_id: analyzed, shirt, periods }),
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
        shirt,
        periodsKey,
        suggestions: job.suggestions,
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
    if (added) {
      setStatus(
        status,
        `${added} ${name} sugerido(s) e adicionado(s) à lista. Confira cada um no ▶ antes de exportar.`,
        "success",
      );
    } else if (found) {
      setStatus(
        status,
        `Os ${found} ${name} encontrado(s) já estão na lista.`,
        "success",
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
$("#auto-shirt").addEventListener("change", (event) => event.target.blur());
$("#auto-kind").addEventListener("change", (event) => event.target.blur());

$("#change-video").addEventListener("click", () => {
  player.pause();
  player.removeAttribute("src");
  player.load();
  mediaId = null;
  clips = [];
  resetPendingMark();
  markingMode = "clip";
  analysisPeriods = [];
  autoResult = null;
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
