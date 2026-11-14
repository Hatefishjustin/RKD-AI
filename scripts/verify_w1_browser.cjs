/* W1 真实浏览器验收：从页面触发一次 Studio 提案导入并查看目标模型。
   0 外部调用、0 密钥、0 费用。由 verify_w1_browser.py 驱动。 */
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const { chromium } = require(path.join(os.homedir(), '.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'));

const url = process.env.RKD_QA_URL;
const evidence = process.env.RKD_QA_EVIDENCE_DIR;
const projectId = process.env.RKD_QA_PROJECT_ID;
const artifactId = process.env.RKD_QA_STUDIO_ARTIFACT_ID;
assert(url && evidence && projectId && artifactId, 'isolated W1 browser config required');

const api = `${url}/api/v1/projects/${projectId}/ai/design-options`;

(async () => {
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  const page = await browser.newPage({ viewport: { width: 1500, height: 1050 } });
  const errors = [];
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('console', m => {
    if (m.type() !== 'error') return;
    const t = m.text();
    if (/Failed to load resource.*404|status of 404/.test(t)) return;
    errors.push('console: ' + t);
  });
  page.on('dialog', async d => { await d.accept('W1 导入'); });
  const obs = { artifactId };
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded' });
    await page.locator('.project-item').first().waitFor({ timeout: 25000 });
    await page.locator('.project-item').first().click();
    await page.locator('.view-tabs button').filter({ hasText: '需求草稿' }).click();
    await page.locator('.design-modes button').filter({ hasText: 'AI 候选' }).click();
    await page.locator('[data-testid="studio-source-select"]').waitFor({ timeout: 20000 });

    const mapping = (await page.locator('[data-testid="studio-mapping"]').innerText()).replace(/\s+/g, ' ');
    obs.mapping_text = mapping;
    assert(/project_ningbo_xiecheng_2026/.test(mapping), 'page does not show the explicit Studio→main mapping');

    const options = await page.locator('[data-testid="studio-source-select"] option').allTextContents();
    obs.source_options = options;
    assert(options.some(o => o.includes(artifactId)), 'Studio valid proposal is not listed');

    const before = await (await page.request.get(`${api}/studio-imports`)).json();
    obs.imports_before = before.items.length;
    assert.equal(before.items.length, 0, 'isolated project already has imports');

    await page.locator('[data-testid="studio-source-select"]').selectOption(artifactId);
    await page.locator('[data-testid="studio-import-button"]').click();
    await page.locator('[data-testid="studio-import-row"]').first().waitFor({ timeout: 25000 });

    const imported = await (await page.request.get(`${api}/studio-imports`)).json();
    obs.imports_after = imported.items.length;
    const row = imported.items[0].revisions[0];
    obs.imported_revision = {
      option_id: row.option_id, revision_no: row.revision_no,
      parent_revision_id: row.parent_revision_id,
      source_artifact_id: row.source.artifact_id,
      unsupported_items: row.unsupported_items.map(u => u.item),
      artifact_count: row.artifacts.length,
    };
    assert.equal(imported.items.length, 1);
    assert.equal(row.source.artifact_id, artifactId);
    assert.equal(row.revision_no, 1);
    assert.equal(row.parent_revision_id, null);
    assert(row.artifacts.length >= 1, 'no target model artifact');

    // API / page / storage version agreement
    const status = await (await page.request.get(api)).json();
    const inGrid = (status.item?.options || []).find(o => o.option_revision_id === row.option_revision_id);
    obs.target_model_in_api = Boolean(inGrid);
    obs.target_model_spatial = inGrid?.model?.spatial ? {
      zones: inGrid.model.spatial.zones.length,
      non_rectangular: inGrid.model.spatial.zones.filter(z => z.polygon_mm.length > 4).map(z => z.object_id),
      unit: inGrid.model.spatial.unit,
      origin_kind: inGrid.model.spatial.source.origin_kind,
    } : null;
    assert(inGrid, 'imported candidate is not visible via the normal candidate API');
    assert(obs.target_model_spatial.zones >= 3 && obs.target_model_spatial.non_rectangular.length >= 1,
      'exact non-rectangular geometry missing from target model');
    assert.equal(obs.target_model_spatial.unit, 'mm');
    assert.equal(obs.target_model_spatial.origin_kind, 'studio_import');

    // SVG bytes from the page link are real and polygon-based
    const svgResp = await page.request.get(`${api}/artifacts/${row.artifacts[0].artifact_id}/content`);
    const svg = await svgResp.text();
    obs.svg_bytes = Buffer.byteLength(svg);
    obs.svg_has_polygon = svg.includes('<polygon');
    assert.equal(svgResp.status(), 200);
    assert(svg.includes('<polygon'), 'target drawing is not polygon-based');
    obs.svg_matches_stored_sha = require('node:crypto').createHash('sha256').update(svg).digest('hex') === row.artifacts[0].sha256;

    // adoption / production / procurement / release untouched
    const adoption = await (await page.request.get(`${url}/api/v1/projects/${projectId}/design`)).json();
    obs.design_item_after_import = adoption.item ?? null;
    obs.adoption = status.adoption;
    assert.equal(status.adoption, null, 'import changed the adoption pointer');

    // field reconciliation from the page
    await page.locator('[data-testid="studio-import-row"] button').filter({ hasText: '字段对账' }).first().click();
    await page.locator('[data-testid="studio-import-detail"] .ledger-table').waitFor({ timeout: 20000 });
    const ledgerRows = await page.locator('[data-testid="studio-import-detail"] .ledger-table tbody tr').count();
    const detailText = (await page.locator('[data-testid="studio-import-detail"]').innerText()).replace(/\s+/g, ' ');
    obs.ledger_rows = ledgerRows;
    obs.unsupported_visible = /相机与人眼视图/.test(detailText) && /材料规格/.test(detailText);
    obs.geometry_mode_visible = /polygon_exact_in_spatial_bbox_derived_in_legacy_objects/.test(detailText);
    assert(ledgerRows > 20, 'field ledger is not visible on the page');
    assert(obs.unsupported_visible, 'named unsupported items are not visible');
    assert(obs.geometry_mode_visible, 'geometry mode / bounding-box loss not visible');

    await page.screenshot({ path: path.join(evidence, 'w1-import-desktop.png'), fullPage: true });

    // 390px
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(700);
    obs.mobile_scroll_width = await page.evaluate(() => document.documentElement.scrollWidth);
    assert(obs.mobile_scroll_width <= 390, `mobile overflow: ${obs.mobile_scroll_width}`);
    await page.screenshot({ path: path.join(evidence, 'w1-import-mobile.png'), fullPage: true });

    obs.page_errors = errors;
    assert.equal(errors.length, 0, 'browser JS errors: ' + errors.join(' | '));
    obs.passed = true;
    fs.writeFileSync(path.join(evidence, 'browser-observations.json'), JSON.stringify(obs, null, 2));
    console.log(JSON.stringify({ passed: true, revision: obs.imported_revision,
      ledger_rows: ledgerRows, svg_bytes: obs.svg_bytes }, null, 2));
    await browser.close();
    process.exit(0);
  } catch (e) {
    obs.passed = false;
    obs.failure = String((e && e.message) || e);
    obs.page_errors = errors;
    fs.writeFileSync(path.join(evidence, 'browser-observations.json'), JSON.stringify(obs, null, 2));
    console.error(String((e && e.stack) || e));
    await browser.close();
    process.exit(1);
  }
})();
