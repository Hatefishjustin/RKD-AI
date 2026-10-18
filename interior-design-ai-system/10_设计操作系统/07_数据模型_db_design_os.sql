-- ============================================================
-- 设计操作系统（Evidence-Driven AI Design OS）· PostgreSQL DDL V1.0
-- 用法：在已执行 db_init.sql 的库上追加：psql -U design -d design -f db_design_os.sql
-- 对应文档：10_设计操作系统/00~06
-- ============================================================

BEGIN;

CREATE SCHEMA IF NOT EXISTS design_os;
SET search_path TO design_os, public;

-- ---------- 枚举 ----------
DO $$ BEGIN
  CREATE TYPE ev_source  AS ENUM ('CLIENT_DIRECT','CLIENT_REPLY','APPROVED_DOCUMENT','DRAWING','SITE_PHOTO','MEASUREMENT','DESIGNER_INPUT','AI_INFERENCE','AI_ASSUMPTION');
  CREATE TYPE ev_level   AS ENUM ('E0','E1','E2','E3','E4','E5');
  CREATE TYPE cr_state   AS ENUM ('NEW','PARSED','NEEDS_CLARIFICATION','CLARIFIED','IMPACT_ANALYSIS','PROPOSAL','PENDING_APPROVAL','APPROVED','EXECUTING','QA','CUSTOMER_CONFIRMATION','SIGNED','CLOSED','CLOSED_CANCELLED');
  CREATE TYPE cr_route   AS ENUM ('AUTO_EXECUTE','HUMAN_REVIEW');
  CREATE TYPE req_intent AS ENUM ('偏好表达','要求修改','看看效果','投诉','施工反馈','信息提供');
  CREATE TYPE script_lvl AS ENUM ('固定API','已验证脚本','参数化模板','受控生成脚本','AI临时脚本');
  CREATE TYPE gate_stat  AS ENUM ('GENERATED','STATIC_CHECK','SANDBOX_RUN','OUTPUT_VALIDATED','APPROVED','REJECTED');
  CREATE TYPE qa_type    AS ENUM ('DESIGN','DRAWING','GEOMETRY','COST','CONSTRUCTION');
  CREATE TYPE qa_verdict AS ENUM ('PASS','WARNING','HUMAN_REVIEW','FAIL');
  CREATE TYPE render_kind AS ENUM ('确认图','终稿图');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ---------- 证据（append-only） ----------
CREATE TABLE IF NOT EXISTS evidence_objects (
  evidence_id   varchar(20) PRIMARY KEY,          -- EV-26-00001
  project_no    varchar(16) NOT NULL,
  cr_id         varchar(20),
  source_type   ev_source NOT NULL,
  evidence_level ev_level NOT NULL,               -- 就低原则由应用层计算
  content_text  text,
  media_ref     varchar(255),                     -- NAS 原件路径（永不删除）
  content_hash  char(64),                         -- SHA-256 防篡改
  actor         varchar(32),                      -- 产生者（含权限角色）
  channel       varchar(24),                      -- 企微/钉钉/表单/系统
  collected_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ev_project ON evidence_objects(project_no);
CREATE INDEX IF NOT EXISTS idx_ev_cr ON evidence_objects(cr_id);
-- 触发器：禁止 UPDATE/DELETE（append-only）
CREATE OR REPLACE FUNCTION ev_no_mutate() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION 'evidence_objects 为 append-only（只增不改不删）'; END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_ev_no_mutate ON evidence_objects;
CREATE TRIGGER trg_ev_no_mutate BEFORE UPDATE OR DELETE ON evidence_objects
  FOR EACH ROW EXECUTE FUNCTION ev_no_mutate();

-- ---------- Request / Requirement / 澄清 ----------
CREATE TABLE IF NOT EXISTS requests (
  request_id    varchar(20) PRIMARY KEY,          -- RQ-26-0001
  project_no    varchar(16) NOT NULL,
  evidence_id   varchar(20) REFERENCES design_os.evidence_objects(evidence_id),
  raw_text      text NOT NULL,
  author        varchar(32) NOT NULL,
  authority_ok  boolean DEFAULT false,            -- 提出人权限核验结果
  intent        req_intent,                       -- 意图判断（"看看效果"不建CR）
  created_at    timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS requirements (
  requirement_id varchar(20) PRIMARY KEY,         -- RM-26-0001
  project_no    varchar(16) NOT NULL,
  request_ids   varchar(20)[] NOT NULL,
  statement     text NOT NULL,                    -- 确认后的需求
  facts         jsonb,                            -- FACT 清单（含证据ID）
  inferences    jsonb,                            -- INFERENCE（含依据）
  assumptions   jsonb,                            -- ASSUMPTION
  unknowns      jsonb,                            -- UNKNOWN
  evidence_level ev_level NOT NULL,               -- 就低
  authority_ok  boolean NOT NULL DEFAULT false,
  status        varchar(16) DEFAULT '已确认'       -- 草稿/待权限/已确认/作废
);

CREATE TABLE IF NOT EXISTS clarifications (
  id            bigserial PRIMARY KEY,
  requirement_id varchar(20) REFERENCES design_os.requirements(requirement_id),
  question      text NOT NULL,                    -- 带选项，一次≤3问
  options       jsonb,
  asked_to      varchar(32),
  answer        text,
  answer_evidence_id varchar(20),
  answered_at   timestamptz,
  reminded      int DEFAULT 0                     -- 24h/48h 提醒计数
);

-- ---------- 变更对象 CR ----------
CREATE TABLE IF NOT EXISTS change_requests (
  cr_id         varchar(20) PRIMARY KEY,          -- CR-26-0001
  project_no    varchar(16) NOT NULL,
  requirement_id varchar(20) REFERENCES design_os.requirements(requirement_id),
  changes       jsonb NOT NULL,                   -- [{object_id, attr, old, new}]
  evidence_ids  varchar(20)[] NOT NULL,
  evidence_level ev_level NOT NULL,
  route         cr_route,
  gate_record   jsonb,                            -- 门禁逐项通过记录
  counterfactual jsonb,                           -- 反事实检查 6 条回答
  customer_confirmed boolean DEFAULT false,
  exec_ladder   script_lvl,                       -- 实际使用的执行阶梯
  artifacts     jsonb,                            -- 产物清单（图纸/渲染/CQ/报告）
  ver_from      int, ver_to int,                  -- Design V n → V n+1
  state         cr_state NOT NULL DEFAULT 'NEW',
  created_at    timestamptz DEFAULT now(),
  closed_at     timestamptz
);
CREATE INDEX IF NOT EXISTS idx_cr_project ON change_requests(project_no);
CREATE INDEX IF NOT EXISTS idx_cr_state ON change_requests(state);

CREATE TABLE IF NOT EXISTS cr_state_log (
  id            bigserial PRIMARY KEY,
  cr_id         varchar(20) NOT NULL,
  from_state    cr_state, to_state cr_state,
  actor         varchar(32) NOT NULL,             -- 人名/Agent名/规则
  reason        text,
  at            timestamptz DEFAULT now()
);

-- ---------- 风险评估与门禁 ----------
CREATE TABLE IF NOT EXISTS risk_assessments (
  cr_id         varchar(20) PRIMARY KEY REFERENCES design_os.change_requests(cr_id),
  scope_r smallint, risk_r smallint, cost_r smallint, schedule_r smallint,
  design_r smallint, construction_r smallint, reversibility_r smallint, evidence_r smallint,  -- 各1~3
  total_score   smallint,
  structural    boolean NOT NULL DEFAULT false,
  mep           boolean NOT NULL DEFAULT false,
  fire          boolean NOT NULL DEFAULT false,
  schedule_critical boolean NOT NULL DEFAULT false,
  reversible    boolean NOT NULL DEFAULT true,
  policy_whitelist boolean NOT NULL DEFAULT false,   -- 设计总监自动执行白名单
  assessed_at   timestamptz DEFAULT now()
);

-- 门禁检查函数：自动执行必须全部为 true（03 文档第4节）
CREATE OR REPLACE FUNCTION gate_check(p_cr varchar) RETURNS jsonb AS $$
  SELECT jsonb_build_object(
    'risk_low',        r.risk_r = 1,
    'evidence_ge_e4',  c.evidence_level >= 'E4',
    'no_structural',   NOT r.structural,
    'no_mep',          NOT r.mep,
    'no_fire',         NOT r.fire,
    'no_schedule_crit',NOT r.schedule_critical,
    'reversible',      r.reversible,
    'customer_confirmed', c.customer_confirmed,
    'counterfactual_ok', COALESCE((c.counterfactual->>'all_clear')::boolean, false),
    'policy_ok',       r.policy_whitelist
  )
  FROM change_requests c JOIN risk_assessments r ON r.cr_id = c.cr_id
  WHERE c.cr_id = p_cr;
$$ LANGUAGE sql STABLE;

-- ---------- 设计事实层 ----------
CREATE TABLE IF NOT EXISTS design_objects (
  object_id     varchar(24) PRIMARY KEY,          -- DO-0031
  project_no    varchar(16) NOT NULL,
  dtype         varchar(16) NOT NULL,             -- space/wall/door/millwork/furniture/point/lighting/material
  name          varchar(64),
  parent_id     varchar(24) REFERENCES design_os.design_objects(object_id),
  attributes    jsonb NOT NULL,
  provenance    jsonb NOT NULL,                   -- 每关键属性：source/evidence_ids/cr_id/approved_at
  verified      boolean DEFAULT false,            -- 无Provenance属性→false，禁止进签发版本
  valid_from    int NOT NULL,                     -- Design Version
  valid_to      int
);
CREATE INDEX IF NOT EXISTS idx_do_project ON design_objects(project_no);

CREATE TABLE IF NOT EXISTS design_versions (
  project_no    varchar(16) NOT NULL,
  version_no    int NOT NULL,
  cr_id         varchar(20),                      -- 一次CR一个版本
  changeset     jsonb,                            -- 对象级 diff
  signed        boolean DEFAULT false,            -- S7 签发后锁定
  snapshot_ref  varchar(255),                     -- NAS 快照路径
  created_at    timestamptz DEFAULT now(),
  PRIMARY KEY (project_no, version_no)
);

CREATE TABLE IF NOT EXISTS impact_edges (
  id            bigserial PRIMARY KEY,
  project_no    varchar(16) NOT NULL,
  from_node     varchar(32) NOT NULL,             -- DO-xxxx 或 材料M-023
  to_node       varchar(64) NOT NULL,             -- DO-xxxx 或 成果物（图纸/渲染/BOQ行/报价行/采购任务/工序）
  edge_type     varchar(16) NOT NULL,             -- part_of/attached_to/uses/generates/affects
  meta          jsonb
);
CREATE INDEX IF NOT EXISTS idx_ie_from ON impact_edges(from_node);
CREATE INDEX IF NOT EXISTS idx_ie_to ON impact_edges(to_node);

-- ---------- 生产层 ----------
CREATE TABLE IF NOT EXISTS script_library (
  script_id     varchar(20) PRIMARY KEY,          -- SC-0001
  title         varchar(96) NOT NULL,
  level         script_lvl NOT NULL,
  cad_version   varchar(16),
  code          text,
  gate_status   gate_stat NOT NULL DEFAULT 'GENERATED',  -- 五道门状态（①②③级为 APPROVED）
  test_cases    jsonb,                            -- 回归用例
  usage_count   int DEFAULT 0,
  updated_at    timestamptz DEFAULT now()
);

CREATE TABLE IF NOT EXISTS render_jobs (
  job_id        bigserial PRIMARY KEY,
  cr_id         varchar(20),
  kind          render_kind NOT NULL,
  model_version varchar(32),                      -- SU/Hub 模型版本（Geometry Lock 基准）
  control_refs  jsonb,                            -- depth/canny/参考图引用
  prompt        text,
  seed          bigint,
  output_ref    varchar(255),
  geometry_qa   qa_verdict,                       -- Vision QA 结论
  retry_count   int DEFAULT 0,
  created_at    timestamptz DEFAULT now()
);

-- ---------- 验证层 ----------
CREATE TABLE IF NOT EXISTS qa_results (
  id            bigserial PRIMARY KEY,
  cr_id         varchar(20),
  task_no       varchar(20),                      -- 施工证据QA挂任务号
  qa_type       qa_type NOT NULL,
  verdict       qa_verdict NOT NULL,
  issues        jsonb,                            -- 问题/缺失清单
  basis         varchar(64),                      -- 规则版本或模型版本
  auto_fix_round int DEFAULT 0,
  at            timestamptz DEFAULT now()
);

-- ---------- 审批（OS 专用，含权限角色） ----------
CREATE TABLE IF NOT EXISTS os_approvals (
  id            bigserial PRIMARY KEY,
  cr_id         varchar(20) NOT NULL,
  approver      varchar(32) NOT NULL,
  authority_role varchar(24) NOT NULL,            -- 权限矩阵中的角色
  decision      varchar(8) NOT NULL DEFAULT '待审批',  -- 待审批/同意/驳回
  comment       text,
  evidence_id   varchar(20),                      -- 批准即形成 E5 证据
  decided_at    timestamptz
);

-- ---------- 权限矩阵 ----------
CREATE TABLE IF NOT EXISTS authority_matrix (
  id            bigserial PRIMARY KEY,
  project_no    varchar(16) NOT NULL,
  person        varchar(32) NOT NULL,
  role_label    varchar(24) NOT NULL,             -- 客户A/客户B/设计总监/施工队…
  can_propose   boolean DEFAULT true,
  can_confirm_design boolean DEFAULT false,
  can_confirm_material boolean DEFAULT false,
  can_sign      boolean DEFAULT false,
  can_site_feedback boolean DEFAULT false,
  UNIQUE (project_no, person)
);

-- ---------- 常用视图 ----------
CREATE OR REPLACE VIEW v_active_cr AS
SELECT cr_id, project_no, state, route, evidence_level, created_at
FROM change_requests
WHERE state NOT IN ('CLOSED','CLOSED_CANCELLED')
ORDER BY created_at;

CREATE OR REPLACE VIEW v_needs_clarify AS
SELECT c.requirement_id, q.question, q.asked_to, q.reminded
FROM clarifications q JOIN requirements c ON c.requirement_id = q.requirement_id
WHERE q.answer IS NULL;

COMMIT;

-- 示例：试点项目权限矩阵（按实际人员修改）
INSERT INTO authority_matrix(project_no, person, role_label, can_confirm_design, can_confirm_material, can_sign)
VALUES ('HZ-26-001', '王总', '客户A', true, true, true),
       ('HZ-26-001', '王太太', '客户B', true, true, false)
ON CONFLICT DO NOTHING;
