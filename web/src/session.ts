export type Account = { user_id: string; username: string; display_name: string; is_admin: boolean | number; active: boolean | number };
export type Session = { mode: "local" | "accounts"; user?: Account; csrf_token?: string };

// Session token lives only in an HttpOnly cookie. CSRF tokens live in memory.
export const apiHeaders: Record<string, string> = { "X-Organization-Id": "org-local" };
export function applySession(session: Session | null) {
  for (const key of Object.keys(apiHeaders)) delete apiHeaders[key];
  if (session?.mode === "local") apiHeaders["X-Organization-Id"] = "org-local";
  if (session?.csrf_token) apiHeaders["X-CSRF-Token"] = session.csrf_token;
}

export function checkSessionResponse(response: Response) {
  if (response.status === 401) window.dispatchEvent(new Event("rkd-session-expired"));
}

export async function accountApi<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(path, { method, headers: { ...apiHeaders, "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  checkSessionResponse(response);
  const result = await response.json();
  if (!response.ok) throw new Error(result.message ?? `请求失败 (${response.status})`);
  return result;
}
