import { FormEvent, ReactNode, useEffect, useState } from "react";
import { Account, Session, accountApi, apiHeaders, applySession } from "./session";

export function AccountGate({ children }: { children: (session: Session) => ReactNode }) {
  const [session, setSession] = useState<Session | null>();
  const [initialized, setInitialized] = useState(true);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function load() {
    setError("");
    try {
      const configResponse = await fetch("/api/v1/auth/config", { headers: apiHeaders });
      // An already-running M1–M4 server may still serve the rebuilt frontend.
      // Only a verified legacy local project response permits this transition.
      if (configResponse.status === 404) {
        const legacy = await fetch("/api/v1/projects", { headers: { "X-Organization-Id": "org-local" } });
        if (!legacy.ok) throw new Error("后台版本未更新，请重启工作台服务");
        const value: Session = { mode: "local" };
        applySession(value); setSession(value); return;
      }
      if (!configResponse.ok) throw new Error("无法读取服务模式，请重试");
      const config = await configResponse.json() as { mode: "local" | "accounts"; initialized: boolean };
      setInitialized(config.initialized);
      if (config.mode === "local") {
        const value: Session = { mode: "local" };
        applySession(value); setSession(value); return;
      }
      const response = await fetch("/api/v1/auth/session");
      if (response.status === 401) { applySession(null); setSession(null); return; }
      if (!response.ok) throw new Error("无法读取登录状态，请重试");
      const value = await response.json() as Session;
      applySession(value); setSession(value);
    } catch (problem) { setError(problem instanceof Error ? problem.message : "无法连接工作台"); }
  }
  useEffect(() => {
    void load();
    const expired = () => { applySession(null); setSession(null); setError("登录已失效，请重新登录"); };
    window.addEventListener("rkd-session-expired", expired);
    return () => window.removeEventListener("rkd-session-expired", expired);
  }, []);
  async function login(event: FormEvent) {
    event.preventDefault(); setBusy(true); setError("");
    try {
      const value = await accountApi<Session>("/api/v1/auth/login", "POST", { username, password });
      setPassword(""); applySession(value); setSession(value);
    } catch (problem) { setError(problem instanceof Error ? problem.message : "登录失败"); }
    finally { setBusy(false); }
  }
  if (session) return children(session);
  return <main className="account-entry">
    <div className="account-entry-brand">RKD AI 工作台</div>
    <section className="account-entry-content">
      <h1>{session === undefined ? "连接工作台" : "登录工作台"}</h1>
      <p>使用个人账号访问已分配的项目。当前为本机账号试用，正式发布尚未开放。</p>
      {error && <p className="account-error" role="alert">{error}</p>}
      {session === undefined ? <button className="dark-action" onClick={() => void load()}>重新连接</button> : initialized ? <form className="account-form" onSubmit={login}>
        <label>登录账号<input name="username" autoComplete="username" required maxLength={64} value={username} onChange={e => setUsername(e.target.value)} autoFocus /></label>
        <label>登录密码<input name="password" type="password" autoComplete="current-password" required maxLength={128} value={password} onChange={e => setPassword(e.target.value)} /></label>
        <button className="dark-action" disabled={busy}>{busy ? "正在登录…" : "登录"}</button>
      </form> : <p>请先在本机运行 <code>scripts/rkd.ps1 start-secure</code> 设置管理员账号和密码。</p>}
    </section>
  </main>;
}

export function AccountControls({ session }: { session: Session }) {
  const [error, setError] = useState("");
  if (session.mode === "local") return null;
  async function logout() {
    try { await accountApi("/api/v1/auth/logout", "POST", {}); window.location.reload(); }
    catch (problem) { setError(problem instanceof Error ? problem.message : "退出失败，请重试"); }
  }
  return <div className="account-controls"><span>{session.user?.display_name}</span><button onClick={() => void logout()}>退出登录</button>{error && <span role="alert">{error}</span>}</div>;
}

type Member = { user_id: string; display_name: string; username: string; role: string; active: number };
const roleNames: Record<string, string> = { manager: "项目负责人", editor: "项目编辑", viewer: "只读成员", none: "撤销访问" };

export function AccountPanel({ projectId }: { projectId?: string }) {
  const [users, setUsers] = useState<Account[]>([]);
  const [members, setMembers] = useState<Member[]>([]);
  const [draft, setDraft] = useState({ username: "", display_name: "", password: "" });
  const [userId, setUserId] = useState("");
  const [role, setRole] = useState("viewer");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function load() {
    const accounts = await accountApi<{ items: Account[] }>("/api/v1/auth/users");
    const membership = projectId ? await accountApi<{ items: Member[] }>(`/api/v1/projects/${projectId}/members`) : { items: [] };
    setUsers(accounts.items); setMembers(membership.items);
  }
  useEffect(() => { void load().catch(e => setError(e.message)); }, [projectId]);
  async function perform(action: () => Promise<unknown>, success: string) {
    setBusy(true); setError(""); setMessage("");
    try { await action(); await load(); setMessage(success); }
    catch (problem) { setError(problem instanceof Error ? problem.message : "保存失败"); }
    finally { setBusy(false); }
  }
  function create(event: FormEvent) {
    event.preventDefault();
    void perform(async () => {
      await accountApi("/api/v1/auth/users", "POST", draft);
      setDraft({ username: "", display_name: "", password: "" });
    }, "账号已创建，请分配项目角色后使用");
  }
  function assign(event: FormEvent) {
    event.preventDefault();
    void perform(() => accountApi(`/api/v1/projects/${projectId}/members`, "POST", { user_id: userId, role }), "项目权限已更新，现有登录会话即时生效");
  }
  return <section className="account-workspace">
    <h2>账号与项目成员</h2>
    <p>管理员可管理本组织全部项目和账号。其他账号只可访问已分配项目；负责人可记录本地验收，编辑可修改草稿，只读成员可查看和下载。上述角色均不授予正式发布权限。</p>
    {message && <p className="account-message" role="status">{message}</p>}
    {error && <p className="account-error" role="alert">{error}</p>}
    <h3>创建个人账号</h3>
    <form className="account-form account-form-wide" onSubmit={create}>
      <label>新账号<input required minLength={3} maxLength={64} pattern="[a-z0-9][a-z0-9_.\-]{2,63}" autoComplete="off" value={draft.username} onChange={e => setDraft({ ...draft, username: e.target.value })} /></label>
      <label>显示姓名<input required maxLength={100} autoComplete="off" value={draft.display_name} onChange={e => setDraft({ ...draft, display_name: e.target.value })} /></label>
      <label>初始密码<input type="password" required minLength={15} maxLength={128} autoComplete="new-password" aria-describedby="account-password-help" value={draft.password} onChange={e => setDraft({ ...draft, password: e.target.value })} /></label>
      <p id="account-password-help">密码为 15–128 个字符，可以使用便于记忆的长句。</p>
      <button className="dark-action" disabled={busy}>创建账号</button>
    </form>
    <h3>当前项目访问权限</h3>
    {projectId ? <><form className="account-form account-form-wide" onSubmit={assign}>
      <label>分配账号<select aria-label="分配账号" required value={userId} onChange={e => setUserId(e.target.value)}><option value="">选择个人账号</option>{users.filter(u => !u.is_admin && u.active).map(u => <option key={u.user_id} value={u.user_id}>{u.display_name}（{u.username}）</option>)}</select></label>
      <label>项目角色<select aria-label="项目角色" value={role} onChange={e => setRole(e.target.value)}>{Object.entries(roleNames).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
      <button className="dark-action" disabled={busy || !userId}>保存项目权限</button>
    </form><ul className="account-member-list">{members.map(m => <li key={m.user_id}><strong>{m.display_name}</strong><span>{roleNames[m.role]}{m.active ? "" : " · 已停用"}</span></li>)}</ul>{members.length === 0 && <p>尚未分配普通成员。管理员仍可管理此项目。</p>}</> : <p>请先选择或创建一个项目。</p>}
    <h3>账号状态</h3>
    <ul className="account-member-list">{users.map(u => <li key={u.user_id}><strong>{u.display_name}（{u.username}）</strong><span>{u.is_admin ? "管理员" : u.active ? "启用" : "停用"}</span>{!u.is_admin && <button className="account-secondary" disabled={busy} onClick={() => void perform(() => accountApi(`/api/v1/auth/users/${u.user_id}`, "PATCH", { active: !u.active }), u.active ? "账号已停用，登录会话已撤销" : "账号已恢复，请重新登录")}>{u.active ? "停用账号" : "恢复账号"}</button>}</li>)}</ul>
  </section>;
}
