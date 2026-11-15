/* W2-R4 表达收口 V2/V3 人眼图前后证据：同一机位/模型的前后全图与窗区、功能区局部。
   before 为上一批 W2-R4 成果（不重新生成、不回写历史），after 为本批最终图。
   0 外部调用。自动只负责裁剪与字节记录；可读性由人工目检判定。 */
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
const { chromium } = require(path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));

const out = process.env.RKD_RENDER_OUT;
const inputs = {
  A: { before: process.env.RKD_RENDER_BEFORE_A, after: process.env.RKD_RENDER_AFTER_A },
  B: { before: process.env.RKD_RENDER_BEFORE_B, after: process.env.RKD_RENDER_AFTER_B },
};
assert(out && inputs.A.before && inputs.A.after && inputs.B.before && inputs.B.after,
  'RKD_RENDER_OUT / BEFORE_A / AFTER_A / BEFORE_B / AFTER_B required');
fs.mkdirSync(out, { recursive: true });

// 相对图幅的局部区域：窗带（左侧）与主要功能区（中右）
const REGIONS = {
  window: { x: 0.00, y: 0.20, w: 0.36, h: 0.58 },
  function: { x: 0.26, y: 0.26, w: 0.66, h: 0.64 },
};

function pngSize(buf) {
  assert(buf.slice(1, 4).toString() === 'PNG', 'not a PNG');
  return { w: buf.readUInt32BE(16), h: buf.readUInt32BE(20) };
}

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const observations = { created_at: new Date().toISOString(), regions: REGIONS, files: [] };
  try {
    for (const letter of ['A', 'B']) {
      for (const phase of ['before', 'after']) {
        const src = path.resolve(inputs[letter][phase]);
        assert(fs.existsSync(src), `missing ${src}`);
        const buf = fs.readFileSync(src);
        const size = pngSize(buf);
        const fullName = `render-${letter}-full-${phase}.png`;
        fs.copyFileSync(src, path.join(out, fullName));
        observations.files.push({ layout: letter, phase, kind: 'full',
          file: fullName, bytes: buf.length, size,
          note: phase === 'before' ? '上一批 W2-R4 原图，只读引用' : '本批最终渲染' });

        // file:// 图片在 setContent 的 about:blank 源下会被浏览器阻止加载，
        // 用 base64 data URL 内联，保证裁剪出来的是真实像素而不是黑屏。
        const dataUrl = `data:image/png;base64,${buf.toString('base64')}`;
        const page = await browser.newPage({ viewport: { width: size.w, height: size.h } });
        await page.setContent(
          `<!doctype html><html><head><meta charset="utf-8"><style>` +
          `html,body{margin:0;padding:0;background:#000}img{display:block;width:${size.w}px;height:${size.h}px}` +
          `</style></head><body><img src="${dataUrl}"></body></html>`,
          { waitUntil: 'load' });
        await page.waitForTimeout(260);
        for (const [region, r] of Object.entries(REGIONS)) {
          const clip = {
            x: Math.round(r.x * size.w), y: Math.round(r.y * size.h),
            width: Math.round(r.w * size.w), height: Math.round(r.h * size.h),
          };
          const name = `render-${letter}-${region}-${phase}.png`;
          await page.screenshot({ path: path.join(out, name), clip, timeout: 60000 });
          observations.files.push({ layout: letter, phase, kind: region,
            file: name, bytes: fs.statSync(path.join(out, name)).size, clip });
        }
        await page.close();
      }
    }
    fs.writeFileSync(path.join(out, 'render-crop-observations.json'),
      JSON.stringify(observations, null, 2));
    console.log(JSON.stringify({ files: observations.files.length,
      note: '自动裁剪完成；窗框/材质/陈设可读性由人工目检在 manual-visual-review.md 判定' }, null, 2));
    await browser.close();
    process.exit(0);
  } catch (e) {
    console.error(String((e && e.stack) || e));
    await browser.close();
    process.exit(1);
  }
})();
