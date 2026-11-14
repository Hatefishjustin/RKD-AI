import { useCallback, useEffect, useMemo, useState } from "react";
import { apiHeaders, checkSessionResponse } from "./session";

type Job = { job_id: string; status: string; phase: string; error_code?: string | null; error_message?: string | null; option_revision_id?: string; settings?: Record<string, any>; config?: Record<string, any>; created_at?: string };
type Quantity = { quantity_id: string; name: string; value: number | null; unit: string; known_status: string; unknown_reason?: string; note?: string; engineering_status?: string; material_groups?: { material_id: string; material_name?: string; area_m2: number }[]; basis_source?: Record<string, any> };
type CostItem = { item: string; material_id?: string; quantity_m2?: number; unit_price_cny?: number; amount_cny?: number; area_basis_source?: string; basis?: string };
type Binding = { status_at_generation?: string; adopted_option_revision_id?: string; adoption_version?: number };
type Revision = {
  production_revision_id: string; job_id: string; option_revision_id: string; option_id: string;
  baseline: Record<string, any>; binding_status?: string; is_current?: boolean;
  quantities: { items: Quantity[]; declared_vs_exact_delta_m2: number };
  cost: { known_items: CostItem[]; assumption_trial_total_cny: number | null; unknown_items: { statement: string; impact: string }[]; total_project_estimate: { value: null }; formal_quote: boolean };
  package: { missing: string[]; render?: Record<string, any>; binding?: Binding; manifest_only_files?: string[]; package_check?: Record<string, any> };
};
type Artifact = { artifact_id: string; filename: string; content_type: string; size_bytes: number; sha256: string };
type Status = { job: Job | null; jobs: Job[]; revision: Revision | null; revisions: Revision[]; artifacts: Artifact[]; adoption: Record<string, any> | null; boundary: Record<string, any> };
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

const BINDING_LABEL: Record<string, string> = {
  current_adopted: "当前采用版本成果",
  historical_preview: "历史候选预览（已换版）",
  candidate_preview: "候选预览（未采用）",
};

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
  const [pickedRevision, setPickedRevision] = useState("");

  const load = useCallback(async () => {
    const [outputs, design] = await Promise.all([
      request<Status>(`${base}/spatial-outputs`),
      request<{ item: null | { options: Option[] } }>(`${base}/design-options`),
    ]);
    setStatus(outputs);
    const spatial = (design.item?.options || []).filter((o) => Boolean(o.model?.spatial));
    setOptions(spatial);
    setSelected((current) => current || spatial[0]?.option_revision_id || "");
    setPickedRevision((current) => current || outputs.revision?.production_revision_id || "");
  }, [base]);

  useEffect(() => { void load().catch((e) => setError((e as Error).message)); }, [load]);

  const pending = useMemo(() => status?.job?.status === "queued" || status?.job?.status === "running", [status]);
  useEffect(() => {
    if (!pending) return;
    const timer = window.setInterval(() => void load().catch(() => undefined), 1500);
    return () => window.clearInterval(timer);
  }, [pending, load]);

  const revision = useMemo(() => {
    if (!status) return null;
    if (pickedRevision) {
      const hit = (status.revisions || []).find((r) => r.production_revision_id === pickedRevision);
      if (hit) return hit;
    }
    return status.revision;
  }, [status, pickedRevision]);

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
      setMessage("已提交同源成果生成；平面、几何净量与成本缺项先出，效果图渲染随后完成。");
      await load();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function cancelJob(jobId: string) {
    setBusy(true); setError(""); setMessage("");
    try {
      await request(`${base}/spatial-outputs/${jobId}/cancel`, "POST", {});
      setMessage("任务已取消；晚到的渲染结果会被丢弃，不登记成果。已完成的历史成果字节保留。");
      await load();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function retryJob(jobId: string) {
    setBusy(true); setError(""); setMessage("");
    try {
      await request(`${base}/spatial-outputs/${jobId}/retry`, "POST", {},
        { "Idempotency-Key": crypto.randomUUID() });
      setMessage("已按原任务参数重试；新任务与原任务关联，不覆盖旧记录。");
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
    <p className="ai-boundary">平面、几何净量与成本都从同一个冻结的候选修订生成；几何依据是精确多边形，包围盒只用于兼容显示。几何净面积<b>不是</b>铺装/完成面工程量；没有材料面依据时完成面量保持 unknown。效果图机位、材质与家具高度是渲染假设，不当实测事实。本页不产生正式报价、采购、发布或施工图。</p>
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
      {pending && status?.job && <button type="button" data-testid="spatial-cancel" disabled={busy} onClick={() => void cancelJob(status.job!.job_id)}>取消本次任务</button>}
      {status?.job && (status.job.status === "failed" || status.job.status === "cancelled") &&
        <button type="button" data-testid="spatial-retry" disabled={busy} onClick={() => void retryJob(status.job!.job_id)}>按原参数重试</button>}
    </div>
    {status?.job?.error_message && <p className="design-feedback error" role="alert">{status.job.error_message}</p>}
    {(status?.revisions?.length ?? 0) > 1 && <div className="spatial-history">
      <strong>成果历史（按任务关联，不按完成顺序推断）</strong>
      <ul>
        {status!.revisions.map((r) => <li key={r.production_revision_id}>
          <button type="button" className={r.production_revision_id === revision?.production_revision_id ? "dark-action" : ""}
            onClick={() => setPickedRevision(r.production_revision_id)}>
            {r.option_id} v{r.baseline?.revision_no} · {BINDING_LABEL[r.binding_status || ""] ?? r.binding_status}
          </button>
          <small> 任务 {(r.job_id || "").slice(-6)} · 模型 {String(r.baseline?.model_hash).slice(0, 8)}</small>
        </li>)}
      </ul>
    </div>}
    {!revision ? <p className="files-empty">尚无同源成果；选择修订后生成。</p> : <div className="spatial-output">
      <div className="spatial-output-head">
        <strong data-testid="spatial-binding">{revision.option_id} v{revision.baseline?.revision_no} · {BINDING_LABEL[revision.binding_status || ""] ?? revision.binding_status}</strong>
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
      <table className="ledger-table" data-testid="spatial-quantities"><thead><tr><th>数量</th><th>数值</th><th>单位</th><th>状态</th></tr></thead>
        <tbody>{revision.quantities.items.map((q) => <tr key={q.quantity_id} data-quantity={q.quantity_id}>
          <td>{q.name}{q.engineering_status === "geometric_only_not_a_finish_quantity" && <small> · 非工程量</small>}</td>
          <td>{q.value === null ? "unknown" : q.value}</td><td>{q.unit}</td><td>{q.known_status}</td>
        </tr>)}</tbody></table>
      <p className="ai-boundary">面积对账：模型自报合计与精确多边形几何净量差 {revision.quantities.declared_vs_exact_delta_m2} ㎡；包围盒仅供对照，不用于计量。</p>
      <div className="spatial-missing"><strong>缺项（不编数值）</strong><ul>{revision.package?.missing?.map((m) => <li key={m}>{m}</li>)}</ul></div>
      <div className="spatial-downloads">
        {["plan.svg", "render.png", "quantity.csv", "cost.html", "package.zip", "manifest.json"].filter((name) =>
          status?.artifacts.some((a) => a.filename === name) || name === "render.png").map((name) =>
          <a key={name} href={`${downloadBase}/${name}`} target="_blank" rel="noreferrer">{name}</a>)}
      </div>
      <div data-testid="spatial-cost">
        <strong>成本（草案，非报价）</strong>
        {revision.cost.known_items.length === 0
          ? <p className="ai-boundary">没有金额：面积依据或价源缺失，金额保持 unknown，不是 0。</p>
          : <table className="ledger-table"><thead><tr><th>项目</th><th>面积</th><th>假设单价</th><th>金额</th><th>面积依据</th></tr></thead>
            <tbody>{revision.cost.known_items.map((i) => <tr key={i.item}>
              <td>{i.item}</td><td>{i.quantity_m2} ㎡</td><td>{i.unit_price_cny}</td>
              <td>{i.amount_cny}</td><td>{i.area_basis_source}</td>
            </tr>)}</tbody></table>}
        {revision.cost.known_items.length > 0 &&
          <p className="ai-boundary">以上为假设单价试算（合计 {revision.cost.assumption_trial_total_cny} 元），面积依据与单价假设同时列出；不是报价，不含损耗/工艺/税。</p>}
        <ul>{revision.cost.unknown_items.map((u) => <li key={u.statement}>{u.statement} · {u.impact}</li>)}</ul>
      </div>
      {revision.package?.package_check && <p className="ai-boundary" data-testid="spatial-package-check">
        交付包自检：{revision.package.package_check.ok ? "通过" : "未通过"} ·
        清单 {revision.package.package_check.checked} 个文件全部在 ZIP 内且字节一致
      </p>}
    </div>}
  </section>;
}
