import { ReviewTasks } from './ReviewTasks';
import { useEffect, useState } from "react";
import { Download, Save } from "lucide-react";
import { apiHeaders, checkSessionResponse } from "./session";

type Settings = { version: number; unit_cost_net: string | null; cost_markup: string; trial_tax_rate: string; source_label: string; include_aisle: boolean; material_specification: string | null; supplier_name: string | null; delivery_location: string | null };
type Artifact = { artifact_id: string; artifact_kind: string; filename: string; download_url: string };
type Production = { production_revision_id: string; revision_no: number; status: string; baseline: { design_revision_no: number; requirement_revision_no: number; boundary_source: string }; settings: Settings; quantities: { quantity_item_id: string; object_id: string; description: string; quantity: string; unit: string }[]; quote: { quantity: string; cost_net: string | null; sale_gross: string | null; tax: string | null }; procurement: { status: string; order_id: string | null }; artifacts: Artifact[] };
type Result = { settings: Settings; item: Production | null; revisions: { revision_no: number; created_at: string }[] };
const defaults: Settings = { version: 0, unit_cost_net: null, cost_markup: "0.2", trial_tax_rate: "0.05", source_label: "unknown", include_aisle: false, material_specification: null, supplier_name: null, delivery_location: null };
const money = (value: string | null) => value === null ? "未知" : new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY" }).format(Number(value));
const artifactNames: Record<string, string> = { quantity_csv: "工程量清单", quotation_html: "量价报告", procurement_json: "采购草稿", production_json: "生产快照", layout_svg: "同源分区图 SVG", layout_dxf: "同源分区图 DXF", manifest_json: "版本清单", package_zip: "完整生产包" };

async function request<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(path, { method, headers: { ...apiHeaders, "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  checkSessionResponse(response);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.message ?? `请求失败（${response.status}）`);
  return payload;
}

export function ProductionPanel({ projectId, designRevision = 0, refreshKey = "", onSaved }: { projectId: string; designRevision?: number; refreshKey?: string; onSaved?: () => void }) {
  const base = `/api/v1/projects/${projectId}/production`;
  const [result, setResult] = useState<Result | null>(null);
  const [settings, setSettings] = useState<Settings>(defaults);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [latestNo, setLatestNo] = useState(0);
  const [designNo, setDesignNo] = useState(designRevision);
  const item = result?.item;
  const historical = Boolean(item && item.revision_no !== latestNo);
  const outdated = item?.status === "source_outdated";

  useEffect(() => {
    let active = true;
    setLoading(true); setError(""); setMessage("");
    Promise.all([request<Result>(base), request<{ item: { revision_no: number } | null }>(`/api/v1/projects/${projectId}/design`)]).then(([saved, design]) => {
      if (!active) return;
      setResult(saved); setSettings(saved.settings); setLatestNo(saved.revisions[0]?.revision_no ?? 0); setDesignNo(design.item?.revision_no ?? 0); setLoading(false);
    }).catch((e: Error) => { if (active) { setError(e.message); setLoading(false); } });
    return () => { active = false; };
  }, [base, projectId, designRevision, refreshKey]);

  async function save() {
    setBusy(true); setError(""); setMessage("");
    try {
      const saved = await request<Result>(`${base}/settings`, "PATCH", { expected_version: settings.version, expected_design_revision: designNo, settings });
      setResult(saved); setSettings(saved.settings); setLatestNo(saved.revisions[0]?.revision_no ?? 0);
      setMessage(saved.item ? `量价与采购草稿已更新为 v${saved.item.revision_no}` : "参数已保存，下次保存设计时自动计算");
      onSaved?.();
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function history(revision: string) {
    setBusy(true); setError("");
    try { setResult(await request<Result>(`${base}/revisions/${revision}`)); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function download(artifact: Artifact) {
    setBusy(true); setError("");
    try {
      const response = await fetch(artifact.download_url, { headers: apiHeaders });
      checkSessionResponse(response);
      if (!response.ok) throw new Error((await response.json()).message);
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a"); anchor.href = url; anchor.download = artifact.filename; anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setMessage(`已下载 ${artifact.filename}`);
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  function field(key: "source_label" | "material_specification" | "supplier_name" | "delivery_location", value: string) {
    setSettings((current) => ({ ...current, [key]: value || (key === "source_label" ? "unknown" : null) }));
  }
  return <section className="production-panel" aria-label="设计生产链" aria-busy={busy || loading}>
    <div className="section-heading"><div><h3>设计 → 量价 → 采购草稿</h3><p className="operation-intro">保存布局后自动更新，面积来自同一设计版本。材料损耗待核对，草稿按净工程量编制。</p></div>
      {item && <label className="production-history">生产版本<select aria-label="查看生产修订" value={item.revision_no} disabled={busy} onChange={(e) => void history(e.target.value)}>{result?.revisions.map((revision) => <option key={revision.revision_no} value={revision.revision_no}>v{revision.revision_no}</option>)}</select></label>}
    </div>
    {error && <p className="design-feedback error" role="alert">{error}</p>}
    {message && <p className="design-feedback" role="status">{message}</p>}
    {loading ? <p className="files-empty">正在读取生产草稿…</p> : <>
      {item ? <>
        <div className="design-baseline"><span>生产 v{item.revision_no} / 设计 v{item.baseline.design_revision_no} / 需求 v{item.baseline.requirement_revision_no}</span><strong>{historical ? "历史版本" : outdated ? "需求已更新 · 请先重新保存设计" : "计算草稿 · 未批准"}</strong></div>
        <div className="production-totals"><div><span>地坪净工程量</span><strong>{item.quote.quantity} <small>m²</small></strong></div><div><span>未税成本</span><strong>{money(item.quote.cost_net)}</strong></div><div><span>含税报价草稿</span><strong>{money(item.quote.sale_gross)}</strong></div></div>
        <p className="production-scope">{item.settings.include_aisle ? "范围：功能分区及预留通道" : "范围：功能分区，不含预留通道"}；未分配区域不计入。{item.baseline.boundary_source === "test_parameters_not_site_verified" ? "来源为测试边界参数。" : "来源为人工边界草稿，待现场核验。"}</p>
        <div className="production-quantities" role="list">{item.quantities.map((quantity) => <div role="listitem" key={quantity.quantity_item_id}><span>{quantity.description}</span><strong>{quantity.quantity} {quantity.unit}</strong></div>)}</div>
        <p className="production-procurement-status">{item.procurement.status === "order_draft_created" ? "采购订单草稿已自动生成，可在采购施工页查看和登记后续事实。" : item.procurement.status === "requires_reconciliation" ? "已有收货或分派记录。最新需求清单已生成，请负责人核对差量后处理，系统未重复生成订单。" : "采购需求已按工程量生成；补全材料规格、供应商和到货地点后，将自动形成订单草稿。"}</p>
        <div className="production-downloads">{item.artifacts.filter((a) => ["package_zip", "quantity_csv", "quotation_html"].includes(a.artifact_kind)).map((artifact) => <button type="button" className="outline-action" key={artifact.artifact_id} disabled={busy} onClick={() => void download(artifact)}><Download size={16} />{artifactNames[artifact.artifact_kind]}</button>)}</div>
      </> : <p className="files-empty">保存一版分区设计，即可自动生成地坪工程量。已有历史设计可保存下方参数，接通当前版本。</p>}
      <details className="production-settings"><summary>地坪范围、价格与采购信息{historical ? "（查看历史时不可修改）" : ""}</summary>
        <form onSubmit={(e) => { e.preventDefault(); void save(); }}>
          <fieldset disabled={busy || historical || outdated}>
            <legend>保存一次，后续设计修订沿用这些参数</legend>
            <label className="production-checkbox"><input type="checkbox" checked={settings.include_aisle} onChange={(e) => setSettings((current) => ({ ...current, include_aisle: e.target.checked }))} />计入预留通道地坪</label>
            <div className="design-fields">
              <label>未税单位成本（元/m²）<input type="number" min="0" step="0.000001" placeholder="未知" value={settings.unit_cost_net ?? ""} onChange={(e) => setSettings((current) => ({ ...current, unit_cost_net: e.target.value || null }))} /></label>
              <label>施工成本加成率（%）<input type="number" required min="0" max="1000" step="0.0001" value={Number(settings.cost_markup) * 100} onChange={(e) => setSettings((current) => ({ ...current, cost_markup: String(Number(e.target.value) / 100) }))} /></label>
              <label>试用税率（%）<input type="number" required min="0" max="100" step="0.0001" value={Number(settings.trial_tax_rate) * 100} onChange={(e) => setSettings((current) => ({ ...current, trial_tax_rate: String(Number(e.target.value) / 100) }))} /></label>
              <label>成本来源<input maxLength={500} placeholder="例如：人工试算成本" value={settings.source_label === "unknown" ? "" : settings.source_label} onChange={(e) => field("source_label", e.target.value)} /></label>
              <label>地坪材料规格<input maxLength={500} placeholder="待确认" value={settings.material_specification ?? ""} onChange={(e) => field("material_specification", e.target.value)} /></label>
              <label>地坪供应商<input maxLength={500} placeholder="待选择" value={settings.supplier_name ?? ""} onChange={(e) => field("supplier_name", e.target.value)} /></label>
              <label>地坪到货地点<input maxLength={500} placeholder="待确认" value={settings.delivery_location ?? ""} onChange={(e) => field("delivery_location", e.target.value)} /></label>
            </div>
            <p className="production-scope">价格仅用于本地试算；材料规格、损耗和供应商选择需要业务核对，保存草稿不会对外下单。</p>
            <button type="submit" className="dark-action"><Save size={16} />保存参数并更新草稿</button>
          </fieldset>
        </form>
      </details>
      <PreReview projectId={projectId} refreshKey={`${item?.production_revision_id || ''}:${item?.status || ''}`} />
    </>}
  </section>;
}

function PreReview({ projectId, refreshKey }: { projectId: string; refreshKey: string }) {
  type Report = { checked_at: string; evidence_sha256: string; baseline: { production_revision_no: number } | null; checks: { code: string; label: string; status: string }[]; pending_professional_reviews: { code: string; label: string; status: string }[]; formal_release_allowed: boolean; engineering_checks_passed: boolean };
  const [submitted, setSubmitted] = useState(0);
  const [submitBusy, setSubmitBusy] = useState(false);
  const [submitMessage, setSubmitMessage] = useState('');
  const [report, setReport] = useState<Report | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { setReport(null); setError(''); setSubmitMessage(''); }, [projectId, refreshKey]);
  useEffect(() => {
    let active = true;
    if (!busy) return;
    request<Report>(`/api/v1/projects/${projectId}/review-readiness`).then(value => { if (active) setReport(value); }).catch(e => { if (active) setError(e.message); }).finally(() => { if (active) setBusy(false); });
    return () => { active = false; };
  }, [busy, projectId, refreshKey]);
  function download() {
    const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2)], { type: 'application/json' }));
    const a = document.createElement('a'); a.href = url; a.download = 'pre-review.json'; a.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <section aria-label="送审前检查">
    <h4>送审前检查</h4><p>检查当前生产版本和文件完整性，列出待专业核验事项。检查结果不授予正式报价或施工发布权限。</p>
    <button type="button" disabled={busy} onClick={() => { setError(''); setReport(null); setBusy(true); }}>{busy ? '正在检查…' : '检查当前生产草稿'}</button>
    {error && <p role="alert">{error}</p>}
    {report && <><p role="status">生产版本：{report.baseline ? `v${report.baseline.production_revision_no}` : '尚无'}；检查时间：{new Date(report.checked_at).toLocaleString('zh-CN')}。正式发布：未开放。</p>
      <ul>{[...report.checks, ...report.pending_professional_reviews].map(check => <li key={check.code}>{check.label}：{check.status === 'passed' ? '通过' : check.status === 'blocked' ? '需处理' : check.status === 'unknown' ? '未核验' : '待指定责任与权限'}</li>)}</ul>
      <button type="button" hidden={Boolean(apiHeaders["X-Organization-Id"])} disabled={!report.engineering_checks_passed || submitBusy} onClick={() => {
        setSubmitBusy(true); setError(''); setSubmitMessage('');
        void request(`/api/v1/projects/${projectId}/review-tasks`, 'POST', { evidence_sha256: report.evidence_sha256 })
          .then(() => { setSubmitted(v => v + 1); setSubmitMessage('草稿审查事项已建立。分派结果见下方记录，等待人员配置不计为已送达。'); })
          .catch(e => setError(e.message)).finally(() => setSubmitBusy(false));
      }}>{submitBusy ? '正在送审…' : '按岗位提交草稿审查'}</button>
      <button type="button" onClick={download}>下载本次检查记录 JSON</button>
    </>}
    {submitMessage && <p role="status">{submitMessage}</p>}
    {!apiHeaders["X-Organization-Id"] && <ReviewTasks key={projectId} projectId={projectId} refreshKey={`${refreshKey}:${submitted}`} />}
  </section>;
}
