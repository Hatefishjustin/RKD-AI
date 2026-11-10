import { useCallback, useEffect, useMemo, useState } from "react";
import { apiHeaders, checkSessionResponse } from "./session";

type Artifact = { artifact_id: string; artifact_kind: string; filename: string; content_type: string; size_bytes: number; sha256: string };
type Job = { job_id: string; status: string; phase: string; attempt_count: number; error_code?: string | null; error_message?: string | null };
type Adoption = { option_revision_id: string; expected_revision: number; status: string; production_task_status: string };
type Revision = {
  production_revision_id: string;
  option_revision_id: string;
  adoption_version: number;
  input_hash: string;
  package: Record<string, any>;
  quantities: { quantity_item_id: string; object_id: string; description: string; quantity: string; unit: string; cost_scope: string }[];
  cost: { quote: Record<string, string | null>; pricing: Record<string, any>; scope_label: string; unknown_items: { statement: string }[] };
  objects: { object_id: string; kind: string; name: string; material_id: string | null; status: string }[];
  materials: { material_id: string; name: string; intent: string }[];
  unknowns: { statement: string; reason: string }[];
  view_mapping: { node_object_map: { object_id: string; source_object_id: string }[] };
};
type Status = {
  configured: boolean;
  provider: Record<string, any>;
  adoption: Adoption | null;
  item: null | { revision: Revision; artifacts: Artifact[]; status: string };
  jobs: Job[];
  formal_quote: boolean;
  legacy_production_sync: boolean;
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
  queued: "已排队", geometry: "整理同源对象", measurement: "确定性计量", pricing: "试算成本",
  outputs: "生成文件", completed: "完成", failed: "失败",
};
const jobText: Record<string, string> = {
  queued: "已排队", running: "生成中", succeeded: "已完成", failed: "失败", cancelled: "已取消",
};

export function AiDevelopmentPanel({ projectId }: { projectId: string }) {
  const base = `/api/v1/projects/${projectId}/ai/development-production`;
  const [status, setStatus] = useState<Status | null>(null);
  const [unitCost, setUnitCost] = useState("");
  const [sourceLabel, setSourceLabel] = useState("");
  const [costMarkup, setCostMarkup] = useState("0.20");
  const [taxRate, setTaxRate] = useState("0.05");
  const [isometric, setIsometric] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const loadSvg = useCallback(async (artifactId: string) => {
    const response = await fetch(`${base}/artifacts/${artifactId}/content`, { headers: apiHeaders });
    checkSessionResponse(response);
    if (!response.ok) throw new Error(`三维预览读取失败 (${response.status})`);
    return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(await response.text())}`;
  }, [base]);

  const load = useCallback(async (quiet = false) => {
    try {
      const result = await request<Status>(base);
      setStatus(result);
      const artifact = result.item?.artifacts.find((item) => item.artifact_kind === "isometric_svg");
      setIsometric(artifact ? await loadSvg(artifact.artifact_id) : "");
      if (!quiet) setError("");
    } catch (e) {
      if (!quiet) setError((e as Error).message);
    }
  }, [base, loadSvg]);

  useEffect(() => { void load(); }, [load]);
  const pending = useMemo(() => Boolean(status?.jobs.some((job) => job.status === "queued" || job.status === "running")), [status]);
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
    if (!status?.adoption) { setError("请先采用一个通过检查的候选"); return; }
    await act(async () => {
      const settings: Record<string, string> = { cost_markup: costMarkup, trial_tax_rate: taxRate };
      if (unitCost.trim()) settings.unit_cost_net = unitCost.trim();
      if (sourceLabel.trim()) settings.source_label = sourceLabel.trim();
      const result = await request<{ item: Job }>(base, "POST",
        { expected_version: status.adoption!.expected_revision, settings },
        { "Idempotency-Key": crypto.randomUUID() });
      setMessage(`深化量价任务 ${result.item.job_id} 已提交；未改动当前设计、量价或采购。`);
      await load(true);
    });
  }

  async function download(artifact: Artifact) {
    await act(async () => {
      const response = await fetch(`${base}/artifacts/${artifact.artifact_id}/content`, { headers: apiHeaders });
      checkSessionResponse(response);
      if (!response.ok) throw new Error(`下载失败 (${response.status})`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url; anchor.download = artifact.filename; anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setMessage(`已下载 ${artifact.filename}`);
    });
  }

  const current = status?.item ?? null;
  const quote = current?.revision.cost.quote;
  const pricing = current?.revision.cost.pricing;
  const canGenerate = Boolean(status?.adoption && status.adoption.status === "adopted_draft" && status?.configured);

  return <section className="ai-panel ai-development-panel" aria-busy={busy}>
    <header className="section-heading"><h3>同源深化与量价草稿</h3><span className="design-status">确定性程序 · 非正式报价</span></header>
    <p className="ai-boundary">只从已采用且通过硬检查的候选生成材料分区、展陈/隔断对象、glTF/等轴测预览、确定性工程量和本地试算。未建模对象、材料单价、损耗、采购换算及正式税务保持未知；不触发旧设计保存链、采购订单或正式发布。</p>
    {error && <p className="design-feedback error" role="alert">{error}</p>}
    {message && <p className="design-feedback" role="status">{message}</p>}
    <div className="ai-development-settings">
      <label>未税单位成本（可留空）<input value={unitCost} onChange={(e) => setUnitCost(e.target.value)} placeholder="留空则金额保持未知" inputMode="decimal" /></label>
      <label>成本来源<input value={sourceLabel} onChange={(e) => setSourceLabel(e.target.value)} placeholder="人工输入时自动标记未专业核验" /></label>
      <label>施工成本加成<input value={costMarkup} onChange={(e) => setCostMarkup(e.target.value)} inputMode="decimal" /></label>
      <label>本地试用税率<input value={taxRate} onChange={(e) => setTaxRate(e.target.value)} inputMode="decimal" /></label>
      <button type="button" className="dark-action" disabled={busy || !canGenerate} onClick={() => void generate()}>生成深化量价草稿</button>
      {!canGenerate && <small>请先在“AI 候选”页采用一个有效候选。</small>}
    </div>
    <div className="ai-job-state"><strong>作业阶段</strong>{status?.jobs.length ? <ul>{status.jobs.slice(0, 5).map((job) => <li key={job.job_id}><code>{job.job_id}</code><span>{jobText[job.status] ?? job.status} · {phaseText[job.phase] ?? job.phase} · 尝试 {job.attempt_count}</span>{job.error_message && <small>{job.error_message}</small>}</li>)}</ul> : <p>尚无深化量价任务。</p>}</div>
    {status?.adoption && <div className="design-baseline"><span>采用版本 v{status.adoption.expected_revision}</span><span>{status.adoption.option_revision_id}</span><span>生产任务：{status.adoption.production_task_status}</span><span>旧生产同步：关闭</span></div>}
    {current ? <>
      {current.status === "source_outdated" && <p className="design-feedback error" role="alert">采用基线已变化，此成果为过期草稿；请使用当前候选重新生成。</p>}
      <div className="ai-development-grid">
        <div className="ai-development-preview">
          <h4>模型驱动三维表达</h4>
          {isometric ? <img src={isometric} alt="模型驱动等轴测预览" /> : <p className="files-empty">正在读取等轴测图...</p>}
          <p><small>glTF 节点与语义对象映射 {current.revision.view_mapping.node_object_map.length} 项；显示高度仅为视觉假设。</small></p>
        </div>
        <div className="ai-development-cost">
          <h4>已知成本与缺项</h4>
          <dl className="ai-option-facts">
            <div><dt>计价面积</dt><dd>{quote?.quantity ?? "未知"} m²</dd></div>
            <div><dt>未税单位成本</dt><dd>{pricing?.unit_cost_net ?? "未知"}</dd></div>
            <div><dt>未税成本</dt><dd>{quote?.cost_net ?? "未知"}</dd></div>
            <div><dt>含税草稿</dt><dd>{quote?.sale_gross ?? "未知"}</dd></div>
            <div><dt>成本来源</dt><dd>{pricing?.source_label ?? "未知"}</dd></div>
            <div><dt>范围</dt><dd>{current.revision.cost.scope_label}</dd></div>
          </dl>
          <ul className="ai-option-conflicts">{current.revision.unknowns.map((item, index) => <li key={index}>{item.statement}：{item.reason}</li>)}</ul>
        </div>
      </div>
      <div className="ai-development-tables">
        <div><h4>对象工程量</h4><table className="ai-development-table"><thead><tr><th>对象</th><th>数量</th><th>ID</th><th>计价范围</th></tr></thead><tbody>{current.revision.quantities.map((item) => <tr key={item.quantity_item_id}><td>{item.description}</td><td>{item.quantity} {item.unit}</td><td><code>{item.object_id}</code></td><td>{item.cost_scope}</td></tr>)}</tbody></table></div>
        <div><h4>深化对象与材料</h4><ul>{current.revision.objects.slice(0, 16).map((item) => <li key={item.object_id}><strong>{item.name}</strong> · {item.kind} · {item.material_id ?? "材料未知"}</li>)}</ul><p><small>材料意向：{current.revision.materials.map((item) => item.name).join("、")}</small></p></div>
      </div>
      <div className="ai-development-artifacts"><h4>真实成果文件</h4><div>{current.artifacts.map((artifact) => <button type="button" key={artifact.artifact_id} disabled={busy} onClick={() => void download(artifact)}>{artifact.filename}<small>{artifact.size_bytes.toLocaleString()} 字节 · SHA {artifact.sha256.slice(0, 12)}…</small></button>)}</div></div>
    </> : <p className="files-empty">尚无同源深化量价成果。采用候选并填写可选试算参数后生成。</p>}
  </section>;
}
