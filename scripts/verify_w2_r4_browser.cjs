/* W2-R4 真实浏览器验收：页面只读展示已登记成果 + 两份平面 SVG 渲染预览。
   0 外部调用。由 verify_w2_r4_browser.py 驱动。 */
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
const crypto = require('node:crypto');
const { chromium } = require(path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));

const url = process.env.RKD_QA_URL;
const evidence = process.env.RKD_QA_EVIDENCE_DIR;
const projectId = process.env.RKD_QA_PROJECT_ID;
const outputsDir = process.env.RKD_QA_OUTPUTS_DIR;
assert(url && evidence && projectId && outputsDir, 'isolated W2-R4 browser config required');

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
  page.on('dialog', async d => { await d.accept('W2-R4'); });
  const obs = {};
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded' });
    await page.locator('.project-item').first().waitFor({ timeout: 25000 });
    await page.locator('.project-item').first().click();
    await page.locator('.view-tabs button').filter({ hasText: '需求草稿' }).click();
    await page.locator('.design-modes button').filter({ hasText: '同源成果' }).click();

    await page.locator('[data-testid="spatial-plan"]').waitFor({ timeout: 90000 });
    await page.locator('[data-testid="spatial-render"]').waitFor({ timeout: 90000 });
    const status = await (await page.request.get(
      `${url}/api/v1/projects/${projectId}/ai/spatial-outputs`)).json();
    obs.job_status = status.job?.status;
    obs.production_revision_id = status.revision?.production_revision_id;
    obs.artifact_names = (status.artifacts || []).map(a => a.filename);
    obs.baseline_generator = status.revision?.baseline?.generator_version;
    obs.baseline_presentation_assumption = status.revision?.baseline?.presentation_assumption;
    obs.package_missing_head = (status.revision?.package?.missing || []).slice(0, 3);
    assert(status.artifacts.some(a => a.filename === 'plan.svg'));
    assert(status.artifacts.some(a => a.filename === 'package.zip'));
    assert(obs.baseline_presentation_assumption === true,
      'page is not showing the R4 presentation-fixture output');

    const planSrc = await page.locator('[data-testid="spatial-plan"]').getAttribute('src');
    const renderSrc = await page.locator('[data-testid="spatial-render"]').getAttribute('src');
    obs.plan_is_blob = Boolean(planSrc && planSrc.startsWith('blob:'));
    obs.render_is_blob = Boolean(renderSrc && renderSrc.startsWith('blob:'));
    assert(obs.plan_is_blob && obs.render_is_blob);

    const qRows = await page.locator('[data-testid="spatial-quantities"] tbody tr').count();
    obs.quantity_rows = qRows;
    const panelText = await page.locator('.ai-spatial-panel').innerText();
    obs.panel_has_missing = /缺项/.test(panelText);
    obs.panel_has_unknown = /unknown/.test(panelText);
    obs.panel_has_trial = /试算|假设单价/.test(panelText);
    obs.panel_has_boundary = /不是报价|内部评审|非现场事实|人工/.test(panelText);
    assert(qRows >= 5, 'quantity table not visible');
    assert(obs.panel_has_missing && obs.panel_has_trial && obs.panel_has_boundary,
      'missing items / trial basis / boundary not visible');

    const base = `${url}/api/v1/projects/${projectId}/ai/spatial-outputs/${obs.production_revision_id}/files`;
    const downloads = {};
    for (const name of ['plan.svg', 'render.png', 'package.zip']) {
      const r = await page.request.get(`${base}/${name}`);
      const buf = await r.body();
      downloads[name] = { status: r.status(), bytes: buf.length,
        sha256: crypto.createHash('sha256').update(buf).digest('hex') };
      assert.equal(r.status(), 200, `${name} download failed`);
      assert(buf.length > 1000, `${name} too small`);
    }
    obs.downloads = downloads;
    const manifest = await (await page.request.get(`${base}/manifest.json`)).json();
    const registered = Object.fromEntries(manifest.files.map(f => [f.filename, f.sha256]));
    obs.manifest_sha_match = ['plan.svg', 'render.png'].every(
      n => registered[n] && registered[n] === downloads[n].sha256);
    obs.zip_sha_match = (status.artifacts.find(a => a.filename === 'package.zip') || {}).sha256
      === downloads['package.zip'].sha256;
    assert(obs.manifest_sha_match && obs.zip_sha_match, 'download bytes do not match registered sha256');

    await page.screenshot({ path: path.join(evidence, 'r4-outputs-desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(800);
    obs.mobile_scroll_width = await page.evaluate(() => document.documentElement.scrollWidth);
    obs.mobile_overflow_elements = await page.evaluate(() => {
      const out = [];
      for (const el of document.querySelectorAll('*')) {
        const r = el.getBoundingClientRect();
        if (r.right > 391 && r.width > 0) {
          out.push({ tag: el.tagName, cls: String(el.className || '').slice(0, 60),
            text: String(el.textContent || '').trim().slice(0, 70),
            right: Math.round(r.right), width: Math.round(r.width) });
        }
      }
      return out.slice(0, 25);
    });
    assert(obs.mobile_scroll_width <= 390, `mobile overflow: ${obs.mobile_scroll_width}`);
    await page.screenshot({ path: path.join(evidence, 'r4-outputs-mobile.png'), fullPage: true });

    // 把两布局的平面 SVG 各渲染成 PNG，供人工目检文字/尺寸/重叠
    const svgPage = await browser.newPage({ viewport: { width: 1400, height: 1100 } });
    obs.plan_previews = [];
    for (const letter of ['A', 'B']) {
      const svgPath = path.join(outputsDir, `layout-${letter}`, 'plan.svg');
      if (!fs.existsSync(svgPath)) continue;
      await svgPage.goto(pathToFileURL(svgPath).href, { waitUntil: 'load' });
      await svgPage.waitForTimeout(500);
      const out = path.join(evidence, `plan-preview-${letter}.png`);
      // SVG 作为独立文档打开时 fullPage 会因 viewBox 计算超时；视口已大于图幅
      await svgPage.screenshot({ path: out, timeout: 60000 });
      obs.plan_previews.push({ layout: letter, file: path.basename(out),
        bytes: fs.statSync(out).size });
    }
    await svgPage.close();
    assert(obs.plan_previews.length === 2, 'both plan previews are required');

    obs.page_errors = errors;
    assert.equal(errors.length, 0, 'browser JS errors: ' + errors.join(' | '));
    obs.passed = true;
    fs.writeFileSync(path.join(evidence, 'browser-observations.json'), JSON.stringify(obs, null, 2));
    console.log(JSON.stringify({ passed: true, quantities: qRows,
      downloads: Object.keys(downloads), previews: obs.plan_previews.length }, null, 2));
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
