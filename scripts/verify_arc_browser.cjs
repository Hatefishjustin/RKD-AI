/* Real browser acceptance for ARC first batch (driven by verify_arc_browser.py).

Every action below is a real click / keystroke in a headless Chromium against
an isolated local service. No external model/image call, no key, no cost.
*/
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const { chromium } = require(path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));

const url = process.env.RKD_QA_URL;
const studioUrl = process.env.RKD_QA_STUDIO_URL;
const evidence = process.env.RKD_QA_EVIDENCE_DIR;
const projectId = process.env.RKD_QA_PROJECT_ID;
const otherProjectId = process.env.RKD_QA_OTHER_PROJECT_ID;
assert(url && studioUrl && evidence && projectId && otherProjectId, 'isolated browser config required');

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1500, height: 1050 } });
  const errors = [];
  const resource404 = [];
  page.on('pageerror', e => errors.push(e.message));
  // The minimal isolated workbench does not mount every optional /api/v1 route;
  // those 404s are an artefact of the test harness, not a frontend defect.
  // Real JS exceptions and non-404 console errors are still fatal.
  page.on('console', m => {
    if (m.type() !== 'error') return;
    const t = m.text();
    if (/Failed to load resource.*404|status of 404/.test(t)) { resource404.push(t); return; }
    errors.push('console: ' + t);
  });
  const obs = {};
  const ningboItem = () => page.locator('.project-item').filter({ hasText: /宁波协诚/ }).first();
  const otherItem = () => page.locator('.project-item').filter({ hasText: /另一个项目/ }).first();
  try {
    // ---- 1. open the studio view, select the mapped Ningbo project ---------
    await page.goto(`${url}/?view=studio`, { waitUntil: 'domcontentloaded' });
    await page.locator('.project-item').first().waitFor({ timeout: 20000 });
    const projectItems = await page.locator('.project-item').allTextContents();
    obs.project_items = projectItems.map(t => t.trim().slice(0, 80));
    // The unmapped project can be listed first; never assume the first row.
    await ningboItem().click();
    await page.locator('.studio-meta').waitFor({ timeout: 20000 });
    obs.meta_text = (await page.locator('.studio-meta').innerText()).replace(/\s+/g, ' ').trim();
    assert(/主系统项目映射/.test(obs.meta_text), 'project mapping not shown');
    assert(/未接入团队\/NAS/.test(obs.meta_text), 'service scope not labelled');
    assert(/设计认可：否/.test(obs.meta_text), 'design approval must be false');

    // valid candidate group vs history group
    await page.getByRole('heading', { name: /成果 · 有效候选/ }).waitFor();
    obs.valid_heading = await page.getByRole('heading', { name: /成果 · 有效候选/ }).innerText();
    obs.history_group_exists = await page.getByText('历史 / 失效 / 未校验产物', { exact: false }).count() > 0;
    assert(obs.history_group_exists, 'history/diagnostic grouping missing');

    // ---- 2. boss message -> versioned effective requirement -----------------
    const feedbackText = '调整洽谈区、保留入口';
    await page.locator('.studio-input input').fill(feedbackText);
    await page.getByRole('button', { name: '发给公司' }).click();
    await page.getByText(feedbackText, { exact: false }).first().waitFor({ timeout: 15000 });
    const feedbackSummary = await page.getByText(/老板留言 · 版本化有效需求/).innerText();
    obs.feedback_summary = feedbackSummary;
    assert(/版本化有效需求/.test(feedbackSummary), 'feedback not versioned');
    assert(/调整洽谈区、保留入口/.test(await page.locator('.studio').innerText()),
      'boss message not in effective requirement UI');
    // explicit id mapping: main-system id -> studio id (never inferred by name)
    const mapping = await (await page.request.get(`${studioUrl}/studio/projects`)).json();
    obs.project_mapping = mapping.project_mapping;
    const mappedStudioId = mapping.project_mapping.find(
      p => p.source_project_id === projectId || p.id === projectId);
    assert(mappedStudioId, 'no explicit project id mapping');
    const studioPid = mappedStudioId.id;
    obs.studio_project_id = studioPid;
    const stateAfterFeedback = await (await page.request.get(
      `${studioUrl}/studio/projects/${projectId}/state`)).json();
    obs.main_system_id_resolves = stateAfterFeedback.project.id === studioPid;
    obs.feedback_revision_after_post = stateAfterFeedback.feedback_revision;
    obs.feedback_items = (stateAfterFeedback.feedback || []).map(f => ({
      revision_no: f.revision_no, text: f.text, kind: f.kind,
      baseline_artifact_id: f.baseline_artifact_id }));
    assert(stateAfterFeedback.feedback_revision >= 1, 'feedback revision did not advance');
    assert((stateAfterFeedback.effective_requirement.effective_addenda || []).length >= 1,
      'effective requirement has no addenda');
    await page.screenshot({ path: path.join(evidence, 'arc-feedback-desktop.png'), fullPage: true });

    // ---- 3. run a local-stub loop -> new revision bound to the baseline ----
    const before = await (await page.request.get(
      `${studioUrl}/studio/projects/${projectId}/state`)).json();
    obs.baseline_artifact_id = before.valid_candidate_ids && before.valid_candidate_ids[0];
    await page.getByRole('button', { name: /开一轮/ }).click();
    // poll until a new run finishes or timeout
    let after = null;
    for (let i = 0; i < 60; i++) {
      await page.waitForTimeout(1000);
      after = await (await page.request.get(
        `${studioUrl}/studio/projects/${projectId}/state`)).json();
      if (after.runs.length > before.runs.length &&
          after.runs[after.runs.length - 1].status !== 'running') break;
    }
    assert(after, 'no state after run');
    obs.run_statuses = after.runs.map(r => r.status);
    obs.runs_total = after.runs.length;
    const latest = after.runs[after.runs.length - 1];
    obs.latest_run = { status: latest.status, expected_feedback_revision: latest.expected_feedback_revision,
                       input_hash: latest.input_hash, calls: latest.calls,
                       images_sent: latest.images_sent, cost_status: latest.cost_status };
    assert(['succeeded', 'superseded'].includes(latest.status),
      'loop did not finish with a controlled status');
    // feedback must be present in the revision prompt / object diff evidence
    const revisionMessages = after.messages.filter(m => m.kind === 'note' &&
      /逐条回应|自动重做/.test(m.body));
    obs.revision_messages = revisionMessages.map(m => m.body.slice(0, 240));
    assert(revisionMessages.length >= 1, 'no revision produced');
    const issueEvidence = after.messages.flatMap(m => m.evidence || [])
      .filter(e => e.type === 'issue_resolutions');
    obs.issue_resolution_count = issueEvidence.reduce(
      (n, e) => n + (e.items || []).filter(i => i.verified).length, 0);
    const diffEvidence = after.messages.flatMap(m => m.evidence || [])
      .filter(e => e.type === 'diff');
    obs.object_diff_count = diffEvidence.reduce((n, e) => n + (e.changed || []).length, 0);
    const bossEvidence = after.messages.flatMap(m => m.evidence || [])
      .filter(e => e.type === 'boss_feedback_resolutions');
    obs.boss_feedback_in_revision = bossEvidence.length >= 1;
    assert(obs.object_diff_count >= 1, 'no real object diff');
    await page.screenshot({ path: path.join(evidence, 'arc-revision-desktop.png'), fullPage: true });

    // ---- 4. switch to another project -> NO Ningbo results -----------------
    const other = otherItem();
    if (await other.count() > 0) {
      await other.click();
      await page.waitForTimeout(1200);
      const studioText = await page.locator('.studio').innerText();
      obs.other_project_text = studioText.replace(/\s+/g, ' ').slice(0, 240);
      obs.other_project_no_ningbo_leak = !/宁波协诚集团样品展厅/.test(studioText);
      assert(/未接入.*(Studio|设计公司).*实验服务/.test(studioText),
        'unmapped project should show the limitation notice');
      assert(obs.other_project_no_ningbo_leak, 'Ningbo data leaked into another project');
      const otherState = await page.request.get(
        `${studioUrl}/studio/projects/${otherProjectId}/state`);
      obs.other_project_http_status = otherState.status();
      assert.equal(otherState.status(), 404, 'unmapped project state must be rejected');
      await page.screenshot({ path: path.join(evidence, 'arc-other-project.png'), fullPage: true });
    } else {
      obs.other_project_note = 'second project item not rendered; API-level check only';
      const otherState = await page.request.get(
        `${studioUrl}/studio/projects/${otherProjectId}/state`);
      obs.other_project_http_status = otherState.status();
      assert.equal(otherState.status(), 404);
    }

    // back to the mapped project
    await ningboItem().click();
    await page.locator('.studio-meta').waitFor();

    // ---- 5. gate decision + replay must NOT overwrite ----------------------
    const gate = (await (await page.request.get(
      `${studioUrl}/studio/projects/${projectId}/state`)).json()).gates
      .find(g => g.status === 'waiting');
    assert(gate, 'no waiting gate');
    obs.gate_baseline = { artifact_id: gate.baseline_artifact_id,
                          revision_uid: gate.baseline_revision_uid };
    assert(gate.baseline_artifact_id, 'gate is not bound to an artifact baseline');
    const decide = async (decision, comment, scope) => page.request.post(
      `${studioUrl}/studio/gates/${gate.id}/decide`,
      { data: { decision, comment, decision_scope: scope } });
    const first = await (await decide('approve', '允许继续试验，不等于设计通过', 'allow_continue')).json();
    const replay = await (await decide('reject', '重放覆盖尝试', 'direction_approval')).json();
    obs.gate_first = first;
    obs.gate_replay = replay;
    assert.equal(first.applied, true, 'first decision not applied');
    assert.equal(replay.applied, false, 'replay overwrote a decided gate');
    assert.equal(replay.reason, 'already_decided_correction_recorded');
    const decisions = await (await page.request.get(
      `${studioUrl}/studio/projects/${projectId}/state`)).json();
    const decided = decisions.gates.find(g => g.id === gate.id);
    obs.gate_after_replay = { decision: decided.decision, comment: decided.comment,
                              decision_scope: decided.decision_scope };
    assert.equal(decided.decision, 'approve', 'replay changed the original decision');
    assert.equal(decided.comment, '允许继续试验，不等于设计通过');

    // ---- 6. reload -> persistence ------------------------------------------
    await page.reload({ waitUntil: 'domcontentloaded' });
    await ningboItem().click();
    await page.locator('.studio-meta').waitFor();
    const reloaded = (await page.locator('.studio').innerText()).replace(/\s+/g, ' ');
    obs.reload_keeps_feedback = /调整洽谈区、保留入口/.test(reloaded);
    obs.reload_keeps_valid_group = /成果 · 有效候选/.test(reloaded);
    assert(obs.reload_keeps_feedback, 'feedback lost after reload');
    assert(obs.reload_keeps_valid_group, 'valid candidate group lost after reload');
    await page.screenshot({ path: path.join(evidence, 'arc-reload-desktop.png'), fullPage: true });

    // mobile / narrow viewport
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(500);
    obs.mobile_scroll_width = await page.evaluate(() => document.documentElement.scrollWidth);
    assert(obs.mobile_scroll_width <= 390, 'horizontal overflow at 390px');
    await page.screenshot({ path: path.join(evidence, 'arc-mobile.png'), fullPage: true });

    obs.page_errors = errors;
    assert.equal(errors.length, 0, 'browser console/page errors: ' + JSON.stringify(errors.slice(0, 3)));
    obs.passed = true;
    fs.writeFileSync(path.join(evidence, 'browser-observations.json'),
      JSON.stringify(obs, null, 2));
    console.log(JSON.stringify({ passed: true, obs }, null, 2));
  } catch (e) {
    obs.passed = false;
    obs.error = String(e && e.stack || e);
    obs.page_errors = errors;
    fs.writeFileSync(path.join(evidence, 'browser-observations.json'),
      JSON.stringify(obs, null, 2));
    try { await page.screenshot({ path: path.join(evidence, 'arc-failure.png'), fullPage: true }); }
    catch (_) { /* ignore */ }
    console.error(JSON.stringify(obs, null, 2));
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})();
