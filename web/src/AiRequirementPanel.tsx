import { useCallback, useEffect, useMemo, useState } from "react";
import { apiHeaders, checkSessionResponse } from "./session";

type AIJob = {
  job_id: string;
  status: string;
  phase: string;
  attempt_count: number;
  error_code?: string | null;
  error_message?: string | null;
  created_at: string;
};
type AIBriefRecord = {
  brief_id: string;
  job_id: string;
  revision_no: number;
  source_kind: string;
  change_reason: string;
  brief: Record<string, any>;
};
type AIStatus = {
  provider: {
    kind: string;
    name: string;
    real_model: boolean;
    external_project_context_allowed: boolean;
    configuration_errors?: string[];
  };
  configured: boolean;
  item: null | {
    job: AIJob;
    brief: AIBriefRecord;
    revisions: AIBriefRecord[];
    runs: Record<string, any>[];
  };
  jobs: AIJob[];
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

const statusText: Record<string, string> = {
  queued: "已排队", running: "模型调用中", succeeded: "已生成候选", failed: "失败", cancelled: "已取消",
};
const phaseText: Record<string, string> = {
  queued: "等待 Worker", understanding: "理解需求", validating: "校验结构", persisting: "保存候选",
  completed: "完成", configuration_failed: "配置检查失败", failed: "失败",
};

function editableBrief(source: Record<string, any>, requirements: string, intent: string): Record<string, any> {
  const brief = JSON.parse(JSON.stringify(source));
  const requirementsSource: Record<string, any>[] = source.requirements || [];
  const intentSource: Record<string, any>[] = source.design_intent || [];
  const lines = (value: string) => value.split("\n").map((line) => line.trim()).filter(Boolean);
  brief.requirements = lines(requirements).map((statement, index) => ({
    ...(requirementsSource[index] || {}),
    item_id: `human-req-${index + 1}`,
    statement,
    origin_kind: "human_edit",
    evidence_status: "unverified",
    known_status: "known",
    priority: "high",
    source_refs: requirementsSource[index]?.source_refs || ["synthetic-input"],
  }));
  brief.design_intent = lines(intent).map((statement, index) => ({
    ...(intentSource[index] || {}),
    item_id: `human-intent-${index + 1}`,
    statement,
    origin_kind: "human_edit",
    evidence_status: "unverified",
    known_status: "inferred",
    priority: "medium",
    source_refs: intentSource[index]?.source_refs || ["synthetic-input"],
  }));
  return brief;
}

export function AiRequirementPanel({ projectId }: { projectId: string }) {
  const base = `/api/v1/projects/${projectId}/ai/requirement-understanding`;
  const [status, setStatus] = useState<AIStatus | null>(null);
  const [text, setText] = useState("");
  const [requirements, setRequirements] = useState("");
  const [intent, setIntent] = useState("");
  const [reason, setReason] = useState("人工修正任务书");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (quiet = false) => {
    try {
      const result = await request<AIStatus>(base);
      setStatus(result);
      if (!quiet) setError("");
    } catch (e) {
      if (!quiet) setError((e as Error).message);
    }
  }, [base]);

  useEffect(() => { void load(); }, [load]);
  const pending = useMemo(() => Boolean(status?.jobs.some((job) => job.status === "queued" || job.status === "running")), [status]);
  useEffect(() => {
    if (!pending) return;
    const timer = window.setInterval(() => void load(true), 1000);
    return () => window.clearInterval(timer);
  }, [pending, load]);

  const current = status?.item ?? null;
  useEffect(() => {
    if (!current) return;
    const brief = current.brief.brief;
    setRequirements((brief.requirements || []).map((item: any) => item.statement).join("\n"));
    setIntent((brief.design_intent || []).map((item: any) => item.statement).join("\n"));
  }, [current?.brief.brief_id]);

  async function act(action: () => Promise<void>) {
    setBusy(true); setError(""); setMessage("");
    try { await action(); } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function submit() {
    await act(async () => {
      const result = await request<{ item: AIJob }>(base, "POST", { natural_language: text }, { "Idempotency-Key": crypto.randomUUID() });
      setMessage(`任务 ${result.item.job_id} 已提交；真实阶段状态见下方。`);
      await load(true);
    });
  }

  async function jobAction(jobId: string, action: "retry" | "cancel") {
    await act(async () => {
      await request(`${base}/jobs/${jobId}/${action}`, "POST", {});
      setMessage(action === "retry" ? "任务已显式重排" : "任务已取消；迟到结果不会写入");
      await load(true);
    });
  }

  async function saveBrief() {
    if (!current) return;
    await act(async () => {
      const brief = editableBrief(current.brief.brief, requirements, intent);
      await request(`${base}/briefs`, "PATCH", {
        job_id: current.job.job_id,
        expected_revision: current.brief.revision_no,
        brief,
        change_reason: reason,
      });
      setMessage("候选任务书已保存为新修订；未创建设计、量价或采购事实。");
      await load(true);
    });
  }

  const providerLabel = !status?.configured
    ? "真实模型通道未配置：提交会产生可见失败记录，不会用规则结果冒充 AI"
    : status.provider.real_model
      ? `真实模型通道已配置：${status.provider.name}`
      : `本地合成测试通道：${status.provider.name}`;

  return <section className="ai-panel" aria-busy={busy}>
    <header className="section-heading">
      <h3>AI 需求理解（候选任务书）</h3>
      <span className="design-status">{providerLabel}</span>
    </header>
    <p className="ai-boundary">本切片只生成有来源状态的结构化任务书；不生成分区布局、工程量、报价、采购草稿或正式批准。项目原件内容未解析，默认不外发项目资料。</p>
    {status?.provider.configuration_errors?.length ? <p className="design-feedback error" role="alert">{status.provider.configuration_errors.join("；")}</p> : null}
    {error && <p className="design-feedback error" role="alert">{error}</p>}
    {message && <p className="design-feedback" role="status">{message}</p>}
    <div className="ai-input-grid">
      <label className="ai-natural-language">自然语言需求<textarea rows={3} maxLength={8000} value={text} onChange={(e) => setText(e.target.value)} placeholder="例如：开放交流，入口在左侧，暖木色，保留宽阔中心展示面" /></label>
      <button type="button" className="dark-action" disabled={busy || !text.trim()} onClick={() => void submit()}>提交需求理解任务</button>
    </div>
    <div className="ai-job-state">
      <strong>作业阶段</strong>
      {status?.jobs.length ? <ul>{status.jobs.slice(0, 5).map((job) => <li key={job.job_id}><code>{job.job_id}</code><span>{statusText[job.status] ?? job.status} · {phaseText[job.phase] ?? job.phase} · 尝试 {job.attempt_count}</span>{job.error_message && <small>{job.error_message}</small>}<span className="ai-actions">{(job.status === "failed" || job.status === "cancelled") && <button type="button" disabled={busy} onClick={() => void jobAction(job.job_id, "retry")}>显式重试</button>}{(job.status === "queued" || job.status === "running") && <button type="button" disabled={busy} onClick={() => void jobAction(job.job_id, "cancel")}>取消</button>}</span></li>)}</ul> : <p>尚无任务。未配置真实模型时，提交会记录明确失败，不产生任务书。</p>}
    </div>
    {current ? <>
      <div className="design-baseline"><span>任务书 v{current.brief.revision_no} · {current.brief.source_kind === "human_edit" ? "人工修订" : "模型候选"}</span><span>生命周期：候选</span><span>{current.brief.change_reason}</span></div>
      <div className="ai-brief-grid">
        <label>关键需求（每行一项）<textarea rows={5} value={requirements} onChange={(e) => setRequirements(e.target.value)} /></label>
        <label>设计意图（每行一项）<textarea rows={5} value={intent} onChange={(e) => setIntent(e.target.value)} /></label>
      </div>
      <div className="ai-facts">
        <div><h4>假设</h4><ul>{(current.brief.brief.assumptions || []).map((item: any) => <li key={item.item_id}>{item.statement}</li>)}</ul></div>
        <div><h4>冲突</h4><ul>{(current.brief.brief.conflicts || []).map((item: any) => <li key={item.conflict_id}>{item.statement}</li>)}</ul></div>
        <div><h4>最少补问</h4><ul>{(current.brief.brief.open_questions || []).map((item: any) => <li key={item.question_id}>{item.statement}</li>)}</ul></div>
        <div><h4>成本已知/缺项</h4><p>合同目标：{current.brief.brief.cost?.budget?.value ?? "未知"}</p><ul>{(current.brief.brief.cost?.unknown_items || []).map((item: any) => <li key={item.item_id}>{item.statement}</li>)}</ul></div>
      </div>
      <details className="design-evidence"><summary>模型运行与来源（{current.runs.length} 次尝试 / {(current.brief.brief.source_refs || []).length} 条来源）</summary><ul>{current.runs.map((run) => <li key={run.run_id}>{run.provider_name} · {run.status} · 真实模型 {run.real_model ? "是" : "否"} · 费用 {run.cost?.cost_known_status ?? "unknown"}</li>)}</ul><ul>{(current.brief.brief.source_refs || []).map((ref: any) => <li key={ref.source_id}>{ref.source_id} · {ref.content_status} · {ref.evidence_status}</li>)}</ul></details>
      <div className="design-command-row"><label>修订理由<input maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} /></label><button type="button" className="outline-action" disabled={busy || !reason.trim()} onClick={() => void saveBrief()}>保存人工修订</button></div>
    </> : <p className="files-empty">尚无候选任务书；当前不显示模拟或规则生成文本。</p>}
  </section>;
}
