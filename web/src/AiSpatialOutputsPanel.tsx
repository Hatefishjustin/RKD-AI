import { useCallback, useEffect, useMemo, useState } from "react";
import { apiHeaders, checkSessionResponse } from "./session";

type Job = { job_id: string; status: string; phase: string; error_code?: string | null; error_message?: string | null; settings?: Record<string, any>; config?: Record<string, any> };
type Quantity = { quantity_id: string; name: string; value: number | null; unit: string; known_status: string; unknown_reason?: string; note?: string };
type Revision = {
  production_revision_id: string; option_revision_id: string; option_id: string;
  baseline: Record<string, any>; quantities: { items: Quantity[]; declared_vs_exact_delta_m2: number };
  cost: { unknown_items: { statement: string; impact: string }[]; total_project_estimate: { value: null } };
  package: { missing: string[]; render?: Record<string, any> };
};
type Artifact = { artifact_id: string; filename: string; content_type: string; size_bytes: number; sha256: string };
type Status = { job: Job | null; jobs: Job[]; revision: Revision | null; artifacts: Artifact[]; boundary: Record<string, any> };
type Option = { option_revision_id: string; option_id: string; revision_no: number; lifecycle_status: string; model: Record<string, any> };

async function request<T>(path: string, method = "GET", body?: unknown, extra?: Record<string, string>): Promise<T> {
  const response = await fetch(path, {
    method,
    headers: { ...apiHeaders, "Content-Type": "application/json", ...(extra || {}) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  checkSessionResponse(response);
  const result = await response.json();
  if (!response.ok) throw new Error((result as any).message ?? `请求失败 (${response.status})`);
  return result as T;
}

export function AiSpatialOutputsPanel({ projectId }: { projectId: string }) {
  const base = `/api/v1/projects/${projectId}/ai`;
  const [status, setStatus] = useState<Status | null>(null);
  const [options, setOptions] = useState<Option[]>([]);
  const [selected, setSelected] = useState("");
  const [render, setRender] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [blobs, setBlobs] = useState<Record<string, string>>({});

  const load = useCallback(async () => {
    const [outputs, design] = await Promise.all([
      request<Status>(`${base}/spatial-outputs`),
      request<{ item: null | { options: Option[] } }>(`${base}/design-options`),
    ]);
    setStatus(outputs);
    const spatial = (design.item?.options || []).filter((o) => Boolean(o.model?.spatial));
    setOptions(spatial);
    setSelected((current) => current || spatial[0]?.option_revision_id || "");
  }, [base]);

  useEffect(() => { void load().catch((e) => setError((e as Error).message)); }, [load]);

  const pending = useMemo(() => status?.job?.status === "queued" || status?.job?.status === "running", [status]);
  useEffect(() => {
    if (!pending) return;
    const timer = window.setInterval(() => void load().catch(() => undefined), 1500);
    return () => window.clearInterval(timer);
  }, [pending, load]);

  const revision = status?.revision || null;
  const downloadBase = revision
    ? `${base}/spatial-outputs/${revision.production_revision_id}/files` : "";

  const loadBlob = useCallback(async (name: string) => {
    if (!downloadBase) return;
    const response = await fetch(`${downloadBase}/${name}`, { headers: apiHeaders });
    checkSessionResponse(response);
    if (!response.ok) return;
    const blob = await response.blob();
    return URL.createObjectURL(blob);
  }, [downloadBase]);

  useEffect(() => {
    if (!revision) { setBlobs({}); return; }
    void (async () => {
      const plan = await loadBlob("plan.svg");
      const png = await loadBlob("render.png");
      setBlobs((current) => {
        Object.values(current).forEach((url) => URL.revokeObjectURL(url));
        return { ...(plan ? { plan } : {}), ...(png ? { render: png } : {}) };
      });
    })();
  }, [revision?.production_revision_id, loadBlob]);

  async function generate() {
    if (!selected) { setError("请先选择带精确 spatial 的模型修订"); return; }
    setBusy(true); setError(""); setMessage("");
    try {
      await request(`${base}/spatial-outputs`, "POST",
        { option_revision_id: selected, settings: { render, width: 1280, height: 800, samples: 40 } },
        { "Idempotency-Key": crypto.randomUUID() });
      setMessage("已提交同源成果生成；平面、净量与成本缺项先出，效果图渲染随后完成。");
      await load();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  const phaseText: Record<string, string> = {
    queued: "已排队", geometry: "读取精确模型", measurement: "复算净量",
    pricing: "整理成本缺项", outputs: "生成图面与打包", completed: "完成", failed: "失败",
  };

  return <section className="ai-spatial-panel" aria-busy={busy}>
    <header className="section-heading"><h3>同源成果（W2 切片）</h3><span className="design-status">精确模型 · 内部评审</span></header>
    <p className="ai-boundary">平面、净量与成本都从同一个冻结的候选修订生成；几何依据是精确多边形，包围盒只用于兼容显示。效果图机位、材质与家具高度是渲染假设，不当实测事实。本页不产生正式报价、采购、发布或施工图。</p>
    {error && <p className="design-feedback error" role="alert">{error}</p>}
    {message && <p className="design-feedback" role="status">{message}</p>}
    <div className="ai-options-toolbar">
      <label>模型修订
        <select data-testid="spatial-revision-select" value={selected} onChange={(e) => setSelected(e.target.value)}>
          <option value="">（选择带精确 spatial 的修订）</option>
          {options.map((o) => <option key={o.option_revision_id} value={o.option_revision_id}>
            {o.option_id} v{o.revision_no} · {o.lifecycle_status}
          </option>)}
        </select>
      </label>
      <label><input type="checkbox" checked={render} onChange={(e) => setRender(e.target.checked)} />生成人眼效果图</label>
      <button type="button" className="dark-action" data-testid="spatial-generate" disabled={busy || !selected} onClick={() => void generate()}>生成同源成果</button>
      {status?.job && <small>任务 {status.job.status} · {phaseText[status.job.phase] ?? status.job.phase}</small>}
    </div>
    {status?.job?.error_message && <p className="design-feedback error" role="alert">{status.job.error_message}</p>}
    {!revision ? <p className="files-empty">尚无同源成果；选择修订后生成。</p> : <div className="spatial-output">
      <div className="spatial-output-head">
        <strong>{revision.option_id} v{revision.baseline?.revision_no}</strong>
        <span>模型 {String(revision.baseline?.model_hash).slice(0, 12)}…</span>
        <span>源 {revision.baseline?.source_artifact_id}</span>
        <span>基线 {revision.baseline?.geometry_authority}</span>
        <span>{revision.baseline?.parent_link_status === "source_parent_not_imported" ? "缺父（差量 unknown）" : "父链完整"}</span>
      </div>
      <div className="spatial-output-grid">
        <figure>
          <img data-testid="spatial-plan" src={blobs.plan} alt="同源平面" />
          <figcaption>平面：分区/家具/动线/尺寸/图例/面积表/机位（概念图，非施工图）</figcaption>
        </figure>
        <figure>
          {blobs.render ? <img data-testid="spatial-render" src={blobs.render} alt="人眼效果图" />
            : <div className="files-empty">未生成效果图或渲染未完成</div>}
          <figcaption>人眼 1.5m · 24mm（机位为推导假设）{revision.package?.render ? ` · ${revision.package.render.seconds}s` : ""}</figcaption>
        </figure>
      </div>
      <table className="ledger-table" data-testid="spatial-quantities"><thead><tr><th>净量</th><th>数值</th><th>单位</th><th>状态</th></tr></thead>
        <tbody>{revision.quantities.items.map((q) => <tr key={q.quantity_id}>
          <td>{q.name}</td><td>{q.value === null ? "unknown" : q.value}</td><td>{q.unit}</td><td>{q.known_status}</td>
        </tr>)}</tbody></table>
      <p className="ai-boundary">面积对账：模型自报合计与精确多边形净量差 {revision.quantities.declared_vs_exact_delta_m2} ㎡；包围盒仅供对照，不用于计量。</p>
      <div className="spatial-missing"><strong>缺项（不编数值）</strong><ul>{revision.package?.missing?.map((m) => <li key={m}>{m}</li>)}</ul></div>
      <div className="spatial-downloads">
        {["plan.svg", "render.png", "quantity.csv", "cost.html", "package.zip", "manifest.json"].filter((name) =>
          status?.artifacts.some((a) => a.filename === name) || name === "render.png").map((name) =>
          <a key={name} href={`${downloadBase}/${name}`} target="_blank" rel="noreferrer">{name}</a>)}
      </div>
      <p className="ai-boundary">成本：金额全部 unknown（没有价源），不是报价；采购与发布未触发。</p>
    </div>}
  </section>;
}
