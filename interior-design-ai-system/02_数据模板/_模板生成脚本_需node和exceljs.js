// 生成 6 个 Excel 数据模板（含公式与下拉校验）
const ExcelJS = require('exceljs');
const path = require('path');

const OUT = 'C:/Users/Administrator/.zcode/workspace/default/interior-design-ai-system/02_数据模板';
const MONEY = '#,##0.00';
const PCT = '0.0%';
const DATE = 'yyyy-mm-dd';

const THIN = { style: 'thin', color: { argb: 'FFB0B0B0' } };
const BORDER = { top: THIN, left: THIN, bottom: THIN, right: THIN };

function headerStyle(cell) {
  cell.font = { bold: true, color: { argb: 'FFFFFFFF' }, size: 11 };
  cell.fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FF1F4E79' } };
  cell.alignment = { vertical: 'middle', horizontal: 'center', wrapText: true };
  cell.border = BORDER;
}

function addReadme(wb, title, lines) {
  const ws = wb.addWorksheet('说明');
  ws.columns = [{ width: 3 }, { width: 110 }];
  ws.getCell('B1').value = title;
  ws.getCell('B1').font = { bold: true, size: 16 };
  let r = 3;
  for (const line of lines) {
    const c = ws.getCell(`B${r}`);
    c.value = line;
    c.alignment = { wrapText: true, vertical: 'top' };
    if (line.startsWith('【')) c.font = { bold: true };
    r++;
  }
  return ws;
}

function buildDataSheet(wb, def) {
  const ws = wb.addWorksheet(def.name, { views: [{ state: 'frozen', ySplit: 1 }] });
  ws.columns = def.columns.map(c => ({ header: c[0], width: c[1] }));
  const n = def.columns.length;
  const hr = ws.getRow(1);
  for (let i = 1; i <= n; i++) headerStyle(hr.getCell(i));
  hr.height = 30;
  const last = def.rows || 200;
  // 下拉校验
  for (const [col, list] of Object.entries(def.lists || {})) {
    for (let r = 2; r <= last; r++) {
      ws.getCell(`${col}${r}`).dataValidation = {
        type: 'list', allowBlank: true, formulae: [`"${list}"`],
        showErrorMessage: true, errorStyle: 'warning', error: '建议从下拉列表选择，保持口径统一'
      };
    }
  }
  // 数字/日期格式
  for (const [col, fmt] of Object.entries(def.numFmt || {})) {
    for (let r = 2; r <= last; r++) ws.getCell(`${col}${r}`).numFmt = fmt;
  }
  // 公式列
  for (const [col, tpl] of Object.entries(def.formulas || {})) {
    for (let r = 2; r <= last; r++) ws.getCell(`${col}${r}`).value = tpl.replace(/\{r\}/g, String(r));
  }
  // 示例数据
  for (const row of (def.sample || [])) ws.addRow(row);
  return ws;
}

async function main() {
  // ============ 1. 客户与项目表 ============
  {
    const wb = new ExcelJS.Workbook();
    addReadme(wb, '客户与项目表（主数据）', [
      '【用途】全公司客户与项目的唯一主台账。线索阶段登记客户，分配项目编号后登记项目。',
      '【填写人】客户信息由老板或行政登记；项目信息由项目经理助理（或行政）维护。',
      '【编号规则】客户 KH-26-001；项目 HZ-26-001（HZ杭州/NB宁波/WZ温州-年份-流水号），终身不变。',
      '【阶段流转】项目"当前阶段"必须按状态机顺序推进：线索→量房→初步方案→报价→签约→深化设计→施工图→采购→施工→验收→售后→归档。',
      '【自动写入】稳定版中本表由 n8n 从钉钉表单和各工作链自动更新，人工只处理异常；快速版为手工维护。',
      '【注意】"企业空间附加信息"列组在企业空间项目立项时必填（对应采集表），住宅项目可留空。',
      '本表含 1 行示例数据（HZ-26-001），正式使用前可删除或保留作参照。'
    ]);
    buildDataSheet(wb, {
      name: '客户表',
      columns: [
        ['客户编号', 12], ['客户名称', 20], ['客户类型', 12], ['联系电话', 16], ['微信号', 16],
        ['来源', 12], ['需求概述', 30], ['预算范围', 14], ['意向等级', 10], ['关联项目编号', 14],
        ['登记日期', 12], ['最近联系日期', 14], ['跟进状态', 12], ['负责人', 10], ['备注', 24]
      ],
      lists: {
        C: '企业,住宅业主,开发商,其他',
        F: '朋友介绍,老客户介绍,其他',
        I: '高,中,低',
        M: '洽谈中,已报价,已签约,已流失,已完成'
      },
      numFmt: { K: DATE, L: DATE },
      sample: [['KH-26-001', '示例：杭州某某科技有限公司', '企业', '138xxxx0000', 'wx-id-001', '朋友介绍', '新办公室 800㎡ 整体设计与施工', '150-200万', '高', 'HZ-26-001', '2026-08-20', '2026-09-01', '已签约', '老板', '决策人：王总；关注点：形象与工期']]
    });
    buildDataSheet(wb, {
      name: '项目表',
      columns: [
        ['项目编号', 12], ['项目名称', 24], ['客户编号', 12], ['项目类型', 12], ['城市', 10],
        ['项目地址', 26], ['建筑面积㎡', 11], ['合同模式', 16], ['设计合同额', 12], ['施工合同额', 12],
        ['当前阶段', 12], ['项目状态', 10], ['立项日期', 12], ['计划交付日期', 13], ['实际交付日期', 13],
        ['主案设计师', 11], ['采购责任人', 11], ['企业名称与定位', 24], ['使用人数', 9], ['部门与空间功能', 24],
        ['动线要求', 20], ['房东物业消防限制', 24], ['决策人', 12], ['期望启用时间', 12], ['总预算', 12],
        ['采购进度%', 11], ['备注', 24]
      ],
      lists: {
        D: '企业空间,办公,住宅,别墅,大平层,餐饮,酒店,旧房改造,其他',
        E: '杭州,宁波,温州,其他',
        H: '设计费,设计费+施工管理费,设计施工一体化,全包',
        K: '线索,量房,初步方案,报价,签约,深化设计,施工图,采购,施工,验收,售后,归档',
        L: '进行中,暂停,已完成,已取消,已流失'
      },
      numFmt: { G: '#,##0', I: MONEY, J: MONEY, M: DATE, N: DATE, O: DATE, Y: MONEY, Z: PCT },
      sample: [['HZ-26-001', '示例：杭州某科技办公室', 'KH-26-001', '企业空间', '杭州', '杭州市××区××路××号3层', 800, '设计施工一体化', 120000, 1500000, '深化设计', '进行中', '2026-08-25', '2027-02-28', '', '老板', '助理设计师', '科技公司·年轻化办公', 60, '开放工位40+会议室3+前台形象区', '客户动线经前台；访客不穿生产区', '物业施工时间8:30-18:00；消防需报审', '王总', '2027-03-01', 1700000, 0.3, '试点项目']]
    });
    await wb.xlsx.writeFile(path.join(OUT, '01_客户与项目表.xlsx'));
  }

  // ============ 2. 施工问题台账 ============
  {
    const wb = new ExcelJS.Workbook();
    addReadme(wb, '施工问题台账（施工问题管理链主表）', [
      '【用途】记录每一个施工问题从发现到关闭的全过程，是施工问题管理链的数据核心。',
      '【填写方式】稳定版：现场人员钉钉表单提交→AI 整理→自动写入本表，责任人只需后续更新"处理方案/整改照片"。快速版：任何人在群内说"报问题"，由助理按本表转填。',
      '【编号规则】WT-26-0001 起逐年累加，由系统自动生成（快速版由助理按顺序编）。',
      '【默认截止时间】紧急 24 小时、重要 3 天、一般 7 天（自发现时间起算）。',
      '【必须老板审批】严重程度=紧急；或重要且影响成本/工期/设计效果=是。',
      '【关闭规则】一般问题复核人（采购责任人）确认关闭；重要/紧急问题老板确认关闭。',
      '【AI 列】"AI整理置信度"由 AI 写入，低于 0.7 的行标记待人工确认；"问题描述"列保留现场原始描述，AI 整理后的标准描述写在"处理方案"前的整理列（如启用）。'
    ]);
    buildDataSheet(wb, {
      name: '问题台账',
      rows: 300,
      columns: [
        ['问题编号', 12], ['项目编号', 12], ['项目地址', 24], ['发现时间', 16], ['发现人', 10],
        ['登记方式', 12], ['问题类型', 12], ['问题描述（原始）', 36], ['现场照片（NAS路径）', 28],
        ['严重程度', 10], ['影响设计效果', 11], ['影响成本', 9], ['影响工期', 9], ['需改图纸', 9],
        ['需老板审批', 11], ['责任方', 10], ['责任人', 10], ['截止时间', 16], ['AI整理置信度', 12],
        ['处理方案', 30], ['整改照片（NAS路径）', 28], ['复核人', 10], ['处理状态', 10], ['逾期次数', 9],
        ['关闭日期', 12], ['关联报价版本', 13], ['关联图纸版本', 13], ['备注', 20]
      ],
      lists: {
        F: '钉钉表单,微信转填,口头转填',
        G: '尺寸,材料,工艺,质量,进度,安全,图纸,客户变更,其他',
        J: '一般,重要,紧急',
        K: '是,否', L: '是,否', M: '是,否', N: '是,否', O: '是,否',
        P: '施工方,供应商,设计方,客户,物业',
        W: '待整理,待处理,处理中,待复核,已升级,已关闭'
      },
      numFmt: { S: '0.00', X: '0', Y: DATE },
      sample: [
        ['WT-26-0001', 'HZ-26-001', '杭州市××区××路××号3层', '2026-09-05 10:30', '李助理', '钉钉表单', '尺寸', '示例：二层隔墙位置与图纸偏差约15cm，遮挡预留插座面板', 'HZ-26-001/09_变更与问题/WT-26-0001_1.jpg', '重要', '是', '否', '是', '是', '是', '施工方', '张队', '2026-09-08 10:30', 0.92, '示例：要求按CAD最新版图纸放线返工，复核后进入下一步工序', 'HZ-26-001/09_变更与问题/WT-26-0001_整改.jpg', '老板', '处理中', 0, '', 'HZ-26-001-Q02', 'CAD-v3', 'AI分派：施工图设计师同步核对插座点位'],
        ['WT-26-0002', 'HZ-26-001', '杭州市××区××路××号3层', '2026-09-07 15:00', '王工', '钉钉表单', '材料', '示例：到场乳胶漆色号与选样卡不符', 'HZ-26-001/09_变更与问题/WT-26-0002_1.jpg', '一般', '否', '否', '否', '否', '否', '供应商', '立邦经销商', '2026-09-14 15:00', 0.88, '示例：退换正确色号，到货后由助理核对色卡', '', '李助理', '待复核', 0, '', '', '', '']
      ]
    });
    await wb.xlsx.writeFile(path.join(OUT, '02_施工问题台账.xlsx'));
  }

  // ============ 3. 供应商与任务 ============
  {
    const wb = new ExcelJS.Workbook();
    addReadme(wb, '供应商与任务（供应商跟进链主表）', [
      '【用途】供应商主数据 + 每个采购/材料任务的跟踪 + 月度评分。',
      '【任务编号规则】GT-26-0001 起逐年累加。',
      '【状态流转】询价中→已报价→已下单→生产中→已发货→已到货→已安装→（整改中）→已完成；任意状态逾期/升级后整改完回到原状态。',
      '【自动提醒】要求交付日前 3 天提醒责任人；逾期 1 天催办；逾期 3 天或累计 2 次升级老板（附供应商历史数据卡）。',
      '【必须老板审批】报价较上次浮动超±10%、更换材料品牌、索赔/退款、延期影响合同工期节点。',
      '【月度评分】"月度评分"表 E 列准时交付率为公式自动计算；C/D 两列由 n8n 每月 1 日从任务表汇总写入（快速版手工填）。'
    ]);
    buildDataSheet(wb, {
      name: '供应商库',
      columns: [
        ['供应商名称', 20], ['类别', 12], ['联系人', 10], ['联系方式', 16], ['服务区域', 12],
        ['常规交付周期(天)', 15], ['询价响应速度', 13], ['价格等级', 10], ['质量评分(1-5)', 12],
        ['配合度评分(1-5)', 14], ['准时交付率', 11], ['历史逾期次数', 12], ['历史质量问题', 24],
        ['售后响应时间', 12], ['适合项目类型', 18], ['是否推荐继续合作', 15], ['最近评估日期', 12], ['备注', 20]
      ],
      lists: {
        B: '水电,瓦工,木工,油漆,定制家具,灯具照明,洁具,地板,瓷砖,涂料,空调机电,消防,软装,门窗,五金,其他',
        E: '杭州,宁波,温州,全国',
        H: '低,中,高',
        P: '推荐,观察,不推荐'
      },
      numFmt: { F: '0', K: PCT, L: '0', Q: DATE },
      sample: [
        ['示例：某某定制家具厂', '定制家具', '陈经理', '139xxxx1111', '杭州', 25, '快', '中', 4.5, 4, 0.9, 1, '示例：2026-05 一次板色差，已换货', '48小时', '企业空间,办公', '推荐', '2026-08-01', '图片'],
        ['示例：某某机电公司', '空调机电', '刘工', '137xxxx2222', '杭州,宁波', 30, '中', '高', 4, 3.5, 0.82, 3, '示例：两次图纸确认拖延', '72小时', '企业空间,餐饮', '观察', '2026-08-01', '报价偏高但质量稳定']
      ]
    });
    buildDataSheet(wb, {
      name: '供应商任务',
      rows: 300,
      columns: [
        ['任务编号', 12], ['项目编号', 12], ['供应商名称', 20], ['任务类型', 10], ['材料/服务内容', 28],
        ['数量与规格', 24], ['要求交付日期', 13], ['责任人', 10], ['状态', 10], ['预计完成日期', 13],
        ['实际完成日期', 13], ['逾期次数', 9], ['最近跟进日期', 13], ['最近跟进摘要', 30],
        ['报价金额', 12], ['较上次报价±%', 13], ['是否需老板审批', 13], ['备注', 20]
      ],
      lists: {
        D: '询价,打样,排产,发货,安装,整改,其他',
        I: '询价中,已报价,已下单,生产中,已发货,已到货,已安装,整改中,已完成,已取消,逾期,已升级',
        Q: '是,否'
      },
      numFmt: { G: DATE, J: DATE, K: DATE, L: '0', M: DATE, O: MONEY, P: '0%' },
      sample: [
        ['GT-26-0001', 'HZ-26-001', '示例：某某定制家具厂', '排产', '前台形象墙木饰面+背景柜体', '详见深化图纸 CAD-v3 第12页', '2026-09-25', '李助理', '生产中', '2026-09-25', '', 0, '2026-09-08', '示例：厂家确认9月10日进场复尺，复尺后3天下单', 186000, 0.03, '否', ''],
        ['GT-26-0002', 'HZ-26-001', '示例：某某机电公司', '发货', '多联机室内机+风口', '12台风盘管+风口26个', '2026-09-12', '李助理', '逾期', '2026-09-12', '', 1, '2026-09-09', '示例：厂家回复物流延误，预计9月11日发出', 96000, 0, '否', '逾期第1天已催办']
      ]
    });
    buildDataSheet(wb, {
      name: '月度评分',
      columns: [
        ['供应商', 20], ['月份', 10], ['任务总数', 10], ['按期完成数', 12],
        ['准时交付率', 12], ['质量评分均分', 13], ['配合度评分均分', 14], ['综合评级', 10]
      ],
      numFmt: { B: '@', C: '0', D: '0', E: PCT, F: '0.0', G: '0.0' },
      formulas: {
        E: '=IFERROR(D{r}/C{r},"")',
        H: '=IF(E{r}="","",IF(E{r}>=0.9,"A",IF(E{r}>=0.75,"B","C")))'
      },
      sample: [['示例：某某定制家具厂', '2026-08', 4, 4, '', 4.5, 4, '']]
    });
    await wb.xlsx.writeFile(path.join(OUT, '03_供应商与任务.xlsx'));
  }

  // ============ 4. 材料与价格库 ============
  {
    const wb = new ExcelJS.Workbook();
    addReadme(wb, '材料与价格库（报价标准化链数据源）', [
      '【用途】材料主数据 + 成本/销售价 + 供应商比价。报价模板的单价一律从本库引用，不允许凭记忆填价。',
      '【材料编号规则】CL-0001 起累加。',
      '【毛利率】J 列为公式（销售价-成本价)/销售价，自动计算，勿手改。',
      '【维护】材料入库时必填：类别、名称、单位、成本价、销售价、更新时间；品牌型号规格尽量齐全。',
      '【比价】供应商1/2 报价用于成本核对；差价超 10% 时在备注标记并同步供应商价格表。',
      '【安全】成本价列涉及商业机密，本文件仅老板和报价责任人可编辑；同步到数据库后按权限隔离。'
    ]);
    buildDataSheet(wb, {
      name: '材料库',
      rows: 300,
      columns: [
        ['材料编号', 11], ['类别', 12], ['材料名称', 22], ['品牌', 12], ['型号', 14], ['规格', 20],
        ['单位', 8], ['成本价', 11], ['销售价', 11], ['毛利率', 10], ['适用项目类型', 16],
        ['更新时间', 12], ['更新人', 9], ['供应商1', 16], ['供应商1报价', 12], ['供应商2', 16],
        ['供应商2报价', 12], ['备注', 20]
      ],
      lists: {
        B: '水电,瓦工,木工,油漆,定制家具,灯具照明,洁具,地板,瓷砖,涂料,空调机电,消防,软装,门窗,五金,其他',
        K: '企业空间,办公,住宅,别墅,餐饮,酒店,通用'
      },
      numFmt: { H: MONEY, I: MONEY, J: PCT, L: DATE, O: MONEY, Q: MONEY },
      formulas: { J: '=IFERROR((I{r}-H{r})/I{r},"")' },
      sample: [
        ['CL-0001', '地板', '示例：多层实木复合地板', '圣象', 'NK0007', '12mm 锁扣', '㎡', 85, 128, '', '通用', '2026-09-01', '老板', '杭州某某建材', 82, '宁波某某建材', 88, ''],
        ['CL-0002', '涂料', '示例：乳胶漆（哑光）', '立邦', '抗甲醛五合一', '18L 桶装', '桶', 260, 420, '', '通用', '2026-09-01', '老板', '立邦经销商A', 255, '', 0, '含调色'],
        ['CL-0003', '灯具照明', '示例：磁吸轨道灯', '西顿', 'CD-12', '12W 3000K', '套', 68, 115, '', '企业空间,办公', '2026-09-01', '老板', '某某照明', 65, '', 0, '']
      ]
    });
    buildDataSheet(wb, {
      name: '供应商价格表',
      rows: 300,
      columns: [
        ['供应商', 20], ['材料/服务', 24], ['区域', 10], ['报价', 12], ['报价日期', 12],
        ['交付周期(天)', 13], ['历史最低价', 12], ['备注', 24]
      ],
      numFmt: { D: MONEY, E: DATE, F: '0', G: MONEY },
      sample: [['示例：杭州某某建材', '多层实木复合地板 12mm', '杭州', 82, '2026-09-01', 7, 80, '满50㎡免运费']]
    });
    await wb.xlsx.writeFile(path.join(OUT, '04_材料与价格库.xlsx'));
  }

  // ============ 5. 报价模板_企业空间 ============
  {
    const wb = new ExcelJS.Workbook();
    const ws = addReadme(wb, '报价模板·企业空间（报价标准化链）', [
      '【铁律】所有金额由公式计算，禁止在公式列手工输入数字；AI 只生成清单草案、查漏、解释，不填价格。',
      '【使用步骤】① 复制本表为新文件，命名"项目编号-Qxx"；② 填第1-2行项目信息；③ 从工程项目库/材料库填入项目、规格、单价（库里没有→标"待询价"并转供应商链）；④ 填数量与损耗；⑤ 公式自动算合价与汇总；⑥ 触发 AI 检查（漏项/重复/异常单价）；⑦ 老板签发后定版归档。',
      '【公式列】J综合单价=人工+材料；K合价=数量×(1+损耗)×综合单价；汇总区全部公式。工作表已开启保护（密码 2026），只开放输入单元格。',
      '【毛利率红线】汇总区毛利率低于 25% 自动标红，签发前必须老板书面确认。',
      '【示例行】黄色底纹两行为示例，正式使用前删除。',
      '【检查清单】见"检查清单"工作表：13 个分部逐一比对，防止漏项。',
      '【损耗默认值】地板/瓷砖 3%~5%，板材 5%~8%，壁纸 10%，按工艺调整。'
    ]);
    const q = wb.addWorksheet('报价单', { views: [{ state: 'frozen', ySplit: 3 }] });
    q.columns = [
      { width: 6 }, { width: 14 }, { width: 26 }, { width: 26 }, { width: 8 },
      { width: 10 }, { width: 9 }, { width: 11 }, { width: 11 }, { width: 11 }, { width: 14 }, { width: 22 }
    ];
    // 头部信息
    q.getCell('A1').value = '项目编号:'; q.getCell('B1').value = 'HZ-26-001';
    q.getCell('D1').value = '项目名称:'; q.getCell('E1').value = '示例：杭州某科技办公室';
    q.getCell('G1').value = '报价版本:'; q.getCell('H1').value = 'Q01';
    q.getCell('J1').value = '日期:'; q.getCell('K1').value = '2026-09-09';
    q.getCell('A2').value = '客户:'; q.getCell('B2').value = '示例：杭州某某科技有限公司';
    q.getCell('D2').value = '编制人:'; q.getCell('E2').value = '';
    q.getCell('G2').value = '报价说明:'; q.getCell('H2').value = '含项/不含项边界见报价说明页（AI 生成后人工确认）';
    [1, 2].forEach(r => { for (let i = 1; i <= 12; i++) q.getRow(r).getCell(i).border = BORDER; });
    // 表头
    const headers = ['序号', '分部', '工程项目/材料名称', '品牌/型号/规格', '单位', '数量', '损耗%', '人工单价', '材料单价', '综合单价', '合价', '备注'];
    headers.forEach((h, i) => { const c = q.getRow(3).getCell(i + 1); c.value = h; headerStyle(c); });
    q.getRow(3).height = 24;
    // 明细行 4..63
    const items = [
      ['【示例】隔墙', '轻钢龙骨石膏板隔墙', '75型轻钢龙骨/12mm石膏板双面', '㎡', 120, 0.05, 45, 38, '隔音棉填充'],
      ['【示例】地面', '多层实木复合地板', '圣象 NK0007 12mm锁扣', '㎡', 200, 0.03, 20, 85, '材料库CL-0001']
    ];
    for (let r = 4; r <= 63; r++) {
      q.getCell(`A${r}`).value = r - 3;
      const idx = r - 4;
      if (idx < items.length) {
        const it = items[idx];
        q.getCell(`B${r}`).value = it[0]; q.getCell(`C${r}`).value = it[1]; q.getCell(`D${r}`).value = it[2];
        q.getCell(`E${r}`).value = it[3]; q.getCell(`F${r}`).value = it[4]; q.getCell(`G${r}`).value = it[5];
        q.getCell(`H${r}`).value = it[6]; q.getCell(`I${r}`).value = it[7]; q.getCell(`L${r}`).value = it[8];
        for (let i = 1; i <= 12; i++) q.getRow(r).getCell(i).fill = { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFF2CC' } };
      }
      q.getCell(`J${r}`).value = `=IF(COUNT(H${r}:I${r})=0,"",N(H${r})+N(I${r}))`;
      q.getCell(`K${r}`).value = `=IF(OR(F${r}="",J${r}=""),"",ROUND(F${r}*(1+N(G${r}))*J${r},2))`;
      for (let i = 1; i <= 12; i++) { const c = q.getRow(r).getCell(i); c.border = BORDER; c.alignment = { vertical: 'center' }; }
      q.getCell(`F${r}`).numFmt = '#,##0.##'; q.getCell(`G${r}`).numFmt = '0.0%';
      ['H', 'I', 'J', 'K'].forEach(col => { q.getCell(`${col}${r}`).numFmt = MONEY; });
      // 分部下拉
      q.getCell(`B${r}`).dataValidation = { type: 'list', allowBlank: true, formulae: ['"拆除与保护,隔墙,水电,地面,墙面,天花,门窗,家具定制,灯具照明,五金洁具,空调消防配合,软装配饰,垃圾清运,其他"'], errorStyle: 'warning', error: '请按分部选择' };
    }
    // 汇总区
    const S = 64;
    q.getCell(`A${S}`).value = '工程直接成本合计'; q.getCell(`K${S}`).value = '=SUM(K4:K63)';
    const summary = [
      ['管理费（直接成本×5%，可调）', '=ROUND(K64*0.05,2)', false],
      ['税金/其他（选填）', 0, true],
      ['设计费', 0, true],
      ['报价合计', '=K64+K66+K67+K68', false],
      ['预计成本（人工+材料+分包实际成本）', 0, true],
      ['预计毛利', '=IF(K69=0,"",K69-K70)', false],
      ['毛利率（红线25%）', '=IFERROR(K71/K69,"")', false]
    ];
    summary.forEach((s, i) => {
      const r = 66 + i;
      q.getCell(`B${r}`).value = s[0];
      q.getCell(`K${r}`).value = s[1];
      q.getCell(`B${r}`).font = { bold: true };
      q.getCell(`K${r}`).numFmt = r === 72 ? '0.0%' : MONEY;
      for (let c2 = 1; c2 <= 12; c2++) q.getRow(r).getCell(c2).border = BORDER;
    });
    q.getCell('K69').font = { bold: true, size: 12, color: { argb: 'FF1F4E79' } };
    q.addConditionalFormatting({
      ref: 'K72',
      rules: [{ type: 'cellIs', operator: 'lessThan', formulae: ['0.25'], style: { font: { color: { argb: 'FFFF0000' }, bold: true }, fill: { type: 'pattern', pattern: 'solid', fgColor: { argb: 'FFFFC7CE' } } } }]
    });
    // 保护：开放输入区
    for (let r = 1; r <= 2; r++) for (let i = 1; i <= 12; i++) q.getRow(r).getCell(i).protection = { locked: false };
    for (let r = 4; r <= 63; r++) ['B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'L'].forEach(col => { q.getCell(`${col}${r}`).protection = { locked: false }; });
    [67, 68, 70].forEach(r => { q.getCell(`K${r}`).protection = { locked: false }; });
    await q.protect('2026', { selectLockedCells: true, selectUnlockedCells: true });
    // 检查清单
    const ck = wb.addWorksheet('检查清单');
    ck.columns = [{ width: 8 }, { width: 20 }, { width: 70 }, { width: 12 }];
    const ckHeaders = ['序号', '分部', '检查要点（对照报价单，防止漏项）', '是否包含'];
    ckHeaders.forEach((h, i) => headerStyle(ck.getRow(1).getCell(i + 1)));
    const checks = [
      ['拆除与保护', '原装修拆除、成品保护、垃圾清运是否单列；拆除范围与现场是否一致'],
      ['隔墙', '轻钢龙骨/钢化玻璃/实体隔墙；隔音、防火要求；门洞加固'],
      ['水电', '强电、弱电、给排水、开关插座点位；水电是否按实结算已写明'],
      ['地面', '不同区域地面材质（地砖/地板/地毯/自流平）；找平与损耗'],
      ['墙面', '乳胶漆/壁纸/木饰面/硬包/造型墙；基层处理'],
      ['天花', '吊顶造型/矿棉板/石膏板/格栅灯位；检修口'],
      ['门窗', '门、门套、五金、玻璃隔断门；防火门要求'],
      ['家具定制', '前台、柜体、会议桌、工位家具；是否甲供'],
      ['灯具照明', '主照明/氛围照明/轨道射灯；智能控制'],
      ['五金洁具', '茶水间、卫生间洁具、五金挂件'],
      ['空调消防配合', '空调改造、新风、喷淋烟感移位、消防报审配合费用'],
      ['软装配饰', '绿植、挂画、logo墙、窗帘'],
      ['垃圾清运及其他', '清运费、管理费、税金、保险、不可预见费（建议3%~5%）']
    ];
    checks.forEach((c, i) => {
      ck.getRow(i + 2).getCell(1).value = i + 1;
      ck.getRow(i + 2).getCell(2).value = c[0];
      ck.getRow(i + 2).getCell(3).value = c[1];
      ck.getRow(i + 2).getCell(4).dataValidation = { type: 'list', allowBlank: true, formulae: ['"包含,不包含,不适用"'] };
      for (let j = 1; j <= 4; j++) ck.getRow(i + 2).getCell(j).border = BORDER;
    });
    await wb.xlsx.writeFile(path.join(OUT, '05_报价模板_企业空间.xlsx'));
  }

  // ============ 6. 报价版本与利润表 ============
  {
    const wb = new ExcelJS.Workbook();
    addReadme(wb, '报价版本与利润表', [
      '【版本登记】每次对外报价生成一条记录，版本号 Q01/Q02 递增；旧版本确认后锁定只读，只增不改。',
      '【审批状态】草稿→待审批（推送老板）→已确认（签发）→已作废；只有"已确认"版本可以发给客户。',
      '【项目利润】收入/成本由公式汇总；"预计"在签约时填，"实际"在项目归档复盘时填；毛利率自动计算。',
      '【纪律】复盘时预计与实际差异超 10% 的项目必须写原因，进入复盘报告。'
    ]);
    buildDataSheet(wb, {
      name: '版本登记',
      rows: 100,
      columns: [
        ['版本编号', 16], ['项目编号', 12], ['报价版本', 10], ['版本日期', 12], ['编制人', 10],
        ['报价合计', 13], ['审批状态', 10], ['审批人', 10], ['审批日期', 12], ['审批意见', 30],
        ['NAS归档路径', 34], ['备注', 18]
      ],
      lists: { G: '草稿,待审批,已确认,已作废' },
      numFmt: { D: DATE, F: MONEY, I: DATE },
      sample: [['HZ-26-001-Q01', 'HZ-26-001', 'Q01', '2026-09-05', '报价助理', 1720000, '已确认', '老板', '2026-09-06', '示例：调整了家具档位后签发', '室内设计公司/HZ-26-001_××科技/06_报价与合同/HZ-26-001-Q01-20260905.xlsx', '']]
    });
    buildDataSheet(wb, {
      name: '项目利润',
      columns: [
        ['项目编号', 12], ['项目名称', 24], ['设计收入', 13], ['施工收入', 13], ['收入合计', 13],
        ['设计成本', 12], ['施工成本', 12], ['成本合计', 12], ['预计毛利', 13], ['毛利率', 10],
        ['已发生成本', 12], ['实际毛利', 13], ['备注', 26]
      ],
      numFmt: { C: MONEY, D: MONEY, E: MONEY, F: MONEY, G: MONEY, H: MONEY, I: MONEY, J: PCT, K: MONEY, L: MONEY },
      formulas: {
        E: '=IF(COUNT(C{r}:D{r})=0,"",SUM(C{r}:D{r}))',
        H: '=IF(COUNT(F{r}:G{r})=0,"",SUM(F{r}:G{r}))',
        I: '=IF(OR(E{r}="",H{r}=""),"",E{r}-H{r})',
        J: '=IFERROR(I{r}/E{r},"")',
        L: '=IF(E{r}="","",E{r}-N(K{r}))'
      },
      sample: [['HZ-26-001', '示例：杭州某科技办公室', 120000, 1500000, '', 48000, 1200000, '', '', '', 980000, '', '示例数据']]
    });
    await wb.xlsx.writeFile(path.join(OUT, '06_报价版本与利润表.xlsx'));
  }

  console.log('ALL 6 WORKBOOKS GENERATED OK');
}

main().catch(e => { console.error(e); process.exit(1); });
