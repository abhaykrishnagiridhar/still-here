// The control page: drive the rover and move its arm by hand. Hold a button (or W A S D, or the
// arrow keys) to drive. The page keeps sending the drive command while the button is held, and the
// server stops the wheels by itself if the commands stop. All work is done by server.py.
import { call } from "./api.js";
import type { Ack, State } from "./api.js";
import { BUSY_PHASES, clamp, driveFor, keyDirection } from "./ui_logic.js";
import type { Direction } from "./ui_logic.js";

const $ = <T extends HTMLElement>(id: string): T => {
  const element = document.getElementById(id);
  if (element === null) throw new Error(`The page is missing #${id}`);
  return element as T;
};

const SEND_EVERY_MS = 100; // how often a held button repeats its command
const POLL_EVERY_MS = 1000;
const ARM_SPEED = 0.6;
const HOME = { base: 0, shoulder: 60, elbow: -90, gripper: 90 };

const statusLine = $<HTMLElement>("status");
const speedInput = $<HTMLInputElement>("speed");
const speedOut = $<HTMLOutputElement>("speed-out");
const stopButton = $<HTMLButtonElement>("stop-now");
const gripButton = $<HTMLButtonElement>("grip");
const homeButton = $<HTMLButtonElement>("arm-home");
const sliders = {
  base: $<HTMLInputElement>("base"),
  shoulder: $<HTMLInputElement>("shoulder"),
  elbow: $<HTMLInputElement>("elbow"),
};
const padButtons = Array.from(document.querySelectorAll<HTMLButtonElement>("[data-dir]"));

let gripperOpen = true;
let held: Direction | null = null;
let timer: number | undefined;
let planRunning = false;

function say(text: string, warn = false): void {
  statusLine.textContent = text;
  statusLine.dataset.tone = warn ? "warn" : "";
}

async function send(path: string, body?: unknown): Promise<void> {
  try {
    await call<Ack>(path, "POST", body);
  } catch (error) {
    say(error instanceof Error ? error.message : "Something went wrong.", true);
    release();
  }
}

function speed(): number {
  return clamp(Number(speedInput.value) / 100, 0, 1);
}

function driveNow(): void {
  if (held !== null) void send("/api/manual/drive", driveFor(held, speed()));
}

function press(direction: Direction): void {
  if (planRunning || held === direction) return;
  release(false);
  held = direction;
  padButtons.forEach((b) => b.classList.toggle("held", b.dataset.dir === direction));
  driveNow();
  timer = window.setInterval(driveNow, SEND_EVERY_MS);
}

function release(tellRover = true): void {
  if (timer !== undefined) window.clearInterval(timer);
  timer = undefined;
  const wasHeld = held !== null;
  held = null;
  padButtons.forEach((b) => b.classList.remove("held"));
  if (tellRover && wasHeld) void send("/api/manual/stop");
}

function sendArm(): void {
  if (planRunning) return;
  void send("/api/manual/arm", {
    base: Number(sliders.base.value),
    shoulder: Number(sliders.shoulder.value),
    elbow: Number(sliders.elbow.value),
    gripper: gripperOpen ? 90 : 0,
    speed: ARM_SPEED,
  });
}

let armTimer: number | undefined;
function sendArmSoon(): void {
  window.clearTimeout(armTimer);
  armTimer = window.setTimeout(sendArm, SEND_EVERY_MS);
}

function showGrip(): void {
  gripButton.textContent = gripperOpen ? "Gripper: open" : "Gripper: closed";
  gripButton.setAttribute("aria-pressed", String(!gripperOpen));
}

function setControlsEnabled(enabled: boolean): void {
  [...padButtons, stopButton, gripButton, homeButton, speedInput, ...Object.values(sliders)].forEach((control) => {
    if (control !== stopButton) control.disabled = !enabled;
  });
}

async function poll(): Promise<void> {
  try {
    const state = await call<State>("/api/state", "GET");
    planRunning = BUSY_PHASES.includes(state.phase);
    setControlsEnabled(!planRunning);
    if (planRunning) {
      release(false);
      say("An approved plan is running, so manual control is off. Stop it on the autonomous page.", true);
    } else if (statusLine.dataset.tone === "warn" && statusLine.textContent?.includes("plan is running")) {
      say("Ready. Hold a button or W A S D to drive.");
    }
  } catch {
    say("Not connected. Start the server with: python server.py", true);
  }
}

padButtons.forEach((button) => {
  const direction = button.dataset.dir as Direction;
  button.addEventListener("pointerdown", (event: PointerEvent) => {
    button.setPointerCapture(event.pointerId);
    press(direction);
  });
  for (const type of ["pointerup", "pointercancel", "lostpointercapture"]) {
    button.addEventListener(type, () => release());
  }
  button.addEventListener("contextmenu", (event) => event.preventDefault());
});

window.addEventListener("keydown", (event: KeyboardEvent) => {
  if (event.repeat || event.target instanceof HTMLInputElement) return;
  if (event.key === " ") {
    event.preventDefault();
    release();
    void send("/api/manual/stop");
    return;
  }
  const direction = keyDirection(event.key);
  if (direction !== null) {
    event.preventDefault();
    press(direction);
  }
});
window.addEventListener("keyup", (event: KeyboardEvent) => {
  if (keyDirection(event.key) !== null && keyDirection(event.key) === held) release();
});
// Letting go of the page for any reason must stop the rover.
window.addEventListener("blur", () => release());
document.addEventListener("visibilitychange", () => {
  if (document.hidden) release();
});

speedInput.addEventListener("input", () => {
  speedOut.textContent = `${speedInput.value}%`;
});
stopButton.addEventListener("click", () => {
  release(false);
  void send("/api/manual/stop");
});
Object.values(sliders).forEach((slider) => slider.addEventListener("input", sendArmSoon));
gripButton.addEventListener("click", () => {
  gripperOpen = !gripperOpen;
  showGrip();
  sendArm();
});
homeButton.addEventListener("click", () => {
  sliders.base.value = String(HOME.base);
  sliders.shoulder.value = String(HOME.shoulder);
  sliders.elbow.value = String(HOME.elbow);
  gripperOpen = true;
  showGrip();
  sendArm();
});

showGrip();
speedOut.textContent = `${speedInput.value}%`;
say("Ready. Hold a button or W A S D to drive. Space stops.");
void poll();
setInterval(() => void poll(), POLL_EVERY_MS);
