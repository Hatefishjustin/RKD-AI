// Repeatable M1–M4 entry regression plus the M5 account pilot, in isolated state.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const { spawn } = require('node:child_process');
const root = path.resolve(__dirname, '..');
const evidence = path.join(root, 'var/evidence/m5-entry', `run-${Date.now()}`);
fs.mkdirSync(evidence, { recursive: true });
const python = path.join(root, '.venv/Scripts/python.exe');
const password = crypto.randomBytes(24).toString('base64url');
const env = { ...process.env, RKD_QA_PASSWORD: password };
let current;
async function start(mode, port = 0) {
  const runtime = path.join(evidence, `${mode}-runtime`);
  const child = spawn(python, [path.join(__dirname, 'run_m5_qa_server.py'), '--runtime', runtime, '--mode', mode, '--port', String(port)], { cwd: root, env, windowsHide: true });
  current = child;
  let output = '';
  const info = await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('QA server startup timeout')), 45000);
    child.stdout.on('data', chunk => {
      output += chunk.toString();
      if (output.includes('\n')) { clearTimeout(timer); try { resolve(JSON.parse(output.split('\n')[0])); } catch (e) { reject(e); } }
    });
    child.stderr.on('data', chunk => fs.appendFileSync(path.join(evidence, `${mode}-server.log`), chunk));
    child.once('error', reject);
    child.once('exit', code => { clearTimeout(timer); reject(new Error(`server exited ${code}`)); });
  });
  return info;
}
async function stop() {
  if (!current || current.exitCode !== null) return;
  const child = current;
  await new Promise(resolve => { child.once('exit', resolve); child.kill(); });
  current = undefined;
}
async function script(name, url, subfolder, args = []) {
  const folder = path.join(evidence, subfolder);
  fs.mkdirSync(folder, { recursive: true });
  const child = spawn(process.execPath, [path.join(__dirname, name), ...args], { cwd: root, env: { ...env, RKD_QA_URL: url, RKD_QA_EVIDENCE_DIR: folder }, windowsHide: true });
  const log = path.join(folder, `${path.basename(name, '.cjs')}${args.includes('--restart') ? '-restart' : ''}.log`);
  child.stdout.on('data', chunk => fs.appendFileSync(log, chunk));
  child.stderr.on('data', chunk => fs.appendFileSync(log, chunk));
  const code = await new Promise((resolve, reject) => { child.once('error', reject); child.once('exit', resolve); });
  assert.equal(code, 0, `${name} failed; see ${log}`);
  console.log(`${name} ${args.join(' ')} passed`);
}
(async () => {
  try {
    let server;
    let localRestart = null;
    if (!process.argv.includes('--accounts-only')) {
      server = await start('local');
      await script('verify_m3_browser.cjs', server.url, 'm3');
      await script('verify_m4_browser.cjs', server.url, 'm4');
      await script('verify_m4_change_browser.cjs', server.url, 'm4');
      const localPid = server.pid;
      await stop();
      server = await start('local', Number(new URL(server.url).port));
      assert.notEqual(server.pid, localPid);
      await script('verify_m3_browser.cjs', server.url, 'm3', ['--restart']);
      localRestart = { before_pid: localPid, after_pid: server.pid };
      await stop();
    }
    server = await start('accounts');
    await script('verify_m5_browser.cjs', server.url, 'm5');
    const accountPid = server.pid;
    await stop();
    server = await start('accounts', Number(new URL(server.url).port));
    assert.notEqual(server.pid, accountPid);
    await script('verify_m5_browser.cjs', server.url, 'm5', ['--restart']);
    fs.writeFileSync(path.join(evidence, 'entry-verification.json'), JSON.stringify({ passed: true, local_restart: localRestart, account_restart: { before_pid: accountPid, after_pid: server.pid }, external_effects: false, runtime_isolated: true }, null, 2));
    console.log(`Evidence: ${evidence}`);
  } finally { await stop(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
