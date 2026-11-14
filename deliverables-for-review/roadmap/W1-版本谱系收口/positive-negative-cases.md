# W1 版本谱系收口 · 正负例与复现

所有条目来自 `scripts/verify_w1_lineage.py` 的真实 HTTP 执行（`lineage-checks.json`，13/13）
与 `scripts/verify_w1_unified_model.py` 的原 22 项回归（`after/regression-original22/checks.json`，22/22）。
环境：隔离主系统库 + 隔离 Studio 库；源为明确标记的本地夹具，**带真实 `parent_revision_uid` 链**；
0 外部调用、0 密钥、0 费用。

## A. 谱系正例

| 编号 | 输入 | 预期 | 实际 |
| --- | --- | --- | --- |
| L01 | 两个不同根的 A（都不带父） | 两个候选，各自 v1，parent null | 两个不同 `option_id`；v1/v1；parent 均为 null |
| L02 | 同根 v1（uid-A-1）→ v2（parent=uid-A-1） | v2 父 = v1 的主系统修订 | v2 `parent_revision_id=ai-option-revision_f044c667fd60`（=v1）；`root_uid=uid-A-1`；`link=resolved` |
| L03 | v1 的两个分叉 v2a / v2b（同一父） | 两者父都指 v1，互不为父 | 编号 3/4，父都是 v1 主 id |
| L09 | 一个声明为夹具的源、一个未声明来源的源 | 传输=studio_import；设计来源按声明，未声明为 unknown | `design_origin={kind: fixture, declared_by: studio_artifact.diagnostics.source}`；另一条 `kind=unknown, declared_by=not_declared` |
| L10 | 导入详情 + 目标模型 | 精确多边形权威；bbox 仅 legacy 且标损失 | `polygon_mm` 与源逐值相等；`geometry_mode=bbox_derived`；`losses` 含 `bounding_box_only`（注意 L10 断言用 `bounding_box_only`，见 evidence） |
| L11 | 采用指定分叉最新版，再采用旧版 | 前者成功且非正式批准；后者 CAS 拒绝 | 200、`formal_approval=false`；旧版 409 `STALE_OPTION_REVISION` |
| L07 | 两个线程用 `Barrier` 同时对同一源发 HTTP | 只产生一个版本，另一个复用 | 两个 200：`reused=false` + `reused=true`；+1 版本、+1 SVG |
| L08 | 两个线程同时对同父的两个分叉发 HTTP | 两个版本、编号不同、父都为 v1 | 200/200；编号 2/3；父同一 v1 主 id；+2 版本 +2 SVG |
| L12 | 确定性接缝：准备完成后、提交前，另一个请求先提交同源 | 外层复用，内层创建；无遗留文件 | 外层 `reused=true`，内层 `reused=false`；+1 版本 +1 SVG |
| L13 | 确定性接缝：准备完成后、提交前，另一个分叉先提交 | 写内重算编号，父都指 v1 | 编号 3/2（外层在锁内从 2 改为 3）；父均为同一 v1；+2 版本 +2 SVG |

## B. 负例（都检查"没有半写入"）

| 编号 | 输入 | 预期 | 实际 |
| --- | --- | --- | --- |
| L04 | 先导入子稿（父未导入） | 明确拒绝，不把旧稿接在新稿后 | 409 `SOURCE_PARENT_NOT_IMPORTED`；补齐父后 1→2→3 链正确 |
| L05 | 缺父但显式 `allow_orphan=true` | parent null + 缺父状态，不伪造 | 200；`parent=null`；`source_parent_not_imported`；`root=uid-A-orphan-1` |
| L06 | 源父 UID 在 Studio 库不存在 | 拒绝，不猜根 | 409 `SOURCE_PARENT_MISSING` |
| 原 W1-07/08/09/11/12/13/14 | 单位错配、目录缺引用、伪多边形、项目映射、sha 不符、非有效候选、旧版本采用、中途失败 | 保持 W1 首版行为 | 22 项回归全部通过；失败不半写入、adoptions 0 行 |

## C. 复现步骤（本地，无外部依赖）

```bash
# 依赖：项目 .venv（Python 3.12，含 jsonschema 4.25.1 / shapely 2.1.2）
export PYTHONPATH="mvp;scripts;."
./.venv/Scripts/python.exe scripts/verify_w1_lineage.py \
  --out var/evidence/roadmap/W1-版本谱系收口/after \
  --runtime var/evidence/roadmap/W1-版本谱系收口/runtime
# 期望：passed 13 / failed 0

./.venv/Scripts/python.exe scripts/verify_w1_unified_model.py \
  --out var/evidence/roadmap/W1-版本谱系收口/after/regression-original22 \
  --runtime var/evidence/roadmap/W1-版本谱系收口/runtime-regression
# 期望：passed 22 / failed 0

./.venv/Scripts/python.exe scripts/verify_w1_browser.py \
  --out var/evidence/roadmap/W1-版本谱系收口/after/browser \
  --runtime var/evidence/roadmap/W1-版本谱系收口/browser-runtime
# 期望：passed true
```

## D. 修正记录（如实，不靠改预期绕过失败）

1. **测试夹具本身是缺陷来源**：W1 首版 `save_valid()` 对所有源稿写 `parent_revision_uid=None`，
   W1-06 却期望"父指向上一导入"——正好证明当时测的是导入顺序。本批给夹具加真实父 UID 链
   （`save_valid(..., parent_artifact=...)`），原 22 项在**不放宽断言**的前提下重跑通过。
2. **L05 第一次失败**：把"父在 Studio 存在但未导入主系统"和"父在 Studio 根本不存在"混成一个夹具，
   被 `SOURCE_PARENT_MISSING` 提前拒绝。拆成两个源分别覆盖 L05（允许缺父）与 L06（源链断裂）。
3. **L05 根谱系断言写错**：缺父导入的 `root_uid` 是源根（父 uid），不是自身 uid；修正断言为
   `uid-A-orphan-1`，没有改业务逻辑去迎合测试。
4. **L11 第一次失败**：分叉后该候选最新版已是 3，用 v2 的 `expected_revision=2` 采用必然 409；
   改为采用该谱系最新版，再验证旧版被 CAS 拒绝——这正好也证明谱系身份能用于采用。

## E. 未覆盖

- 多进程并发、PG 并发、断电/崩溃恢复：只在单进程多线程 + 隔离 SQLite 上验证。
- 真实模型/真实设计来源：源是夹具；`design_origin` 只验证"按声明保留"的机制。
- W2 制图/渲染/量价、`Q10`：未开始。
