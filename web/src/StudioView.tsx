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
  project: { id: string; name: string; site: any; requirement: any;
             source_project_id?: string; mapping_note?: string };
  messages: Message[]; artifacts: Artifact[]; gates: Gate[]; runs: Run[];
  reviews: Array<{ id: string; verdict: string; summary: string; issues: any[] }>;
  usage: { tokens_in: number; tokens_out: number; tokens_total: number };
  roster: Role[];
  channel: { configured: boolean; model: string; run_limit: number; project_limit: number };
  running: boolean;
  feedback?: Array<{ id: string; revision_no: number; kind: string; text: string;
                     baseline_artifact_id?: string; status: string }>;
  feedback_revision?: number;
  effective_requirement?: { effective_input_hash?: string; effective_addenda?: any[] };
  service_scope?: { mode: string; label: string; team_nas_supported: boolean;
                    supported_project_ids: string[]; project_id_mapping: string };
  valid_candidate_ids?: string[];
  stage_status?: { flow_finished: boolean; valid_artifact_exists: boolean;
                   waiting_user: boolean; design_approved_by_user: boolean; note: string };
  error?: string;
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
  const [decisionScope, setDecisionScope] = useState<Record<string, string>>({});
  const [openEvidence, setOpenEvidence] = useState<number | null>(null);
  const timer = useRef<number | null>(null);

  // ARC-04: no project hardcoding. The studio id IS the main-system project id;
  // a project that is not explicitly mapped shows a limitation notice, never
  // another project's (Ningbo) data.
  const studioId = projectId ?? "";
  const mapped = !!projectId;

  async function load() {
    if (!mapped) { setState(null); return; }
    try {
      const res = await fetch(`${API}/studio/projects/${encodeURIComponent(studioId)}/state`,
        { cache: "no-store" });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setState(null);
        setError(body.error || `状态读取失败 ${res.status}`);
        return;
      }
      setState(await res.json());
      setError("");
    } catch (e) {
      setState(null);
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
    if (!mapped) return;
    setBusy(true);
    try {
      const res = await fetch(`${API}/studio/projects/${encodeURIComponent(studioId)}/run`, { method: "POST" });
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
    if (!mapped || !draft.trim()) return;
    const res = await fetch(`${API}/studio/projects/${encodeURIComponent(studioId)}/messages`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: draft.trim() }),
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) { setError(body.error || "留言未保存"); return; }
    setDraft("");
    setError(`留言已写入版本化有效需求 v${body.feedback?.revision_no ?? "?"}；下一轮修订将读取该输入`);
    void load();
  }

  async function decide(gate: Gate, decision: "approve" | "reject") {
    const comment = gateComment[gate.id] || "";
    if (decision === "reject" && !comment.trim()) { setError("驳回必须写理由"); return; }
    const scope = decisionScope[gate.id] || "allow_continue";
    const res = await fetch(`${API}/studio/gates/${gate.id}/decide`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision, comment, decision_scope: scope }),
    });
    const body = await res.json().catch(() => ({}));
    setError(body.note || (res.ok ? "决定已记录" : (body.error || "决定失败")));
    void load();
  }

  if (!mapped || !state) {
    return <section className="studio">
      <p className="studio-empty">
        {!mapped ? "当前项目未接入本机设计公司实验服务，不显示其他项目（含宁波）的结果。"
                 : (error || "正在连接设计公司…")}
      </p>
    </section>;
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

      <div className="studio-meta">
        <span>主系统项目映射：<code>{state.project.source_project_id || state.project.id}</code></span>
        <span>{state.service_scope?.label || "本机实验服务"}</span>
        <span>{state.service_scope?.team_nas_supported ? "团队/NAS 已支持" : "未接入团队/NAS"}</span>
        <span>有效需求 v{state.feedback_revision ?? 0}</span>
        <span>状态：{state.stage_status?.flow_finished ? "流程跑完" : "未跑完"} ·
          {state.stage_status?.valid_artifact_exists ? "有有效成果" : "无有效成果"} ·
          {state.stage_status?.waiting_user ? "等待用户" : "无需等待"} ·
          设计认可：{state.stage_status?.design_approved_by_user ? "是" : "否（只能由用户给出）"}</span>
      </div>

      {error && <p className="studio-error" role="alert">{error}</p>}

      {(state.feedback || []).length > 0 && (
        <details className="json-box" open>
          <summary>老板留言 · 版本化有效需求（{state.feedback!.length} 条）</summary>
          <ul>{(state.feedback || []).map(f => (
            <li key={f.id}>v{f.revision_no} [{f.kind}] {f.text}
              {f.baseline_artifact_id ? ` · 绑定基线 ${f.baseline_artifact_id}` : ""}</li>
          ))}</ul>
        </details>
      )}

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
              <textarea placeholder="驳回必须写理由（会进入版本化反馈）"
                value={gateComment[waitingGate.id] || ""}
                onChange={(e) => setGateComment((c) => ({ ...c, [waitingGate.id]: e.target.value }))} />
              <label className="gate-scope">
                决定语义：
                <select value={decisionScope[waitingGate.id] || "allow_continue"}
                  onChange={(e) => setDecisionScope((c) => ({ ...c, [waitingGate.id]: e.target.value }))}>
                  <option value="allow_continue">允许继续试验（不等于设计通过）</option>
                  <option value="direction_approval">认可设计方向（不等于设计通过）</option>
                </select>
              </label>
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
          <h3>成果 · 有效候选（{state.valid_candidate_ids?.length ?? 0}）</h3>
          {sketches.filter((s) => (s as any).display_group === "valid").map((s) => {
            const plan = plans.find((p) => p.option_id === s.option_id && p.revision === s.revision);
            return (
              <figure key={s.id}>
                <img src={`${API}${s.svg_url}`} alt={`候选 ${s.option_id} v${s.revision}`} />
                <figcaption>
                  候选 {s.option_id} · v{s.revision}
                  {plan?.payload?.strategy?.name ? ` · ${plan.payload.strategy.name}` : ""}
                  <br /><small>基线 {plan?.id} · 校验 {(plan as any)?.contract_status}</small>
                </figcaption>
              </figure>
            );
          })}
          {plans.filter((p) => (p as any).display_group === "valid").length > 0 && (
            <details className="json-box">
              <summary>有效候选数据（版本化 JSON）</summary>
              {plans.filter((p) => (p as any).display_group === "valid").map((p) => (
                <div key={p.id}>
                  <strong>候选 {p.option_id} v{p.revision}</strong>
                  <pre>{JSON.stringify(p.payload, null, 1)}</pre>
                </div>
              ))}
            </details>
          )}
          <details className="json-box">
            <summary>历史 / 失效 / 未校验产物（保留，不删除，不等于有效候选）</summary>
            <ul>
              {state.artifacts.filter((a) => (a as any).display_group !== "valid").map((a) => (
                <li key={a.id}>
                  <code>{a.id}</code> · {a.kind} · v{a.revision} · {a.status} ·
                  {(a as any).contract_status}
                  {(a as any).diagnostics?.repair_feedback
                    ? <div><small>{(a as any).diagnostics.repair_feedback.slice(0, 300)}</small></div>
                    : null}
                </li>
              ))}
            </ul>
          </details>
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
