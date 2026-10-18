const assert = require('node:assert/strict');
const path = require('node:path');
const os = require('node:os');
const { chromium } = require(process.env.RKD_PLAYWRIGHT_MODULE || path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));

const url = process.env.RKD_QA_URL || 'http://127.0.0.1:8080';

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const projectName = `M4 浏览器验收采购 ${Date.now()}`;
  const errors = [];
  page.on('pageerror', (error) => errors.push(error.message));
  try {
    await page.goto(url);
    await page.getByLabel('新建项目', { exact: true }).fill(projectName);
    await page.getByRole('button', { name: '创建项目', exact: true }).click();
    await page.getByRole('heading', { name: projectName, exact: true }).waitFor();
    await page.getByRole('button', { name: /采购施工/ }).click();
    await page.getByLabel('供应商', { exact: true }).fill('M4 测试供应商');
    await page.getByLabel('到货地点', { exact: true }).fill('M4 测试现场');
    await page.getByLabel('材料名称', { exact: true }).fill('测试灯具');
    await page.getByLabel('订单数量', { exact: true }).fill('10');
    await page.getByRole('button', { name: '保存订单草稿', exact: true }).click();
    await page.getByText('材料订单草稿已保存', { exact: true }).waitFor();
    await page.getByText('订单 10', { exact: true }).waitFor();
    await page.getByLabel('数量', { exact: true }).fill('6');
    await page.getByLabel('证据引用', { exact: true }).fill('browser-receipt-01');
    await page.getByRole('button', { name: '记录收货', exact: true }).click();
    await page.getByText('收货记录已保存', { exact: true }).waitFor();
    await page.getByText('已收 6', { exact: true }).waitFor();
    await page.getByLabel('数量', { exact: true }).fill('4');
    await page.getByLabel('目标区域', { exact: true }).fill('接待区');
    await page.getByLabel('接收班组', { exact: true }).fill('施工班组 A');
    await page.getByLabel('证据引用', { exact: true }).fill('browser-allocation-01');
    await page.getByRole('button', { name: '记录分派', exact: true }).click();
    await page.getByText('材料分派已保存', { exact: true }).waitFor();
    await page.getByText('已分派 4', { exact: true }).waitFor();
    const overflow = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth }));
    assert(overflow.document <= overflow.viewport + 1, JSON.stringify(overflow));
    assert.deepEqual(errors, []);
    await page.screenshot({ path: path.join(process.env.RKD_QA_EVIDENCE_DIR || 'var/evidence', 'm4-procurement-browser.png'), fullPage: true });
    console.log(JSON.stringify({ passed: true, project_name: projectName, overflow, errors }));
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
