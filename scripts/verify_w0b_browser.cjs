/* W0 二次收口真实浏览器验收（真实点击/输入，headless Edge）。

   覆盖：连续两条同基线留言 → 合并为一轮；已消费后的提示不是失败告警；
   跨候选待办 → 明确告警 + 待办清单 + 显式作废；累计返工可见；390px 不溢出。
   无外部模型/图片调用、无密钥、费用 0。由 verify_w0b_browser.py 驱动。
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
const bId = process.env.RKD_QA_BASELINE_B_ID;
assert(url && studioUrl && evidence && projectId && aId && aUid && bId,
  'isolated browser config required');

const getState = async (page) => {
  const r = await page.request.get(
    `${studioUrl}/studio/projects/${encodeURIComponent(projectId)}/state`);
  assert.equal(r.status(), 200, 'studio state not readable');
  return r.json();
};

const taskbar = async (page) =>
  (await page.locator('.studio-taskbar').innerText()).replace(/\s+/g, ' ');

const sendMessage = async (page, text, baselineId) => {
  await page.locator('[data-testid="baseline-select"]').selectOption(baselineId || '');
  await page.locator('.studio-input input').fill(text);
  await page.getByRole('button', { name: '发给公司' }).click();
  await page.locator('.studio-pending, .studio-note, .studio-error').first()
    .waitFor({ timeout: 15000 }).catch(() => {});
  // the versioned feedback list must contain the new message
  await page.getByText(text, { exact: false }).first().waitFor({ timeout: 15000 });
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
  page.on('dialog', async d => { await d.accept('先处理 A 这条，B 的留到下一轮'); });

  const obs = { baseline_a: aId, baseline_b: bId };
  try {
    await page.goto(`${url}/?view=studio`, { waitUntil: 'domcontentloaded' });
    await page.locator('.project-item').first().waitFor({ timeout: 25000 });
    await page.locator('.project-item').filter({ hasText: /宁波协诚/ }).first().click();
    await page.locator('.studio-meta').waitFor({ timeout: 20000 });

    const before = await getState(page);
    obs.before_runs = before.runs.length;
    obs.trial_progress_initial = before.trial_progress;
    obs.snapshot = before.snapshot;

    // ---- 1. 累计返工可见（不是每轮归零） ---------------------------------
    let bar = await taskbar(page);
    obs.taskbar_initial = bar.slice(0, 500);
    assert(/设计试验累计：第 \d+ 轮/.test(bar), 'taskbar does not show cumulative trial rounds');
    assert(/自动返工 \d+\/\d+/.test(bar), 'taskbar does not show cumulative auto-rework');

    // ---- 2. 连续两条同基线留言 → 页面显示「合并 2 条」 -------------------
    await sendMessage(page, '把 F3 转到 -15 度，保留入口', aId);
    await sendMessage(page, '中岛圆角再收一点，保留入口', aId);
    const afterMsgs = await getState(page);
    obs.task_resolution_before_run = afterMsgs.task_resolution;
    obs.pending_queue = afterMsgs.pending_queue;
    bar = await taskbar(page);
    obs.taskbar_merged = bar.slice(0, 500);
    assert(/合并 2 条同基线留言/.test(bar),
      'page does not show that the two same-baseline messages are merged');

    // ---- 3. 跑一轮；旧的都已消费，提示只能是 note 不是告警 --------------
    await page.getByRole('button', { name: /开一轮/ }).click();
    let after = null;
    for (let i = 0; i < 160; i++) {
      after = await getState(page);
      if (after.runs.length > before.runs.length &&
          after.runs[after.runs.length - 1].status !== 'running') break;
      await page.waitForTimeout(500);
    }
    assert(after && after.runs.length > before.runs.length, 'no new run finished');
    const lastRun = after.runs[after.runs.length - 1];
    obs.last_run = {
      id: lastRun.id, status: lastRun.status, task_kind: lastRun.task_kind,
      target_artifact_id: lastRun.target_artifact_id,
      auto_rework_total: lastRun.auto_rework_total,
      trial_key: lastRun.trial_key,
    };
    assert.equal(lastRun.task_kind, 'revise');
    assert.equal(lastRun.status, 'succeeded');
    const revs = (after.artifacts || []).filter(
      a => a.kind === 'spatial-plan' && a.run_id === lastRun.id && a.revision >= 2);
    assert(revs.length >= 1, 'no continued revision produced');
    obs.new_revision_parent_uid = revs[0].parent_revision_uid;
    assert.equal(revs[0].parent_revision_uid, aUid);

    // 两个已消费的留言都指向同一 run
    const consumed = (after.feedback || []).filter(
      f => f.consumed_by_run === lastRun.id).map(f => f.revision_no);
    obs.consumed_feedback_revisions = consumed;
    assert(consumed.length >= 2, 'the two merged messages were not consumed together');

    await page.waitForTimeout(3000);   // 2.5s poll
    obs.status_texts = await page.locator('[role="status"]').allInnerTexts();
    obs.note_after_run = obs.status_texts.join(' | ');
    obs.alert_count_after_run = await page.locator('.studio-error[role="alert"]').count();
    assert(obs.status_texts.some(t => /已经执行过/.test(t)),
      'page does not explain that the latest message was already executed');
    assert.equal(obs.alert_count_after_run, 0,
      'a successfully executed round is painted as a red alert');
    await page.screenshot({ path: path.join(evidence, 'w0b-merged-desktop.png'),
      fullPage: true });

    // ---- 4. 跨候选待办：告警 + 清单 + 显式作废 ---------------------------
    await sendMessage(page, 'B 的入口动线再顺一下', bId);
    await sendMessage(page, 'A 的东洽谈区尺度再调一下', aId);
    await page.waitForTimeout(3000);
    const conflict = await getState(page);
    obs.task_resolution_conflict = conflict.task_resolution;
    assert.equal(conflict.task_resolution.kind, 'conflict');
    assert.equal(conflict.task_resolution.conflict_code, 'multiple_pending_feedback');
    const alertText = await page.locator('.studio-error[role="alert"]').first()
      .innerText();
    obs.alert_text = alertText.replace(/\s+/g, ' ').slice(0, 400);
    assert(/不能自动合并/.test(obs.alert_text), 'alert does not explain the conflict');
    const pendingItems = page.locator('.studio-pending li');
    obs.pending_count = await pendingItems.count();
    obs.pending_text = (await page.locator('.studio-pending').innerText())
      .replace(/\s+/g, ' ');
    assert.equal(obs.pending_count, 1, 'the older pending message is not listed');
    assert(/B 的入口动线再顺一下/.test(obs.pending_text),
      'pending list does not show the message that must be decided');
    await page.screenshot({ path: path.join(evidence, 'w0b-pending-desktop.png'),
      fullPage: true });

    await page.getByRole('button', { name: '作废这条' }).click();
    await page.waitForTimeout(3000);
    const afterWithdraw = await getState(page);
    obs.after_withdraw = {
      task_kind: afterWithdraw.task_resolution.kind,
      target_artifact_id: afterWithdraw.task_resolution.target_artifact_id,
      pending_count: (afterWithdraw.task_resolution.pending_feedback || []).length,
      current_feedback_status: (afterWithdraw.feedback || [])
        .map(f => ({ rev: f.revision_no, status: f.status })),
    };
    assert.equal(afterWithdraw.task_resolution.kind, 'revise');
    assert.equal(afterWithdraw.task_resolution.target_artifact_id, aId);
    assert.equal((afterWithdraw.task_resolution.pending_feedback || []).length, 0);
    const withdrawnStillListed = (afterWithdraw.feedback_history || []).some(
      f => f.text === 'B 的入口动线再顺一下' && f.status === 'superseded');
    obs.withdrawn_text_preserved = withdrawnStillListed;
    obs.withdrawn_row = (afterWithdraw.feedback_history || [])
      .filter(f => f.status === 'superseded')
      .map(f => ({ rev: f.revision_no, text: f.text, superseded_by: f.superseded_by }));
    const pageWithdrawnText = (await page.locator('.studio-withdrawn').innerText())
      .replace(/\s+/g, ' ');
    const pageHasWithdrawn = /已作废/.test(pageWithdrawnText)
      && /B 的入口动线再顺一下/.test(pageWithdrawnText);
    obs.page_shows_withdrawn = pageHasWithdrawn;
    obs.page_withdrawn_text = pageWithdrawnText.slice(0, 300);
    assert(withdrawnStillListed,
      'withdrawn message disappeared instead of being kept as superseded history');
    assert(pageHasWithdrawn, 'page does not show the withdrawn message / its reason');

    // ---- 5. 390px 窄屏不横向溢出 ----------------------------------------
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(700);
    obs.mobile_scroll_width = await page.evaluate(() => document.documentElement.scrollWidth);
    obs.mobile_inner_width = await page.evaluate(() => window.innerWidth);
    assert(obs.mobile_scroll_width <= 390,
      `mobile overflow: scrollWidth=${obs.mobile_scroll_width}`);
    await page.screenshot({ path: path.join(evidence, 'w0b-mobile.png'), fullPage: true });

    obs.page_errors = errors;
    assert.equal(errors.length, 0, 'browser JS errors: ' + errors.join(' | '));
    obs.passed = true;
    fs.writeFileSync(path.join(evidence, 'browser-observations.json'),
      JSON.stringify(obs, null, 2));
    console.log(JSON.stringify({ passed: true, run: obs.last_run,
      consumed: obs.consumed_feedback_revisions,
      pending_count: obs.pending_count,
      mobile_scroll_width: obs.mobile_scroll_width }, null, 2));
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
