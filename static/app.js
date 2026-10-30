const $ = (id) => document.getElementById(id);

const state = {
  demo: false,
  connected: false,
  recording: false,
  hrShown: 0,
  waves: { eeg: [], ppg: [], temp: [], phase: 0 },
  history: [],
};

const BAND_COLORS = {
  Delta: ["#7aa2ff", "b-delta"],
  Theta: ["#8b7cff", "b-theta"],
  Alpha: ["#5ce1c5", "b-alpha"],
  Beta: ["#f5c15c", "b-beta"],
  Gamma: ["#ff8aa0", "b-gamma"],
};

function drawWave(canvas, data, color, fill) {
  if (!canvas || !data || !data.length) return;
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  const min = Math.min(...data);
  const max = Math.max(...data);
  const span = max - min || 1;
  ctx.beginPath();
  data.forEach((v, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - ((v - min) / span) * (h * 0.82) - h * 0.09;
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.shadowColor = color;
  ctx.shadowBlur = 8;
  ctx.stroke();
  if (fill) {
    ctx.lineTo(w, h);
    ctx.lineTo(0, h);
    ctx.closePath();
    ctx.shadowBlur = 0;
    ctx.fillStyle = fill;
    ctx.fill();
  }
}

function drawHistory(canvas, hist) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  ctx.clearRect(0, 0, w, h);
  ctx.strokeStyle = "rgba(140,180,220,0.12)";
  ctx.lineWidth = 1;
  for (let y = 0; y <= 4; y++) {
    const yy = 12 + ((h - 24) * y) / 4;
    ctx.beginPath();
    ctx.moveTo(0, yy);
    ctx.lineTo(w, yy);
    ctx.stroke();
  }
  if (!hist || hist.length < 2) return;
  const series = [
    ["vigilance", "#5ce1c5"],
    ["attention", "#f5c15c"],
    ["mood", "#7aa2ff"],
    ["autonomic", "#ff8aa0"],
  ];
  const n = hist.length;
  series.forEach(([key, color]) => {
    ctx.beginPath();
    let started = false;
    hist.forEach((p, i) => {
      const v = p[key];
      if (v == null) return;
      const x = (i / Math.max(n - 1, 1)) * w;
      const y = h - 12 - (v / 100) * (h - 24);
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else ctx.lineTo(x, y);
    });
    if (!started) return;
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.shadowColor = color;
    ctx.shadowBlur = 6;
    ctx.stroke();
  });
}

function setText(id, value) {
  const el = $(id);
  if (el) el.textContent = value;
}

function banner(text, bad) {
  const el = $("banner");
  if (!text) {
    el.classList.add("hidden");
    return;
  }
  el.classList.remove("hidden");
  el.classList.toggle("bad", !!bad);
  el.textContent = text;
}

async function defFetch(url, body) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  return res.json().catch(() => ({}));
}

async function loadPorts() {
  const res = await fetch("/api/ports");
  const data = await res.json();
  const sel = $("port");
  const current = sel.value;
  sel.innerHTML = "";
  const ports = data.ports || [];
  if (!ports.length) {
    const o = document.createElement("option");
    o.value = "";
    o.textContent = "No ports found";
    sel.appendChild(o);
    return;
  }
  ports.forEach((p) => {
    const o = document.createElement("option");
    o.value = p.device;
    o.textContent = p.likely ? `${p.name} (likely board)` : p.name;
    sel.appendChild(o);
  });
  const prefer = ports.find((p) => p.likely) || ports[0];
  sel.value = ports.some((p) => p.device === current) ? current : prefer.device;
}

function renderBands(bands) {
  const root = $("bands");
  if (!bands || !bands.length) return;
  if (!root.childElementCount) {
    bands.forEach((b) => {
      const wrap = document.createElement("div");
      wrap.className = `band ${BAND_COLORS[b.name] ? BAND_COLORS[b.name][1] : ""}`;
      wrap.innerHTML = `<div class="bar-track"><div class="bar-fill" data-name="${b.name}"></div></div>
        <div class="name">${b.name}</div><div class="hz">${b.range}</div>`;
      root.appendChild(wrap);
    });
  }
  bands.forEach((b) => {
    const fill = root.querySelector(`[data-name="${b.name}"]`);
    if (fill) fill.style.height = `${Math.round((b.level || 0) * 100)}%`;
  });
}

function applyLive(msg) {
  const live = msg.live || {};
  const hr = live.heart_rate;
  if (typeof hr === "number") {
    state.hrShown += (hr - state.hrShown) * 0.35;
    setText("hr", String(Math.round(state.hrShown)));
    const period = Math.max(0.38, 60 / hr);
    $("heart").style.animationDuration = `${period}s`;
  } else {
    setText("hr", "--");
  }
  setText("hrNote", live.heart_note || "");

  if (typeof live.temperature_c === "number") {
    setText("temp", live.temperature_c.toFixed(2));
  } else setText("temp", "--");

  renderBands(live.eeg_bands);
  if (live.eeg_wave) state.waves.eeg = live.eeg_wave;
  if (live.ppg_wave) state.waves.ppg = live.ppg_wave;
  if (live.temperature_trend) state.waves.temp = live.temperature_trend;

  const moving = live.motion && live.motion.moving;
  $("orb").classList.toggle("moving", !!moving);
  setText("motionLabel", moving ? "Moving" : "Still");

  const q = msg.quality || {};
  const bits = [];
  if (q.motion_warning) bits.push(q.motion_warning);
  if (q.message) bits.push(q.message);
  const link = msg.link || {};
  if (link.error) bits.push(link.error);
  banner(bits.join(" - "), !!(q.message && String(q.message).toLowerCase().includes("low confidence")) || !!link.error);

  const vig = (msg.results || {}).vigilance || {};
  const card = document.querySelector('[data-key="vigilance"]');
  card.classList.remove("green", "yellow", "red");
  if (vig.color) card.classList.add(vig.color);
  setText("vigScore", vig.score == null ? "--" : String(vig.score));
  const pill = $("vigColor");
  pill.className = `pill ${vig.color || "gray"}`;
  pill.textContent = vig.color === "green" ? "Alert" : vig.color === "yellow" ? "Fading" : vig.color === "red" ? "Sleepy" : "-";
  setText("vigMeaning", vig.meaning || "");
  setText("vigTip", vig.tip ? `What does this mean for me? ${vig.tip}` : "");
  setText("vigConf", vig.confidence ? `Confidence: ${vig.confidence}` : "");

  const att = (msg.results || {}).attention || {};
  const words = { rising: "Rising", steady: "Steady", dipping: "Dipping" };
  setText("attTrend", words[att.trend] || att.trend || "-");
  setText("attLabel", att.label || "");
  setText("attTip", att.tip ? `What does this mean for me? ${att.tip}` : "");
  setText("attNote", att.note || "");
  setText("attConf", att.confidence ? `Confidence: ${att.confidence}` : "");

  const mood = (msg.results || {}).mood || {};
  $("moodGauge").querySelector(".gauge-track").classList.toggle("off", mood.available === false);
  setText("moodMsg", mood.message || mood.meaning || "");
  setText("moodTip", mood.detail || mood.tip || "");
  setText("moodConf", mood.confidence ? `Confidence: ${mood.confidence}` : "");

  const auto = (msg.results || {}).autonomic || {};
  const waiting = !auto.ready;
  $("autoWait").classList.toggle("hidden", !waiting);
  $("autoReady").classList.toggle("hidden", waiting);
  if (waiting) {
    $("autoFill").style.width = `${Math.round((auto.progress || 0) * 100)}%`;
    setText("autoWaitMsg", auto.wait_message || "Collecting data...");
  } else {
    const leanWords = { calm: "Calm lean", stressed: "Stressed lean", balanced: "In the middle" };
    setText("autoLean", leanWords[auto.lean] || auto.lean || "-");
    setText("autoMeaning", auto.meaning || "");
    setText("autoAgree", auto.agreement || "");
  }
  setText("autoTip", auto.tip ? `What does this mean for me? ${auto.tip}` : "");
  setText("autoConf", auto.confidence ? `Confidence: ${auto.confidence}` : "");

  const cal = msg.calibration || {};
  const active = cal.phase === "eyes_closed" || cal.phase === "eyes_open";
  $("calPanel").classList.toggle("hidden", !active);
  if (active) {
    setText("calCount", String(cal.remaining_s ?? ""));
    setText("calPhase", cal.phase === "eyes_closed" ? "Eyes closed" : "Eyes open");
    setText("calPrompt", cal.prompt || "");
  }

  state.history = msg.history || state.history;
  state.recording = !!msg.recording;
  $("recBtn").classList.toggle("hot", state.recording);
  $("recBtn").textContent = state.recording ? "Stop recording" : "Record session";

  const demoOn = (link.mode || "") === "demo";
  state.demo = demoOn;
  $("demoBtn").classList.toggle("on", demoOn);
  $("demoBtn").textContent = demoOn ? "Demo Mode on" : "Demo Mode";
  state.connected = !!link.connected && link.mode === "serial";
  $("connectBtn").textContent = state.connected ? "Disconnect" : "Connect";
}

function connectWs() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = (ev) => {
    try {
      applyLive(JSON.parse(ev.data));
    } catch (err) {
      console.warn(err);
    }
  };
  ws.onclose = () => setTimeout(connectWs, 1200);
}

function tickWaves() {
  state.waves.phase += 1;
  const shift = (arr) => {
    if (!arr || arr.length < 4) return arr;
    const n = state.waves.phase % arr.length;
    return arr.slice(n).concat(arr.slice(0, n));
  };
  drawWave($("eegWave"), shift(state.waves.eeg), "#5ce1c5", "rgba(92,225,197,0.08)");
  drawWave($("ppgWave"), shift(state.waves.ppg), "#ff5d73", "rgba(255,93,115,0.10)");
  drawWave($("tempWave"), state.waves.temp, "#f5c15c", "rgba(245,193,92,0.08)");
  drawHistory($("history"), state.history);
  requestAnimationFrame(tickWaves);
}

$("refreshPorts").onclick = loadPorts;
$("connectBtn").onclick = async () => {
  if (state.connected) {
    await defFetch("/api/disconnect", {});
    return;
  }
  const port = $("port").value;
  if (!port) {
    banner("No COM port found. Plug in the board, then press ?.", true);
    return;
  }
  await defFetch("/api/demo", { enabled: false });
  await defFetch("/api/connect", { port });
};
$("demoBtn").onclick = async () => {
  await defFetch("/api/demo", { enabled: !state.demo });
};
$("calBtn").onclick = async () => {
  await defFetch("/api/calibrate", {});
};
$("recBtn").onclick = async () => {
  await defFetch("/api/record", { start: !state.recording });
};

loadPorts();
connectWs();
tickWaves();

if (new URLSearchParams(location.search).get("demo") === "1") {
  defFetch("/api/demo", { enabled: true });
}
