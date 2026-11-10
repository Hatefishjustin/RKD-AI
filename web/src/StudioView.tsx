import { useEffect, useMemo, useRef, useState } from "react";
import "./studio.css";

const API = "http://127.0.0.1:8099";

type Role = { id: string; name: string; title: string; initial: string; color: string };
type Message = {
  id: number; role: string; kind: string; body: string;
  evidence: Array<Record<string, unknown>>; tokens_in: number; tokens_out: number;
  model?: string | null; created_at: string;
};
type Artifact = {
  id: string; kind: string; option_id?: string | null; revision: number;
  parent_revision?: number | null; author: string; sha256: string; status: string;
  payload?: any; svg_url?: string;
};
type Gate = { id: string; title: string; detail: string; status: string; decision?: string | null; comment?: string | null };
type State = {
  project: { id: string; name: string; site: any; requirement: any };
  messages: Message[]; artifacts: Artifact[]; gates: Gate[];
  reviews: Array<{ id: string; verdict: string; summary: string; issues: any[] }>;
  usage: { tokens_in: number; tokens_out: number; tokens_total: number };
  roster: Role[];
  channel: { configured: boolean; model: string; run_limit: number; project_limit: number };
  running: boolean;
};

const KIND_LABEL: Record<string, string> = {
  task: "派活", say: "发言", discussion: "讨论", artifact: "交付", review: "评审",
  revise: "修订", gate: "闸口", note: "记录", tool: "工具", boss: "老板", decision: "决定",
};

export function StudioView({ projectId }: { projectId?: string }) {
  const [state, setState] = useState<State | null>(null);
  const [error, setError] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState("");
  const [gateComment, setGateComment] = useState<Record<string, string>>({});
  const [openEvidence, setOpenEvidence] = useState<number | null>(null);
  const timer = useRef<number | null>(null);

  const studioId = projectId === "ningbo-xiecheng" ? "ningbo-xiecheng" : "ningbo-xiecheng";

  async function load() {
    try {
      const res = await fetch(`${API}/studio/projects/${studioId}/state`, { cache: "no-store" });
      if (!res.ok) throw new Error(`状态读取失败 ${res.status}`);
      setState(await res.json());
      setError("");
    } catch (e) {
      setError((e as Error).message + "（Studio 服务未启动？运行 python -m rkd_mvp.studio.server）");
    }
  }

  useEffect(() => {
    void load();
    timer.current = window.setInterval(() => { void load(); }, 2500);
    return () => { if (timer.current) window.clearInterval(timer.current); };
  }, [studioId]);

  const lastByRole = useMemo(() => {
    const map: Record<string, Message> = {};
    for (const m of state?.messages ?? []) map[m.role] = m;
    return map;
  }, [state]);

  async function run() {
    setBusy(true);
    try {
      const res = await fetch(`${API}/studio/projects/${studioId}/run`, { method: "POST" });
      const body = await res.json();
      if (!res.ok) setError(body.error || "启动失败");
      else void load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function send() {
    if (!draft.trim()) return;
    await fetch(`${API}/studio/projects/${studioId}/messages`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: draft.trim() }),
    });
    setDraft("");
    void load();
  }

  async function decide(gate: Gate, decision: "approve" | "reject") {
    const comment = gateComment[gate.id] || "";
    if (decision === "reject" && !comment.trim()) { setError("驳回必须写理由"); return; }
    await fetch(`${API}/studio/gates/${gate.id}/decide`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, comment }),
    });
    void load();
  }

  if (!state) {
    return <section className="studio"><p className="studio-empty">{error || "正在连接设计公司…"}</p></section>;
  }

  const waitingGate = state.gates.find((g) => g.status === "waiting");
  const plans = state.artifacts.filter((a) => a.kind === "spatial-plan");
  const sketches = state.artifacts.filter((a) => a.kind === "plan-sketch");

  return (
    <section className="studio">
      <header className="studio-top">
        <div>
          <span className="studio-eyebrow">RKD 设计公司 · 项目工作台</span>
          <h2>{state.project.name}</h2>
        </div>
        <div className="studio-status">
          <span className={state.channel.configured ? "chip ok" : "chip warn"}>
            {state.channel.configured ? `通道 ${state.channel.model}` : "通道未配置（无密钥）"}
          </span>
          <span className="chip">本轮 {state.usage.tokens_total.toLocaleString()} tokens</span>
          <span className="chip">上限 {(state.channel.run_limit / 1000).toFixed(0)}k / 回路</span>
          <button className="studio-run" onClick={() => void run()} disabled={busy || state.running}>
            {state.running ? "正在开会…" : "开一轮（A1）"}
          </button>
        </div>
      </header>

      {error && <p className="studio-error" role="alert">{error}</p>}

      <div className="studio-grid">
        <aside className="studio-roster">
          <h3>花名册</h3>
          {state.roster.map((r) => {
            const last = lastByRole[r.id];
            return (
              <div className="roster-row" key={r.id}>
                <span className="avatar" style={{ background: r.color }}>{r.initial}</span>
                <div>
                  <strong>{r.name}</strong>
                  <small>{r.title}</small>
                  <em>{last ? `${KIND_LABEL[last.kind] || last.kind} · ${relTime(last.created_at)}` : "待命"}</em>
                </div>
              </div>
            );
          })}
        </aside>

        <div className="studio-timeline">
          <h3>时间线</h3>
          {waitingGate && (
            <div className="gate-card">
              <strong>等你决定：{waitingGate.title}</strong>
              <pre>{waitingGate.detail}</pre>
              <textarea placeholder="驳回必须写理由（会进规范库候选）"
                value={gateComment[waitingGate.id] || ""}
                onChange={(e) => setGateComment((c) => ({ ...c, [waitingGate.id]: e.target.value }))} />
              <div className="gate-actions">
                <button onClick={() => void decide(waitingGate, "approve")}>批准</button>
                <button className="ghost" onClick={() => void decide(waitingGate, "reject")}>驳回</button>
              </div>
            </div>
          )}
          {state.messages.filter((m) => m.kind !== "tool").map((m) => {
            const role = state.roster.find((r) => r.id === m.role);
            return (
              <article className="msg" key={m.id}>
                <span className="avatar small" style={{ background: role?.color || "#8b96a1" }}>
                  {role?.initial || "?"}
                </span>
                <div className="msg-body">
                  <div className="msg-head">
                    <strong>{role?.name || (m.role === "BOSS" ? "老板" : m.role)}</strong>
                    <span className={`kind kind-${m.kind}`}>{KIND_LABEL[m.kind] || m.kind}</span>
                    <time>{new Date(m.created_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</time>
                  </div>
                  <p className="msg-text">{m.body}</p>
                  {m.evidence?.length > 0 && (
                    <button className="ev-toggle" onClick={() => setOpenEvidence(openEvidence === m.id ? null : m.id)}>
                      依据 {m.evidence.length} 条 {openEvidence === m.id ? "▾" : "▸"}
                    </button>
                  )}
                  {openEvidence === m.id && (
                    <ul className="ev-list">
                      {m.evidence.map((e, i) => (
                        <li key={i}><code>{String(e.type)}</code> {JSON.stringify(e).slice(0, 320)}</li>
                      ))}
                    </ul>
                  )}
                </div>
              </article>
            );
          })}
          {state.messages.length === 0 && (
            <p className="studio-empty">还没有对话。点右上角“开一轮”，让公司开始工作。</p>
          )}
        </div>

        <aside className="studio-artifacts">
          <h3>成果</h3>
          {sketches.map((s) => {
            const plan = plans.find((p) => p.option_id === s.option_id && p.revision === s.revision);
            return (
              <figure key={s.id}>
                <img src={`${API}${s.svg_url}`} alt={`候选 ${s.option_id} v${s.revision}`} />
                <figcaption>
                  候选 {s.option_id} · v{s.revision}
                  {plan?.payload?.strategy?.name ? ` · ${plan.payload.strategy.name}` : ""}
                </figcaption>
              </figure>
            );
          })}
          {plans.length > 0 && (
            <details className="json-box">
              <summary>候选数据（版本化 JSON）</summary>
              {plans.map((p) => (
                <div key={p.id}>
                  <strong>候选 {p.option_id} v{p.revision}</strong>
                  <pre>{JSON.stringify(p.payload, null, 1).slice(0, 1800)}</pre>
                </div>
              ))}
            </details>
          )}
          {state.reviews.map((r) => (
            <details className="json-box" key={r.id}>
              <summary>评审 · {r.verdict}</summary>
              <p>{r.summary}</p>
              <ol>{r.issues.map((i: any, k: number) => (
                <li key={k}><b>{i.severity}</b> {i.rule_id} {i.objects?.join("/")}<br />{i.evidence}<br /><i>{i.suggest}</i></li>
              ))}</ol>
            </details>
          ))}
        </aside>
      </div>

      <div className="studio-input">
        <input value={draft} placeholder="@空间规划 把中岛往南挪一点；或写你的意见" onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") void send(); }} />
        <button onClick={() => void send()}>发给公司</button>
      </div>
    </section>
  );
}

function relTime(iso: string) {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "刚刚";
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
  return `${Math.floor(diff / 3600)} 小时前`;
}
