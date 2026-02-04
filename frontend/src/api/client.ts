import { useAuth } from "../store/auth";

export const API_BASE = "";

type Json = Record<string, unknown> | unknown[] | string | number | boolean | null;

function getAuthHeader(): string {
  const token = useAuth.getState().token;
  if (token) {
    return `Bearer ${token}`;
  }
  return "";
}

export async function http<T = any>(
  path: string,
  init?: RequestInit & { json?: Json; timeoutMs?: number }
): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), init?.timeoutMs ?? 30_000);

  const isFormData = init?.body instanceof FormData;

  const headers: HeadersInit = {
    ...(isFormData ? {} : { "Content-Type": "application/json" }),
    "Authorization": getAuthHeader(),
    ...(init?.headers ?? {}),
  };

  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
    body: init?.json !== undefined ? JSON.stringify(init.json) : init?.body,
    signal: controller.signal,
  }).finally(() => clearTimeout(timeout));

  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`HTTP ${res.status} ${res.statusText}: ${text}`);
  }
  const ct = res.headers.get("content-type") || "";
  if (ct.includes("application/json")) return (await res.json()) as T;
  return (await res.text()) as T;
}

export async function streamSSE(
  path: string,
  body: any,
  onEvent: (dataLine: string) => void
) {
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Authorization": getAuthHeader(),
    },
    body: JSON.stringify(body),
  });

  if (!res.ok || !res.body) {
    throw new Error(`SSE failed: ${res.status} ${res.statusText}`);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const parts = buffer.split("\n\n");
    buffer = parts.pop() ?? "";

    for (const p of parts) {
      const lines = p.split("\n");
      for (const line of lines) {
        if (line.startsWith("data:")) {
          onEvent(line.slice(5).trim());
        }
      }
    }
  }
}