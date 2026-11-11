import { Fragment, useEffect, useMemo, useRef, useState } from "react";
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
type Run = {
  id: string; status: string; started_at: string; ended_at?: string | null;
  tokens_in: number; tokens_out: number; error?: string | null;
};
type State = {
  project: { id: string; name: string; site: any; requirement: any };
  messages: Message[]; artifacts: Artifact[]; gates: Gate[]; runs: Run[];
  reviews: Array<{ id: string; verdict: string; summary: string; issues: any[] }>;
  usage: { tokens_in: number; tokens_out: number; tokens_total: number };
  roster: Role[];
  channel: { configured: boolean; model: string; run_limit: number; project_limit: number };
  running: boolean;
};

const KIND_LABEL: Record<string, string> = {
  task: "派活", say: "发言", discussion: "讨论", artifact: "交付", review: "评审",
  revise: "修订", rework: "自动打回", "visual-review": "看图自评", gate: "闸口",
  note: "记录", tool: "工具", boss: "老板", decision: "决定",
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
  const runs = state.runs ?? [];
  const totalTokens = runs.reduce((s, r) => s + (r.tokens_in || 0) + (r.tokens_out || 0), 0);
  const feed = state.messages.filter((m) => m.kind !== "tool").map((m) => {
    let ri = -1;
    runs.forEach((r, k) => {
      if (new Date(r.started_at).getTime() <= new Date(m.created_at).getTime() + 1500) ri = k;
    });
    return { m, ri };
  });

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
          <span className="chip">累计 {totalTokens.toLocaleString()} tokens</span>
          <span className="chip">上限 {(state.channel.project_limit / 1000).toFixed(0)}k / 项目</span>
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
          {feed.map(({ m, ri }, i) => {
            const role = state.roster.find((r) => r.id === m.role);
            const run = runs[ri];
            const showSep = i === 0 || feed[i - 1].ri !== ri;
            const runLabel = run
              ? `${ri + 1} 轮 · ${run.status === "incomplete" ? "未完成（不算通过）"
                  : run.status === "running" ? "进行中"
                  : run.status === "succeeded" ? "流程走完（未验收）" : run.status}`
              : "开轮前的记录";
            return (
              <Fragment key={m.id}>
                {showSep && (
                  <div className={`round-sep ${run?.status === "incomplete" ? "bad" : ""}`}>
                    <b>第 {runLabel}</b>
                    {run && <span>{((run.tokens_in || 0) + (run.tokens_out || 0)).toLocaleString()} tokens</span>}
                    {run?.error && <small>{run.error.slice(0, 150)}</small>}
                  </div>
                )}
                <article className="msg">
                  <span className="avatar small" style={{ background: role?.color || "#8b96a1" }}>
                    {role?.initial || "?"}
                  </span>
                  <div className="msg-body">
                    <div className="msg-head">
                      <strong>{role?.name || (m.role === "BOSS" ? "老板" : m.role)}</strong>
                      <span className={`kind kind-${m.kind}`}>{KIND_LABEL[m.kind] || m.kind}</span>
                      <time>{new Date(m.created_at).toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}</time>
                    </div>
                    <p className="msg-text">{readable(m.body)}</p>
                    {m.evidence?.length > 0 && (
                      <button className="ev-toggle" onClick={() => setOpenEvidence(openEvidence === m.id ? null : m.id)}>
                        依据 {m.evidence.length} 条 {openEvidence === m.id ? "▾" : "▸"}
                      </button>
                    )}
                    {openEvidence === m.id && (
                      <ul className="ev-list">
                        {m.evidence.map((e, k) => (
                          <li key={k}><code>{String(e.type)}</code> {evidenceText(e)}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                </article>
              </Fragment>
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

/** Turn a structured deliverable into something a person can actually read. */
function readable(body: string): string {
  const t = (body || "").trim();
  if (!t.startsWith("{") && !t.startsWith("[")) return t;
  try {
    const d = JSON.parse(t);
    const only = Object.keys(d);
    if (only.length === 1 && ["response", "reply", "answer", "text", "content", "message"].includes(only[0])) {
      const v = d[only[0]];
      if (typeof v === "string") return v;
      if (v && typeof v === "object") return readable(JSON.stringify(v));
    }
    if (d.summary && d.observations) {
      const obs: any[] = d.observations || [];
      return `看图自评（观感，不作判据）｜${d.summary}\n`
        + obs.slice(0, 4).map((x) =>
          `· ${x.target}：${x.observation}${x.gap ? "｜差距：" + x.gap : ""}${x.suggest ? "｜" + x.suggest : ""}`).join("\n")
        + (d.limits ? `\n看不出来的：${d.limits}` : "");
    }
    if (d.goal) {
      const must: string[] = d.must_have || [];
      const open: string[] = d.open_questions || [];
      return `任务书｜${d.goal}\n必须项 ${must.length} 条：${must.slice(0, 4).join("；")}${must.length > 4 ? "…" : ""}`
        + `\n待老板确认 ${open.length} 条：${open.slice(0, 2).join("；")}`;
    }
    if (d.strategy) {
      const s = d.strategy || {};
      const trade: string[] = s.tradeoffs || [];
      return `候选「${s.name || "未命名"}」｜${s.narrative || ""}\n取舍：${trade.slice(0, 2).join("；")}`
        + `\n分区 ${(d.zones || []).length} 个 · 家具 ${(d.furniture || []).length} 件 · `
        + `灯位 ${((d.ceiling || {}).fixtures || []).length} 个 · 非直角 ${(s.non_orthogonal || []).length} 处`;
    }
    if (d.verdict) {
      const issues: any[] = d.issues || [];
      const blockers = issues.filter((x) => x.severity === "blocker").length;
      const lines = issues.slice(0, 5).map((x) =>
        `· ${x.severity} ${x.rule_id} → ${(x.objects || []).join("/")}：${x.evidence || ""}｜改法：${x.suggest || ""}`);
      return `评审｜${d.verdict}，意见 ${issues.length} 条（blocker ${blockers}）\n${d.summary || ""}\n${lines.join("\n")}`;
    }
    if (d.responses) {
      const rs: any[] = d.responses || [];
      const acc = rs.filter((r) => r.action === "accept").length;
      const lines = rs.slice(0, 5).map((r) => `· ${r.issue_id} ${r.action}：${r.change || r.reason || ""}`);
      return `逐条回应 ${rs.length} 条，接受 ${acc} 条\n${lines.join("\n")}\n（修订后的完整数据在右侧成果栏）`;
    }
    return Object.entries(d).slice(0, 6)
      .map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v)?.slice(0, 100)}`).join("\n");
  } catch {
    return t;
  }
}

function evidenceText(e: Record<string, unknown>): string {
  const parts: string[] = [];
  if (e.name) parts.push(String(e.name));
  if (e.label) parts.push(String(e.label));
  if (e.instruction) parts.push("指令：" + String(e.instruction).slice(0, 140));
  if (e.context_chars !== undefined) parts.push(`上下文 ${e.context_chars} 字`);
  if (e.tools_allowed) parts.push("可用工具 " + (e.tools_allowed as string[]).join("/"));
  if (e.args) parts.push("参数 " + JSON.stringify(e.args).slice(0, 120));
  if (e.result) parts.push("返回：" + String(e.result).slice(0, 180));
  if (e.tokens_in !== undefined) parts.push(`本次 ${e.tokens_in}+${e.tokens_out} tokens`);
  if (e.id) parts.push(String(e.id));
  if (e.reason) parts.push(String(e.reason));
  if (e.changed) parts.push("改动对象 " + (e.changed as string[]).slice(0, 8).join("、"));
  if (e.items) parts.push("条目 " + (e.items as unknown[]).length + " 条");
  if (e.image_count !== undefined) parts.push(`图片 ${e.image_count} 张`);
  if (e.images) parts.push("来源：" + (e.images as any[])
    .map((x) => `${x.label}（${x.source || x.detail || ""}）`).join("；").slice(0, 260));
  if (e.note) parts.push(String(e.note));
  if (e.reference) parts.push(`基准 ${e.reference} → 当前 ${e.current || ""}`);
  if (e.rule) parts.push(String(e.rule));
  if (e.count !== undefined) parts.push(`次数 ${e.count}`);
  if (e.log) parts.push("打回记录 " + (e.log as any[]).map((x) => `v${x.rev} ${x.qc}`).join("；"));
  if (e.usage) parts.push(`token ${(e.usage as any).in}+${(e.usage as any).out}`);
  if (e.reused) parts.push("沿用老板尚未决定的闸口");
  return parts.length ? parts.join(" · ") : JSON.stringify(e).slice(0, 220);
}

function relTime(iso: string) {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "刚刚";
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
  return `${Math.floor(diff / 3600)} 小时前`;
}
