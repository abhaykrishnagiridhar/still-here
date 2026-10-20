// What the server sends back, and one function to ask it things. Shared by the operator page and
// the control page. The shapes match operator_core.py and server.py.

export interface PlanStepView {
  n: number;
  id: number;
  x: number;
  y: number;
}

export interface LeftView {
  id: number;
  reason: string;
}

export interface PlanView {
  key: string;
  ok: boolean;
  note: string;
  order: PlanStepView[];
  left: LeftView[];
  path: [number, number][];
}

// One finished run of autonomous mode (autopilot.py).
export interface EpisodeView {
  number: number;
  moved: number;
  outcome: string; // "clean", "bumped" or "unverified"
  brushed: string | null;
  corridor_mm: number;
  next_corridor_mm: number;
}

export interface AutopilotView {
  active: boolean;
  episode: number;
  episodes: number;
  message: string;
  corridor_mm: number;
  extra_mm: number;
  history: EpisodeView[];
}

export interface State {
  phase: string;
  message: string;
  can_approve: boolean;
  survivor_px: [number, number] | null;
  plan: PlanView | null;
  progress: { done: number; total: number };
  link_up: boolean;
  verified: boolean | null;
  notice: string | null;
  learned: string | null;
  frame: { w: number; h: number };
  camera_error: string | null;
  rover_connected: boolean;
  rover_address: string;
  rover_error: string;
  autopilot: AutopilotView | null; // null unless the server was started with --auto
}

export interface ReportBody {
  text: string;
}

export interface Ack {
  ok: boolean;
  message?: string;
}

// Ask the server. A refusal comes back as an Error carrying the server's own explanation.
export async function call<T>(path: string, method: "GET" | "POST", body?: unknown): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = `The server said ${response.status}.`;
    try {
      const parsed = (await response.json()) as { detail?: unknown };
      if (typeof parsed.detail === "string") detail = parsed.detail;
    } catch {
      // keep the plain status message
    }
    throw new Error(detail);
  }
  return (await response.json()) as T;
}
