"""Versioned, sourced notes on how real designers organise an exhibition plan.

These are *method references*, not geometry templates. They were distilled from
publicly available floor plans, textbooks, a national standard and a peer
reviewed study (see SOURCES). They are used only to brief the real design model
and to explain the drawing conventions; the program never derives a layout
from them, never copies any drawing, and never treats empirical numbers as
code compliance.
"""
from __future__ import annotations

from typing import Any

REFERENCE_VERSION = "rkd-design-reference.v1"
RESEARCH_DATE = "2026-11-10"

SOURCES: list[dict[str, str]] = [
    {"id": "std-wwt0089", "title": "WW/T 0089-2018 博物馆陈列展览形式设计与施工规范",
     "kind": "national_standard",
     "note": "观众通道最窄 ≥2.4m；常规沿顺时针展开；避免回头路与交叉路线；人流、物流、消防疏散分流；概念设计阶段即应设计流线。"},
    {"id": "book-museum-story", "title": "《博物馆设计：故事、语调及其他》参观线路类型",
     "kind": "book",
     "note": "肠形（单线叙事）、一眼瞧见再看一遍（回到起点重看核心）、弹球形（自由比较）、中心英雄式（明星展品居中）。先决定故事怎么读，再决定平面图形。"},
    {"id": "book-display-design", "title": "《展示设计》（人民邮电出版社，单宁）平面布局与流线设计",
     "kind": "textbook",
     "note": "串联 / 放射 / 串联兼通道 / 走道 / 大厅 / 混合六类；动线要求清晰、有序、便捷、灵活；成果分平面布局图、功能分区图、动线图三层表达。"},
    {"id": "case-jintangjiang-300", "title": "金堂奖「往来无白」300㎡ 玻璃制品展厅一层/二层平面布局图",
     "kind": "published_floor_plan", "url": "https://www.jintangjiang.cn/v_detail-33079?jwork=1",
     "note": "前端接待介绍—产品展示—深度洽谈三段成环；主入口凹入弧形门斗与橱窗；服务前台配吧椅；两间洽谈室画真实桌椅；茶水间、储藏、办公室、楼梯「上19步」、标高 +0.160、绿植、片墙与弧形展具；粗黑墙体、地面材质填充、中英文图注。"},
    {"id": "case-shejiben-560", "title": "设计本「开物营造丨重构—宽驰大家居新展厅」560㎡ 平面布置图/轴测图",
     "kind": "published_floor_plan", "url": "https://m.shejiben.com/sjs/8523819/case-4025092-1.html",
     "note": "入口展示区 / 中心洽谈区 / 产品陈列区三区；玻璃砖圆厅与方厅两个入口概念；插入体块与隔断形成独立小场景；洽谈与物料选样结合置于中心；西侧景观内庭；明确反对大仓库式平铺陈列。"},
    {"id": "case-600-bio", "title": "600㎡ 生物科技企业展厅「一轴四区」公开案例",
     "kind": "case_study", "url": "https://www.xskup.com/index.php/news/7396",
     "note": "前厅形象区 80㎡（LED 屏/发光 LOGO/时间轴/荣誉）→ 核心展示区 300㎡ → 商务洽谈区 100㎡（雾化玻璃、半私密桌、茶水）→ 多功能路演厅 120㎡；一条视觉主轴兼作动线引导。"},
    {"id": "case-misumi", "title": "MiSUMi & Fictiv 广州企业展厅单向叙事动线",
     "kind": "case_study", "url": "https://www.kamleuk.com/?p=23151",
     "note": "品牌形象序厅（圆形发光 LOGO 形象墙 + LED 主屏）→ 全球供应链数字展区 → 标准件实物展区 → 定制工艺样品 → 企业文化走廊 → 商务洽谈；少展板多交互，色彩软性分区代替厚重隔墙。"},
    {"id": "guide-rhythm", "title": "展厅平面布局的动线逻辑与功能分区（华文创意展览）",
     "kind": "industry_guide", "url": "https://www.hw-sheji.com/1009.html",
     "note": "展陈面积:通行面积紧凑型约 6:4；开场在入口五步内、高潮在动线约三分之二处、收束近出口；密—疏—密；休息节点视线朝向下一展区预告；大件展项逐项核实退距。"},
    {"id": "guide-scale", "title": "展厅空间布局细节大全（维钊展览）",
     "kind": "industry_guide", "url": "https://www.vzhaomice.com/app-cms/newsdetail.html?id=620909845",
     "note": "主通道 ≥2.0m、次通道 ≥1.2m、拐角不低于 1.0m；核心展区之间预留 5–8㎡ 缓冲留白；入口开阔无遮挡、出口独立避免进出交叉；预判拥堵点。"},
    {"id": "paper-foar-2025", "title": "Frontiers of Architectural Research 2025: Natural movement / museum layout visibility graph analysis",
     "kind": "peer_reviewed", "url": "https://journal.hep.com.cn/foar/EN/pdf/10.1016/j.foar.2025.03.001",
     "note": "组合式（环形 + L 形）布局在平均深度与视觉整合度上表现最好；开敞廊道有利人流分散，复杂迂回转折切碎流线并增加认知负荷；广东省博物馆整合度 0.917、南通博物院 0.813。"},
    {"id": "case-nanjing-museum", "title": "有方：南京博物院二期 / 程泰宁·筑境设计",
     "kind": "case_study", "url": "https://www.archiposition.com/items/20180525120741",
     "note": "200m 地下通廊 + 4 个下沉庭院 + 12 个采光中庭串联多馆，用中庭打断冗长观览流线，让观众在节点重新选择。"},
    {"id": "case-guangdong-museum", "title": "广东省博物馆参观路线与双环结构资料",
     "kind": "case_study", "url": "https://gz.bendibao.com/tour/2021426/ly292816.shtml",
     "note": "同一组展厅通过调整起点与次序服务不同停留时长；首都博物馆/珠海市博物馆双环开放式动线适合知识点相对独立的内容。"},
]

PATTERNS: list[dict[str, Any]] = [
    {"pattern_id": "narrative-loop", "name": "前厅叙事环游", "topology": "loop",
     "sequence": ["入口门斗/前厅", "品牌形象墙", "主展中岛", "分区展墙", "深度洽谈", "收束/出口"],
     "use_when": "企业品牌馆、需要完整讲一遍故事、入口出口相邻", "cost": "中央区域需处理成视觉焦点，不能留空心"},
    {"pattern_id": "central-hub", "name": "中心枢纽 + 分支口袋", "topology": "branch",
     "sequence": ["序厅枢纽", "主题展区 A", "主题展区 B", "半私密洽谈", "服务后勤"],
     "use_when": "多主题并行、观众需按兴趣选择、洽谈要相对独立", "cost": "枢纽要宽敞，分支入口需清晰引导"},
    {"pattern_id": "linear-story", "name": "单线叙事 + 快捷通道", "topology": "branch",
     "sequence": ["序厅", "递进一", "递进二", "高潮（约 2/3 处）", "缓冲留白", "收束与洽谈"],
     "use_when": "时间线/工艺流程/发展史", "cost": "必须给赶时间的访客一条快速通过路径"},
    {"pattern_id": "hero-island", "name": "中心英雄 + 自由散点", "topology": "loop",
     "sequence": ["入口视觉通廊", "中心明星展项", "环绕展岛", "侧向洽谈凹室"],
     "use_when": "有一件核心产品或主展台要被第一眼看到", "cost": "无强制路线时靠视觉焦点与灯光引导"},
]

PRINCIPLES: list[str] = [
    "先写一句话主题与内容序列，再选拓扑原型，最后才画动线与几何；不要先摆通道再塞内容。",
    "功能有层级：入口门斗/前厅形象 → 主展示（核心展项、中岛、展墙）→ 深度转化（洽谈、选样、茶水）→ 收束/出口；另需服务台、储藏、后勤与缓冲留白，不能只有三个并排矩形。",
    "节奏：开场在入口五步内，高潮在动线约三分之二处，收束近出口；密—疏—密，核心展区之间留 5–8㎡ 缓冲；休息节点视线朝向下一展区预告。",
    "视觉焦点：形象墙、中心主展台或景观内庭至少一处；避免从入口一眼看穿到出口；用片墙、门洞、弧形展墙、隔断和高低差软划分，而不是硬切矩形。",
    "主展陈面放主动线，辅展陈面放次动线；主通道行业常见 ≥2.0m（规范底线 2.4m，本项目不宣称合规），次通道 ≥1.2m；避免回头路、交叉路线和无意义的曲折。",
    "真实图纸用粗实线画墙与结构、中实线画展具与区域边界、细实线画尺寸；家具与展具画真实轮廓（桌椅、前台、中岛、绿植、楼梯），标注中英文名称、尺寸、标高、比例与图例。",
    "常见错误：只排展项不排路径、核心展项放在偏僻角落、直通流线无节奏、内凹过多导致空间零碎、忽略团队接待与后勤、把洽谈区做成另一个空矩形。",
]

DRAWING_CONVENTIONS: list[str] = [
    "图框与标题栏：项目名、图名、比例、版本、日期、状态；概念平面必须标注「非施工图」。",
    "墙体用粗实线并表达厚度；门洞断开墙线并画门扇开启弧线；入口加中英文标注。",
    "地面材质用浅色填充或规律斜线区分，不同功能区不用高饱和色块。",
    "动线用淡灰通道 + 虚线箭头表达方向与顺序，区分主次。",
    "功能区标注中文名 + 英文小字 + 面积；家具与展具用轮廓而非文字占位。",
    "外框标注总尺寸，关键节点标注局部尺寸或标高；右下角图例说明线型与符号。",
]


def prompt_brief() -> str:
    """Compact, source-tagged briefing injected into the real model's prompt."""
    lines = [f"真实设计参考（{REFERENCE_VERSION}，{RESEARCH_DATE} 研究；仅学方法，不复制图纸、不替代规范复核）：",
             "工作顺序：" + " → ".join(["一句话主题与内容序列", "选拓扑原型", "排功能层级与节奏", "落平面几何", "图纸表达与走查校验"]),
             "可选原型（按叙事选，不要固定套用）："]
    lines += [f"- {item['pattern_id']}｜{item['name']}｜序列：{' → '.join(item['sequence'])}｜适用：{item['use_when']}｜代价：{item['cost']}"
              for item in PATTERNS]
    lines.append("必须遵守的布局原则：")
    lines += [f"{index + 1}. {text}" for index, text in enumerate(PRINCIPLES)]
    lines.append("图纸表达要求：" + "；".join(DRAWING_CONVENTIONS[:4]))
    lines.append("来源（本地研究摘要，不外发）：" + "；".join(item["id"] for item in SOURCES))
    return "\n".join(lines)


def public() -> dict[str, Any]:
    return {"reference_version": REFERENCE_VERSION, "research_date": RESEARCH_DATE,
            "source_count": len(SOURCES), "sources": [dict(item) for item in SOURCES],
            "pattern_ids": [item["pattern_id"] for item in PATTERNS],
            "principle_count": len(PRINCIPLES),
            "boundary": "layout method reference only; no drawing copied, no code compliance claimed"}
