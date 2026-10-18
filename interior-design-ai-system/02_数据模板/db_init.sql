-- ============================================================
-- 室内设计公司 AI 工作链系统 · PostgreSQL 建表脚本 V1.0
-- 用法：psql -U postgres -f db_init.sql
-- 说明：字段与 00_数据字典.md、Excel 模板一一对应。
--       枚举与业务规则见 01_诊断与流程/03_三大工作链节点设计.md
-- ============================================================

BEGIN;

-- 枚举类型（与数据字典 2 节一致）
DO $$ BEGIN
  CREATE TYPE project_stage   AS ENUM ('线索','量房','初步方案','报价','签约','深化设计','施工图','采购','施工','验收','售后','归档');
  CREATE TYPE project_status  AS ENUM ('进行中','暂停','已完成','已取消','已流失');
  CREATE TYPE issue_type      AS ENUM ('尺寸','材料','工艺','质量','进度','安全','图纸','客户变更','其他');
  CREATE TYPE severity        AS ENUM ('一般','重要','紧急');
  CREATE TYPE responsible_party AS ENUM ('施工方','供应商','设计方','客户','物业');
  CREATE TYPE issue_status    AS ENUM ('待整理','待处理','处理中','待复核','已升级','已关闭');
  CREATE TYPE stask_status    AS ENUM ('询价中','已报价','已下单','生产中','已发货','已到货','已安装','整改中','已完成','已取消','逾期','已升级');
  CREATE TYPE stask_type      AS ENUM ('询价','打样','排产','发货','安装','整改','其他');
  CREATE TYPE supplier_cat    AS ENUM ('水电','瓦工','木工','油漆','定制家具','灯具照明','洁具','地板','瓷砖','涂料','空调机电','消防','软装','门窗','五金','其他');
  CREATE TYPE contract_mode   AS ENUM ('设计费','设计费+施工管理费','设计施工一体化','全包');
  CREATE TYPE quote_status    AS ENUM ('草稿','待审批','已确认','已作废');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ---------- 客户 ----------
CREATE TABLE IF NOT EXISTS customers (
  customer_no    varchar(16) PRIMARY KEY,          -- KH-26-001
  name           varchar(64) NOT NULL,
  customer_type  varchar(16),                      -- 企业/住宅业主/开发商/其他
  phone          varchar(32),
  wechat         varchar(64),
  source         varchar(16),                      -- 朋友介绍/老客户介绍/其他
  demand_summary text,
  budget_range   varchar(32),
  intent_level   varchar(4),                       -- 高/中/低
  reg_date       date DEFAULT CURRENT_DATE,
  last_contact   date,
  follow_status  varchar(8),                       -- 洽谈中/已报价/已签约/已流失/已完成
  owner          varchar(16)
);

-- ---------- 项目 ----------
CREATE TABLE IF NOT EXISTS projects (
  project_no      varchar(16) PRIMARY KEY,         -- HZ-26-001
  name            varchar(96) NOT NULL,
  customer_no     varchar(16) REFERENCES customers(customer_no),
  project_type    varchar(16),
  city            varchar(8),
  address         varchar(128),
  area_sqm        numeric(9,1),
  contract_mode   contract_mode,
  design_amount   numeric(12,2),
  construction_amount numeric(12,2),
  stage           project_stage DEFAULT '线索',
  status          project_status DEFAULT '进行中',
  start_date      date,
  planned_delivery date,
  actual_delivery date,
  lead_designer   varchar(16),
  procurement_owner varchar(16),
  -- 企业空间附加字段
  corp_position   varchar(128),                    -- 企业名称与定位
  headcount       int,
  dept_functions  text,                            -- 部门与空间功能
  circulation_req text,                            -- 动线要求
  external_constraints text,                       -- 房东/物业/消防限制
  decision_maker  varchar(32),
  expected_opening date,
  total_budget    numeric(12,2),
  procurement_progress numeric(5,4),               -- 0~1
  remark          text
);
COMMENT ON TABLE projects IS '项目主表；阶段只能按状态机顺序推进（见02_企业空间项目标准流程与状态机.md）';

-- ---------- 施工问题 ----------
CREATE TABLE IF NOT EXISTS issues (
  issue_no        varchar(16) PRIMARY KEY,         -- WT-26-0001
  project_no      varchar(16) REFERENCES projects(project_no),
  address         varchar(128),
  found_at        timestamp NOT NULL,
  found_by        varchar(16),
  source          varchar(12),                     -- 钉钉表单/微信转填/口头转填
  issue_type      issue_type,
  raw_description text NOT NULL,                   -- 原始描述，永不覆盖
  photos          text[],
  severity        severity,
  affects_design  boolean,
  affects_cost    boolean,
  affects_schedule boolean,
  needs_drawing_change boolean,
  needs_boss_approval boolean,                     -- 紧急 或 重要且任一影响=是
  responsible_party responsible_party,
  assignee        varchar(16),
  deadline        timestamp,                       -- 默认：紧急+24h/重要+3d/一般+7d
  ai_confidence   numeric(3,2),                    -- AI 整理置信度 <0.7 待人工确认
  solution        text,
  rectification_photos text[],
  reviewer        varchar(16),
  status          issue_status DEFAULT '待处理',
  overdue_count   int DEFAULT 0,
  closed_at       timestamp,
  related_quote_ver varchar(24),
  related_drawing_ver varchar(24),
  remark          text
);
COMMENT ON COLUMN issues.raw_description IS '现场原始描述；AI 整理结果写入 solution 前的标准描述由应用层维护，原文字段禁止覆盖';

-- ---------- 供应商 ----------
CREATE TABLE IF NOT EXISTS suppliers (
  name            varchar(64) PRIMARY KEY,
  category        supplier_cat,
  contact         varchar(16),
  phone           varchar(32),
  region          varchar(32),
  lead_time_days  int,
  response_speed  varchar(4),                      -- 快/中/慢
  price_level     varchar(4),                      -- 低/中/高
  quality_score   numeric(2,1),
  cooperation_score numeric(2,1),
  ontime_rate     numeric(4,3),                    -- 公式列：每月由任务表汇总更新
  overdue_total   int DEFAULT 0,
  quality_issues_history text,
  aftersales_sla  varchar(16),
  suitable_project_types text,
  recommended     varchar(4),                      -- 推荐/观察/不推荐
  last_review_date date,
  remark          text
);

-- ---------- 供应商任务 ----------
CREATE TABLE IF NOT EXISTS supplier_tasks (
  task_no         varchar(16) PRIMARY KEY,         -- GT-26-0001
  project_no      varchar(16) REFERENCES projects(project_no),
  supplier_name   varchar(64) REFERENCES suppliers(name),
  task_type       stask_type,
  content         text,
  spec_qty        text,
  required_date   date,
  owner           varchar(16),
  status          stask_status DEFAULT '询价中',
  eta_date        date,
  done_date       date,
  overdue_count   int DEFAULT 0,
  last_followup_at date,
  last_followup_note text,
  quoted_amount   numeric(12,2),
  price_change_pct numeric(5,4),                   -- 较上次报价 ±；|x|>0.10 触发审批
  needs_boss_approval boolean,
  remark          text
);

-- ---------- 材料 ----------
CREATE TABLE IF NOT EXISTS materials (
  material_no     varchar(12) PRIMARY KEY,         -- CL-0001
  category        supplier_cat,
  name            varchar(96),
  brand           varchar(32),
  model           varchar(48),
  spec            varchar(96),
  unit            varchar(8),
  cost_price      numeric(12,2),
  sale_price      numeric(12,2),
  suit_types      text,
  updated_at      date DEFAULT CURRENT_DATE,
  updated_by      varchar(16),
  remark          text
);

-- ---------- 供应商价格 ----------
CREATE TABLE IF NOT EXISTS supplier_prices (
  id              serial PRIMARY KEY,
  supplier_name   varchar(64) REFERENCES suppliers(name),
  material_desc   varchar(128),
  region          varchar(16),
  price           numeric(12,2),
  quote_date      date,
  lead_time_days  int,
  lowest_price    numeric(12,2),
  remark          text
);

-- ---------- 报价版本 ----------
CREATE TABLE IF NOT EXISTS quote_versions (
  version_no      varchar(32) PRIMARY KEY,         -- HZ-26-001-Q02
  project_no      varchar(16) REFERENCES projects(project_no),
  version_seq     int NOT NULL,
  version_date    date DEFAULT CURRENT_DATE,
  created_by      varchar(16),
  total_amount    numeric(12,2),
  gross_margin    numeric(5,4),                    -- 毛利率，红线 0.25
  status          quote_status DEFAULT '草稿',
  approver        varchar(16),
  approved_at     timestamp,
  approval_note   text,
  nas_path        varchar(255),
  UNIQUE (project_no, version_seq)
);

-- ---------- 项目利润 ----------
CREATE TABLE IF NOT EXISTS project_profits (
  project_no      varchar(16) PRIMARY KEY REFERENCES projects(project_no),
  design_income   numeric(12,2),
  construction_income numeric(12,2),
  design_cost     numeric(12,2),
  construction_cost numeric(12,2),
  incurred_cost   numeric(12,2),                   -- 已发生成本
  actual_gross_profit numeric(12,2),               -- 归档复盘时核定
  remark          text
);

-- ---------- 审批记录（老板待审批清单数据源） ----------
CREATE TABLE IF NOT EXISTS approvals (
  id              bigserial PRIMARY KEY,
  created_at      timestamp DEFAULT CURRENT_TIMESTAMP,
  source_chain    varchar(12) NOT NULL,            -- issue / supplier / quote
  business_no     varchar(32) NOT NULL,            -- WT-xx / GT-xx / 版本号
  title           varchar(128) NOT NULL,
  detail_json     jsonb,                           -- 结构化数据卡
  requester       varchar(16),
  boss_decision   varchar(8) DEFAULT '待审批',      -- 待审批/同意/驳回
  boss_comment    text,
  decided_at      timestamp,
  notify_status   varchar(12) DEFAULT '已推送'
);

-- ---------- 序号生成（编号规则见数据字典） ----------
CREATE TABLE IF NOT EXISTS seq_counters (
  seq_key   varchar(32) PRIMARY KEY,               -- 如 WT-26 / GT-26 / HZ-26
  seq_value int NOT NULL DEFAULT 0
);
CREATE OR REPLACE FUNCTION next_no(p_key varchar, p_width int DEFAULT 4)
RETURNS varchar AS $$
  UPDATE seq_counters SET seq_value = seq_value + 1 WHERE seq_key = p_key
  RETURNING p_key || '-' || lpad(seq_value::text, p_width, '0');
$$ LANGUAGE sql;

-- ---------- 视图：老板待审批清单 / 逾期任务 ----------
CREATE OR REPLACE VIEW v_boss_approval AS
SELECT id, created_at, source_chain, business_no, title, detail_json
FROM approvals WHERE boss_decision = '待审批' ORDER BY created_at;

CREATE OR REPLACE VIEW v_overdue_issues AS
SELECT issue_no, project_no, severity, assignee, deadline, overdue_count
FROM issues
WHERE status NOT IN ('已关闭','待整理') AND deadline < CURRENT_TIMESTAMP;

CREATE OR REPLACE VIEW v_overdue_tasks AS
SELECT task_no, project_no, supplier_name, task_type, required_date, owner, overdue_count
FROM supplier_tasks
WHERE status NOT IN ('已完成','已取消') AND required_date < CURRENT_DATE;

COMMIT;

-- 初始化序号（示例：2026 年）
INSERT INTO seq_counters(seq_key, seq_value) VALUES
  ('WT-26', 0), ('GT-26', 0), ('KH-26', 0), ('HZ-26', 0), ('NB-26', 0), ('WZ-26', 0)
ON CONFLICT DO NOTHING;
