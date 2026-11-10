import { useEffect, useState } from "react";
import { apiHeaders, checkSessionResponse } from "./session";

type Program = { scenario: string; boundary_source: string; width: string; length: string; aisle_width: string; zones: { zone_id: string; name: string; min_area_m2: string }[] };
type Quote = { quantity: string; cost_net: string | null; sale_gross: string | null };
type Model = { width: string; length: string; zones: { zone_id: string; name: string; x: string; y: string; width: string; length: string; area_m2: string }[] };
type Change = { change_id: string; change_no: number; title: string; reason: string; description: string; version: number; status: string; proposal: { design_program?: Program }; impact: { quantity_delta_m2?: string; cost_delta_net?: string | null; quote_before?: Quote; quote_after?: Quote; preview?: { model: Model }; reproduction?: { requirement_revision_no: number; design_revision_no: number; production_revision_no: number } }; artifacts: { artifact_id: string; filename: string }[]; acceptances: { evidence_ref: string; conclusion: string }[] };
const labels: Record<string, string> = { draft: "待计算", analyzed: "待负责人复核", accepted: "复核通过", rejected: "已拒绝", rework: "需修改后重新提出" };
const money = (value?: string | null) => value == null ? "未知" : new Intl.NumberFormat("zh-CN", { style: "currency", currency: "CNY" }).format(Number(value));
async function request<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(path, { method, headers: { ...apiHeaders, "Content-Type": "application/json", ...(method === "POST" ? { "Idempotency-Key": `ui-model-change-${crypto.randomUUID()}` } : {}) }, body: body === undefined ? undefined : JSON.stringify(body) });
  checkSessionResponse(response);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.message ?? `请求失败（${response.status}）`);
  return payload;
}

function Review({ change, busy, manager, canEdit, onAction }: { change: Change; busy: boolean; manager: boolean; canEdit: boolean; onAction: (action: string, change: Change, body?: object) => Promise<void> }) {
  const [evidence, setEvidence] = useState("");
  const [note, setNote] = useState("");
  const [checked, setChecked] = useState(false);
  const [conclusion, setConclusion] = useState("accepted");
  const impact = change.impact;
  const model = impact.preview?.model;
  return <article className="procurement-card model-change-card">
    <div className="section-heading"><div><strong>变更 {change.change_no} · {change.title}</strong><small>{change.reason}</small></div><span className="saved-tag">{impact.reproduction ? "新草稿已生成" : labels[change.status] ?? change.status}</span></div>
    <p>{change.description}</p>
    {impact.quote_after && <>
      <div className="change-comparison"><div><span>地坪净工程量</span><strong>{impact.quote_before?.quantity} → {impact.quote_after.quantity} m²</strong><small>变化 {impact.quantity_delta_m2} m²</small></div><div><span>未税成本</span><strong>{money(impact.quote_before?.cost_net)} → {money(impact.quote_after.cost_net)}</strong><small>变化 {money(impact.cost_delta_net)}</small></div><div><span>含税报价草稿</span><strong>{money(impact.quote_before?.sale_gross)} → {money(impact.quote_after.sale_gross)}</strong><small>沿用分析时的范围、加成及试用税率</small></div></div>
      {model && <details className="change-preview" open={change.status === "analyzed"}><summary>查看候选分区与面积 · 规则生成</summary><svg viewBox={`0 0 ${model.width} ${model.length}`} role="img" aria-label={`变更 ${change.change_no} 候选分区图`}><rect width={model.width} height={model.length} fill="#f0f2ed" stroke="#65715e" strokeWidth="0.04" />{model.zones.map((zone, index) => <g key={zone.zone_id}><rect x={zone.x} y={zone.y} width={zone.width} height={zone.length} fill={index % 2 ? "#dce8c9" : "#e9e7d6"} stroke="#65715e" strokeWidth="0.03" /><text x={Number(zone.x) + Number(zone.width) / 2} y={Number(zone.y) + Number(zone.length) / 2} fontSize="0.38" textAnchor="middle">{zone.name}</text></g>)}</svg><div className="production-quantities">{model.zones.map((zone) => <div key={zone.zone_id}><span>{zone.name}</span><strong>{zone.area_m2} m²</strong></div>)}</div><p className="operation-intro">{impact.reproduction ? "这是已复核并用于生成新设计的分析候选图。" : "候选图尚未保存为设计版本。"}现场、消防及结构条件仍待专业核验。</p></details>}
    </>}
    {change.status === "draft" && <button type="button" disabled={busy || !canEdit} onClick={() => void onAction("analyze", change)}>计算变更影响</button>}
    {change.status === "analyzed" && (manager ? <form className="change-review-form" onSubmit={(event) => { event.preventDefault(); void onAction("acceptance", change, { conclusion, checklist: ["候选分区、计量范围和量价差额已复核"], evidence_ref: evidence, note }); }}><label className="production-checkbox"><input required type="checkbox" checked={checked} disabled={busy} onChange={(event) => setChecked(event.target.checked)} />已复核候选分区、计量范围和量价差额</label><div className="edit-row"><label>复核证据<input required value={evidence} disabled={busy} onChange={(event) => setEvidence(event.target.value)} placeholder="现场记录或评审文件编号" /></label><label>责任人备注<input value={note} disabled={busy} onChange={(event) => setNote(event.target.value)} /></label><label>复核结论<select value={conclusion} disabled={busy} onChange={(event) => setConclusion(event.target.value)}><option value="accepted">通过，可生成新草稿</option><option value="rework">需修改</option><option value="rejected">拒绝</option></select></label><button type="submit" disabled={busy || !checked || !evidence.trim()}>记录复核结论</button></div></form> : <p className="operation-intro">等待项目负责人记录复核结论。</p>)}
    {change.status === "accepted" && !impact.reproduction && <div className="section-actions">{manager ? <button type="button" disabled={busy} onClick={() => void onAction("reproduce", change)}>生成新设计与量价草稿</button> : <p>等待项目负责人生成新草稿。</p>}<small>使用已复核的候选尺寸；如基线变化，将拒绝应用旧结论。</small></div>}
    {impact.reproduction && <p className="design-feedback" role="status">已生成需求 v{impact.reproduction.requirement_revision_no} → 设计 v{impact.reproduction.design_revision_no} → 生产 v{impact.reproduction.production_revision_no}。可在上方下载新生产包；专业批准和正式发布仍待执行。</p>}
    {change.artifacts.length > 0 && <div className="artifact-list">{change.artifacts.map((artifact) => <button key={artifact.artifact_id} type="button" disabled={busy} onClick={() => void onAction(`download/${artifact.artifact_id}`, change, { filename: artifact.filename })}>下载 {artifact.filename}</button>)}</div>}
    {change.acceptances.length > 0 && <p className="operation-intro">复核证据：{change.acceptances.at(-1)?.evidence_ref}</p>}
  </article>;
}

export function ChangeProductionPanel({ projectId, role, refreshKey, onSaved }: { projectId: string; role?: string; refreshKey: string; onSaved: () => void }) {
  const base = `/api/v1/projects/${projectId}`;
  const [program, setProgram] = useState<Program | null>(null);
  const [designNo, setDesignNo] = useState(0);
  const [items, setItems] = useState<Change[]>([]);
  const [form, setForm] = useState({ title: "", reason: "", description: "" });
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const manager = role === undefined || role === "manager";
  async function load() {
    const [req, design, changes] = await Promise.all([request<{ item: { content: { design_program?: Program } } | null }>(`${base}/requirements`), request<{ item: { revision_no: number } | null }>(`${base}/design`), request<{ items: Change[] }>(`${base}/changes`)]);
    return { program: req.item?.content.design_program ?? null, designNo: design.item?.revision_no ?? 0, items: changes.items.filter((change) => change.proposal.design_program) };
  }
  function apply(saved: Awaited<ReturnType<typeof load>>) { setProgram(saved.program); setDesignNo(saved.designNo); setItems(saved.items); }
  useEffect(() => {
    let active = true;
    setLoading(true); setError(""); setMessage("");
    load().then((saved) => { if (active) { apply(saved); setLoading(false); } }).catch((e: Error) => { if (active) { setError(e.message); setLoading(false); } });
    return () => { active = false; };
  }, [base, refreshKey]);
  async function act(action: string, change: Change, body: object = {}) {
    setBusy(true); setError(""); setMessage("");
    try {
      if (action.startsWith("download/")) {
        const response = await fetch(`${base}/changes/artifacts/${action.slice(9)}/content`, { headers: apiHeaders });
        checkSessionResponse(response);
        if (!response.ok) throw new Error((await response.json()).message);
        const url = URL.createObjectURL(await response.blob());
        const anchor = document.createElement("a"); anchor.href = url; anchor.download = (body as { filename: string }).filename; anchor.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
        setMessage("分析文件已下载");
      } else {
        await request(`${base}/changes/${change.change_id}/${action}`, "POST", { expected_version: change.version, ...body });
        apply(await load());
        if (action === "reproduce") onSaved();
        else setMessage(action === "analyze" ? "影响分析已生成，请复核候选图及量价差额" : "责任人的复核结论已保存");
      }
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function create() {
    setBusy(true); setError(""); setMessage("");
    try {
      await request(`${base}/changes`, "POST", { ...form, design_program: program });
      setForm({ title: "", reason: "", description: "" }); apply(await load()); setMessage("尺寸变更已保存，请计算影响后复核");
    } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  return <section className="change-production-panel" aria-label="尺寸变更与再生产" aria-busy={busy || loading}>
    <div className="section-heading"><div><h3>尺寸变更 → 复核 → 新设计与量价</h3><p className="operation-intro">以当前设计为基线，重新生成规则分区，沿用已保存的地坪价格和采购参数。旧成果保留。</p></div><button className="outline-action" type="button" disabled={busy || loading} onClick={() => { setBusy(true); load().then(apply).catch((e: Error) => setError(e.message)).finally(() => setBusy(false)); }}>刷新基线</button></div>
    {error && <p className="design-feedback error" role="alert">{error}</p>}{message && <p className="design-feedback" role="status">{message}</p>}
    {loading ? <p className="files-empty">正在读取设计与变更…</p> : <>
      {program && designNo > 0 ? role !== "viewer" && <details className="production-settings"><summary>提出尺寸变更 · 当前设计 v{designNo}</summary><form onSubmit={(event) => { event.preventDefault(); void create(); }}><fieldset disabled={busy}><legend>功能区名称与最小面积沿用当前需求，分区位置按新尺寸重新计算</legend><div className="edit-row"><label>变更标题<input required value={form.title} onChange={(event) => setForm((current) => ({ ...current, title: event.target.value }))} /></label><label>变更原因<input required value={form.reason} onChange={(event) => setForm((current) => ({ ...current, reason: event.target.value }))} /></label><label>变更说明<input required value={form.description} onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))} /></label></div><div className="edit-row">{([['width', '变更后外框宽度（m）'], ['length', '变更后外框长度（m）'], ['aisle_width', '变更后通道宽度（m）']] as const).map(([key, label]) => <label key={key}>{label}<input type="number" required min="0.001" step="0.001" value={program[key]} onChange={(event) => setProgram({ ...program, [key]: event.target.value })} /></label>)}<button type="submit">保存尺寸变更</button></div></fieldset></form></details> : <p className="files-empty">先在需求与设计页保存一版设计，再提出尺寸变更。</p>}
      <div className="change-list">{items.map((change) => <Review key={change.change_id} change={change} busy={busy} manager={manager} canEdit={role !== "viewer"} onAction={act} />)}</div>
    </>}
  </section>;
}
