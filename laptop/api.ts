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

export interface State {
  phase: string;
  message: string;
  can_approve: boolean;
  survivor_px: [number, number] | null;
  plan: PlanView | null;
  progress: { done: number; total: number };
  link_up: boolean;
  verified: boolean | null;
  frame: { w: number; h: number };
  camera_error: string | null;
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
