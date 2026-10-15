// The operator page: shows the camera with the plan drawn on it, lets the person tap the
// survivor, approve the plan, stop the rover, and read the report. All work is done by
// server.py; this page only asks and shows. Text is always set with textContent.
import { call } from "./api.js";
import type { Ack, ReportBody, State } from "./api.js";
import { BUSY_PHASES, END_PHASES, headlineFor, roverNotice, toDisplay, toFrame, toneFor } from "./ui_logic.js";

const $ = <T extends HTMLElement>(id: string): T => {
  const element = document.getElementById(id);
  if (element === null) throw new Error(`The page is missing #${id}`);
  return element as T;
};

const video = $<HTMLImageElement>("video");
const mark = $<HTMLElement>("tap-mark");
const headline = $<HTMLElement>("headline");
const statusLine = $<HTMLElement>("status");
const approve = $<HTMLButtonElement>("approve");
const stop = $<HTMLButtonElement>("stop");
const again = $<HTMLButtonElement>("again");
const clearTap = $<HTMLButtonElement>("clear-tap");
const steps = $<HTMLElement>("steps");
const kept = $<HTMLElement>("kept");
const bar = $<HTMLElement>("progress-bar");
const progressText = $<HTMLElement>("progress-text");
const report = $<HTMLElement>("report");
const reportText = $<HTMLElement>("report-text");

let current: State | null = null;
let reportShown = false;

function setStatus(text: string, tone: string): void {
  statusLine.textContent = text;
  statusLine.dataset.tone = tone;
}

function row(left: string, right: string, rightClass: string): HTMLLIElement {
  const li = document.createElement("li");
  const a = document.createElement("span");
  const b = document.createElement("span");
  a.textContent = left;
  b.textContent = right;
  b.className = rightClass;
  li.append(a, b);
  return li;
}

function fill<T>(list: HTMLElement, rows: T[], emptyText: string, build: (item: T) => HTMLLIElement): void {
  list.replaceChildren();
  if (rows.length === 0) {
    const li = document.createElement("li");
    li.textContent = emptyText;
    li.className = "empty";
    list.append(li);
    return;
  }
  rows.forEach((item) => list.append(build(item)));
}

function drawMark(state: State): void {
  if (state.survivor_px === null) {
    mark.hidden = true;
    return;
  }
  const spot = toDisplay(state.survivor_px, video.getBoundingClientRect().width, state.frame.w);
  mark.style.left = `${spot.left}px`;
  mark.style.top = `${spot.top}px`;
  mark.hidden = false;
}

function render(state: State): void {
  current = state;
  const notice = roverNotice(state.rover_connected, state.rover_address, state.rover_error);
  const tone = notice !== null ? "warn" : toneFor(state.phase, state.link_up, state.verified, state.camera_error);
  setStatus(notice ?? state.camera_error ?? state.message, tone);
  headline.textContent = headlineFor(state.phase, state.verified);

  const plan = state.plan;
  fill(steps, plan ? plan.order : [], "No blocks need to move yet.", (p) =>
    row(`${p.n}. block_${p.id}`, `${Math.round(p.x)}, ${Math.round(p.y)} mm`, "where"));
  fill(kept, plan ? plan.left : [], "Nothing is being left in place.", (k) => row(`block_${k.id}`, k.reason, "why"));

  const busy = BUSY_PHASES.includes(state.phase);
  const finished = END_PHASES.includes(state.phase);
  approve.disabled = !state.can_approve || !state.rover_connected;
  stop.disabled = !busy;
  again.hidden = !finished;
  clearTap.hidden = state.survivor_px === null || busy || finished;
  video.style.cursor = busy || finished ? "default" : "crosshair";

  const { done, total } = state.progress;
  bar.style.width = total ? `${Math.round((100 * done) / total)}%` : "0";
  progressText.textContent = total ? `${done} of ${total} steps done` : "";

  drawMark(state);
  if (finished && !reportShown) void loadReport();
  if (!finished) {
    report.hidden = true;
    reportShown = false;
  }
}

async function refresh(): Promise<void> {
  try {
    render(await call<State>("/api/state", "GET"));
  } catch {
    setStatus("Not connected. Start the server with: python server.py", "warn");
    approve.disabled = true;
    stop.disabled = true;
  }
}

async function loadReport(): Promise<void> {
  try {
    const body = await call<ReportBody>("/api/report", "GET");
    reportText.textContent = body.text;
    report.hidden = false;
    reportShown = true;
  } catch {
    // the next poll tries again
  }
}

async function act(path: string, body?: unknown): Promise<void> {
  try {
    await call<Ack>(path, "POST", body);
  } catch (error) {
    setStatus(error instanceof Error ? error.message : "Something went wrong.", "warn");
    return;
  }
  void refresh();
}

video.addEventListener("click", (event: MouseEvent) => {
  if (current === null || BUSY_PHASES.includes(current.phase) || END_PHASES.includes(current.phase)) return;
  const spot = toFrame(event.clientX, event.clientY, video.getBoundingClientRect(), current.frame);
  void act("/api/survivor", spot);
});
approve.addEventListener("click", () => {
  if (current !== null && current.plan !== null) void act("/api/approve", { key: current.plan.key });
});
stop.addEventListener("click", () => void act("/api/abort"));
again.addEventListener("click", () => void act("/api/reset"));
clearTap.addEventListener("click", () => void act("/api/survivor/clear"));

void refresh();
setInterval(() => void refresh(), 500);
