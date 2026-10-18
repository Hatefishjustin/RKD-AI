const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const { chromium } = require(process.env.RKD_PLAYWRIGHT_MODULE || path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));
const url = process.env.RKD_QA_URL;
const evidence = process.env.RKD_QA_EVIDENCE_DIR;
const password = process.env.RKD_QA_PASSWORD;
assert(url && evidence && password, 'isolated QA configuration required');

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  const results = {};
  async function login(name) {
    await page.goto(url);
    await page.getByLabel('登录账号', { exact: true }).fill(name);
    await page.getByLabel('登录密码', { exact: true }).fill(password);
    await page.getByRole('button', { name: '登录', exact: true }).click();
    await page.getByRole('button', { name: '退出登录', exact: true }).waitFor();
  }
  async function csrf() { return (await (await page.request.get(`${url}/api/v1/auth/session`)).json()).csrf_token; }
  async function viewport(name) {
    const sizes = await page.evaluate(() => ({ viewport: innerWidth, document: document.documentElement.scrollWidth }));
    assert(sizes.document <= sizes.viewport + 1, JSON.stringify(sizes));
    await page.screenshot({ path: path.join(evidence, `${name}.png`), fullPage: true });
    return sizes;
  }
  try {
    await login('qa-admin');
    if (process.argv.includes('--restart')) {
      const previous = JSON.parse(fs.readFileSync(path.join(evidence, 'accounts-browser.json')));
      await page.getByRole('button', { name: '账号与成员管理', exact: true }).click();
      await page.locator('.account-member-list strong').filter({ hasText: 'M5 只读测试成员（qa-viewer）' }).waitFor();
      const projects = await (await page.request.get(`${url}/api/v1/projects`)).json();
      assert(projects.items.some(p => p.project_id === previous.project_id));
      const members = await (await page.request.get(`${url}/api/v1/projects/${previous.project_id}/members`)).json();
      assert.equal(members.items.find(m => m.username === 'qa-viewer').role, 'viewer');
      fs.writeFileSync(path.join(evidence, 'accounts-restart.json'), JSON.stringify({ passed: true, project_id: previous.project_id, retained_members: members.items.length, errors }, null, 2));
      return;
    }
    await page.getByLabel('新建项目', { exact: true }).fill('M5 账号浏览器验收项目');
    await page.getByRole('button', { name: '创建项目', exact: true }).click();
    await page.getByRole('heading', { name: 'M5 账号浏览器验收项目', exact: true }).waitFor();
    const projects = await (await page.request.get(`${url}/api/v1/projects`)).json();
    const project = projects.items.find(p => p.name === 'M5 账号浏览器验收项目');
    await page.getByRole('button', { name: '账号与成员管理', exact: true }).click();
    await page.getByLabel('新账号', { exact: true }).fill('qa-viewer');
    await page.getByLabel('显示姓名', { exact: true }).fill('M5 只读测试成员');
    await page.getByLabel('初始密码', { exact: true }).fill(password);
    await page.getByRole('button', { name: '创建账号', exact: true }).click();
    await page.getByText('账号已创建，请分配项目角色后使用', { exact: true }).waitFor();
    await page.getByLabel('分配账号', { exact: true }).selectOption({ label: 'M5 只读测试成员（qa-viewer）' });
    await page.getByLabel('项目角色', { exact: true }).selectOption('viewer');
    await page.getByRole('button', { name: '保存项目权限', exact: true }).click();
    await page.getByText('项目权限已更新，现有登录会话即时生效', { exact: true }).waitFor();
    results.desktop = await viewport('accounts-desktop');
    await page.setViewportSize({ width: 390, height: 844 });
    results.mobile = await viewport('accounts-mobile');
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.getByRole('button', { name: /资料与图纸/ }).click();
    const fileBytes = Buffer.from('%PDF-1.4\nM5 browser upload test\n%%EOF');
    await page.locator('input[type=file]').setInputFiles({ name: 'm5-permission-test.pdf', mimeType: 'application/pdf', buffer: fileBytes });
    await page.getByText('m5-permission-test.pdf', { exact: true }).waitFor();
    const files = await (await page.request.get(`${url}/api/v1/projects/${project.project_id}/files`)).json();
    const file = files.items.find(f => f.filename === 'm5-permission-test.pdf');
    assert.equal(file.sha256, crypto.createHash('sha256').update(fileBytes).digest('hex'));
    await page.getByRole('button', { name: '退出登录', exact: true }).click();
    await login('qa-viewer');
    assert.equal(await page.locator('.project-item').count(), 1);
    assert.equal((await page.request.get(`${url}/api/v1/projects/audit-floor`)).status(), 404);
    assert.equal((await page.request.patch(`${url}/api/v1/projects/${project.project_id}`, { headers: { 'X-CSRF-Token': await csrf() }, data: { name: 'should not save', expected_version: 0 } })).status(), 403);
    await page.getByRole('button', { name: /资料与图纸/ }).click();
    const downloading = page.waitForEvent('download');
    await page.getByRole('link', { name: '下载 m5-permission-test.pdf', exact: true }).click();
    const download = await downloading;
    assert.deepEqual(fs.readFileSync(await download.path()), fileBytes);
    assert.equal(await page.evaluate(() => document.cookie.includes('rkd_session')), false);
    results.viewer = { visible_projects: 1, cross_project: 404, denied_write: 403, download_sha256: file.sha256 };
    const viewerCookies = await context.cookies();
    await page.getByRole('button', { name: '退出登录', exact: true }).click();
    await page.getByRole('heading', { name: '登录工作台', exact: true }).waitFor();
    const stolen = viewerCookies.find(c => c.name === 'rkd_session');
    assert.equal((await page.request.get(`${url}${file.download_url}`, { headers: { Cookie: `${stolen.name}=${stolen.value}` } })).status(), 401);
    results.logout_revoked_download = true;
    await login('qa-admin');
    results.project_id = project.project_id;
    results.errors = errors;
    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(evidence, 'accounts-browser.json'), JSON.stringify({ passed: true, ...results }, null, 2));
    console.log('M5 browser login, roles, upload/download, logout and responsive checks passed');
  } catch (error) {
    fs.writeFileSync(path.join(evidence, 'browser-failure.txt'), await page.locator('body').innerText());
    await page.screenshot({ path: path.join(evidence, 'browser-failure.png'), fullPage: true });
    throw error;
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
