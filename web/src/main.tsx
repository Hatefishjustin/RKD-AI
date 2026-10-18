import { ChangeEvent, FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Download, Eye, Minus, Plus, Upload, X } from "lucide-react";
import { getDocument, GlobalWorkerOptions } from "pdfjs-dist";
import type { PDFDocumentProxy, RenderTask } from "pdfjs-dist";
import pdfWorkerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import "./styles.css";
import { DesignWorkspace } from "./DesignWorkspace";
import { AccountControls, AccountGate, AccountPanel } from "./AccountAccess";
import { apiHeaders, checkSessionResponse, Session } from "./session";

GlobalWorkerOptions.workerSrc = pdfWorkerUrl;

type Project = {
  organization_id: string;
  project_id: string;
  name: string;
  version: number;
  role?: "manager" | "editor" | "viewer";
};

type FileAsset = {
  file_id: string;
  filename: string;
  kind: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  source_kind: string;
  source_ref: string;
  format_status: string;
  created_at: string;
  revision: number;
  download_url: string;
};

type Decision = { key: string; value: string | string[]; source: string; status: string; source_conflict: string | null };
type Issue = {
  issue_id: string;
  source_file_id: string | null;
  source_ref: string;
  source_locator: string;
  issue_type: string;
  severity: "low" | "medium" | "high";
  title: string;
  detail: Record<string, unknown>;
  disposition_status: "open" | "in_review" | "resolved" | "deferred" | "unknown";
  disposition_reason: string | null;
  version: number;
};
type Job = {
  job_id: string;
  job_type: string;
  status: "queued" | "running" | "succeeded" | "retryable" | "failed" | "cancelled";
  attempt_count: number;
  input_ref: string;
  output: { issue_count?: number; promotion_status?: string };
  error_code: string | null;
  error_message: string | null;
  updated_at: string;
};
type EstimateLine = {
  line_id: string;
  order_index: number;
  category: string;
  section: string;
  sequence: string;
  name: string;
  unit: string;
  quantity: string | null;
  main_material_unit_cost: string | null;
  auxiliary_unit_cost: string | null;
  labor_unit_cost: string | null;
  current_cost: string | null;
  source_quantity: string | null;
  source_amount: string;
  inclusion_status: "included" | "excluded";
  exclusion_reason: string | null;
  source_scope_conflict: boolean;
  source_locator: string;
};
type EstimateResult = {
  source_total_before_tax: string;
  source_discounted_before_tax: string;
  source_reconciliation_difference: string;
  included_construction_cost: string | null;
  excluded_source_cost: string;
  construction_net_sale: string | null;
  construction_gross_sale: string | null;
  design_cost_net: string | null;
  design_net_sale: string | null;
  design_gross_sale: string | null;
  combined_net_sale: string | null;
  combined_tax: string | null;
  combined_gross_sale: string | null;
  contract_target_gross: string;
  gross_gap_to_contract_target: string | null;
  trial_tax_rate: string;
  construction_cost_markup: string;
  design_cost_markup: string;
  included_line_count: number;
  excluded_line_count: number;
};
type Estimate = {
  estimate_id: string;
  name: string;
  currency: string;
  revision_no: number;
  source_hash: string;
  source_summary: Record<string, string>;
  source_notes: string[];
  assumptions: Record<string, string | null>;
  lines: EstimateLine[];
  calculation: { result: EstimateResult; warnings: { code: string; message: string }[]; formula_version: string };
};
type EstimateArtifact = { artifact_id: string; artifact_kind: string; filename: string; content_type: string; sha256: string; size_bytes: number; status: string; revision_no: number; download_url?: string };
type Requirement = { requirement_id: string; revision_no: number; status: string; source_kind: string; change_reason: string; content: { title: string; project_name: string; project_type: string; status: string; generation_method: string; budget: Record<string, string>; scope: Record<string, string | string[]>; evidence_policy: Record<string, string | boolean>; open_questions: string[] }; source_refs: { type: string; key?: string; filename?: string; source?: string; source_ref?: string; source_conflict?: string | null }[]; input_hash: string; created_at: string };
type Preview = { url: string; name: string; contentType: string };
type Deduction = { deduction_id: string; x: string; y: string; width: string; length: string };
type SpatialModel = {
  spatial_unit_id: string; name: string; unit_kind: string; revision_no: number;
  geometry_revision_id?: string; width?: string; length?: string; area_m2?: string;
  deductions?: Deduction[]; quantity_items?: { quantity_item_id: string; description: string; quantity: string; unit: string; formula: string; source_status: string }[];
  revisions?: { geometry_revision_id: string; revision_no: number; width_text: string; length_text: string; area_m2_text: string; created_at: string }[];
  artifacts?: { artifact_id: string; artifact_kind: string; filename: string; content_type: string; sha256: string; size_bytes: number; status: string; download_url?: string }[];
  quote?: { quote_revision_id: string; formula_version: string; pricing: { unit_cost_net: string | null; cost_markup: string; trial_tax_rate: string; source_label: string }; result: { quantity: string; unit: string; cost_net: string | null; sale_net: string | null; tax: string | null; sale_gross: string | null; status: string } } | null;
};
type ProcurementLine = { line_id: string; item_code: string; item_name: string; specification: string; ordered_quantity: string; received_quantity: string; allocated_quantity: string; remaining_quantity: string; unit: string };
type ProcurementOrder = { order_id: string; revision_no: number; status: string; supplier_name: string; delivery_location: string; source_kind: string; source_ref: string; external_effects_enabled: boolean; version: number; created_at: string; updated_at: string; lines: ProcurementLine[]; receipts: { receipt_id: string; receipt_no: string; receiver: string; evidence_ref: string; lines: { line_id: string; quantity_text: string; unit: string }[] }[]; allocations: { allocation_id: string; line_id: string; quantity_text: string; target_area: string; recipient: string; evidence_ref: string }[] };
type ChangeArtifact = { artifact_id: string; artifact_kind: string; filename: string; content_type: string; sha256: string; size_bytes: number };
type ChangeRequest = { change_id: string; change_no: number; issue_id: string | null; title: string; reason: string; description: string; status: string; version: number; baseline: Record<string, unknown>; proposal: Record<string, string | null>; impact: { affected_artifact_count?: number; quantity_delta_m2?: string | null; cost_delta_net?: string | null; schedule_delta_days?: string | null; approval_status?: string; new_outputs_required?: boolean }; artifacts: ChangeArtifact[]; acceptances: { acceptance_id: string; conclusion: string; evidence_ref: string; note: string }[] };

async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: { ...apiHeaders, ...(init.headers ?? {}) },
  });
  checkSessionResponse(response);
  const body = (await response.json()) as T & { message?: string };
  if (!response.ok) throw new Error(body.message ?? `请求失败 (${response.status})`);
  return body;
}

function transferFile(path: string, file: File, onProgress: (value: number) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const request = new XMLHttpRequest();
    request.open("PUT", path);
    Object.entries(apiHeaders).forEach(([key, value]) => request.setRequestHeader(key, value));
    request.setRequestHeader("Content-Type", "application/octet-stream");
    request.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(Math.round((event.loaded / event.total) * 100));
    };
    request.onload = () => {
      if (request.status === 401) window.dispatchEvent(new Event("rkd-session-expired"));
      if (request.status >= 200 && request.status < 300) resolve();
      else {
        let message = `上传失败 (${request.status})`;
        try { message = JSON.parse(request.responseText).message ?? message; } catch { /* non-JSON network failure */ }
        reject(new Error(message));
      }
    };
    request.onerror = () => reject(new Error("文件传输中断，请重新选择文件"));
    request.send(file);
  });
}

function formatSize(bytes: number): string {
  return bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.ceil(bytes / 1024)} KB`;
}

function formatMoney(value: string | null | undefined): string {
  return value == null ? "未知" : `¥${Number(value).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function kindLabel(kind: string): string {
  const labels: Record<string, string> = {
    floor_plan_pdf: "平面图 PDF", cad_floor_plan_dwg: "CAD 原图 DWG",
    cad_floor_plan_dxf_secondary_export: "CAD 对照 DXF", legacy_budget_workbook: "源预算 XLS",
    site_photo: "现场照片", uploaded_file: "上传原件",
  };
  return labels[kind] ?? "原件";
}

function PdfPreview({ url }: { url: string }) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const viewerRef = useRef<HTMLDivElement>(null);
  const [document, setDocument] = useState<PDFDocumentProxy>();
  const [pageNumber, setPageNumber] = useState(1);
  const [zoom, setZoom] = useState(1);
  const [error, setError] = useState("");

  useEffect(() => {
    let disposed = false;
    const task = getDocument({ url });
    task.promise.then((loaded) => {
      if (!disposed) setDocument(loaded);
    }).catch((reason: Error) => { if (!disposed) setError(reason.message); });
    return () => { disposed = true; void task.destroy(); };
  }, [url]);

  useEffect(() => {
    if (!document) return;
    let disposed = false;
    let renderTask: RenderTask | undefined;
    document.getPage(pageNumber).then((page) => {
      if (disposed || !canvasRef.current) return;
      const base = page.getViewport({ scale: 1 });
      const available = Math.max(280, (viewerRef.current?.clientWidth ?? 800) - 36);
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      const scale = Math.min(1.25, available / base.width) * zoom;
      const viewport = page.getViewport({ scale: scale * ratio });
      const canvas = canvasRef.current;
      canvas.width = Math.ceil(viewport.width);
      canvas.height = Math.ceil(viewport.height);
      canvas.style.width = `${viewport.width / ratio}px`;
      canvas.style.height = `${viewport.height / ratio}px`;
      renderTask = page.render({ canvas, viewport });
      return renderTask.promise;
    }).catch((reason: Error) => { if (!disposed && reason.name !== "RenderingCancelledException") setError(reason.message); });
    return () => { disposed = true; renderTask?.cancel(); };
  }, [document, pageNumber, zoom]);

  return <div className="pdf-preview"><div className="pdf-toolbar"><button type="button" onClick={() => setPageNumber(Math.max(1, pageNumber - 1))} disabled={!document || pageNumber === 1} aria-label="上一页">上一页</button><span>{pageNumber} / {document?.numPages ?? 1}</span><button type="button" onClick={() => setPageNumber(Math.min(document?.numPages ?? 1, pageNumber + 1))} disabled={!document || pageNumber >= (document?.numPages ?? 1)} aria-label="下一页">下一页</button><span className="pdf-toolbar-spacer" /><button type="button" onClick={() => setZoom(Math.max(0.5, zoom - 0.25))} disabled={zoom <= 0.5} aria-label="缩小" title="缩小"><Minus size={16} /></button><span>{Math.round(zoom * 100)}%</span><button type="button" onClick={() => setZoom(Math.min(3, zoom + 0.25))} disabled={zoom >= 3} aria-label="放大" title="放大"><Plus size={16} /></button></div><div className="pdf-canvas-area" ref={viewerRef}>{error ? <p role="alert">预览失败：{error}</p> : !document ? <p>正在打开图纸...</p> : null}<canvas ref={canvasRef} /></div></div>;
}

function App({ session }: { session: Session }) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedId, setSelectedId] = useState<string>();
  const [newName, setNewName] = useState("");
  const [editName, setEditName] = useState("");
  const [busy, setBusy] = useState(false);
  const [connected, setConnected] = useState(false);
  const [message, setMessage] = useState("正在读取本地项目...");
  const [view, setView] = useState<"overview" | "requirements" | "files" | "issues" | "estimate" | "spatial" | "procurement" | "jobs" | "accounts">("overview");
  const [files, setFiles] = useState<FileAsset[]>([]);
  const [decisions, setDecisions] = useState<Decision[]>([]);
  const [issues, setIssues] = useState<Issue[]>([]);
  const [jobs, setJobs] = useState<Job[]>([]);
  const [estimate, setEstimate] = useState<Estimate>();
  const [estimateArtifacts, setEstimateArtifacts] = useState<EstimateArtifact[]>([]);
  const [requirement, setRequirement] = useState<Requirement>();
  const [estimateLineDrafts, setEstimateLineDrafts] = useState<Record<string, {
    quantity: string; main_material_unit_cost: string; auxiliary_unit_cost: string;
    labor_unit_cost: string; inclusion_status: EstimateLine["inclusion_status"];
  }>>({});
  const [estimateAssumptions, setEstimateAssumptions] = useState({
    trial_tax_rate: "0.05", construction_cost_markup: "0.20", design_cost_markup: "0.60", design_cost_net: "",
  });
  const [estimateSearch, setEstimateSearch] = useState("");
  const [estimateScope, setEstimateScope] = useState<"all" | "included" | "excluded">("all");
  const [spatial, setSpatial] = useState<SpatialModel>();
  const [procurementOrders, setProcurementOrders] = useState<ProcurementOrder[]>([]);
  const [procurementDraft, setProcurementDraft] = useState({ supplier_name: "", delivery_location: "", item_name: "", specification: "unknown", quantity: "1", unit: "件" });
  const [procurementAction, setProcurementAction] = useState({ quantity: "1", target_area: "", recipient: "", evidence_ref: "" });
  const [changes, setChanges] = useState<ChangeRequest[]>([]);
  const [changeDraft, setChangeDraft] = useState({ title: "", reason: "", description: "", quantity_delta_m2: "", cost_delta_net: "", schedule_delta_days: "" });
  const [changeAcceptance, setChangeAcceptance] = useState({ evidence_ref: "", note: "" });
  const [spatialDraft, setSpatialDraft] = useState({ width: "10", length: "5", deductions: [] as Deduction[], unit_cost_net: "100", cost_markup: "0.20", trial_tax_rate: "0.05" });
  const [issueDrafts, setIssueDrafts] = useState<Record<string, { status: Issue["disposition_status"]; reason: string }>>({});
  const [uploadMessage, setUploadMessage] = useState("");
  const [preview, setPreview] = useState<Preview>();

  const selected = useMemo(
    () => projects.find((project) => project.project_id === selectedId) ?? projects[0],
    [projects, selectedId],
  );

  function applyEstimate(value?: Estimate) {
    setEstimate(value);
    if (!value) {
      setEstimateLineDrafts({});
      return;
    }
    setEstimateLineDrafts(Object.fromEntries(value.lines.map((line) => [line.line_id, {
      quantity: line.quantity ?? "",
      main_material_unit_cost: line.main_material_unit_cost ?? "",
      auxiliary_unit_cost: line.auxiliary_unit_cost ?? "",
      labor_unit_cost: line.labor_unit_cost ?? "",
      inclusion_status: line.inclusion_status,
    }])));
    setEstimateAssumptions({
      trial_tax_rate: String(value.assumptions.trial_tax_rate ?? "0.05"),
      construction_cost_markup: String(value.assumptions.construction_cost_markup ?? "0.20"),
      design_cost_markup: String(value.assumptions.design_cost_markup ?? "0.60"),
      design_cost_net: String(value.assumptions.design_cost_net ?? ""),
    });
  }

  async function loadProjects(preferredId?: string) {
    const result = await api<{ items: Project[] }>("/api/v1/projects");
    setProjects(result.items);
    setConnected(true);
    const defaultProject = result.items.find((item) => item.project_id === "project_ningbo_xiecheng_2026") ?? result.items[0];
    setSelectedId(preferredId ?? defaultProject?.project_id);
    setEditName(result.items.find((item) => item.project_id === preferredId)?.name ?? defaultProject?.name ?? "");
    setMessage(result.items.length ? "项目数据已从本地存储加载" : "还没有项目，请创建第一个项目");
  }

  useEffect(() => {
    loadProjects().catch((error: Error) => {
      setConnected(false);
      setMessage(error.message);
    });
  }, []);

  useEffect(() => {
    if (selected) setEditName(selected.name);
  }, [selected]);

  useEffect(() => {
    if (!selected) return;
    const projectId = selected.project_id;
    setFiles([]);
    setDecisions([]);
    setIssues([]);
    setJobs([]);
    setSpatial(undefined);
    setProcurementOrders([]);
    setChanges([]);
    setEstimateArtifacts([]);
    setRequirement(undefined);
    applyEstimate(undefined);
    Promise.all([
      api<{ items: FileAsset[] }>(`/api/v1/projects/${projectId}/files`),
      api<{ items: Decision[] }>(`/api/v1/projects/${projectId}/decisions`),
      api<{ items: Issue[] }>(`/api/v1/projects/${projectId}/issues`),
      api<{ items: Job[] }>(`/api/v1/projects/${projectId}/jobs`),
      api<{ items: { estimate_id: string }[] }>(`/api/v1/projects/${projectId}/estimates`),
      api<{ items: SpatialModel[] }>(`/api/v1/projects/${projectId}/spatial`),
      api<{ item?: Requirement }>(`/api/v1/projects/${projectId}/requirements`),
      api<{ items: ProcurementOrder[] }>(`/api/v1/projects/${projectId}/procurement/orders`),
      api<{ items: ChangeRequest[] }>(`/api/v1/projects/${projectId}/changes`),
    ]).then(async ([fileResult, decisionResult, issueResult, jobResult, estimateResult, spatialResult, requirementResult, procurementResult, changeResult]) => {
      setFiles(fileResult.items);
      setDecisions(decisionResult.items);
      setIssues(issueResult.items);
      setJobs(jobResult.items);
      const model = spatialResult.items[0];
      setSpatial(model);
      if (model?.width && model.length) setSpatialDraft({ width: model.width, length: model.length, deductions: model.deductions ?? [], unit_cost_net: model.quote?.pricing.unit_cost_net ?? "", cost_markup: model.quote?.pricing.cost_markup ?? "0.20", trial_tax_rate: model.quote?.pricing.trial_tax_rate ?? "0.05" });
      const estimateSummary = estimateResult.items[0];
      applyEstimate(estimateSummary
        ? await api<Estimate>(`/api/v1/projects/${projectId}/estimates/${estimateSummary.estimate_id}`)
        : undefined);
      setRequirement(requirementResult.item);
      setProcurementOrders(procurementResult.items);
      setChanges(changeResult.items);
      setIssueDrafts(Object.fromEntries(issueResult.items.map((issue) => [issue.issue_id, {
        status: issue.disposition_status,
        reason: issue.disposition_reason ?? "",
      }])));
    }).catch((error: Error) => setMessage(error.message));
  }, [selected?.project_id]);

  useEffect(() => () => { if (preview) URL.revokeObjectURL(preview.url); }, [preview]);

  const targetAmount = decisions.find((item) => item.key === "contract_target_gross_cny")?.value;
  const taxRate = decisions.find((item) => item.key === "trial_tax_rate")?.value;
  const targetConflict = decisions.find((item) => item.key === "contract_target_gross_cny")?.source_conflict;
  const visibleEstimateLines = useMemo(() => {
    const query = estimateSearch.trim().toLowerCase();
    return (estimate?.lines ?? []).filter((line) => (
      (estimateScope === "all" || line.inclusion_status === estimateScope)
      && (!query || `${line.section} ${line.name} ${line.source_locator}`.toLowerCase().includes(query))
    ));
  }, [estimate, estimateScope, estimateSearch]);

  async function createProject(event: FormEvent) {
    event.preventDefault();
    const name = newName.trim();
    if (!name) return;
    setBusy(true);
    try {
      const project = await api<Project>("/api/v1/projects", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      setNewName("");
      await loadProjects(project.project_id);
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function renameProject(event: FormEvent) {
    event.preventDefault();
    if (!selected || !editName.trim() || editName.trim() === selected.name) return;
    setBusy(true);
    try {
      const project = await api<Project>(`/api/v1/projects/${selected.project_id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: editName.trim(), expected_version: selected.version }),
      });
      await loadProjects(project.project_id);
      setMessage("项目名称已保存");
    } catch (error) {
      setMessage((error as Error).message);
      await loadProjects(selected.project_id).catch(() => undefined);
    } finally {
      setBusy(false);
    }
  }

  async function createProcurementOrder(event: FormEvent) {
    event.preventDefault();
    if (!selected || !procurementDraft.supplier_name.trim() || !procurementDraft.item_name.trim()) return;
    setBusy(true);
    try {
      const order = await api<ProcurementOrder>(`/api/v1/projects/${selected.project_id}/procurement/orders`, { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": `ui-order-${crypto.randomUUID()}` }, body: JSON.stringify({ supplier_name: procurementDraft.supplier_name, delivery_location: procurementDraft.delivery_location, lines: [{ item_name: procurementDraft.item_name, specification: procurementDraft.specification, ordered_quantity: procurementDraft.quantity, unit: procurementDraft.unit }] }) });
      setProcurementOrders((current) => [order, ...current.filter((item) => item.order_id !== order.order_id)]);
      setMessage("材料订单草稿已保存");
    } catch (error) { setMessage((error as Error).message); } finally { setBusy(false); }
  }

  async function procurementActionSubmit(order: ProcurementOrder, action: "receipts" | "allocations") {
    const line = order.lines[0];
    if (!line || !selected) return;
    setBusy(true);
    try {
      const payload = action === "receipts"
        ? { expected_version: order.version, receiver: "本地试用人员", evidence_ref: procurementAction.evidence_ref || "本地收货记录", lines: [{ line_id: line.line_id, quantity: procurementAction.quantity }] }
        : { expected_version: order.version, target_area: procurementAction.target_area || "待分派区域", recipient: procurementAction.recipient || "施工班组（草稿）", evidence_ref: procurementAction.evidence_ref || "本地分派记录", lines: [{ line_id: line.line_id, quantity: procurementAction.quantity }] };
      const updated = await api<ProcurementOrder>(`/api/v1/projects/${selected.project_id}/procurement/orders/${order.order_id}/${action}`, { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": `ui-${action}-${crypto.randomUUID()}` }, body: JSON.stringify(payload) });
      setProcurementOrders((current) => current.map((item) => item.order_id === updated.order_id ? updated : item));
      setMessage(action === "receipts" ? "收货记录已保存" : "材料分派已保存");
    } catch (error) { setMessage((error as Error).message); } finally { setBusy(false); }
  }

  async function createChange(event: FormEvent) {
    event.preventDefault();
    if (!selected || !changeDraft.title.trim() || !changeDraft.reason.trim() || !changeDraft.description.trim()) return;
    setBusy(true);
    try {
      const change = await api<ChangeRequest>(`/api/v1/projects/${selected.project_id}/changes`, { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": `ui-change-${crypto.randomUUID()}` }, body: JSON.stringify({ ...changeDraft, issue_id: issues[0]?.issue_id ?? null, quantity_delta_m2: changeDraft.quantity_delta_m2 || null, cost_delta_net: changeDraft.cost_delta_net || null, schedule_delta_days: changeDraft.schedule_delta_days || null }) });
      setChanges((current) => [change, ...current]);
      setMessage("变更请求已保存");
    } catch (error) { setMessage((error as Error).message); } finally { setBusy(false); }
  }

  async function analyzeChange(change: ChangeRequest) {
    if (!selected) return;
    setBusy(true);
    try {
      const updated = await api<ChangeRequest>(`/api/v1/projects/${selected.project_id}/changes/${change.change_id}/analyze`, { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": `ui-change-analyze-${crypto.randomUUID()}` }, body: JSON.stringify({ expected_version: change.version, notes: "本地规则快照分析" }) });
      setChanges((current) => current.map((item) => item.change_id === updated.change_id ? updated : item));
      setMessage("影响分析已生成，新成果为待人工确认草稿");
    } catch (error) { setMessage((error as Error).message); } finally { setBusy(false); }
  }

  async function acceptChange(change: ChangeRequest) {
    if (!selected) return;
    setBusy(true);
    try {
      const updated = await api<ChangeRequest>(`/api/v1/projects/${selected.project_id}/changes/${change.change_id}/acceptance`, { method: "POST", headers: { "Content-Type": "application/json", "Idempotency-Key": `ui-change-accept-${crypto.randomUUID()}` }, body: JSON.stringify({ conclusion: "accepted", checklist: ["影响范围已复核", "新成果已查看"], evidence_ref: changeAcceptance.evidence_ref || "本地验收记录", note: changeAcceptance.note }) });
      setChanges((current) => current.map((item) => item.change_id === updated.change_id ? updated : item));
      setMessage("变更验收已记录");
    } catch (error) { setMessage((error as Error).message); } finally { setBusy(false); }
  }

  async function uploadFile(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file || !selected) return;
    setBusy(true);
    setUploadMessage("正在创建上传会话...");
    try {
      const session = await api<{ upload_id: string; upload_url: string }>(`/api/v1/projects/${selected.project_id}/uploads`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ filename: file.name, size_bytes: file.size }),
      });
      setUploadMessage("正在传输 0%");
      await transferFile(session.upload_url, file, (progress) => setUploadMessage(`正在传输 ${progress}%`));
      setUploadMessage("正在校验文件字节...");
      await api(`/api/v1/projects/${selected.project_id}/uploads/${session.upload_id}/complete`, {
        method: "POST", headers: { "Content-Type": "application/json" }, body: "{}",
      });
      const result = await api<{ items: FileAsset[] }>(`/api/v1/projects/${selected.project_id}/files`);
      setFiles(result.items);
      setUploadMessage("原件已保存；解析尚未执行");
    } catch (error) {
      setUploadMessage((error as Error).message);
    } finally {
      setBusy(false);
      event.target.value = "";
    }
  }

  async function previewFile(file: FileAsset) {
    if (!selected) return;
    try {
      const response = await fetch(`/api/v1/projects/${selected.project_id}/files/${file.file_id}/content?preview=1`, {
        headers: apiHeaders,
      });
      if (!response.ok) throw new Error(`文件读取失败 (${response.status})`);
      const url = URL.createObjectURL(await response.blob());
      setPreview({ url, name: file.filename, contentType: file.content_type });
    } catch (error) {
      setUploadMessage((error as Error).message);
    }
  }

  async function saveIssueDisposition(issue: Issue) {
    if (!selected) return;
    const draft = issueDrafts[issue.issue_id];
    if (!draft?.reason.trim()) {
      setMessage("请先填写问题处置理由");
      return;
    }
    try {
      const updated = await api<Issue>(`/api/v1/projects/${selected.project_id}/issues/${issue.issue_id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...draft, reason: draft.reason.trim(), expected_version: issue.version }),
      });
      setIssues((current) => current.map((item) => item.issue_id === updated.issue_id ? updated : item));
      setIssueDrafts((current) => ({ ...current, [updated.issue_id]: { status: updated.disposition_status, reason: updated.disposition_reason ?? "" } }));
      setMessage("问题处置已保存；未改变专业批准状态");
    } catch (error) {
      setMessage((error as Error).message);
    }
  }

  async function updateJob(job: Job, action: "retry" | "cancel") {
    if (!selected) return;
    try {
      await api<Job>(`/api/v1/projects/${selected.project_id}/jobs/${job.job_id}/${action}`, { method: "POST" });
      const result = await api<{ items: Job[] }>(`/api/v1/projects/${selected.project_id}/jobs`);
      setJobs(result.items);
      setMessage(action === "retry" ? "任务已重试，重复问题不会重复生成" : "任务已取消");
    } catch (error) {
      setMessage((error as Error).message);
    }
  }

  async function saveEstimateLine(line: EstimateLine) {
    if (!selected || !estimate) return;
    const draft = estimateLineDrafts[line.line_id];
    if (!draft) return;
    setBusy(true);
    try {
      const updated = await api<Estimate>(
        `/api/v1/projects/${selected.project_id}/estimates/${estimate.estimate_id}/lines/${line.line_id}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision: estimate.revision_no,
            ...draft,
            exclusion_reason: draft.inclusion_status === "excluded" ? "workbench_manual_exclusion" : null,
            change_reason: `工作台修改：${line.section} / ${line.name}`,
          }),
        },
      );
      applyEstimate(updated);
      setMessage(`预算明细已保存为修订 v${updated.revision_no}`);
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function calculateEstimate(event: FormEvent) {
    event.preventDefault();
    if (!selected || !estimate) return;
    setBusy(true);
    try {
      const updated = await api<Estimate>(
        `/api/v1/projects/${selected.project_id}/estimates/${estimate.estimate_id}/calculations`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            expected_revision: estimate.revision_no,
            ...estimateAssumptions,
            design_cost_net: estimateAssumptions.design_cost_net.trim() || null,
            change_reason: "工作台更新试算参数",
          }),
        },
      );
      applyEstimate(updated);
      setMessage(`试算已保存为修订 v${updated.revision_no}`);
    } catch (error) {
      setMessage((error as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function exportEstimate() {
    if (!selected || !estimate) return;
    setBusy(true);
    try {
      const result = await api<{ items: EstimateArtifact[] }>(`/api/v1/projects/${selected.project_id}/estimates/${estimate.estimate_id}/export`, { method: "POST" });
      setEstimateArtifacts(result.items);
      setMessage(`预算修订 v${result.items[0]?.revision_no ?? estimate.revision_no} 已生成 ${result.items.length} 个真实成果`);
    } catch (error) { setMessage((error as Error).message); }
    finally { setBusy(false); }
  }

  async function downloadEstimateArtifact(artifact: EstimateArtifact) {
    if (!selected) return;
    try {
      const response = await fetch(`/api/v1/projects/${selected.project_id}/estimates/artifacts/${artifact.artifact_id}/content`, { headers: apiHeaders });
      if (!response.ok) throw new Error(`成果下载失败 (${response.status})`);
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a"); anchor.href = url; anchor.download = artifact.filename; anchor.click(); URL.revokeObjectURL(url);
      setMessage(`已下载 ${artifact.filename}`);
    } catch (error) { setMessage((error as Error).message); }
  }

  async function saveSpatial(event: FormEvent) {
    event.preventDefault();
    if (!selected) return;
    setBusy(true);
    try {
      const updated = await api<SpatialModel>(`/api/v1/projects/${selected.project_id}/spatial/revisions`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ spatial_unit_id: spatial?.spatial_unit_id ?? `space-${selected.project_id}-test-floor`, name: spatial?.name ?? "测试地坪区域", width: spatialDraft.width, length: spatialDraft.length, deductions: spatialDraft.deductions, pricing: { unit_cost_net: spatialDraft.unit_cost_net.trim() || null, cost_markup: spatialDraft.cost_markup, trial_tax_rate: spatialDraft.trial_tax_rate, source_label: "M2 测试成本快照（人工输入）" }, expected_revision: spatial?.revision_no ?? 0, change_reason: "M2 参数几何编辑" }),
      });
      setSpatial(updated);
      setMessage(`几何已保存为修订 v${updated.revision_no}，净面积 ${updated.area_m2} m²`);
    } catch (error) { setMessage((error as Error).message); }
    finally { setBusy(false); }
  }

  async function downloadSpatialArtifact(artifact: NonNullable<SpatialModel["artifacts"]>[number]) {
    if (!selected) return;
    try {
      const response = await fetch(`/api/v1/projects/${selected.project_id}/spatial/artifacts/${artifact.artifact_id}/content`, { headers: apiHeaders });
      if (!response.ok) throw new Error(`成果下载失败 (${response.status})`);
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a"); anchor.href = url; anchor.download = artifact.filename; anchor.click(); URL.revokeObjectURL(url);
      setMessage(`已下载 ${artifact.filename}`);
    } catch (error) { setMessage((error as Error).message); }
  }

  function addDeduction() {
    setSpatialDraft((current) => ({ ...current, deductions: [...current.deductions, { deduction_id: `deduction-${current.deductions.length + 1}`, x: "0", y: "0", width: "2", length: "2" }] }));
  }

  async function downloadChangeArtifact(artifact: ChangeArtifact) {
    if (!selected) return;
    try {
      const response = await fetch(`/api/v1/projects/${selected.project_id}/changes/artifacts/${artifact.artifact_id}/content`, { headers: apiHeaders });
      checkSessionResponse(response);
      if (!response.ok) throw new Error("变更成果下载失败，请检查登录和项目权限");
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement("a"); anchor.href = url; anchor.download = artifact.filename; anchor.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { setMessage(error instanceof Error ? error.message : "下载失败"); }
  }

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-mark">RKD</div>
        <div>
          <div className="product-name">RKD AI 工作台</div>
          <div className="product-subtitle">室内设计生产系统 · {session.mode === "accounts" ? "本机账号试用" : "本地单用户版"}</div>
        </div>
        <div className="connection-state"><span className={`state-dot ${connected ? "" : "offline"}`} />{connected ? "本地已连接" : "连接中断"}</div>
        <AccountControls session={session} />
      </header>

      <main className="workspace">
        <aside className="project-rail">
          <div className="rail-heading"><span>项目</span><span className="project-count">{projects.length}</span></div>
          <div className="project-list">
            {projects.map((project) => (
              <button
                className={`project-item ${selected?.project_id === project.project_id ? "active" : ""}`}
                key={project.project_id}
                onClick={() => setSelectedId(project.project_id)}
              >
                <span className="project-avatar">{project.name.slice(0, 1).toUpperCase()}</span>
                <span className="project-item-copy"><strong>{project.name}</strong><small>本地项目</small></span>
              </button>
            ))}
          </div>
          {(session.mode === "local" || session.user?.is_admin) && <form className="new-project" onSubmit={createProject}>
            <label htmlFor="new-project-name">新建项目</label>
            <div className="inline-form">
              <input id="new-project-name" value={newName} onChange={(event) => setNewName(event.target.value)} placeholder="项目名称" />
              <button type="submit" disabled={busy || !newName.trim()} aria-label="创建项目" title="创建项目"><Plus size={18} /></button>
            </div>
          </form>}
          {session.user?.is_admin ? <button className="account-nav" onClick={() => setView("accounts")}>账号与成员管理</button> : null}
        </aside>

        <section className="content-area">
          <div className="content-heading">
            <div>
              <div className="eyebrow">项目概览</div>
              <h1>{selected?.name ?? "欢迎使用 RKD AI"}</h1>
              <p className="heading-note" role="status">{message}</p>
            </div>
            {selected && <div className="project-id">ID <code>{selected.project_id}</code></div>}
          </div>

          {selected && <nav className="view-tabs" aria-label="项目页面"><button className={view === "overview" ? "active" : ""} onClick={() => setView("overview")}>概览</button><button className={view === "requirements" ? "active" : ""} onClick={() => setView("requirements")}>需求草稿 <span>{requirement ? `v${requirement.revision_no}` : "-"}</span></button><button className={view === "files" ? "active" : ""} onClick={() => setView("files")}>资料与图纸 <span>{files.length}</span></button><button className={view === "issues" ? "active" : ""} onClick={() => setView("issues")}>检查与问题 <span>{issues.filter((issue) => issue.disposition_status !== "resolved").length}</span></button><button className={view === "estimate" ? "active" : ""} onClick={() => setView("estimate")}>预算与试算 <span>{estimate ? 1 : 0}</span></button><button className={view === "spatial" ? "active" : ""} onClick={() => setView("spatial")}>空间与工程量 <span>{spatial?.revision_no ?? 0}</span></button><button className={view === "procurement" ? "active" : ""} onClick={() => setView("procurement")}>采购施工 <span>{procurementOrders.length}</span></button><button className={view === "jobs" ? "active" : ""} onClick={() => setView("jobs")}>成果与任务 <span>{jobs.length}</span></button></nav>}

          {session.mode === "accounts" && selected && <p className="permission-notice">当前权限：{selected.role === "viewer" ? "只读 · 可以查看和下载，不能保存修改" : selected.role === "editor" ? "项目编辑 · 可保存草稿，本地验收需项目负责人" : "项目负责人"}。正式发布、外部下单和付款未开放。</p>}
          {view === "accounts" && session.user?.is_admin ? <AccountPanel projectId={selected?.project_id} /> : selected && view === "overview" ? (
            <>
              <div className="summary-grid">
                <article className="summary-card emphasis"><span>当前状态</span><strong>已创建</strong><small>{files.length} 份文件</small></article>
                <article className="summary-card"><span>含税目标</span><strong>{targetAmount ? `¥${Number(targetAmount).toLocaleString("zh-CN")}` : "未知"}</strong><small>{taxRate ? `试用税率 ${Number(taxRate) * 100}% · 用户确认口径` : "尚无预算数据"}</small></article>
                <article className="summary-card"><span>本地版本</span><strong>v{selected.version}</strong><small>服务端已保存</small></article>
              </div>
              {targetConflict && <p className="source-notice">当前 60 万元按用户确认的含税目标显示；源预算标为“不含税”，两者口径冲突已保留。5% 仅作本地试用，正式税务口径待核验。</p>}
              <section className="panel project-settings">
                  <div className="panel-title"><div><span className="eyebrow">项目设置</span><h2>基本信息</h2></div><span className="saved-tag">已持久化</span></div>
                  <form className="edit-form" onSubmit={renameProject}>
                    <label htmlFor="edit-project-name">项目名称</label>
                    <div className="edit-row"><input id="edit-project-name" value={editName} onChange={(event) => setEditName(event.target.value)} /><button type="submit" disabled={busy || !editName.trim() || editName.trim() === selected.name}>保存</button></div>
                  </form>
                  <dl className="metadata"><div><dt>组织</dt><dd>{selected.organization_id}</dd></div><div><dt>存储</dt><dd>var/app.sqlite3</dd></div></dl>
              </section>
            </>
          ) : selected && view === "requirements" ? (
            <DesignWorkspace key={selected.project_id} projectId={selected.project_id} onRequirementSaved={() => { void api<{ item: Requirement }>(`/api/v1/projects/${selected.project_id}/requirements`).then((r) => setRequirement(r.item)); }} />
          ) : selected && view === "files" ? (
            <section className="file-workspace">
              <div className="section-heading"><div><span className="eyebrow">项目资料</span><h2>资料与图纸</h2></div><label className={`upload-button ${busy ? "disabled" : ""}`}><Upload size={16} /><span>上传文件</span><input type="file" onChange={uploadFile} disabled={busy} /></label></div>
              {uploadMessage && <p className="operation-message" role="status">{uploadMessage}</p>}
              {files.length ? <div className="file-table-wrap"><table className="file-table"><thead><tr><th>文件</th><th>来源</th><th>大小</th><th>处理状态</th><th>操作</th></tr></thead><tbody>{files.map((file) => {
                const canPreview = file.content_type === "application/pdf" || file.content_type.startsWith("image/");
                return <tr key={file.file_id}><td><strong>{file.filename}</strong><small>v{file.revision} · {kindLabel(file.kind)} · {file.source_ref}</small></td><td>{file.source_kind === "seed_fixture" ? "宁波项目原件" : "本地上传"}</td><td>{formatSize(file.size_bytes)}</td><td>{file.format_status === "source_manifest_verified" ? "来源哈希已核对" : file.format_status === "signature_checked" ? "格式已核对 · 未解析" : "已保存 · 待核对格式"}</td><td><div className="file-actions">{canPreview && <button type="button" onClick={() => previewFile(file)} aria-label={`预览 ${file.filename}`} title="预览"><Eye size={17} /></button>}<a href={file.download_url} download={file.filename} aria-label={`下载 ${file.filename}`} title="下载原件"><Download size={17} /></a></div></td></tr>;
              })}</tbody></table></div> : <div className="files-empty">暂无文件</div>}
            </section>
          ) : selected && view === "issues" ? (
            <section className="operation-workspace">
              <div className="section-heading"><div><span className="eyebrow">来源证据</span><h2>检查与问题</h2></div><span className="saved-tag">候选不等于批准</span></div>
              <p className="operation-intro">以下记录来自已接入的 CAD 报告和项目口径冲突。处置只记录责任人的判断，不会把候选图元提升为工程量。</p>
              <div className="issue-list">{issues.map((issue) => {
                const draft = issueDrafts[issue.issue_id] ?? { status: issue.disposition_status, reason: issue.disposition_reason ?? "" };
                return <article className="issue-row" key={issue.issue_id}><div className="issue-main"><div className="issue-title"><span className={`severity severity-${issue.severity}`}>{issue.severity === "high" ? "高" : issue.severity === "medium" ? "中" : "低"}</span><strong>{issue.title}</strong></div><p>{issue.source_locator}</p><small>{issue.detail?.promotion_status === "not-approved" ? "专业批准状态：未批准" : `来源引用：${issue.source_ref}`}</small></div><div className="issue-form"><select value={draft.status} onChange={(event) => setIssueDrafts((current) => ({ ...current, [issue.issue_id]: { ...draft, status: event.target.value as Issue["disposition_status"] } }))}><option value="open">待处理</option><option value="in_review">复核中</option><option value="resolved">已处理</option><option value="deferred">延期</option><option value="unknown">未知</option></select><input value={draft.reason} onChange={(event) => setIssueDrafts((current) => ({ ...current, [issue.issue_id]: { ...draft, reason: event.target.value } }))} placeholder="记录处置理由" /><button type="button" onClick={() => saveIssueDisposition(issue)}>保存</button></div></article>;
              })}</div>
            </section>
          ) : selected && view === "estimate" ? (
            estimate ? <section className="estimate-workspace">
              <div className="section-heading"><div><span className="eyebrow">版本化成本试算</span><h2>预算与试算</h2></div><div className="section-actions"><button type="button" className="dark-action" onClick={exportEstimate} disabled={busy}><Download size={15} />导出当前修订</button><span className="saved-tag">修订 v{estimate.revision_no}</span></div></div>
              <p className="operation-intro">源 XLS 只读保留。明细工作副本按 Decimal 计算；施工和设计分别按成本加成，合同目标、源报价和试算结果不混用。</p>

              <div className="estimate-summary">
                <article><span>源表工程总造价（未税）</span><strong>{formatMoney(estimate.calculation.result.source_total_before_tax)}</strong><small>汇总!D8 · 明细对账差 {formatMoney(estimate.calculation.result.source_reconciliation_difference)}</small></article>
                <article><span>纳入范围成本</span><strong>{formatMoney(estimate.calculation.result.included_construction_cost)}</strong><small>排除 {estimate.calculation.result.excluded_line_count} 行 · {formatMoney(estimate.calculation.result.excluded_source_cost)}</small></article>
                <article><span>施工含税试算</span><strong>{formatMoney(estimate.calculation.result.construction_gross_sale)}</strong><small>成本加成 {Number(estimate.calculation.result.construction_cost_markup) * 100}%</small></article>
                <article><span>设计含税试算</span><strong>{formatMoney(estimate.calculation.result.design_gross_sale)}</strong><small>{estimate.calculation.result.design_cost_net == null ? "设计成本未知，不按 0 计算" : `成本 ${formatMoney(estimate.calculation.result.design_cost_net)}`}</small></article>
                <article className="estimate-total"><span>施工 + 设计含税试算</span><strong>{formatMoney(estimate.calculation.result.combined_gross_sale)}</strong><small>合同含税目标 {formatMoney(estimate.calculation.result.contract_target_gross)} · 差额 {formatMoney(estimate.calculation.result.gross_gap_to_contract_target)}</small></article>
              </div>

              <div className="estimate-layout">
                <form className="estimate-assumptions" onSubmit={calculateEstimate}>
                  <div><span className="eyebrow">试算参数</span><h3>成本加成与税率</h3></div>
                  <label>施工成本加成<input type="number" min="0" step="0.01" value={estimateAssumptions.construction_cost_markup} onChange={(event) => setEstimateAssumptions((current) => ({ ...current, construction_cost_markup: event.target.value }))} /></label>
                  <label>设计成本加成<input type="number" min="0" step="0.01" value={estimateAssumptions.design_cost_markup} onChange={(event) => setEstimateAssumptions((current) => ({ ...current, design_cost_markup: event.target.value }))} /></label>
                  <label>试用税率<input type="number" min="0" step="0.01" value={estimateAssumptions.trial_tax_rate} onChange={(event) => setEstimateAssumptions((current) => ({ ...current, trial_tax_rate: event.target.value }))} /></label>
                  <label>设计未税成本<input type="number" min="0" step="0.01" placeholder="未知" value={estimateAssumptions.design_cost_net} onChange={(event) => setEstimateAssumptions((current) => ({ ...current, design_cost_net: event.target.value }))} /></label>
                  <button type="submit" disabled={busy}>保存参数并试算</button>
                </form>
                <div className="estimate-basis">
                  <div><span>源优惠价</span><strong>{formatMoney(estimate.calculation.result.source_discounted_before_tax)}</strong><small>源表标注不含税</small></div>
                  <div><span>合同目标</span><strong>{formatMoney(estimate.calculation.result.contract_target_gross)}</strong><small>用户确认含税口径</small></div>
                  <div><span>公式版本</span><strong>{estimate.calculation.formula_version}</strong><small>税率仅作本地试用</small></div>
                </div>
              </div>

              <div className="estimate-warnings">{estimate.calculation.warnings.map((warning) => <p key={warning.code}><strong>{warning.code}</strong>{warning.message}</p>)}</div>
              {estimateArtifacts.length > 0 && <div className="estimate-artifacts"><div className="eyebrow">真实成果文件</div><div className="artifact-list">{estimateArtifacts.map((artifact) => <button type="button" key={artifact.artifact_id} onClick={() => downloadEstimateArtifact(artifact)}><Download size={15} /><span>{artifact.filename}</span><small>v{artifact.revision_no} · {artifact.size_bytes.toLocaleString()} bytes</small></button>)}</div></div>}

              <div className="estimate-toolbar">
                <div><span className="eyebrow">工作副本明细</span><h3>{visibleEstimateLines.length} / {estimate.lines.length} 行</h3></div>
                <input value={estimateSearch} onChange={(event) => setEstimateSearch(event.target.value)} placeholder="搜索区域、项目或来源单元格" />
                <select value={estimateScope} onChange={(event) => setEstimateScope(event.target.value as typeof estimateScope)}><option value="all">全部范围</option><option value="included">已纳入</option><option value="excluded">已排除</option></select>
              </div>
              <div className="estimate-table-wrap"><table className="estimate-table"><thead><tr><th>区域 / 项目</th><th>来源</th><th>工程量</th><th>主材成本</th><th>辅材成本</th><th>人工成本</th><th>当前成本</th><th>范围</th><th>操作</th></tr></thead><tbody>{visibleEstimateLines.map((line) => {
                const draft = estimateLineDrafts[line.line_id] ?? { quantity: "", main_material_unit_cost: "", auxiliary_unit_cost: "", labor_unit_cost: "", inclusion_status: line.inclusion_status };
                const updateDraft = (change: Partial<typeof draft>) => setEstimateLineDrafts((current) => ({ ...current, [line.line_id]: { ...draft, ...change } }));
                return <tr key={line.line_id} className={line.inclusion_status === "excluded" ? "excluded" : ""}><td><strong>{line.section}</strong><span>{line.name}</span><small>{line.unit} · 源金额 {formatMoney(line.source_amount)}</small></td><td><code>{line.source_locator}</code>{line.source_scope_conflict && <small>源范围有冲突</small>}</td><td><input type="number" min="0" step="0.0001" value={draft.quantity} onChange={(event) => updateDraft({ quantity: event.target.value })} /></td><td><input type="number" min="0" step="0.01" value={draft.main_material_unit_cost} onChange={(event) => updateDraft({ main_material_unit_cost: event.target.value })} /></td><td><input type="number" min="0" step="0.01" value={draft.auxiliary_unit_cost} onChange={(event) => updateDraft({ auxiliary_unit_cost: event.target.value })} /></td><td><input type="number" min="0" step="0.01" value={draft.labor_unit_cost} onChange={(event) => updateDraft({ labor_unit_cost: event.target.value })} /></td><td>{formatMoney(line.current_cost)}</td><td><select value={draft.inclusion_status} onChange={(event) => updateDraft({ inclusion_status: event.target.value as EstimateLine["inclusion_status"] })}><option value="included">纳入</option><option value="excluded">排除</option></select>{line.exclusion_reason && <small>{line.exclusion_reason}</small>}</td><td><button type="button" disabled={busy} onClick={() => saveEstimateLine(line)}>保存</button></td></tr>;
              })}</tbody></table></div>
            </section> : <section className="empty-state"><div className="empty-icon">¥</div><h2>暂无预算</h2><p>当前项目尚未接入预算源文件。</p></section>
          ) : selected && view === "spatial" ? (
            <section className="operation-workspace">
              <div className="section-heading"><div><span className="eyebrow">M2 受控测试区域</span><h2>空间与工程量</h2></div><span className="saved-tag">修订 v{spatial?.revision_no ?? 0}</span></div>
              <p className="operation-intro">这是参数几何测试对象。尺寸和扣除区由人工明确输入，面积由确定性公式计算，结果可继续接报价和成果版本。</p>
              <form className="panel edit-form" onSubmit={saveSpatial}>
                <div className="edit-row"><label>外框宽度（m）<input type="number" min="0.01" step="0.01" value={spatialDraft.width} onChange={(event) => setSpatialDraft((current) => ({ ...current, width: event.target.value }))} /></label><label>外框长度（m）<input type="number" min="0.01" step="0.01" value={spatialDraft.length} onChange={(event) => setSpatialDraft((current) => ({ ...current, length: event.target.value }))} /></label><label>未税单位成本（元/m²）<input type="number" min="0" step="0.01" placeholder="未知" value={spatialDraft.unit_cost_net} onChange={(event) => setSpatialDraft((current) => ({ ...current, unit_cost_net: event.target.value }))} /></label><label>成本加成<input type="number" min="0" step="0.01" value={spatialDraft.cost_markup} onChange={(event) => setSpatialDraft((current) => ({ ...current, cost_markup: event.target.value }))} /></label><label>试用税率<input type="number" min="0" step="0.01" value={spatialDraft.trial_tax_rate} onChange={(event) => setSpatialDraft((current) => ({ ...current, trial_tax_rate: event.target.value }))} /></label><button type="submit" disabled={busy}>保存几何与报价</button></div>
                <div className="section-heading"><div><span className="eyebrow">可选扣除区域</span><h3>{spatialDraft.deductions.length} 个扣除区</h3></div><button type="button" onClick={addDeduction}>新增扣除区</button></div>
                {spatialDraft.deductions.map((deduction, index) => <div className="edit-row" key={deduction.deduction_id}><strong>{deduction.deduction_id}</strong>{(["x", "y", "width", "length"] as const).map((key) => <label key={key}>{key}<input type="number" min="0" step="0.01" value={deduction[key]} onChange={(event) => setSpatialDraft((current) => ({ ...current, deductions: current.deductions.map((item, itemIndex) => itemIndex === index ? { ...item, [key]: event.target.value } : item) }))} /></label>)}<button type="button" aria-label="删除扣除区" onClick={() => setSpatialDraft((current) => ({ ...current, deductions: current.deductions.filter((_, itemIndex) => itemIndex !== index) }))}>删除</button></div>)}
              </form>
              {spatial?.area_m2 && <div className="summary-grid"><article className="summary-card emphasis"><span>净面积</span><strong>{spatial.area_m2} m²</strong><small>外框 {spatial.width} × {spatial.length} m</small></article>{(spatial.quantity_items ?? []).map((item) => <article className="summary-card" key={item.quantity_item_id}><span>{item.description}</span><strong>{item.quantity} {item.unit}</strong><small>{item.formula}</small></article>)}</div>}
              {spatial?.quote && <div className="summary-grid"><article className="summary-card"><span>未税报价（草稿）</span><strong>{spatial.quote.result.sale_net ? `¥${spatial.quote.result.sale_net}` : "未知"}</strong><small>单位成本 {spatial.quote.pricing.unit_cost_net ?? "未知"} · 加成 {Number(spatial.quote.pricing.cost_markup) * 100}%</small></article><article className="summary-card"><span>含税报价（草稿）</span><strong>{spatial.quote.result.sale_gross ? `¥${spatial.quote.result.sale_gross}` : "未知"}</strong><small>试用税率 {Number(spatial.quote.pricing.trial_tax_rate) * 100}%</small></article><article className="summary-card"><span>报价基线</span><strong>v{spatial.revision_no}</strong><small>{spatial.quote.formula_version} · {spatial.quote.pricing.source_label}</small></article></div>}
              {spatial?.artifacts?.length ? <div className="file-table-wrap"><table className="file-table"><thead><tr><th>成果文件</th><th>类型</th><th>字节</th><th>状态</th><th>操作</th></tr></thead><tbody>{spatial.artifacts.map((artifact) => <tr key={artifact.artifact_id}><td><strong>{artifact.filename}</strong><small>SHA-256 {artifact.sha256.slice(0, 16)}...</small></td><td>{artifact.artifact_kind}</td><td>{artifact.size_bytes.toLocaleString()}</td><td>{artifact.status}</td><td><button type="button" onClick={() => downloadSpatialArtifact(artifact)} aria-label={`下载 ${artifact.filename}`} title="下载成果"><Download size={17} /></button></td></tr>)}</tbody></table></div> : null}
              {spatial?.revisions && <div className="file-table-wrap"><table className="file-table"><thead><tr><th>修订</th><th>尺寸</th><th>净面积</th><th>来源</th><th>时间</th></tr></thead><tbody>{spatial.revisions.map((revision) => <tr key={revision.geometry_revision_id}><td>v{revision.revision_no}</td><td>{revision.width_text} × {revision.length_text} m</td><td>{revision.area_m2_text} m²</td><td>参数输入</td><td>{revision.created_at}</td></tr>)}</tbody></table></div>}
            </section>
          ) : selected && view === "procurement" ? (
            <section className="operation-workspace">
              <div className="section-heading"><div><span className="eyebrow">M4-01 采购施工闭环</span><h2>材料订单、收货与分派</h2></div><span className="saved-tag">外部下单已关闭</span></div>
              <p className="operation-intro">这里记录采购草稿和现场事实。数量由订单→收货→分派逐步守恒；当前版本只保存本地记录，不会向供应商下单或付款。</p>
              <form className="panel edit-form" onSubmit={createProcurementOrder}><div className="edit-row"><label>供应商<input required value={procurementDraft.supplier_name} onChange={(event) => setProcurementDraft((current) => ({ ...current, supplier_name: event.target.value }))} placeholder="测试供应商" /></label><label>到货地点<input required value={procurementDraft.delivery_location} onChange={(event) => setProcurementDraft((current) => ({ ...current, delivery_location: event.target.value }))} placeholder="项目现场" /></label><label>材料名称<input required value={procurementDraft.item_name} onChange={(event) => setProcurementDraft((current) => ({ ...current, item_name: event.target.value }))} placeholder="地板" /></label><label>规格<input value={procurementDraft.specification} onChange={(event) => setProcurementDraft((current) => ({ ...current, specification: event.target.value }))} /></label><label>订单数量<input required type="number" min="0.0001" step="0.0001" value={procurementDraft.quantity} onChange={(event) => setProcurementDraft((current) => ({ ...current, quantity: event.target.value }))} /></label><label>单位<input required value={procurementDraft.unit} onChange={(event) => setProcurementDraft((current) => ({ ...current, unit: event.target.value }))} /></label><button type="submit" disabled={busy}>保存订单草稿</button></div></form>
              <div className="procurement-actions"><label>数量<input type="number" min="0.0001" step="0.0001" value={procurementAction.quantity} onChange={(event) => setProcurementAction((current) => ({ ...current, quantity: event.target.value }))} /></label><label>目标区域<input value={procurementAction.target_area} onChange={(event) => setProcurementAction((current) => ({ ...current, target_area: event.target.value }))} placeholder="接待区" /></label><label>接收班组<input value={procurementAction.recipient} onChange={(event) => setProcurementAction((current) => ({ ...current, recipient: event.target.value }))} placeholder="施工班组 A" /></label><label>证据引用<input value={procurementAction.evidence_ref} onChange={(event) => setProcurementAction((current) => ({ ...current, evidence_ref: event.target.value }))} placeholder="照片或记录编号" /></label></div>
              <div className="procurement-list">{procurementOrders.length ? procurementOrders.map((order) => <article className="procurement-card" key={order.order_id}><div className="section-heading"><div><strong>{order.supplier_name} · {order.delivery_location}</strong><small>订单草稿 v{order.revision_no} · {order.source_ref}</small></div><span className="saved-tag">{order.status}</span></div>{order.lines.map((line) => <div className="procurement-line" key={line.line_id}><div><strong>{line.item_name}</strong><small>{line.specification} · {line.unit}</small></div><span>订单 {line.ordered_quantity}</span><span>已收 {line.received_quantity}</span><span>已分派 {line.allocated_quantity}</span><span>可分派 {line.remaining_quantity}</span></div>)}<div className="section-actions"><button type="button" disabled={busy} onClick={() => void procurementActionSubmit(order, "receipts")}>记录收货</button><button type="button" disabled={busy} onClick={() => void procurementActionSubmit(order, "allocations")}>记录分派</button></div>{order.receipts.length > 0 && <small>收货记录 {order.receipts.length} 条 · 分派记录 {order.allocations.length} 条</small>}</article>) : <div className="files-empty">还没有材料订单草稿</div>}</div>
              <div className="change-workspace"><div className="section-heading"><div><span className="eyebrow">M4-02 问题与变更</span><h3>变更影响与验收</h3></div><span className="saved-tag">旧成果保留</span></div><p className="operation-intro">变更绑定当前项目的设计/几何基线，分析会生成新的 JSON、HTML 和 manifest 草稿。验收只记录责任人的结论，不自动发布施工图或执行外部动作。</p><form className="panel edit-form" onSubmit={createChange}><div className="edit-row"><label>变更标题<input required value={changeDraft.title} onChange={(event) => setChangeDraft((current) => ({ ...current, title: event.target.value }))} placeholder="现场材料替换" /></label><label>原因<input required value={changeDraft.reason} onChange={(event) => setChangeDraft((current) => ({ ...current, reason: event.target.value }))} placeholder="供应不足" /></label><label>变更说明<input required value={changeDraft.description} onChange={(event) => setChangeDraft((current) => ({ ...current, description: event.target.value }))} placeholder="描述前后差异" /></label><label>工程量变化（m²）<input type="number" step="0.0001" value={changeDraft.quantity_delta_m2} onChange={(event) => setChangeDraft((current) => ({ ...current, quantity_delta_m2: event.target.value }))} placeholder="未知" /></label><label>未税成本变化<input type="number" step="0.01" value={changeDraft.cost_delta_net} onChange={(event) => setChangeDraft((current) => ({ ...current, cost_delta_net: event.target.value }))} placeholder="未知" /></label><label>工期变化（天）<input type="number" step="0.0001" value={changeDraft.schedule_delta_days} onChange={(event) => setChangeDraft((current) => ({ ...current, schedule_delta_days: event.target.value }))} placeholder="未知" /></label><button type="submit" disabled={busy}>保存变更请求</button></div></form><div className="procurement-actions"><label>验收证据<input value={changeAcceptance.evidence_ref} onChange={(event) => setChangeAcceptance((current) => ({ ...current, evidence_ref: event.target.value }))} placeholder="照片或签证编号" /></label><label>验收备注<input value={changeAcceptance.note} onChange={(event) => setChangeAcceptance((current) => ({ ...current, note: event.target.value }))} placeholder="责任人备注" /></label></div><div className="change-list">{changes.length ? changes.map((change) => <article className="procurement-card" key={change.change_id}><div className="section-heading"><div><strong>变更 {change.change_no} · {change.title}</strong><small>{change.reason} · v{change.version}</small></div><span className="saved-tag">{change.status}</span></div><p>{change.description}</p><div className="procurement-line"><span>影响成果 {change.impact.affected_artifact_count ?? "待分析"}</span><span>工程量 {change.impact.quantity_delta_m2 ?? "未知"}</span><span>成本 {change.impact.cost_delta_net ?? "未知"}</span><span>工期 {change.impact.schedule_delta_days ?? "未知"}</span></div><div className="section-actions">{change.status === "draft" && <button type="button" disabled={busy} onClick={() => void analyzeChange(change)}>生成影响分析</button>}{change.status === "analyzed" && <button type="button" disabled={busy} onClick={() => void acceptChange(change)}>记录验收通过</button>}</div>{change.artifacts.length > 0 && <div className="artifact-list">{change.artifacts.map((artifact) => <button type="button" key={artifact.artifact_id} onClick={() => void downloadChangeArtifact(artifact)}>{artifact.filename} · {artifact.size_bytes.toLocaleString()} bytes</button>)}</div>}{change.acceptances.length > 0 && <small>验收：{change.acceptances[change.acceptances.length - 1].conclusion} · {change.acceptances[change.acceptances.length - 1].evidence_ref}</small>}</article>) : <div className="files-empty">还没有变更请求</div>}</div></div>
            </section>
          ) : selected && view === "jobs" ? (
            <section className="operation-workspace">
              <div className="section-heading"><div><span className="eyebrow">持久执行</span><h2>成果与任务</h2></div><span className="saved-tag">重启可恢复</span></div>
              <p className="operation-intro">任务状态、尝试次数和输入来源写入本地数据库。失败或重启后的任务允许重试，已取消或已完成任务不会被伪装成成功。</p>
              <div className="job-list">{jobs.map((job) => <article className="job-row" key={job.job_id}><div><strong>{job.job_type === "cad_report_import" ? "CAD 报告接入" : job.job_type}</strong><p>{job.input_ref} · attempt {job.attempt_count}</p>{job.error_message && <small>{job.error_code}: {job.error_message}</small>}</div><div className="job-state"><span className={`job-status job-${job.status}`}>{job.status}</span>{job.output.issue_count !== undefined && <small>{job.output.issue_count} 条来源问题</small>}{(job.status === "retryable" || job.status === "failed") && <button type="button" onClick={() => updateJob(job, "retry")}>重试</button>}{(job.status === "queued" || job.status === "running" || job.status === "retryable") && <button type="button" onClick={() => updateJob(job, "cancel")}>取消</button>}</div></article>)}</div>
            </section>
          ) : (
            <section className="empty-state"><div className="empty-icon">＋</div><h2>创建第一个项目</h2><p>在左侧输入项目名称。</p></section>
          )}
        </section>
      </main>
      {preview && <div className="preview-overlay" role="dialog" aria-modal="true" aria-label={`预览 ${preview.name}`}><div className="preview-window"><header><strong>{preview.name}</strong><button type="button" onClick={() => setPreview(undefined)} aria-label="关闭预览" title="关闭预览"><X size={20} /></button></header>{preview.contentType === "application/pdf" ? <PdfPreview url={preview.url} /> : <img src={preview.url} alt={preview.name} />}</div></div>}
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<AccountGate>{session => <App key={session.user?.user_id ?? "local"} session={session} />}</AccountGate>);
