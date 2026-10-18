const assert = require('node:assert/strict');
const path = require('node:path');
const os = require('node:os');
const fs = require('node:fs');
const crypto = require('node:crypto');
const { chromium } = require(process.env.RKD_PLAYWRIGHT_MODULE || path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));

const url = process.env.RKD_QA_URL || 'http://127.0.0.1:8080';
const headers = { 'X-Organization-Id': 'org-local' };

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  try {
    await page.goto(url);
    const projects = await (await page.request.get(`${url}/api/v1/projects`, { headers })).json();
    let selected;
    for (const project of projects.items) {
      const design = await (await page.request.get(`${url}/api/v1/projects/${project.project_id}/design`, { headers })).json();
      const spatial = await (await page.request.get(`${url}/api/v1/projects/${project.project_id}/spatial`, { headers })).json();
      if (spatial.items?.[0]) { selected = { project, design: design.item, spatial: spatial.items[0] }; break; }
    }
    assert(selected, 'no project with an M2 baseline');
    await page.locator('.project-item').filter({ hasText: selected.project.name }).click();
    await page.getByRole('button', { name: /采购施工/ }).click();
    await page.getByLabel('变更标题', { exact: true }).fill('浏览器现场材料变更');
    await page.getByLabel('原因', { exact: true }).fill('现场材料不可供');
    await page.getByLabel('变更说明', { exact: true }).fill('替换为同等规格材料并记录影响');
    await page.getByLabel('工程量变化（m²）', { exact: true }).fill('1.5');
    await page.getByLabel('未税成本变化', { exact: true }).fill('800');
    await page.getByLabel('工期变化（天）', { exact: true }).fill('1');
    await page.getByRole('button', { name: '保存变更请求', exact: true }).click();
    await page.getByText('变更请求已保存', { exact: true }).waitFor();
    await page.getByRole('button', { name: '生成影响分析', exact: true }).click();
    await page.getByText('影响分析已生成，新成果为待人工确认草稿', { exact: true }).waitFor();
    await page.getByText('影响成果', { exact: false }).first().waitFor();
    await page.getByLabel('验收证据', { exact: true }).fill('browser-change-acceptance-01');
    await page.getByRole('button', { name: '记录验收通过', exact: true }).click();
    await page.getByText('变更验收已记录', { exact: true }).waitFor();
    await page.getByText('accepted', { exact: true }).first().waitFor();
    const changes = await (await page.request.get(`${url}/api/v1/projects/${selected.project.project_id}/changes`, { headers })).json();
    const current = changes.items[0];
    assert.equal(current.status, 'accepted');
    const downloads = [];
    for (const artifact of current.artifacts) {
      const waiting = page.waitForEvent('download');
      await page.getByRole('button', { name: new RegExp(artifact.filename.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) }).first().click();
      const download = await waiting;
      const file = await download.path();
      const bytes = fs.readFileSync(file);
      assert.equal(bytes.length, artifact.size_bytes);
      assert.equal(crypto.createHash('sha256').update(bytes).digest('hex'), artifact.sha256);
      downloads.push({ filename: artifact.filename, size_bytes: bytes.length, sha256: artifact.sha256 });
    }
    const overflow = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth }));
    assert(overflow.document <= overflow.viewport + 1, JSON.stringify(overflow));
    assert.deepEqual(errors, []);
    await page.screenshot({ path: path.join(process.env.RKD_QA_EVIDENCE_DIR || 'var/evidence', 'm4-change-browser.png'), fullPage: true });
    fs.writeFileSync(path.join(process.env.RKD_QA_EVIDENCE_DIR || 'var/evidence', 'm4-change-verification.json'), JSON.stringify({ change_id: current.change_id, downloads, overflow, errors }, null, 2));
    console.log(JSON.stringify({ passed: true, project_id: selected.project.project_id, design_revision_id: selected.design?.design_revision_id ?? null, geometry_revision_id: selected.spatial.geometry_revision_id, overflow, errors }));
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
