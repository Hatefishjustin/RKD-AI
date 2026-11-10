import { useEffect, useState } from 'react';
import { accountApi, apiHeaders, checkSessionResponse } from './session';

type Check = { code: string; status: string; note: string; artifact_ids: string[] };
type Task = { checklist_prompts: { code: string; label: string }[]; checklist: { items: Check[] } | null; task_id: string; project_id: string; project_name?: string; position_name: string; status: string; version: number; source_outdated: boolean; routing_status: string; can_review: boolean; note: string | null; snapshot: { artifacts: { artifact_id: string; filename: string }[]; baseline: { production_revision_no: number } } };
const stateNames: Record<string, string> = { pending: '待草稿审查', reviewed: '草稿审查已记录', changes_requested: '需修改' };

export function ReviewTasks({ projectId, refreshKey = '' }: { projectId?: string; refreshKey?: string }) {
  const [summary, setSummary] = useState<{ pending: number; changes_requested: number; unverified_items: number; historical_tasks: number }>();
  const [items, setItems] = useState<Task[]>([]);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    let active = true;
    async function load() {
      try {
        const projects = projectId ? [{ project_id: projectId, name: '' }] : (await accountApi<{ items: { project_id: string; name: string }[] }>('/api/v1/projects')).items;
        const results = await Promise.all(projects.map(async project => {
          const result = await accountApi<{ items: Task[]; summary?: { pending: number; changes_requested: number; unverified_items: number; historical_tasks: number } }>(`/api/v1/projects/${project.project_id}/review-tasks`);
          if (active && projectId) setSummary(result.summary);
          return result.items.map(item => ({ ...item, project_name: project.name }));
        }));
        if (active) { setItems(results.flat().filter(item => projectId || item.can_review)); setError(''); }
      } catch (e) { if (active) setError((e as Error).message); }
      finally { if (active) setLoading(false); }
    }
    setLoading(true); void load();
    const timer = window.setInterval(() => void load(), 60000);
    return () => { active = false; window.clearInterval(timer); };
  }, [projectId, refreshKey, refresh]);
  return <details className="review-tasks" open={Boolean(projectId)}>
    <summary>{projectId ? '本项目草稿审查记录' : `我的草稿审查待办（${items.length}）`}</summary>
    <p>按当前岗位和项目权限分派，每分钟刷新。结论仅针对所列生产版本，正式发布尚未开放。</p>
    <button type="button" disabled={loading} onClick={() => setRefresh(v => v + 1)}>刷新审查事项</button>
    {projectId && summary && <p role="status">当前版：{summary.pending}项待审、{summary.changes_requested}项需修改、{summary.unverified_items}个已记录检查项仍未核验。历史事项{summary.historical_tasks}项；正式发布关闭。</p>}
    {error && <p role="alert">待办读取失败：{error}。请刷新后重试。</p>}
    {loading ? <p role="status">正在读取…</p> : !error && items.length === 0 && <p>{projectId ? '尚无送审记录。请先检查当前生产草稿。' : '当前没有分派给你的待办。'}</p>}
    {!loading && items.map(item => <ReviewTask key={item.task_id} item={item} onSaved={() => setRefresh(v => v + 1)} />)}
  </details>;
}

function ReviewTask({ item, onSaved }: { item: Task; onSaved: () => void }) {
  const [checks, setChecks] = useState<Check[]>(item.checklist_prompts.map(prompt => ({ code: prompt.code, status: 'unknown', note: '', artifact_ids: [] })));
  const [note, setNote] = useState(''); const [status, setStatus] = useState('changes_requested');
  const [busy, setBusy] = useState(false); const [error, setError] = useState('');
  async function save() {
    setBusy(true); setError('');
    try { await accountApi(`/api/v1/projects/${item.project_id}/review-tasks/${item.task_id}`, 'POST', { expected_version: item.version, status, note, checklist: checks }); onSaved(); }
    catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function download() {
    setBusy(true); setError('');
    try {
      const response = await fetch(`/api/v1/projects/${item.project_id}/review-tasks/${item.task_id}/evidence`, { headers: apiHeaders });
      checkSessionResponse(response);
      if (!response.ok) throw new Error((await response.json()).message || '审核包下载失败');
      const url = URL.createObjectURL(await response.blob());
      const anchor = document.createElement('a'); anchor.href = url; anchor.download = `draft-review-${item.task_id}.zip`; anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  return <article className="review-task">
    <h4>{item.project_name && `${item.project_name} · `}{item.position_name} · 生产 v{item.snapshot.baseline.production_revision_no}</h4>
    <p>{stateNames[item.status]}{item.source_outdated ? ' · 成果已变化，请重新检查并送审' : item.status === 'pending' && item.routing_status === 'awaiting_assignment' ? ' · 等待管理员配置有效岗位成员及项目权限，需避开制作者和提交者' : ''}</p>
    <button type="button" disabled={busy} onClick={() => void download()}>下载本版草稿审核包</button>
    <p>包含送审时的8份成果、文件校验清单和当前审查记录。历史版本会标注已变化，不作为当前版结论。</p>
    {item.checklist && <ul>{item.checklist.items.map(check => <li key={check.code}>{item.checklist_prompts.find(p => p.code === check.code)?.label}：{check.status === 'checked' ? '已核对（人工记录）' : check.status === 'needs_changes' ? '需修改' : '未核验'} · {check.note}</li>)}</ul>}
    {item.note && <p>审查说明：{item.note}</p>}
    {error && <p role="alert">{error}</p>}
    {item.can_review && <form onSubmit={e => { e.preventDefault(); void save(); }}>
      <fieldset disabled={busy}><legend>记录本版草稿审查</legend>
        <label>草稿审查结论<select aria-label="草稿审查结论" value={status} onChange={e => setStatus(e.target.value)}><option value="changes_requested">需要修改</option><option value="reviewed">已审查，记录意见</option></select></label>
        {checks.map((check, index) => <fieldset key={check.code}><legend>{item.checklist_prompts[index].label}</legend>
          <label>项目状态<select aria-label={`${item.checklist_prompts[index].label}状态`} value={check.status} onChange={e => setChecks(old => old.map((c, i) => i === index ? { ...c, status: e.target.value } : c))}><option value="unknown">未核验</option><option value="checked">已核对（人工记录）</option><option value="needs_changes">需要修改</option></select></label>
          <label>依据或待核验原因<textarea required maxLength={1000} value={check.note} onChange={e => setChecks(old => old.map((c, i) => i === index ? { ...c, note: e.target.value } : c))} /></label>
          <label>引用本版成果（可多选；已核对时必选）<select multiple aria-label={`${item.checklist_prompts[index].label}成果`} value={check.artifact_ids} onChange={e => { const ids = Array.from(e.target.selectedOptions, o => o.value); setChecks(old => old.map((c, i) => i === index ? { ...c, artifact_ids: ids } : c)); }}>{item.snapshot.artifacts.map(a => <option key={a.artifact_id} value={a.artifact_id}>{a.filename}</option>)}</select></label>
        </fieldset>)}
        <p>未核验项目保持未知，已核对仅表示本人记录，不代表有权专业签署。</p>
        <label>审查说明<textarea required maxLength={2000} value={note} onChange={e => setNote(e.target.value)} /></label>
        <button type="submit">{busy ? '正在保存…' : '保存草稿审查记录'}</button>
      </fieldset>
    </form>}
  </article>;
}
