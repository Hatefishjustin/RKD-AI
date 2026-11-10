import { useCallback, useEffect, useMemo, useState } from "react";
import { apiHeaders, checkSessionResponse } from "./session";

type Artifact = { artifact_id: string; filename: string; size_bytes: number; sha256: string };
type Option = {
  option_revision_id: string;
  option_id: string;
  set_id: string;
  revision_no: number;
  strategy_id: string;
  strategy: { statement: string; tradeoffs: string[] };
  model: Record<string, any>;
  validation: { status: string; hard_checks: { code: string; status: string; message: string }[] };
  materials: { material_id: string; name: string; intent: string }[];
  cost: { budget: { value: any; known_status: string }; unknown_items: { statement: string }[] };
  feedback: { text: string | null; parsed_intents: string[]; locks: string[] };
  diff: { object_id: string; field: string; reason: string }[];
  conflicts: { statement: string }[];
  artifacts: Artifact[];
  source_kind: string;
  lifecycle_status: string;
};
type CandidateSet = { set_id: string; status: string; phase: string; error_code?: string | null; error_message?: string | null; attempt_count: number };
type Adoption = { option_id: string; revision_no: number; expected_revision: number; status: string; production_task_status: string };
type OptionStatus = {
  provider: { kind: string; name: string; real_model: boolean; configuration_errors?: string[] };
  configured: boolean;
  item: null | { set: CandidateSet; options: Option[] };
  sets: CandidateSet[];
  adoption: Adoption | null;
};

async function request<T>(path: string, method = "GET", body?: unknown, extraHeaders?: Record<string, string>): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: { ...apiHeaders, "Content-Type": "application/json", ...(extraHeaders || {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  checkSessionResponse(response);
  const result = await response.json();
  if (!response.ok) throw new Error(result.message ?? `请求失败 (${response.status})`);
  return result;
}

const phaseText: Record<string, string> = {
  queued: "已排队", strategy: "形成策略", geometry: "落成几何", validation: "检查几何",
  outputs: "生成图面", completed: "完成", configuration_failed: "配置检查失败", failed: "失败",
};
const setStatusText: Record<string, string> = {
  queued: "已排队", running: "生成中", succeeded: "已完成", failed: "失败", cancelled: "已取消",
};

export function AiDesignOptionsPanel({ projectId }: { projectId: string }) {
  const base = `/api/v1/projects/${projectId}/ai/design-options`;
  const [status, setStatus] = useState<OptionStatus | null>(null);
  const [briefReady, setBriefReady] = useState(false);
  const [svgData, setSvgData] = useState<Record<string, string>>({});
  const [feedbacks, setFeedbacks] = useState<Record<string, string>>({});
  const [lockEntrance, setLockEntrance] = useState(true);
  const [lockDisplay, setLockDisplay] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const artifactUrl = useCallback((artifactId: string) => `${base}/artifacts/${artifactId}/content`, [base]);

  const loadSvg = useCallback(async (artifactId: string) => {
    const response = await fetch(artifactUrl(artifactId), { headers: apiHeaders });
    checkSessionResponse(response);
    if (!response.ok) throw new Error(`候选图面读取失败 (${response.status})`);
    const text = await response.text();
    return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(text)}`;
  }, [artifactUrl]);

  const load = useCallback(async (quiet = false) => {
    try {
      const [result, brief] = await Promise.all([
        request<OptionStatus>(base),
        request<{ item: unknown }>(`/api/v1/projects/${projectId}/ai/requirement-understanding`),
      ]);
      setStatus(result);
      setBriefReady(Boolean(brief.item));
      const ids = result.item?.options.flatMap((option) => option.artifacts.map((artifact) => artifact.artifact_id)) || [];
      const entries = await Promise.all(ids.map(async (id) => [id, await loadSvg(id)] as const));
      setSvgData(Object.fromEntries(entries));
      if (!quiet) setError("");
    } catch (e) {
      if (!quiet) setError((e as Error).message);
    }
  }, [base, projectId, loadSvg]);

  useEffect(() => { void load(); }, [load]);
  const pending = useMemo(() => Boolean(status?.sets.some((item) => item.status === "queued" || item.status === "running")), [status]);
  useEffect(() => {
    if (!pending) return;
    const timer = window.setInterval(() => void load(true), 1000);
    return () => window.clearInterval(timer);
  }, [pending, load]);

  async function act(action: () => Promise<void>) {
    setBusy(true); setError(""); setMessage("");
    try { await action(); } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function generate() {
    await act(async () => {
      const result = await request<{ item: CandidateSet }>(base, "POST", {}, { "Idempotency-Key": crypto.randomUUID() });
      setMessage(`候选集 ${result.item.set_id} 已提交；真实阶段状态见下方。`);
      await load(true);
    });
  }

  async function revise(option: Option) {
    const feedback = (feedbacks[option.option_id] || "").trim();
    if (!feedback) { setError("请先填写自然语言反馈"); return; }
    await act(async () => {
      const locks = [lockEntrance ? "entrance" : "", lockDisplay ? "display" : ""].filter(Boolean);
      const result = await request<{ diff: { object_id: string; field: string }[] }>(
        `${base}/${option.option_id}/revise`, "POST",
        { expected_revision: option.revision_no, feedback, locks },
      );
      setMessage(`已生成候选 v${option.revision_no + 1}，实际对象变化 ${result.diff.length} 项；未改动量价或采购。`);
      await load(true);
    });
  }

  async function adopt(option: Option) {
    await act(async () => {
      const expectedVersion = status?.adoption?.expected_revision ?? 0;
      await request(`${base}/${option.option_id}/adopt`, "POST",
        { expected_revision: option.revision_no, expected_version: expectedVersion });
      setMessage("已采用为当前草稿；同源量价/成果任务尚未接入，正式批准未发生。");
      await load(true);
    });
  }

  async function cancel(setId: string) {
    await act(async () => {
      await request(`${base}/sets/${setId}/cancel`, "POST", {});
      setMessage("候选集已取消；迟到结果不会写入。");
      await load(true);
    });
  }

  const providerLabel = !status?.configured
    ? "设计候选通道未配置：不会生成候选"
    : status.provider.real_model
      ? `真实模型通道已配置：${status.provider.name}`
      : `本地合成设计通道（非真实 AI）：${status.provider.name}`;

  return <section className="ai-panel ai-options-panel" aria-busy={busy}>
    <header className="section-heading">
      <h3>AI 设计候选</h3>
      <span className="design-status">{providerLabel}</span>
    </header>
    <p className="ai-boundary">候选图面、反馈修订和采用草稿均独立于当前设计、量价、采购与正式批准。合成通道用于验证真实几何链，不代表模型设计质量或 AD 验收。</p>
    {status?.provider.configuration_errors?.length ? <p className="design-feedback error" role="alert">{status.provider.configuration_errors.join("；")}</p> : null}
    {error && <p className="design-feedback error" role="alert">{error}</p>}
    {message && <p className="design-feedback" role="status">{message}</p>}
    <div className="ai-options-toolbar">
      <button type="button" className="dark-action" disabled={busy || !briefReady || !status?.configured} onClick={() => void generate()}>生成两个可比较候选</button>
      <label><input type="checkbox" checked={lockEntrance} onChange={(e) => setLockEntrance(e.target.checked)} />保留入口</label>
      <label><input type="checkbox" checked={lockDisplay} onChange={(e) => setLockDisplay(e.target.checked)} />保留展柜</label>
      {!briefReady && <small>请先在“需求”页生成并保存结构化任务书。</small>}
    </div>
    <div className="ai-job-state">
      <strong>候选集阶段</strong>
      {status?.sets.length ? <ul>{status.sets.slice(0, 5).map((item) => <li key={item.set_id}><code>{item.set_id}</code><span>{setStatusText[item.status] ?? item.status} · {phaseText[item.phase] ?? item.phase} · 尝试 {item.attempt_count}</span>{item.error_message && <small>{item.error_message}</small>}<span className="ai-actions">{(item.status === "queued" || item.status === "running") && <button type="button" disabled={busy} onClick={() => void cancel(item.set_id)}>取消</button>}</span></li>)}</ul> : <p>尚无候选集。</p>}
    </div>
    {status?.adoption && <div className="design-baseline"><strong>当前采用草稿 v{status.adoption.revision_no}</strong><span>{status.adoption.option_id}</span><span>量价任务：{status.adoption.production_task_status}</span><span>非正式批准</span></div>}
    {status?.item ? <div className="ai-option-grid">
      {status.item.options.map((option) => <article className="ai-option-card" key={option.option_revision_id}>
        <header><strong>{option.strategy.statement}</strong><small>候选 v{option.revision_no} · {option.strategy_id} · {option.lifecycle_status}</small></header>
        {option.artifacts[0] && svgData[option.artifacts[0].artifact_id]
          ? <img className="ai-option-svg" src={svgData[option.artifacts[0].artifact_id]} alt={`${option.strategy_id} 候选平面`} />
          : <div className="files-empty">正在读取候选图面...</div>}
        <dl className="ai-option-facts">
          <div><dt>入口 / 动线</dt><dd>{option.model.boundary.entrance.side} · {option.model.circulation.kind} · {option.model.circulation.segments.length} 段</dd></div>
          <div><dt>材料意向</dt><dd>{option.materials.map((item) => item.name).join("、")}</dd></div>
          <div><dt>成本已知</dt><dd>{option.cost.budget.value ?? "未知"}</dd></div>
          <div><dt>成本缺项</dt><dd>{option.cost.unknown_items.map((item) => item.statement).join("；") || "无"}</dd></div>
          <div><dt>硬检查</dt><dd>{option.validation.hard_checks.filter((item) => item.status === "passed").length}/{option.validation.hard_checks.length} 通过</dd></div>
          <div><dt>取舍</dt><dd>{option.strategy.tradeoffs.join("；")}</dd></div>
        </dl>
        {option.conflicts.length > 0 && <ul className="ai-option-conflicts">{option.conflicts.map((item, index) => <li key={index}>{item.statement}</li>)}</ul>}
        {option.diff.length > 0 && <details><summary>相对上一版对象变化（{option.diff.length} 项）</summary><ul>{option.diff.map((item, index) => <li key={index}>{item.object_id} · {item.field} · {item.reason}</li>)}</ul></details>}
        <label className="ai-feedback-input">自然语言反馈<textarea rows={2} value={feedbacks[option.option_id] || ""} onChange={(e) => setFeedbacks((current) => ({ ...current, [option.option_id]: e.target.value }))} placeholder="例如：更开放但保留入口" /></label>
        <div className="ai-option-actions"><button type="button" className="outline-action" disabled={busy} onClick={() => void revise(option)}>生成反馈修订</button><button type="button" className="dark-action" disabled={busy || option.validation.status !== "passed"} onClick={() => void adopt(option)}>采用为当前草稿</button></div>
      </article>)}
    </div> : <p className="files-empty">尚无候选图面；生成后会在这里并排显示不同空间组织。</p>}
  </section>;
}
