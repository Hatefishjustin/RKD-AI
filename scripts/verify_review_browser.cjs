const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const { chromium } = require(path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const url = process.env.RKD_QA_URL;
const evidence = process.env.RKD_QA_EVIDENCE_DIR;
assert(url && evidence, 'isolated browser test configuration required');
(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = []; page.on('pageerror', e => errors.push(e.message));
  async function login(username) {
    await page.goto(url);
    await page.getByLabel('登录账号', { exact: true }).fill(username);
    await page.getByLabel('登录密码', { exact: true }).fill('Transport verification passphrase 2026');
    await page.getByRole('button', { name: '登录', exact: true }).click();
    await page.getByRole('button', { name: '退出登录', exact: true }).waitFor();
  }
  try {
    await login('admin');
    await page.locator('.view-tabs button').filter({ hasText: '采购施工' }).click();
    await page.getByRole('button', { name: '检查当前生产草稿', exact: true }).click();
    await page.getByRole('button', { name: '按岗位提交草稿审查', exact: true }).click();
    await page.getByText('草稿审查事项已建立。', { exact: false }).waitFor();
    const result = await (await page.request.get(url + '/api/v1/projects/alpha/review-tasks')).json();
    assert.equal(result.items.filter(item => !item.source_outdated).length, 2);
    await page.getByRole('button', { name: '退出登录', exact: true }).click();
    await login('staff');
    const inbox = page.locator('.review-tasks').first();
    await inbox.locator('summary').filter({ hasText: '（1）' }).waitFor();
    await inbox.locator('summary').click();
    for (let index = 0; index < 3; index++) await inbox.locator('form textarea').nth(index).fill('隔离验证：等待现场及专业证据');
    await inbox.getByLabel('审查说明', { exact: true }).fill('浏览器隔离测试：需现场核验边界，不构成正式批准。');
    await inbox.getByLabel('草稿审查结论', { exact: true }).selectOption('reviewed');
    await page.screenshot({ path: path.join(evidence, 'review-desktop.png'), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    const sizes = await page.evaluate(() => ({ width: innerWidth, document: document.documentElement.scrollWidth }));
    assert(sizes.document <= sizes.width + 1, JSON.stringify(sizes));
    await page.screenshot({ path: path.join(evidence, 'review-mobile.png'), fullPage: true });
    await inbox.getByRole('button', { name: '保存草稿审查记录', exact: true }).click();
    await inbox.locator('summary').filter({ hasText: '（0）' }).waitFor();
    const saved = await (await page.request.get(url + '/api/v1/projects/alpha/review-tasks')).json();
    assert(saved.items.some(item => item.status === 'reviewed' && item.note.includes('浏览器隔离测试')));
    assert.equal(saved.formal_release_allowed, false); assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(evidence, 'review-browser.json'), JSON.stringify({ passed: true, submitted: result.items.length, draft_review_recorded: true, sizes, errors }, null, 2));
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
