/* W0 real-browser acceptance: select an OLD plan, give feedback, run a revise,
   and verify the new revision's parent points at the plan the user picked.

   Driven by verify_w0_browser.py. Real clicks/keystrokes in headless Edge.
   No external model/image call, no key, no cost.
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
const baselineId = process.env.RKD_QA_BASELINE_ID;
const baselineUid = process.env.RKD_QA_BASELINE_UID;
assert(url && studioUrl && evidence && projectId && baselineId && baselineUid,
  'isolated browser config required');

const getState = async (page) => {
  const r = await page.request.get(
    `${studioUrl}/studio/projects/${encodeURIComponent(projectId)}/state`);
  assert.equal(r.status(), 200, 'studio state not readable');
  return r.json();
};

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1500, height: 1050 } });
  const errors = [];
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('console', m => {
    if (m.type() !== 'error') return;
    const t = m.text();
    if (/Failed to load resource.*404|status of 404/.test(t)) return;
    errors.push('console: ' + t);
  });
  const obs = { baseline_id: baselineId, baseline_uid: baselineUid };
  try {
    await page.goto(`${url}/?view=studio`, { waitUntil: 'domcontentloaded' });
    await page.locator('.project-item').first().waitFor({ timeout: 20000 });
    await page.locator('.project-item').filter({ hasText: /宁波协诚/ }).first().click();
    await page.locator('.studio-meta').waitFor({ timeout: 20000 });

    const before = await getState(page);
    obs.before_runs = before.runs.length;
    obs.before_task_kind = before.task_resolution && before.task_resolution.kind;
    obs.baseline_in_valid_group = (before.artifacts || []).some(
      a => a.id === baselineId && a.display_group === 'valid');
    assert(obs.baseline_in_valid_group, 'selected old plan is not a valid candidate');

    // ---- 1. explicitly pick the OLD plan in the page -----------------------
    const select = page.locator('[data-testid="baseline-select"]');
    await select.waitFor({ timeout: 15000 });
    const options = await select.locator('option').allTextContents();
    obs.baseline_options = options.map(t => t.trim().slice(0, 100));
    assert(obs.baseline_options.some(t => t.includes(baselineId)),
      'old plan not offered in the baseline picker');
    await select.selectOption(baselineId);
    obs.selected_option_value = await select.inputValue();
    assert.equal(obs.selected_option_value, baselineId);

    // ---- 2. feedback bound to that old plan --------------------------------
    const feedbackText = '把主动线净宽扩大到 2100mm，保留入口';
    await page.locator('.studio-input input').fill(feedbackText);
    await page.getByRole('button', { name: '发给公司' }).click();
    await page.getByText(feedbackText, { exact: false }).first().waitFor({ timeout: 15000 });

    const afterFeedback = await getState(page);
    const latestFb = (afterFeedback.feedback || []).slice(-1)[0] || {};
    obs.feedback = {
      revision_no: latestFb.revision_no,
      baseline_artifact_id: latestFb.baseline_artifact_id,
      baseline_selection: latestFb.baseline_selection,
      task_kind: latestFb.task_kind,
    };
    obs.task_resolution_after_feedback = afterFeedback.task_resolution;
    assert.equal(latestFb.baseline_artifact_id, baselineId, 'feedback lost the selected baseline');
    assert.equal(latestFb.baseline_selection, 'user_selected');
    assert.equal(afterFeedback.task_resolution.kind, 'revise');
    assert.equal(afterFeedback.task_resolution.target_revision_uid, baselineUid);

    const taskbarText = (await page.locator('.studio-taskbar').innerText()).replace(/\s+/g, ' ');
    obs.meta_after_feedback = taskbarText.slice(0, 400);
    assert(/本轮任务：revise/.test(taskbarText), 'page does not show the revise task');
    assert(taskbarText.includes(baselineId), 'page does not show the selected old baseline');
    await page.screenshot({ path: path.join(evidence, 'w0-feedback-desktop.png'), fullPage: true });

    // ---- 3. run the loop; new revision must point at the OLD version --------
    await page.getByRole('button', { name: /开一轮/ }).click();
    let after = null;
    for (let i = 0; i < 120; i++) {
      after = await getState(page);
      if (after.runs.length > before.runs.length &&
          after.runs[after.runs.length - 1].status !== 'running') break;
      await page.waitForTimeout(500);
    }
    assert(after && after.runs.length > before.runs.length, 'no new run finished');
    const lastRun = after.runs[after.runs.length - 1];
    obs.last_run = {
      status: lastRun.status, task_kind: lastRun.task_kind,
      target_artifact_id: lastRun.target_artifact_id,
      target_revision_uid: lastRun.target_revision_uid,
    };
    const newPlans = (after.artifacts || []).filter(
      a => a.kind === 'spatial-plan' && a.run_id === lastRun.id);
    obs.new_plans = newPlans.map(a => ({
      id: a.id, revision: a.revision,
      parent_revision_uid: a.parent_revision_uid,
      display_group: a.display_group }));
    obs.fresh_AB_in_revise_run = newPlans.filter(a => a.revision === 1).length;
    const revision = newPlans.find(a => a.revision >= 2);
    assert(revision, 'no continued revision was produced');
    assert.equal(revision.parent_revision_uid, baselineUid,
      'parent_revision_uid does not point at the user-selected OLD version');
    assert.equal(obs.fresh_AB_in_revise_run, 0, 'revise regenerated A/B instead of continuing');
    assert.equal(lastRun.task_kind, 'revise');
    assert.equal(lastRun.status, 'succeeded');

    // page must show the parent version for an old-vs-new comparison
    const bodyText = await page.locator('.studio').innerText();
    obs.page_shows_parent_uid = bodyText.includes(baselineUid);
    obs.page_shows_revise_note = /旧基线续改|旧方案续改|续改旧基线/.test(bodyText);
    assert(obs.page_shows_parent_uid || obs.page_shows_revise_note,
      'page has no old-vs-new comparison');
    // wait for the 2.5s poll to refresh the single waiting gate title
    await page.getByText('旧方案续改完成', { exact: false }).first()
      .waitFor({ timeout: 12000 }).catch(() => {});
    obs.gate_title_after_revise = await page.locator('.gate-card strong').first()
      .innerText().catch(() => '');
    await page.screenshot({ path: path.join(evidence, 'w0-revision-desktop.png'), fullPage: true });

    // ---- 4. 390px narrow viewport: no horizontal overflow ------------------
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(600);
    obs.mobile_scroll_width = await page.evaluate(() => document.documentElement.scrollWidth);
    obs.mobile_inner_width = await page.evaluate(() => window.innerWidth);
    assert(obs.mobile_scroll_width <= 390,
      `mobile overflow: scrollWidth=${obs.mobile_scroll_width}`);
    await page.screenshot({ path: path.join(evidence, 'w0-mobile.png'), fullPage: true });

    obs.page_errors = errors;
    assert.equal(errors.length, 0, 'browser JS errors: ' + errors.join(' | '));
    obs.passed = true;
    fs.writeFileSync(path.join(evidence, 'browser-observations.json'),
      JSON.stringify(obs, null, 2));
    console.log(JSON.stringify({ passed: true, key: obs.last_run,
      parent_matches: true, mobile_scroll_width: obs.mobile_scroll_width }, null, 2));
    await browser.close();
    process.exit(0);
  } catch (e) {
    obs.passed = false;
    obs.failure = String(e && e.message || e);
    obs.page_errors = errors;
    fs.writeFileSync(path.join(evidence, 'browser-observations.json'),
      JSON.stringify(obs, null, 2));
    console.error(String(e && e.stack || e));
    await browser.close();
    process.exit(1);
  }
})();
