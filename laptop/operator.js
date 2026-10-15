// The operator page: shows the camera with the plan drawn on it, lets the person tap the
// survivor, approve the plan, stop the rover, and read the report. All work is done by
// server.py; this page only asks and shows. Text is always set with textContent.
(() => {
  const $ = (id) => document.getElementById(id);
  const video = $("video");
  const mark = $("tap-mark");
  const statusLine = $("status");
  const headline = $("headline");
  const approve = $("approve");
  const stop = $("stop");
  const again = $("again");
  const clearTap = $("clear-tap");
  const steps = $("steps");
  const kept = $("kept");
  const bar = $("progress-bar");
  const progressText = $("progress-text");
  const report = $("report");
  const reportText = $("report-text");

  const WARN_PHASES = ["blocked", "aborted", "need_survivor"];
  const BUSY_PHASES = ["waiting", "running", "verifying"];
  const HEADLINES = {
    scanning: "Looking at the scene.",
    need_survivor: "Find the survivor.",
    plan_ready: "Check the plan, then approve it.",
    blocked: "There is no safe way through.",
    clear: "The way is already clear.",
    waiting: "Waiting for the rover.",
    running: "The rover is clearing the way.",
    verifying: "Checking the result.",
    aborted: "The run was stopped.",
  };
  const END_PHASES = ["done", "aborted"];

  let current = null;
  let reportShown = false;

  function setStatus(text, tone) {
    statusLine.textContent = text;
    statusLine.dataset.tone = tone || "";
  }

  function row(left, right, rightClass) {
    const li = document.createElement("li");
    const a = document.createElement("span");
    const b = document.createElement("span");
    a.textContent = left;
    b.textContent = right;
    b.className = rightClass;
    li.append(a, b);
    return li;
  }

  function fill(list, rows, emptyText, build) {
    list.replaceChildren();
    if (!rows.length) {
      const li = document.createElement("li");
      li.textContent = emptyText;
      li.className = "empty";
      list.append(li);
      return;
    }
    rows.forEach((r) => list.append(build(r)));
  }

  function drawMark(state) {
    if (!state.survivor_px) { mark.hidden = true; return; }
    const scale = video.getBoundingClientRect().width / state.frame.w;
    mark.style.left = `${state.survivor_px[0] * scale}px`;
    mark.style.top = `${state.survivor_px[1] * scale}px`;
    mark.hidden = false;
  }

  function render(state) {
    current = state;
    const warn = WARN_PHASES.includes(state.phase) || !state.link_up || state.camera_error || state.verified === false;
    setStatus(state.camera_error || state.message, state.verified === true ? "ok" : (warn ? "warn" : ""));
    headline.textContent = state.phase === "done"
      ? (state.verified ? "The way is clear." : "The rover finished, but it is not confirmed.")
      : (HEADLINES[state.phase] || HEADLINES.scanning);

    const plan = state.plan;
    fill(steps, plan ? plan.order : [], "No blocks need to move yet.", (p) =>
      row(`${p.n}. block_${p.id}`, `${Math.round(p.x)}, ${Math.round(p.y)} mm`, "where"));
    fill(kept, plan ? plan.left : [], "Nothing is being left in place.", (k) =>
      row(`block_${k.id}`, k.reason, "why"));

    const busy = BUSY_PHASES.includes(state.phase);
    const finished = END_PHASES.includes(state.phase);
    approve.disabled = !state.can_approve;
    stop.disabled = !busy;
    again.hidden = !finished;
    clearTap.hidden = !state.survivor_px || busy || finished;
    video.style.cursor = busy || finished ? "default" : "crosshair";

    const { done, total } = state.progress;
    bar.style.width = total ? `${Math.round((100 * done) / total)}%` : "0";
    progressText.textContent = total ? `${done} of ${total} steps done` : "";

    drawMark(state);
    if (finished && !reportShown) loadReport();
    if (!finished) { report.hidden = true; reportShown = false; }
  }

  async function call(path, method, body) {
    const response = await fetch(path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    });
    if (!response.ok) {
      let detail = `The server said ${response.status}.`;
      try { detail = (await response.json()).detail || detail; } catch (_) { /* keep the default */ }
      throw new Error(detail);
    }
    return response.json();
  }

  async function refresh() {
    try {
      render(await call("/api/state", "GET"));
    } catch (_) {
      setStatus("Not connected. Start the server with: python server.py", "warn");
      approve.disabled = true;
      stop.disabled = true;
    }
  }

  async function loadReport() {
    try {
      const body = await call("/api/report", "GET");
      reportText.textContent = body.text;
      report.hidden = false;
      reportShown = true;
    } catch (_) { /* the next poll tries again */ }
  }

  async function act(path, body) {
    try {
      await call(path, "POST", body);
    } catch (error) {
      setStatus(error.message, "warn");
      return;
    }
    refresh();
  }

  video.addEventListener("click", (event) => {
    if (!current || BUSY_PHASES.includes(current.phase) || END_PHASES.includes(current.phase)) return;
    const rect = video.getBoundingClientRect();
    act("/api/survivor", {
      x: ((event.clientX - rect.left) * current.frame.w) / rect.width,
      y: ((event.clientY - rect.top) * current.frame.h) / rect.height,
    });
  });
  approve.addEventListener("click", () => current && current.plan && act("/api/approve", { key: current.plan.key }));
  stop.addEventListener("click", () => act("/api/abort"));
  again.addEventListener("click", () => act("/api/reset"));
  clearTap.addEventListener("click", () => act("/api/survivor/clear"));

  refresh();
  setInterval(refresh, 500);
})();
