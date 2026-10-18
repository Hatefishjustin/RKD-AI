const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { chromium } = require(process.env.RKD_PLAYWRIGHT_MODULE || path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));

const root = path.resolve(__dirname, '..');
const evidence = process.env.RKD_QA_EVIDENCE_DIR || path.join(root, 'var/evidence/m3');
const url = process.env.RKD_QA_URL || 'http://127.0.0.1:8080';
const headers = { 'X-Organization-Id': 'org-local' };
fs.mkdirSync(evidence, { recursive: true });

async function api(page, projectId) {
  const response = await page.request.get(`${url}/api/v1/projects/${projectId}/design`, { headers });
  assert.equal(response.status(), 200);
  return (await response.json()).item;
}
async function inspectViewport(page, name) {
  await page.locator('.design-workspace').scrollIntoViewIfNeeded();
  const widths = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth }));
  assert(widths.document <= widths.viewport + 1, `${name}: horizontal overflow ${JSON.stringify(widths)}`);
  const visible = await page.locator('.design-drawing svg').boundingBox();
  assert(visible.width > 200 && visible.height > 200, `${name}: missing geometry drawing`);
  await page.screenshot({ path: path.join(evidence, `${name}.png`), fullPage: true });
  await page.locator('.design-drawing').screenshot({ path: path.join(evidence, `${name}-drawing.png`) });
  return { ...widths, drawing: visible };
}

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  try {
    await page.goto(url);
    if (process.argv.includes('--restart')) {
      const previous = JSON.parse(fs.readFileSync(path.join(evidence, 'browser-verification.json'), 'utf8'));
      await page.getByRole('button', { name: new RegExp(previous.project_name) }).click();
      await page.locator('.view-tabs button').filter({ hasText: '需求' }).click();
      await page.getByRole('button', { name: '分区布局', exact: true }).click();
      const design = await api(page, previous.project_id);
      assert.equal(design.design_revision_id, previous.final_design.design_revision_id);
      assert.deepEqual(design.model, previous.final_design.model);
      assert.deepEqual(design.artifacts, previous.final_design.artifacts);
      await page.getByText('设计 v3 / 需求 v3', { exact: true }).waitFor();
      const desktop = await inspectViewport(page, 'desktop-confirm');
      await page.setViewportSize({ width: 390, height: 844 });
      const mobile = await inspectViewport(page, 'mobile-confirm');
      await page.screenshot({ path: path.join(evidence, 'restart.png'), fullPage: true });
      assert.deepEqual(errors, []);
      fs.writeFileSync(path.join(evidence, 'restart-verification.json'), JSON.stringify({ passed: true, design_revision_id: design.design_revision_id, revision_no: design.revision_no, artifacts: design.artifacts.length, desktop, mobile, errors }, null, 2));
      console.log('M3 browser reload after server process restart passed');
      return;
    }
    const projectName = `M3 浏览器验收展厅 ${Date.now()}`;
    await page.getByLabel('新建项目', { exact: true }).fill(projectName);
    await page.getByRole('button', { name: '创建项目', exact: true }).click();
    await page.getByRole('heading', { name: projectName, exact: true }).waitFor();
    const projects = await (await page.request.get(`${url}/api/v1/projects`, { headers })).json();
    const projectId = projects.items.find((p) => p.name === projectName).project_id;
    await page.locator('.view-tabs button').filter({ hasText: '需求' }).click();
    await page.getByLabel('设计备注', { exact: true }).fill('M3 自动化验收测试参数，非宁波现场尺寸。');
    await page.getByRole('button', { name: '保存需求草稿', exact: true }).click();
    await page.getByText('需求已保存为 v2', { exact: true }).waitFor();
    await page.getByRole('button', { name: '生成分区布局', exact: true }).click();
    await page.getByText('设计 v1 已保存，生成 7 份成果', { exact: true }).waitFor();
    const initial = await api(page, projectId);
    assert.equal(initial.model.zone_area_m2, '78.00');
    const desktop = await inspectViewport(page, 'desktop');
    await page.getByLabel('分区宽度（m）', { exact: true }).fill('2');
    await page.getByRole('button', { name: '检查并保存布局', exact: true }).click();
    await page.getByText('设计 v2 已保存，生成 7 份成果', { exact: true }).waitFor();
    const edited = await api(page, projectId);
    assert.equal(edited.model.zones[0].area_m2, '13.00');
    assert.equal(edited.model.unassigned_area_m2, '6.50');
    await page.getByLabel('X（m）', { exact: true }).fill('11');
    await page.getByRole('button', { name: '检查并保存布局', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: '超出外框' }).waitFor();
    assert.equal((await api(page, projectId)).revision_no, 2);
    await page.getByLabel('X（m）', { exact: true }).fill('0');
    await page.getByRole('button', { name: '需求', exact: true }).click();
    await page.getByLabel('外框宽度（m）', { exact: true }).fill('16');
    await page.getByRole('button', { name: '保存需求草稿', exact: true }).click();
    await page.getByText('需求已保存为 v3', { exact: true }).waitFor();
    assert.equal((await api(page, projectId)).status, 'source_outdated');
    await page.getByRole('button', { name: '生成分区布局', exact: true }).click();
    await page.getByText('设计 v3 已保存，生成 7 份成果', { exact: true }).waitFor();
    const final = await api(page, projectId);
    assert.equal(final.model.zone_area_m2, '104.00');
    assert.deepEqual(final.model.zones.map((z) => z.zone_id), initial.model.zones.map((z) => z.zone_id));
    await page.setViewportSize({ width: 390, height: 844 });
    const mobile = await inspectViewport(page, 'mobile');
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.getByRole('button', { name: '成果与历史', exact: true }).click();
    const downloads = [];
    for (const artifact of final.artifacts) {
      const pending = page.waitForEvent('download');
      await page.getByRole('button', { name: `下载 ${artifact.filename}`, exact: true }).click();
      const download = await pending;
      const target = path.join(evidence, artifact.filename);
      await download.saveAs(target);
      const bytes = fs.readFileSync(target);
      assert.equal(bytes.length, artifact.size_bytes);
      assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'), artifact.sha256);
      downloads.push({ filename: artifact.filename, sha256: artifact.sha256, size_bytes: bytes.length });
    }
    await page.getByLabel('查看设计修订', { exact: true }).selectOption('1');
    await page.getByText('旧版成果', { exact: true }).waitFor();
    const old = await (await page.request.get(`${url}/api/v1/projects/${projectId}/design/revisions/1`, { headers })).json();
    assert.equal(old.item.status, 'superseded');
    const oldZip = old.item.artifacts.find((a) => a.artifact_kind === 'package_zip');
    const oldPending = page.waitForEvent('download');
    await page.getByRole('button', { name: `下载 ${oldZip.filename}`, exact: true }).click();
    const oldDownload = await oldPending;
    await oldDownload.saveAs(path.join(evidence, oldZip.filename));
    assert.equal(crypto.createHash('sha256').update(fs.readFileSync(path.join(evidence, oldZip.filename))).digest('hex'), oldZip.sha256);
    await page.getByLabel('查看设计修订', { exact: true }).selectOption('3');
    await page.getByText('设计草稿 · 未批准', { exact: true }).waitFor();
    await page.screenshot({ path: path.join(evidence, 'outputs.png'), fullPage: true });
    const reportName = final.artifacts.find((a) => a.artifact_kind === 'report_html').filename;
    await page.goto(`file:///${path.join(evidence, reportName).replaceAll('\\', '/')}`);
    await page.locator('svg').waitFor();
    await page.screenshot({ path: path.join(evidence, 'report.png'), fullPage: true });
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(evidence, 'browser-verification.json'), JSON.stringify({ passed: true, project_id: projectId, project_name: projectName, desktop, mobile, initial_design: initial, edited_design: edited, final_design: final, downloads, historical_zip: oldZip, errors }, null, 2));
    console.log(JSON.stringify({ passed: true, project_id: projectId, revisions: 3, downloads: downloads.length + 1, desktop, mobile, errors }));
  } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exit(1); });
