import { useCallback, useEffect, useState } from "react";
import { apiHeaders, checkSessionResponse } from "./session";

type ProjectFile = { file_id: string; filename: string; sha256: string; size_bytes: number; download_url: string };
type Segment = { segment_id: string; locator: string; text: string };
type Extraction = {
  extraction_id: string; file_id: string; filename: string; status: string; status_reason: string | null;
  segment_count: number; segments: Segment[]; text_sha256: string | null; file_sha256: string;
  warnings: string[]; extractor_kind: string; current: boolean;
};
type Artifact = { artifact_id: string; artifact_kind: string; filename: string; size_bytes: number; sha256: string };
type Handover = {
  supported_scope: { statement: string; status: string }[];
  unsupported_scope: { statement: string; reason: string }[];
  review_tasks: { role: string; statement: string; status: string }[];
  source_extractions: { filename: string; status: string; segment_count: number }[];
  object_ids: string[];
};
type Delivery = {
  item: null | {
    delivery: { delivery_id: string; production_revision_id: string; input_hash: string; handover: Handover };
    artifacts: Artifact[]; status: string;
  };
  jobs: { delivery_id: string }[];
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
  extracted: "已解析文本", no_extractable_text_layer: "无可靠文本层", unsupported_format: "本切片不解析",
  draft: "技术草稿 · 待专业复核", source_outdated: "采用基线已变化 · 过期",
};
const artifactText: Record<string, string> = {
  technical_plan_svg: "技术平面（标注）", detail_node_svg: "节点示意", material_schedule_csv: "材料做法表",
  technical_handover_html: "技术交接说明", handover_json: "交接数据 JSON",
  delivery_manifest_json: "成果清单", delivery_zip: "技术交付包 ZIP",
};

export function AiSourceDeliveryPanel({ projectId }: { projectId: string }) {
  const base = `/api/v1/projects/${projectId}`;
  const [files, setFiles] = useState<ProjectFile[]>([]);
  const [extractions, setExtractions] = useState<Extraction[]>([]);
  const [delivery, setDelivery] = useState<Delivery | null>(null);
  const [openFile, setOpenFile] = useState("");
  const [plan, setPlan] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = useCallback(async () => {
    try {
      const [fileList, extractionList, deliveryState] = await Promise.all([
        request<{ items: ProjectFile[] }>(`${base}/files`),
        request<{ items: Extraction[] }>(`${base}/ai/source-extractions`),
        request<Delivery>(`${base}/ai/technical-delivery`),
      ]);
      setFiles(fileList.items);
      setExtractions(extractionList.items);
      setDelivery(deliveryState);
      const planArtifact = deliveryState.item?.artifacts.find((item) => item.artifact_kind === "technical_plan_svg");
      if (planArtifact) {
        const response = await fetch(`${base}/ai/technical-delivery/artifacts/${planArtifact.artifact_id}/content`, { headers: apiHeaders });
        setPlan(response.ok ? `data:image/svg+xml;charset=utf-8,${encodeURIComponent(await response.text())}` : "");
      } else {
        setPlan("");
      }
    } catch (e) {
      setError((e as Error).message);
    }
  }, [base]);

  useEffect(() => { void load(); }, [load]);

  async function act(action: () => Promise<void>) {
    setBusy(true); setError(""); setMessage("");
    try { await action(); } catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  async function extract(fileId: string) {
    await act(async () => {
      const result = await request<{ item: Extraction; status: string }>(`${base}/ai/source-extractions`, "POST", { file_id: fileId });
      setMessage(`${result.item.filename}：${statusText[result.item.status] ?? result.item.status}${result.item.status_reason ? `（${result.item.status_reason}）` : ""}。内容仅存本地，未外发。`);
      await load();
    });
  }

  async function generate() {
    await act(async () => {
      await request(`${base}/ai/technical-delivery`, "POST", {}, { "Idempotency-Key": crypto.randomUUID() });
      setMessage("已从当前采用的同源深化包生成技术交付草稿；未创建施工图、订单或正式发布。");
      await load();
    });
  }

  async function download(artifact: Artifact) {
    await act(async () => {
      const response = await fetch(`${base}/ai/technical-delivery/artifacts/${artifact.artifact_id}/content`, { headers: apiHeaders });
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

  const extractedByFile = new Map(extractions.map((item) => [item.file_id, item]));
  const current = delivery?.item ?? null;

  return <section className="ai-panel ai-source-delivery-panel" aria-busy={busy}>
    <header className="section-heading"><h3>原件内容与技术交付草稿</h3><span className="design-status">本地解析 · 非施工图</span></header>
    <p className="ai-boundary">解析只读取已保存的原件字节，保留可定位片段；扫描件、CAD 与图片明确标记未解析，不编造内容。抽取结果仅本地可查，未获明确批准前不进入外部模型上下文。技术交付草稿绑定同一采用对象集，供专业复核准备，不是施工图、正式报价或发布。</p>
    {error && <p className="design-feedback error" role="alert">{error}</p>}
    {message && <p className="design-feedback" role="status">{message}</p>}

    <div className="ai-development-tables">
      <div><h4>项目原件与解析状态（{files.length}）</h4>
        {files.length ? <ul className="ai-option-conflicts">{files.map((file) => {
          const record = extractedByFile.get(file.file_id);
          return <li key={file.file_id}>
            <strong>{file.filename}</strong> · {record ? `${statusText[record.status] ?? record.status} · ${record.segment_count} 段${record.current ? "" : " · 原件已变化"}` : "尚未解析"}
            <div className="ai-source-actions">
              <button type="button" className="outline-action" disabled={busy} onClick={() => void extract(file.file_id)}>{record ? "重新解析" : "解析原件"}</button>
              <a href={file.download_url} target="_blank" rel="noopener noreferrer">打开原件</a>
              {record && record.segments.length > 0 && <button type="button" className="outline-action" onClick={() => setOpenFile(openFile === file.file_id ? "" : file.file_id)}>{openFile === file.file_id ? "收起片段" : "查看来源片段"}</button>}
            </div>
            {record?.status_reason && <small>{record.status_reason}</small>}
            {openFile === file.file_id && record && <ol className="ai-source-segments">{record.segments.slice(0, 20).map((segment) => <li key={segment.segment_id}><code>{segment.locator}</code><span>{segment.text.slice(0, 240)}</span></li>)}</ol>}
          </li>;
        })}</ul> : <p className="files-empty">尚无项目原件。</p>}
      </div>
      <div><h4>技术交付草稿</h4>
        <div className="design-baseline"><span>{current ? statusText[current.status] ?? current.status : "尚未生成"}</span><span>专业复核：待办</span><span>施工发布：关闭</span></div>
        <button type="button" className="dark-action" disabled={busy} onClick={() => void generate()}>从当前深化包生成技术交付草稿</button>
        <p><small>需先在「深化量价」页生成并采用有效候选；采用基线变化后旧交付包自动标记过期，旧文件仍可下载。</small></p>
        {current ? <>
          <p><code>{current.delivery.production_revision_id}</code> · 输入哈希 <code>{current.delivery.input_hash.slice(0, 16)}…</code></p>
          {current.status === "source_outdated" && <p className="design-feedback error" role="alert">采用基线已变化，此技术包为过期草稿，不得用于交接。</p>}
          {plan && <div className="ai-development-preview"><h4>技术平面（标注对象 ID 与边界尺寸）</h4><img src={plan} alt="同源技术平面草稿" /></div>}
          <h4>已支持范围</h4><ul className="ai-option-conflicts">{current.delivery.handover.supported_scope.map((item, index) => <li key={index}>{item.statement} · {item.status}</li>)}</ul>
          <h4>明确缺项</h4><ul className="ai-option-conflicts">{current.delivery.handover.unsupported_scope.map((item, index) => <li key={index}>{item.statement}：{item.reason}</li>)}</ul>
          <h4>专业复核待办</h4><ul className="ai-option-conflicts">{current.delivery.handover.review_tasks.map((item, index) => <li key={index}>{item.role} · {item.statement} · {item.status}</li>)}</ul>
          <div className="ai-development-artifacts"><h4>真实成果文件（{current.artifacts.length}）</h4><div>{current.artifacts.map((artifact) => <button type="button" key={artifact.artifact_id} disabled={busy} onClick={() => void download(artifact)}>{artifactText[artifact.artifact_kind] ?? artifact.filename}<small>{artifact.filename} · {artifact.size_bytes.toLocaleString()} 字节 · SHA {artifact.sha256.slice(0, 12)}…</small></button>)}</div></div>
        </> : <p className="files-empty">尚无技术交付成果。</p>}
      </div>
    </div>
  </section>;
}
