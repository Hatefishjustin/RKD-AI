/* W2-R4 表达收口 V1 图面证据：真实前后全图 / 入口·洽谈区局部 / 打印缩放。
   自动几何检查（编号重叠、出界、最小字号）与人工目检分列，不互相代替。
   0 外部调用。由 build_w2_r4_closeout_review.py 或手工调用。 */
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const { pathToFileURL } = require('node:url');
const { chromium } = require(path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));

const out = process.env.RKD_VISUAL_OUT;
const before = {
  A: process.env.RKD_VISUAL_BEFORE_A,
  B: process.env.RKD_VISUAL_BEFORE_B,
};
const after = {
  A: process.env.RKD_VISUAL_AFTER_A,
  B: process.env.RKD_VISUAL_AFTER_B,
};
assert(out && before.A && before.B && after.A && after.B,
  'RKD_VISUAL_OUT / BEFORE_A / BEFORE_B / AFTER_A / AFTER_B required');
fs.mkdirSync(out, { recursive: true });

// 与 ai_spatial_outputs / plan_layers 同一坐标系：西南原点，+X 东 +Y 北
const REGIONS = {
  A: {
    entry: [0, 8200, 6200, 14000],
    meeting: [18000, 6800, 26170, 14200],
  },
  B: {
    entry: [0, 8200, 5400, 14200],
    meeting: [16800, 13400, 26170, 17920],
  },
};
const LEGACY_METRICS = { ox: 80, oy: 110, scale: 880 / 26170, w: 26170, h: 17920 };

function metrics(svgText) {
  const m = /data-plan-metrics="([^"]+)"/.exec(svgText);
  if (m) {
    const [ox, oy, scale, w, h] = m[1].split(',').map(Number);
    return { ox, oy, scale, w, h, layered: true };
  }
  return { ...LEGACY_METRICS, layered: false };
}

function clipFor(rect, mt, pad = 55) {
  const [x0, y0, x1, y1] = rect;
  const px0 = mt.ox + x0 * mt.scale;
  const px1 = mt.ox + x1 * mt.scale;
  const py0 = mt.oy + (mt.h - y1) * mt.scale;
  const py1 = mt.oy + (mt.h - y0) * mt.scale;
  return {
    x: Math.max(0, px0 - pad), y: Math.max(0, py0 - pad),
    width: Math.min(2000, px1 - px0 + pad * 2),
    height: Math.min(2000, py1 - py0 + pad * 2),
  };
}

function autoGeometryCheck(svgText, mt) {
  // 只检查图面标注层（data-anno=1）：表格文字按行列排布不参与互相遮挡判定
  const sizeMatch = /<svg[^>]*width="([\d.]+)"[^>]*height="([\d.]+)"/.exec(svgText);
  const bounds = sizeMatch ? { w: Number(sizeMatch[1]), h: Number(sizeMatch[2]) }
    : { w: 1500, h: 1500 };
  const items = [];
  const re = /<text([^>]*)>([\s\S]*?)<\/text>/g;
  let m;
  while ((m = re.exec(svgText)) !== null) {
    if (!m[1].includes('data-anno="1"')) continue;
    const x = Number((/x="([\d.-]+)"/.exec(m[1]) || [])[1] || 0);
    const y = Number((/y="([\d.-]+)"/.exec(m[1]) || [])[1] || 0);
    const fs = Number((/font-size="([\d.]+)"/.exec(m[1]) || [])[1] || 10);
    const text = m[2].replace(/<[^>]+>/g, '').trim();
    const middle = /text-anchor="middle"/.test(m[1]);
    const width = Math.max(12, text.length * fs * 0.62);
    const left = middle ? x - width / 2 : x;
    items.push({ text, x, y, fs, left, right: left + width, top: y - fs, bottom: y + 3 });
  }
  const overlaps = [];
  for (let i = 0; i < items.length; i += 1) {
    for (let j = i + 1; j < items.length; j += 1) {
      const a = items[i], b = items[j];
      const ox = Math.min(a.right, b.right) - Math.max(a.left, b.left);
      const oy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
      if (ox > 3 && oy > 3) overlaps.push({ a: a.text, b: b.text, overlap_px: [Math.round(ox), Math.round(oy)] });
    }
  }
  const outside = items.filter(t => t.left < 0 || t.right > bounds.w || t.top < 0 || t.bottom > bounds.h)
    .map(t => t.text);
  return {
    annotation_count: items.length,
    min_font_size: items.length ? Math.min(...items.map(t => t.fs)) : null,
    overlaps, overlap_count: overlaps.length,
    outside_count: outside.length, outside_samples: outside.slice(0, 8),
    bounds,
    note: '自动几何检查只覆盖带 data-anno 的图面标注；不代表人工目检通过',
  };
}

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const observations = {
    created_at: new Date().toISOString(),
    regions_mm: REGIONS,
    screenshots: [],
    auto_geometry_check: {},
    manual_visual_review: '见复核包 manual-visual-review.md（自动断言不代替人工目检）',
  };
  const page = await browser.newPage({ viewport: { width: 1500, height: 1550 } });
  try {
    for (const letter of ['A', 'B']) {
      for (const [phase, svgPath] of [['before', before[letter]], ['after', after[letter]]]) {
        assert(fs.existsSync(svgPath), `missing ${svgPath}`);
        const svgText = fs.readFileSync(svgPath, 'utf-8');
        const mt = metrics(svgText);
        await page.goto(pathToFileURL(path.resolve(svgPath)).href, { waitUntil: 'load' });
        await page.waitForTimeout(320);

        // 全图（正常屏幕缩放）
        const full = path.join(out, `plan-${letter}-full-${phase}.png`);
        await page.screenshot({ path: full, timeout: 60000 });
        observations.screenshots.push({ layout: letter, phase, kind: 'full',
          file: path.basename(full), bytes: fs.statSync(full).size,
          metrics: mt, scope: '正常屏幕缩放 1500px 视口' });

        // 局部：入口 / 洽谈区，前后用同一 mm 区域换算，不靠目测裁剪
        for (const [region, rect] of Object.entries(REGIONS[letter])) {
          const clip = clipFor(rect, mt);
          const target = path.join(out, `plan-${letter}-${region}-${phase}.png`);
          await page.screenshot({ path: target, clip, timeout: 60000 });
          observations.screenshots.push({ layout: letter, phase, kind: region,
            file: path.basename(target), bytes: fs.statSync(target).size,
            region_mm: rect, clip_px: clip });
        }

        // 打印目标尺寸：A4 横向可用宽 270mm，检查缩放后小字是否仍可读
        const printPage = await browser.newPage({ viewport: { width: 1200, height: 1700 } });
        const scaled = svgText.replace(/<svg([^>]*)>/,
          (all, attrs) => `<svg${attrs} style="width:270mm;height:auto;display:block">`);
        await printPage.setContent(
          `<!doctype html><html><head><meta charset="utf-8"><style>body{margin:8mm;background:#fff}</style></head>` +
          `<body>${scaled}</body></html>`, { waitUntil: 'load' });
        await printPage.waitForTimeout(300);
        const printTarget = path.join(out, `plan-${letter}-print-${phase}.png`);
        await printPage.screenshot({ path: printTarget, timeout: 60000 });
        observations.screenshots.push({ layout: letter, phase, kind: 'print_a4_width',
          file: path.basename(printTarget), bytes: fs.statSync(printTarget).size,
          scope: 'SVG 缩放到 A4 横向可用宽 270mm' });
        await printPage.close();

        observations.auto_geometry_check[`${letter}-${phase}`] = autoGeometryCheck(svgText, mt);
      }
    }
    fs.writeFileSync(path.join(out, 'capture-observations.json'),
      JSON.stringify(observations, null, 2));
    console.log(JSON.stringify({
      screenshots: observations.screenshots.length,
      auto_geometry: Object.fromEntries(Object.entries(observations.auto_geometry_check)
        .map(([k, v]) => [k, { annotations: v.annotation_count,
          overlaps: v.overlap_count, outside: v.outside_count,
          min_font: v.min_font_size }])),
    }, null, 2));
    await browser.close();
    process.exit(0);
  } catch (e) {
    console.error(String((e && e.stack) || e));
    await browser.close();
    process.exit(1);
  }
})();
