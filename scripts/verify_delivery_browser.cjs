/* Real browser acceptance for the "资料与技术交付" workspace tab.
   Started by scripts/verify_delivery_browser.py with an isolated local server. */
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const { chromium } = require(path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));

const url = process.env.RKD_QA_URL;
const evidence = process.env.RKD_QA_EVIDENCE_DIR;
const projectId = process.env.RKD_QA_PROJECT_ID;
assert(url && evidence && projectId, 'isolated browser test configuration required');

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  const observations = {};
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded' });
    await page.locator('.project-item').first().click();
    await page.locator('.view-tabs button').filter({ hasText: '需求草稿' }).click();
    await page.locator('.design-modes button').filter({ hasText: '资料与技术交付' }).click();
    await page.getByRole('heading', { name: '原件内容与技术交付草稿' }).waitFor();

    const row = page.locator('.ai-source-delivery-panel li').filter({ hasText: '浏览器验收说明.txt' }).first();
    await row.waitFor();
    await row.getByRole('button', { name: '解析原件' }).click();
    await row.getByText('已解析文本', { exact: false }).waitFor({ timeout: 15000 });
    await row.getByRole('button', { name: '查看来源片段' }).click();
    const segments = await row.locator('.ai-source-segments li').count();
    assert(segments >= 1, 'source locator segments must be visible');
    observations.source_segments_visible = segments;
    observations.source_locator = await row.locator('.ai-source-segments code').first().textContent();

    await page.getByRole('button', { name: '从当前深化包生成技术交付草稿' }).click();
    await page.getByText('真实成果文件（7）', { exact: false }).waitFor({ timeout: 20000 });
    await page.getByText('非施工图', { exact: false }).first().waitFor();
    await page.getByText('专业复核：待办', { exact: false }).waitFor();
    await page.getByText('施工发布：关闭', { exact: false }).waitFor();
    observations.boundary_labels_visible = true;

    const api = `${url}/api/v1/projects/${projectId}`;
    const state = await (await page.request.get(`${api}/ai/technical-delivery`)).json();
    assert.equal(state.item.status, 'draft');
    assert.equal(state.item.artifacts.length, 7);
    assert.equal(state.professional_review, 'pending');
    assert.equal(state.construction_issue, false);
    assert.equal(state.formal_quote, false);
    assert.equal(state.publication_status, 'not_approved');
    observations.artifact_kinds = state.item.artifacts.map(item => item.artifact_kind).sort();
    observations.input_hash = state.item.delivery.input_hash;

    const extractionState = await (await page.request.get(`${api}/ai/source-extractions`)).json();
    const extracted = extractionState.items.find(item => item.filename === '浏览器验收说明.txt');
    assert(extracted && extracted.status === 'extracted', 'real source extraction must be persisted');
    assert.equal(extractionState.external_content_allowed, false);
    observations.extraction_status = extracted.status;
    observations.extraction_segments = extracted.segment_count;

    // Real download through the UI: click the ZIP artifact and verify bytes.
    const zipArtifact = state.item.artifacts.find(item => item.artifact_kind === 'delivery_zip');
    assert(zipArtifact, 'ZIP artifact missing');
    const downloadButton = page.locator('.ai-development-artifacts button').filter({ hasText: '技术交付包 ZIP' }).first();
    const [download] = await Promise.all([
      page.waitForEvent('download', { timeout: 20000 }),
      downloadButton.click(),
    ]);
    const zipPath = path.join(evidence, 'technical-delivery.zip');
    await download.saveAs(zipPath);
    const size = fs.statSync(zipPath).size;
    assert.equal(size, zipArtifact.size_bytes, 'downloaded ZIP byte count must match the registry');
    observations.download = { filename: download.suggestedFilename(), bytes: size, matches_registry: true };

    await page.screenshot({ path: path.join(evidence, 'delivery-desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    const sizes = await page.evaluate(() => ({ width: innerWidth, document: document.documentElement.scrollWidth }));
    assert(sizes.document <= sizes.width + 1, `horizontal overflow: ${JSON.stringify(sizes)}`);
    await page.screenshot({ path: path.join(evidence, 'delivery-mobile.png'), fullPage: true });
    observations.mobile = sizes;
    assert.deepEqual(errors, [], 'browser console errors');

    fs.writeFileSync(path.join(evidence, 'delivery-browser.json'), JSON.stringify({
      passed: true, url, project_id: projectId, observations, errors,
    }, null, 2));
    console.log(JSON.stringify({ passed: true, observations }, null, 2));
  } finally {
    await browser.close();
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
