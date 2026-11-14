/* W0 文字反馈保守判定 · 真实浏览器验收（headless Edge，真实点击/输入）。

   只做一件事：用老板的**正常文字入口**发一条普通留言
   「把 F3 旋转到 -30 度，其他家具不动」，点「开一轮」，确认：
   - 页面把它当作旧基线续改（revise），不是重新生成 A/B；
   - 新修订只改 F3，父版本等于用户选中的旧版；
   - 无逗号尾部诉求仍以 unknown+pending 可见；无红色告警/JS 错误；390px 不溢出。
   验收脚本不注入 objectives/locks，结构化目标由服务端从文字解析。
   0 外部调用、0 密钥、0 费用。由 verify_text_browser.py 驱动。
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
const aId = process.env.RKD_QA_BASELINE_ID;
const aUid = process.env.RKD_QA_BASELINE_UID;
assert(url && studioUrl && evidence && projectId && aId && aUid,
  'isolated browser config required');

const TEXT = '把 F3 旋转到 -30 度并让整体更有设计感';

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
  page.on('dialog', async d => { await d.accept('按这条改，其他不动'); });

  const obs = { text: TEXT, baseline_a: aId, baseline_uid: aUid };
  try {
    await page.goto(`${url}/?view=studio`, { waitUntil: 'domcontentloaded' });
    await page.locator('.project-item').first().waitFor({ timeout: 25000 });
    await page.locator('.project-item').filter({ hasText: /宁波协诚/ }).first().click();
    await page.locator('.studio-meta').waitFor({ timeout: 20000 });

    const before = await getState(page);
    obs.before_runs = before.runs.length;

    // ---- 正常文字入口：选旧方案 + 只输入文字 -----------------------------
    await page.locator('[data-testid="baseline-select"]').selectOption(aId);
    await page.locator('.studio-input input').fill(TEXT);
    await page.getByRole('button', { name: '发给公司' }).click();
    await page.getByText(TEXT, { exact: false }).first().waitFor({ timeout: 15000 });

    const posted = await getState(page);
    obs.task_resolution = {
      kind: posted.task_resolution.kind,
      target_artifact_id: posted.task_resolution.target_artifact_id,
    };
    assert.equal(posted.task_resolution.kind, 'revise',
      'a normal text message on a selected baseline must be a revise, not a new generate');
    assert.equal(posted.task_resolution.target_artifact_id, aId);

    // ---- 开一轮 -----------------------------------------------------------
    await page.getByRole('button', { name: /开一轮/ }).click();
    let after = null;
    for (let i = 0; i < 200; i++) {
      after = await getState(page);
      if (after.runs.length > before.runs.length &&
          after.runs[after.runs.length - 1].status !== 'running') break;
      await page.waitForTimeout(500);
    }
    assert(after && after.runs.length > before.runs.length, 'no new run finished');
    const lastRun = after.runs[after.runs.length - 1];
    obs.last_run = { id: lastRun.id, status: lastRun.status,
      task_kind: lastRun.task_kind };
    assert.equal(lastRun.task_kind, 'revise');
    assert.equal(lastRun.status, 'succeeded');

    const rev = (after.artifacts || []).find(
      a => a.kind === 'spatial-plan' && a.run_id === lastRun.id && a.revision >= 2);
    assert(rev, 'no continued revision produced');
    obs.new_revision = { id: rev.id, revision: rev.revision,
      parent_revision_uid: rev.parent_revision_uid };
    assert.equal(rev.parent_revision_uid, aUid);

    // 结构化目标来自服务端的文字解析，只认 F3
    const integ = (rev.diagnostics || {}).integrity || {};
    const rows = integ.objective_rechecks || [];
    const meas = rows.filter(r => r.kind === 'measurable');
    const pres = rows.filter(r => r.kind === 'preserve');
    obs.objective_rechecks = rows.map(r => ({
      kind: r.kind, rule_id: r.rule_id, target: r.target,
      target_objects: r.target_objects, state: r.objective_rechecked,
      user_confirmed: r.user_confirmed,
    }));
    obs.object_diff = (rev.diagnostics || {}).object_diff;
    assert.equal(meas.length, 1, 'expected exactly one measurable objective');
    assert.deepEqual(meas[0].target_objects, ['F3'],
      'the named object F3 must be the only target, not the whole furniture group');
    assert.equal(meas[0].objective_rechecked, 'pass');
    assert.deepEqual(obs.object_diff, ['furniture:F3']);
    const pend = rows.filter(r => r.kind === 'aesthetic' || r.kind === 'unparsed');
    obs.pending_rechecks = pend.map(r => ({
      kind: r.kind, reason: r.unparsed_reason, residual: r.residual_text,
      state: r.objective_rechecked, user_confirmed: r.user_confirmed,
    }));
    assert(pend.length >= 1 &&
      pend.some(r => r.unparsed_reason === 'unparsed_remainder_in_clause' &&
        String(r.residual_text || '').includes('设计感')) &&
      pend.every(r => r.objective_rechecked === 'unknown' &&
        r.user_confirmed === 'pending'),
      'the unparsed tail of a comma-free compound sentence must stay pending');

    // ---- 页面状态 ---------------------------------------------------------
    await page.waitForTimeout(3000);
    obs.status_texts = await page.locator('[role="status"]').allInnerTexts();
    obs.alert_count = await page.locator('.studio-error[role="alert"]').count();
    assert.equal(obs.alert_count, 0, 'a successful text-driven revision is painted as an alert');
    const pageText = (await page.locator('body').innerText()).replace(/\s+/g, ' ');
    obs.page_has_pending_note = /未验证|等用户确认/.test(pageText);
    obs.page_pending_excerpt = (pageText.match(/.{0,60}未验证.{0,80}/) || [''])[0];
    assert(obs.page_has_pending_note,
      'the page does not surface the unparsed/pending requirement');
    const taskbar = (await page.locator('.studio-taskbar').innerText()).replace(/\s+/g, ' ');
    obs.taskbar = taskbar.slice(0, 400);
    assert(/旧基线|revise|续改|第 \d+ 版|v\d/i.test(taskbar),
      'taskbar does not show the continued-revision task');
    await page.screenshot({ path: path.join(evidence, 'conservative-desktop.png'),
      fullPage: true });

    // ---- 390px ------------------------------------------------------------
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(700);
    obs.mobile_scroll_width = await page.evaluate(() => document.documentElement.scrollWidth);
    obs.mobile_inner_width = await page.evaluate(() => window.innerWidth);
    assert(obs.mobile_scroll_width <= 390,
      `mobile overflow: scrollWidth=${obs.mobile_scroll_width}`);
    await page.screenshot({ path: path.join(evidence, 'conservative-mobile.png'),
      fullPage: true });

    obs.page_errors = errors;
    assert.equal(errors.length, 0, 'browser JS errors: ' + errors.join(' | '));
    obs.passed = true;
    fs.writeFileSync(path.join(evidence, 'browser-observations.json'),
      JSON.stringify(obs, null, 2));
    console.log(JSON.stringify({ passed: true, run: obs.last_run,
      targets: meas[0].target_objects, diff: obs.object_diff }, null, 2));
    await browser.close();
    process.exit(0);
  } catch (e) {
    obs.passed = false;
    obs.failure = String((e && e.message) || e);
    obs.page_errors = errors;
    fs.writeFileSync(path.join(evidence, 'browser-observations.json'),
      JSON.stringify(obs, null, 2));
    console.error(String((e && e.stack) || e));
    await browser.close();
    process.exit(1);
  }
})();
