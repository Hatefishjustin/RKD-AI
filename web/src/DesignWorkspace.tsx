import { useEffect, useState } from "react";
import { CheckCircle2, Download, FilePlus2, Plus, RefreshCw, Save, Trash2 } from "lucide-react";
import { apiHeaders, checkSessionResponse } from "./session";
import { AiRequirementPanel } from "./AiRequirementPanel";
import { AiDesignOptionsPanel } from "./AiDesignOptionsPanel";
import { AiSpatialOutputsPanel } from "./AiSpatialOutputsPanel";
import { AiDevelopmentPanel } from "./AiDevelopmentPanel";
import { AiSourceDeliveryPanel } from "./AiSourceDeliveryPanel";
import { ProductionPanel } from "./ProductionPanel";

type ZoneRequest = { zone_id: string; name: string; min_area_m2: string };
type Program = { scenario: string; boundary_source: string; width: string; length: string; aisle_width: string; zones: ZoneRequest[] };
type Requirement = { requirement_id: string; revision_no: number; input_hash: string; source_refs: { type: string; key?: string; filename?: string; file_id?: string; source?: string; source_conflict?: string | null }[]; content: { budget: Record<string, string>; scope: Record<string, string | string[]>; open_questions: string[]; design_program?: Program; design_notes?: string } };
type Zone = { zone_id: string; name: string; x: string; y: string; width: string; length: string; area_m2: string; min_area_m2: string };
type Model = { width: string; length: string; aisle_width: string; zones: Zone[]; total_area_m2: string; zone_area_m2: string; aisle_area_m2: string; unassigned_area_m2: string };
type Artifact = { artifact_id: string; artifact_kind: string; filename: string; size_bytes: number; sha256: string; status: string; download_url: string };
type Check = { code: string; status: string; message: string };
type Design = { design_revision_id: string; revision_no: number; requirement_revision_no: number; status: string; model: Model; validation: { hard_checks: Check[]; professional_checks: Check[]; rule_version: string }; artifacts: Artifact[]; source_kind: string; change_reason: string; actor_id: string };
type Revision = { revision_no: number; requirement_revision_no: number; source_kind: string; change_reason: string; created_at: string };

const initialProgram: Program = { scenario: "showroom", boundary_source: "test_parameters_not_site_verified", width: "12", length: "8", aisle_width: "1.5", zones: [
  { zone_id: "reception", name: "接待区", min_area_m2: "12" }, { zone_id: "display", name: "展示区", min_area_m2: "24" }, { zone_id: "discussion", name: "洽谈区", min_area_m2: "12" },
] };
const statusNames: Record<string, string> = { draft: "设计草稿 · 未批准", superseded: "旧版成果", source_outdated: "需求已更新 · 待重新生成" };
const artifactNames: Record<string, string> = { layout_svg: "分区图 SVG", layout_dxf: "分区图 DXF", zone_csv: "分区面积清单", model_json: "模型与需求快照", report_html: "设计检查报告", manifest_json: "成果版本清单", package_zip: "完整成果包 ZIP" };

async function request<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(path, { method, headers: { ...apiHeaders, "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
  checkSessionResponse(response);
  const result = await response.json();
  if (!response.ok) throw new Error(result.message ?? `请求失败 (${response.status})`);
  return result;
}

export function DesignWorkspace({ projectId, onRequirementSaved }: { projectId: string; onRequirementSaved: () => void }) {
  const base = `/api/v1/projects/${projectId}`;
  const [mode, setMode] = useState<"requirements" | "options" | "development" | "delivery" | "layout" | "outputs" | "spatial-outputs">("requirements");
  const [requirement, setRequirement] = useState<Requirement | null>(null);
  const [program, setProgram] = useState<Program>(structuredClone(initialProgram));
  const [notes, setNotes] = useState("");
  const [reason, setReason] = useState("保存展厅功能需求草稿");
  const [design, setDesign] = useState<Design | null>(null);
  const [model, setModel] = useState<Model | null>(null);
  const [revisions, setRevisions] = useState<Revision[]>([]);
  const [latestNo, setLatestNo] = useState(0);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [selectedZone, setSelectedZone] = useState("");
  const dirty = Boolean(requirement && (JSON.stringify(program) !== JSON.stringify(requirement.content.design_program ?? initialProgram) || notes !== (requirement.content.design_notes ?? "")));
  const modelDirty = Boolean(model && design && JSON.stringify(model) !== JSON.stringify(design.model));
  const historical = Boolean(design && design.revision_no !== latestNo);

  function applyRequirement(value: Requirement | null) {
    setRequirement(value);
    setProgram(structuredClone(value?.content.design_program ?? initialProgram));
    setNotes(value?.content.design_notes ?? "");
  }
  function applyDesign(value: Design | null) {
    setDesign(value); setModel(value ? structuredClone(value.model) : null);
    setSelectedZone(value?.model.zones[0]?.zone_id ?? "");
  }
  useEffect(() => {
    let active = true;
    Promise.all([request<{ item: Requirement | null }>(`${base}/requirements`), request<{ item: Design | null; revisions: Revision[] }>(`${base}/design`)]).then(([r, d]) => {
      if (!active) return;
      applyRequirement(r.item); applyDesign(d.item); setRevisions(d.revisions); setLatestNo(d.revisions[0]?.revision_no ?? 0); setLoading(false);
    }).catch((e: Error) => { if (active) { setError(e.message); setLoading(false); } });
    return () => { active = false; };
  }, [base]);

  async function act(action: () => Promise<void>) {
    setBusy(true); setError(""); setMessage("");
    try { await action(); } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function saveRequirement() {
    await act(async () => {
      const draft = requirement ?? (await request<{ item: Requirement }>(`${base}/requirements/drafts`, "POST", {})).item;
      const saved = await request<{ item: Requirement }>(`${base}/requirements`, "PATCH", { expected_revision: draft.revision_no, design_program: program, design_notes: notes, change_reason: reason });
      applyRequirement(saved.item);
      const refreshed = await request<{ item: Design | null; revisions: Revision[] }>(`${base}/design`);
      applyDesign(refreshed.item); setRevisions(refreshed.revisions); setLatestNo(refreshed.revisions[0]?.revision_no ?? 0);
      onRequirementSaved(); setMessage(`需求已保存为 v${saved.item.revision_no}`);
    });
  }
  async function saveDesign(generate: boolean) {
    if (!requirement) return;
    await act(async () => {
      const saved = await request<{ item: Design }>(`${base}/design/revisions`, "POST", { expected_revision: latestNo, requirement_revision_no: requirement.revision_no, change_reason: reason, ...(generate ? {} : { model }) });
      applyDesign(saved.item);
      const refreshed = await request<{ item: Design; revisions: Revision[] }>(`${base}/design`);
      setRevisions(refreshed.revisions); setLatestNo(refreshed.item.revision_no); setMode("layout");
      setMessage(`设计 v${saved.item.revision_no} 已保存，生成 ${saved.item.artifacts.length} 份成果`);
    });
  }
  async function loadRevision(value: string) {
    await act(async () => {
      const r = await request<{ item: Design }>(`${base}/design/revisions/${value}`);
      applyDesign(r.item);
    });
  }
  async function download(artifact: Artifact) {
    await act(async () => {
      const response = await fetch(artifact.download_url, { headers: apiHeaders });
      checkSessionResponse(response);
      if (!response.ok) { const failure = await response.json(); throw new Error(failure.message); }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob), anchor = document.createElement("a");
      anchor.href = url; anchor.download = artifact.filename; anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setMessage(`已下载 ${artifact.filename}`);
    });
  }
  async function openSource(fileId: string) {
    await act(async () => {
      const files = await request<{ items: { file_id: string; download_url: string }[] }>(`${base}/files`);
      const file = files.items.find((item) => item.file_id === fileId);
      if (!file) throw new Error("来源原件未找到");
      window.open(file.download_url, "_blank", "noopener");
    });
  }
  function updateZone(id: string, key: "x" | "y" | "width" | "length", value: string) {
    setModel((m) => m ? { ...m, zones: m.zones.map((z) => z.zone_id === id ? { ...z, [key]: value } : z) } : m);
  }

  const selected = model?.zones.find((z) => z.zone_id === selectedZone);
  const width = Math.max(1, Number(model?.width ?? 12));
  const length = Math.max(1, Number(model?.length ?? 8));
  return <section className="design-workspace" aria-busy={busy || loading}>
    <header className="section-heading"><h2>展厅设计草稿</h2><span className="design-status">规则生成 · 待人工确认</span></header>
    <nav className="design-modes" aria-label="设计流程">{(["requirements", "options", "spatial-outputs", "development", "delivery", "layout", "outputs"] as const).map((tab) => <button key={tab} className={mode === tab ? "active" : ""} onClick={() => setMode(tab)}>{tab === "requirements" ? "需求" : tab === "options" ? "AI 候选" : tab === "spatial-outputs" ? "同源成果" : tab === "development" ? "深化量价" : tab === "delivery" ? "资料与技术交付" : tab === "layout" ? "分区布局" : "成果与历史"}</button>)}</nav>
    {error && <p className="design-feedback error" role="alert">{error}</p>}
    {message && <p className="design-feedback" role="status">{message}</p>}
    {loading ? <p className="files-empty">正在读取设计数据...</p> : mode === "requirements" ? <>
      <AiRequirementPanel projectId={projectId} />
      <div className="design-baseline"><span>需求 {requirement ? `v${requirement.revision_no}` : "未保存"}</span><span>边界：{program.boundary_source === "test_parameters_not_site_verified" ? "测试参数" : "人工草稿"} · 未经现场核验</span>{dirty && <strong>有未保存修改</strong>}</div>
      <form onSubmit={(e) => { e.preventDefault(); void saveRequirement(); }} className="design-program">
        <div className="design-fields">
          <label>边界来源<select value={program.boundary_source} onChange={(e) => setProgram((p) => ({ ...p, boundary_source: e.target.value }))}><option value="test_parameters_not_site_verified">测试参数</option><option value="manual_boundary_not_site_verified">人工边界草稿</option></select></label>
          {(["width", "length", "aisle_width"] as const).map((k) => <label key={k}>{k === "width" ? "外框宽度（m）" : k === "length" ? "外框长度（m）" : "预留通道宽度（m）"}<input type="number" required min="0.001" max="500" step="0.001" value={program[k]} onChange={(e) => setProgram((p) => ({ ...p, [k]: e.target.value }))} /></label>)}
        </div>
        <div className="design-subheading"><h3>功能分区</h3><button type="button" className="icon-action" title="新增分区" aria-label="新增分区" disabled={program.zones.length >= 12} onClick={() => setProgram((p) => ({ ...p, zones: [...p.zones, { zone_id: `zone-${crypto.randomUUID().slice(0, 8)}`, name: "新分区", min_area_m2: "10" }] }))}><Plus size={18} /></button></div>
        <div className="design-zone-requests">{program.zones.map((z, i) => <div className="design-zone-request" key={z.zone_id}><label>分区名称<input required maxLength={60} value={z.name} onChange={(e) => setProgram((p) => ({ ...p, zones: p.zones.map((v, j) => i === j ? { ...v, name: e.target.value } : v) }))} /></label><label>最小面积（m²）<input type="number" required min="0.001" step="0.001" value={z.min_area_m2} onChange={(e) => setProgram((p) => ({ ...p, zones: p.zones.map((v, j) => i === j ? { ...v, min_area_m2: e.target.value } : v) }))} /></label><button type="button" className="icon-action" title={`删除 ${z.name}`} aria-label={`删除 ${z.name}`} disabled={program.zones.length <= 1} onClick={() => setProgram((p) => ({ ...p, zones: p.zones.filter((v) => v.zone_id !== z.zone_id) }))}><Trash2 size={16} /></button></div>)}</div>
        <label className="design-notes">设计备注<textarea rows={3} maxLength={4000} value={notes} onChange={(e) => setNotes(e.target.value)} /></label>
        <div className="design-command-row"><label>修订理由<input required maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} /></label><button type="submit" className="dark-action" disabled={busy}><Save size={16} />保存需求草稿</button><button type="button" className="outline-action" disabled={busy || dirty || !requirement?.content.design_program} onClick={() => void saveDesign(true)}><FilePlus2 size={16} />生成分区布局</button></div>
      </form>
      {requirement && <details className="design-evidence"><summary>已保存的业务口径与来源（{requirement.source_refs.length} 条）</summary><dl className="design-facts"><div><dt>合同含税目标</dt><dd>{requirement.content.budget.contract_target_gross_cny === "unknown" ? "未知" : `¥${requirement.content.budget.contract_target_gross_cny}`}</dd></div><div><dt>试用税率</dt><dd>{requirement.content.budget.tax_rate}</dd></div><div><dt>排除范围</dt><dd>{Array.isArray(requirement.content.scope.excluded_scopes) ? requirement.content.scope.excluded_scopes.join("、") : String(requirement.content.scope.excluded_scopes)}</dd></div></dl><ul>{requirement.source_refs.map((ref, i) => <li key={i}>{ref.file_id ? <button type="button" onClick={() => void openSource(ref.file_id!)}>{ref.filename}</button> : <span>{ref.key} · {ref.source}</span>}{ref.source_conflict && <small>来源口径冲突：{ref.source_conflict}</small>}</li>)}</ul></details>}
    </> : mode === "options" ? <AiDesignOptionsPanel projectId={projectId} /> : mode === "spatial-outputs" ? <AiSpatialOutputsPanel projectId={projectId} /> : mode === "development" ? <AiDevelopmentPanel projectId={projectId} /> : mode === "delivery" ? <AiSourceDeliveryPanel projectId={projectId} /> : mode === "layout" ? !design || !model ? <div className="files-empty">尚无分区布局 <button className="outline-action" onClick={() => setMode("requirements")}>返回需求</button></div> : <>
      <div className="design-baseline"><span>设计 v{design.revision_no} / 需求 v{design.requirement_revision_no}</span><strong>{statusNames[design.status]}</strong>{modelDirty && <span>预览有未保存修改</span>}</div>
      <div className="design-editor"><div className="design-drawing"><svg viewBox={`-0.6 -0.6 ${width + 1.2} ${length + 1.2}`} role="img" aria-label="展厅功能分区布局" preserveAspectRatio="xMidYMid meet"><rect width={width} height={length} fill="#fff" stroke="#485565" strokeWidth=".025" /><rect width={width} height={Number(model.aisle_width)} fill="#f1f3f5" /><text x={width / 2} y={Number(model.aisle_width) / 2} textAnchor="middle" dominantBaseline="middle" fontSize=".24">预留通道 {model.aisle_width} m</text>{model.zones.map((z, i) => <g key={z.zone_id} tabIndex={0} role="button" aria-label={`选择 ${z.name}`} onClick={() => setSelectedZone(z.zone_id)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSelectedZone(z.zone_id); } }}><rect x={Number(z.x)} y={Number(z.y)} width={Math.max(0, Number(z.width))} height={Math.max(0, Number(z.length))} fill={["#def0e8", "#e8edf8", "#f7ead6", "#f3e3e9"][i % 4]} stroke={selectedZone === z.zone_id ? "#367858" : "#758190"} strokeWidth={selectedZone === z.zone_id ? ".07" : ".018"} /><text x={Number(z.x) + Number(z.width) / 2} y={Number(z.y) + Number(z.length) / 2} textAnchor="middle" fontSize={Math.min(.3, Math.max(.07, Number(z.width) / (z.name.length + 1)))}>{z.name}</text><text x={Number(z.x) + Number(z.width) / 2} y={Number(z.y) + Number(z.length) / 2 + .4} textAnchor="middle" fontSize={Math.min(.23, Math.max(.06, Number(z.width) / 9))}>{(Number(z.width) * Number(z.length)).toFixed(2)} m²</text></g>)}</svg><div className="drawing-caption">{model.width} × {model.length} m · 功能分区草稿 · 未批准</div></div>
      <aside className="design-inspector"><label>选择分区<select value={selectedZone} onChange={(e) => setSelectedZone(e.target.value)}>{model.zones.map((z) => <option key={z.zone_id} value={z.zone_id}>{z.name}</option>)}</select></label>{selected && <><small>对象 ID：{selected.zone_id}</small>{(["x", "y", "width", "length"] as const).map((k) => <label key={k}>{({ x: "X（m）", y: "Y（m）", width: "分区宽度（m）", length: "分区长度（m）" })[k]}<input type="number" step="0.001" min="0" disabled={historical || design.status === "source_outdated"} value={selected[k]} onChange={(e) => updateZone(selected.zone_id, k, e.target.value)} /></label>)}<p>最小面积 {selected.min_area_m2} m²</p></>}<label>修订理由<input value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} /></label><button type="button" className="dark-action" disabled={busy || historical || !modelDirty || design.status === "source_outdated" || dirty} onClick={() => void saveDesign(false)}><Save size={16} />检查并保存布局</button><button className="outline-action" disabled={busy || dirty || !requirement?.content.design_program} onClick={() => void saveDesign(true)}><RefreshCw size={16} />按当前需求重新生成</button></aside></div>
      <ul className="design-zone-legend">{model.zones.map((z, i) => <li key={z.zone_id}><span className="design-zone-swatch" style={{ background: ["#def0e8", "#e8edf8", "#f7ead6", "#f3e3e9"][i % 4] }} />{z.name}<strong>{(Number(z.width) * Number(z.length)).toFixed(2)} m²</strong></li>)}</ul>
      <div className="design-metrics"><span>已保存分区面积 <strong>{design.model.zone_area_m2} m²</strong></span><span>通道 <strong>{design.model.aisle_area_m2} m²</strong></span><span>未分配 <strong>{design.model.unassigned_area_m2} m²</strong></span></div>
      <div className="design-checks"><h3>已保存版本检查</h3><ul>{design.validation.hard_checks.map((c) => <li key={c.code}><CheckCircle2 size={15} /><span>{c.message}</span></li>)}</ul><div className="design-professional">{design.validation.professional_checks.map((c) => <p key={c.code}>待专业复核：{c.message}</p>)}</div></div>
    </> : <>
      <div className="design-output-heading"><h3>成果版本</h3><label>查看修订<select aria-label="查看设计修订" value={design?.revision_no ?? ""} onChange={(e) => void loadRevision(e.target.value)} disabled={busy || revisions.length === 0}>{!design && <option value="">无成果</option>}{revisions.map((r) => <option key={r.revision_no} value={r.revision_no}>设计 v{r.revision_no} / 需求 v{r.requirement_revision_no}</option>)}</select></label></div>
      {design ? <><div className="design-baseline"><strong>{statusNames[design.status]}</strong><span>{design.change_reason} · {design.actor_id}</span></div><div className="design-artifact-list">{design.artifacts.map((a) => <div className="design-artifact" key={a.artifact_id}><div><strong>{artifactNames[a.artifact_kind]}</strong><small>{a.filename} · {a.size_bytes.toLocaleString()} 字节</small><code>SHA-256 {a.sha256.slice(0, 20)}...</code></div><button type="button" className="icon-action" disabled={busy} title={`下载 ${a.filename}`} aria-label={`下载 ${a.filename}`} onClick={() => void download(a)}><Download size={18} /></button></div>)}</div></> : <p className="files-empty">尚无设计成果</p>}
    </>}
    {mode !== "requirements" && mode !== "options" && mode !== "development" && mode !== "delivery" && !historical && <ProductionPanel projectId={projectId} designRevision={design?.revision_no ?? 0} refreshKey={design?.design_revision_id ?? ""} />}
  </section>;
}
