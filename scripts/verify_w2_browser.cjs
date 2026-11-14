/* W2 真实浏览器验收：页面选中精确模型修订→生成→看平面/人眼图/净量/下载。
   0 外部调用。由 verify_w2_browser.py 驱动。 */
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const { chromium } = require(path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));

const url = process.env.RKD_QA_URL;
const evidence = process.env.RKD_QA_EVIDENCE_DIR;
const projectId = process.env.RKD_QA_PROJECT_ID;
const revisionId = process.env.RKD_QA_OPTION_REVISION_ID;
assert(url && evidence && projectId && revisionId, 'isolated W2 browser config required');

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
  page.on('dialog', async d => { await d.accept('W2'); });
  const obs = { revisionId };
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded' });
    await page.locator('.project-item').first().waitFor({ timeout: 25000 });
    await page.locator('.project-item').first().click();
    await page.locator('.view-tabs button').filter({ hasText: '需求草稿' }).click();
    await page.locator('.design-modes button').filter({ hasText: '同源成果' }).click();
    await page.locator('[data-testid="spatial-revision-select"]').waitFor({ timeout: 20000 });

    await page.waitForTimeout(1500);
    const options = await page.locator('[data-testid="spatial-revision-select"] option').allTextContents();
    obs.revision_options = options;
    obs.panel_errors = await page.locator('.ai-spatial-panel .design-feedback.error').allInnerTexts().catch(() => []);
    obs.panel_text_head = (await page.locator('.ai-spatial-panel').innerText()).replace(/\s+/g, ' ').slice(0, 300);
    assert(options.some(t => t.includes('v1')), 'spatial revision is not selectable: ' + JSON.stringify(obs));

    await page.locator('[data-testid="spatial-revision-select"]').selectOption(revisionId);
    await page.locator('[data-testid="spatial-generate"]').click();

    // wait for the job to finish (render included) and outputs to appear
    await page.locator('[data-testid="spatial-plan"]').waitFor({ timeout: 300000 });
    await page.locator('[data-testid="spatial-render"]').waitFor({ timeout: 300000 });
    const status = await (await page.request.get(
      `${url}/api/v1/projects/${projectId}/ai/spatial-outputs`)).json();
    obs.job_status = status.job?.status;
    obs.job_phase = status.job?.phase;
    obs.production_revision_id = status.revision?.production_revision_id;
    obs.baseline = status.revision?.baseline;
    obs.artifact_names = (status.artifacts || []).map(a => a.filename);
    assert.equal(status.job?.status, 'succeeded');
    assert(status.artifacts.some(a => a.filename === 'plan.svg'));
    assert(status.artifacts.some(a => a.filename === 'package.zip'));

    const planSrc = await page.locator('[data-testid="spatial-plan"]').getAttribute('src');
    const renderSrc = await page.locator('[data-testid="spatial-render"]').getAttribute('src');
    obs.plan_is_blob = Boolean(planSrc && planSrc.startsWith('blob:'));
    obs.render_is_blob = Boolean(renderSrc && renderSrc.startsWith('blob:'));

    const qRows = await page.locator('[data-testid="spatial-quantities"] tbody tr').count();
    obs.quantity_rows = qRows;
    const panelText = (await page.locator('.ai-spatial-panel').innerText()).replace(/\s+/g, ' ');
    obs.panel_has_missing = /缺项/.test(panelText);
    obs.panel_has_unknown = /unknown/.test(panelText);
    obs.panel_has_boundary = /不是报价|内部评审/.test(panelText);
    assert(qRows >= 5, 'quantity table is not visible');
    assert(obs.panel_has_missing && obs.panel_has_unknown, 'missing items / unknown not visible');

    // downloads: plan + render + zip bytes match registered SHA
    const base = `${url}/api/v1/projects/${projectId}/ai/spatial-outputs/${obs.production_revision_id}/files`;
    const downloads = {};
    for (const name of ['plan.svg', 'render.png', 'package.zip']) {
      const r = await page.request.get(`${base}/${name}`);
      const buf = await r.body();
      downloads[name] = { status: r.status(), bytes: buf.length,
        sha256: require('node:crypto').createHash('sha256').update(buf).digest('hex') };
      assert.equal(r.status(), 200, `${name} download failed`);
      assert(buf.length > 1000, `${name} too small`);
    }
    obs.downloads = downloads;
    const manifest = await (await page.request.get(`${base}/manifest.json`)).json();
    const registered = Object.fromEntries(manifest.files.map(f => [f.filename, f.sha256]));
    const artifactSha = Object.fromEntries((status.artifacts || []).map(a => [a.filename, a.sha256]));
    obs.manifest_sha_match = ['plan.svg', 'render.png'].every(n => registered[n] && registered[n] === downloads[n].sha256);
    obs.artifact_sha_match = artifactSha['package.zip'] === downloads['package.zip'].sha256;
    assert(obs.manifest_sha_match && obs.artifact_sha_match,
      'download bytes do not match registered sha256');

    await page.screenshot({ path: path.join(evidence, 'w2-outputs-desktop.png'), fullPage: true });

    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(800);
    obs.mobile_scroll_width = await page.evaluate(() => document.documentElement.scrollWidth);
    assert(obs.mobile_scroll_width <= 390, `mobile overflow: ${obs.mobile_scroll_width}`);
    await page.screenshot({ path: path.join(evidence, 'w2-outputs-mobile.png'), fullPage: true });

    obs.page_errors = errors;
    assert.equal(errors.length, 0, 'browser JS errors: ' + errors.join(' | '));
    obs.passed = true;
    fs.writeFileSync(path.join(evidence, 'browser-observations.json'), JSON.stringify(obs, null, 2));
    console.log(JSON.stringify({ passed: true, job: obs.job_status,
      quantities: qRows, downloads: Object.keys(downloads) }, null, 2));
    await browser.close();
    process.exit(0);
  } catch (e) {
    obs.passed = false;
    obs.failure = String((e && e.message) || e);
    obs.page_errors = errors;
    fs.writeFileSync(path.join(evidence, 'browser-observations.json'), JSON.stringify(obs, null, 2));
    console.error(String((e && e.stack) || e));
    await browser.close();
    process.exit(1);
  }
})();
