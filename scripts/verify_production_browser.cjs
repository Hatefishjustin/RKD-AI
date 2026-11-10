const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const { chromium } = require(process.env.RKD_PLAYWRIGHT_MODULE || path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const url = process.env.RKD_QA_URL;
const evidence = process.env.RKD_QA_EVIDENCE_DIR;
if (!url || !evidence) throw new Error('isolated URL and evidence required');
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex');

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  async function api(route) {
    const response = await page.request.get(url + route);
    assert.equal(response.status(), 200);
    return response.json();
  }
  try {
    await page.goto(url);
    let projectName, projectId;
    if (process.argv.includes('--restart')) {
      const previous = JSON.parse(fs.readFileSync(path.join(evidence, 'browser.json'), 'utf8'));
      projectName = previous.project_name; projectId = previous.project_id;
      await page.getByRole('button', { name: new RegExp(projectName) }).click();
      await page.locator('.view-tabs button').filter({ hasText: '需求' }).click();
      await page.getByRole('button', { name: '分区布局', exact: true }).click();
      await page.getByRole('region', { name: '设计生产链' }).getByText('104.0000', { exact: false }).first().waitFor();
      const restored = (await api(`/api/v1/projects/${projectId}/production`)).item;
      assert.equal(restored.production_revision_id, previous.final.production_revision_id);
      assert.deepEqual(restored.quantities, previous.final.quantities);
      assert.deepEqual(restored.artifacts, previous.final.artifacts);
      assert.deepEqual(errors, []);
      fs.writeFileSync(path.join(evidence, 'browser-restart.json'), JSON.stringify({ passed: true, production_revision_id: restored.production_revision_id, errors }, null, 2));
      return;
    }
    projectName = `LINK 地坪整链测试 ${Date.now()}`;
    await page.getByLabel('新建项目', { exact: true }).fill(projectName);
    await page.getByRole('button', { name: '创建项目', exact: true }).click();
    await page.getByRole('heading', { name: projectName, exact: true }).waitFor();
    projectId = (await api('/api/v1/projects')).items.find(p => p.name === projectName).project_id;
    await page.locator('.view-tabs button').filter({ hasText: '需求' }).click();
    await page.getByLabel('设计备注', { exact: true }).fill('LINK 测试数据，非现场尺寸，非真实供应商采购');
    await page.getByRole('button', { name: '保存需求草稿', exact: true }).click();
    await page.getByText('需求已保存为 v2', { exact: true }).waitFor();
    await page.getByRole('button', { name: '生成分区布局', exact: true }).click();
    await page.getByText('设计 v1 已保存，生成 7 份成果', { exact: true }).waitFor();
    let panel = page.getByRole('region', { name: '设计生产链' });
    await panel.getByText('78.0000', { exact: false }).first().waitFor();
    let production = (await api(`/api/v1/projects/${projectId}/production`)).item;
    assert.equal(production.quote.sale_gross, null);
    await panel.locator('summary').click();
    await panel.getByLabel('未税单位成本（元/m²）', { exact: true }).fill('100');
    await panel.getByLabel('成本来源', { exact: true }).fill('浏览器测试成本，未专业核验');
    await panel.getByLabel('地坪材料规格', { exact: true }).fill('明确标记的测试地坪规格');
    await panel.getByLabel('地坪供应商', { exact: true }).fill('测试供应商（不下单）');
    await panel.getByLabel('地坪到货地点', { exact: true }).fill('测试现场');
    await panel.getByRole('button', { name: '保存参数并更新草稿' }).click();
    await panel.getByText('量价与采购草稿已更新为 v2', { exact: true }).waitFor();
    production = (await api(`/api/v1/projects/${projectId}/production`)).item;
    assert.equal(production.quote.sale_gross, '9828.00');
    const before = {};
    for (const artifact of production.artifacts) {
      const response = await page.request.get(url + artifact.download_url);
      assert.equal(response.status(), 200);
      before[artifact.artifact_id] = { url: artifact.download_url, sha256: sha(await response.body()) };
    }
    await page.getByRole('button', { name: '需求', exact: true }).click();
    await page.getByLabel('外框宽度（m）', { exact: true }).fill('16');
    await page.getByRole('button', { name: '保存需求草稿', exact: true }).click();
    await page.getByText('需求已保存为 v3', { exact: true }).waitFor();
    assert.equal((await api(`/api/v1/projects/${projectId}/production`)).item.status, 'source_outdated');
    await page.getByRole('button', { name: '生成分区布局', exact: true }).click();
    await page.getByText('设计 v2 已保存，生成 7 份成果', { exact: true }).waitFor();
    panel = page.getByRole('region', { name: '设计生产链' });
    await panel.getByText('104.0000', { exact: false }).first().waitFor();
    const final = (await api(`/api/v1/projects/${projectId}/production`)).item;
    assert.equal(final.quote.sale_gross, '13104.00');
    for (const original of Object.values(before)) {
      const response = await page.request.get(url + original.url);
      assert.equal(response.status(), 200);
      assert.equal(sha(await response.body()), original.sha256);
    }
    // One batched desktop/mobile inspection for the new panel.
    const views = [];
    for (const [name, width, height] of [['desktop', 1440, 1000], ['mobile', 390, 844]]) {
      await page.setViewportSize({ width, height });
      await panel.scrollIntoViewIfNeeded();
      const dimensions = await page.evaluate(() => ({ width: innerWidth, document: document.documentElement.scrollWidth }));
      assert(dimensions.document <= dimensions.width + 1, JSON.stringify(dimensions));
      await panel.screenshot({ path: path.join(evidence, name + '-production.png') });
      views.push({ name, ...dimensions });
    }
    await page.setViewportSize({ width: 1440, height: 1000 });
    const pending = page.waitForEvent('download');
    await panel.getByRole('button', { name: '完整生产包', exact: true }).click();
    const downloaded = await pending;
    const downloadPath = path.join(evidence, downloaded.suggestedFilename());
    await downloaded.saveAs(downloadPath);
    const zipArtifact = final.artifacts.find(a => a.artifact_kind === 'package_zip');
    assert.equal(sha(fs.readFileSync(downloadPath)), zipArtifact.sha256);
    // Procurement tab reads the automatic M4 draft without copying quantities.
    await page.locator('.view-tabs button').filter({ hasText: '采购施工' }).click();
    await page.locator('.procurement-card').filter({ hasText: final.production_revision_id }).waitFor();
    const orders = (await api(`/api/v1/projects/${projectId}/procurement/orders`)).items;
    const order = orders.find(o => o.order_id === final.procurement.order_id);
    assert.equal(order.lines.reduce((sum, item) => sum + Number(item.ordered_quantity), 0), 104);
    assert.equal(order.external_effects_enabled, false);
    await page.getByRole('region', { name: '设计生产链' }).getByLabel('查看生产修订').selectOption('2');
    await page.getByRole('region', { name: '设计生产链' }).getByText('历史版本', { exact: true }).waitFor();
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(evidence, 'browser.json'), JSON.stringify({ passed: true, project_name: projectName, project_id: projectId, initial_quote_gross: '9828.00', final, order, old_files_unchanged: Object.keys(before).length, views, errors }, null, 2));
    console.log(JSON.stringify({ passed: true, project_id: projectId, quantity: final.quote.quantity, gross: final.quote.sale_gross, views }));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
