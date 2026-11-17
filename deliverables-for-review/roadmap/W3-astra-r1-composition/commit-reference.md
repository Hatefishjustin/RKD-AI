# 提交与复现引用

## 稳定引用

| 名称 | 值 |
| --- | --- |
| 基线（第一轮 Astra 整改交付） | `446a6f6526391e1dcc6313f8247760c883448063` |
| 本轮代码提交（R1 组合根接线 + 测试 + harness + 状态） | `dbc907e` |
| 本轮复核包元数据提交（本文件与 `manifest.json`） | 见 `git log --oneline -3`（本文件生成时尚未提交，避免写死易变 HEAD） |
| 分支 | `master` |
| 代码 diff | `git diff 446a6f6 dbc907e -- mvp scripts PROJECT_STATUS.md`（已落盘 `changes.patch`，8 文件 +761/−10） |
| 复现 harness diff | 含于上（`scripts/w3_composition_findings.py` 为新增文件） |

上一轮基线：`72442c7` → `86e3e36`（第一轮代码）/ `446a6f6`（第一轮复核包元数据）。

## 复现命令（本机实测，Windows + 项目虚拟环境）

环境约定：Python 必须用 `./.venv/Scripts/python.exe`（含 jsonschema/shapely）；`PYTHONPATH` 用分号分隔。

### 1. 冻结基线

```bash
mkdir -p var/evidence/roadmap/W3-astra-r1-composition/before
git archive 446a6f6 mvp contracts scripts PROJECT_STATUS.md AGENTS.md \
  | tar -x -C var/evidence/roadmap/W3-astra-r1-composition/before
```

必须包含 `mvp/persistence/sqlite`（`SQLiteStore._migrate()` 从这里读迁移）。只归档 `mvp/rkd_mvp` 会因缺迁移报 `no such table: mvp_state`。

### 2. 基线复现（期望 5/5 vulnerable，退出码 0）

```bash
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe scripts/w3_composition_findings.py \
  --code-root "var/evidence/roadmap/W3-astra-r1-composition/before" \
  --label before \
  --out "var/evidence/roadmap/W3-astra-r1-composition/before/harness" \
  --expect vulnerable
```

### 3. 工作树复跑（期望 5/5 fixed，退出码 0）

```bash
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe scripts/w3_composition_findings.py \
  --code-root "." \
  --label after \
  --out "var/evidence/roadmap/W3-astra-r1-composition/after/harness" \
  --expect fixed
```

任一项与 `--expect` 不符返回退出码 2。

### 4. 永久回归

```bash
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe -m unittest discover -s mvp/tests -p "test_w3_composition_root.py"
# -> Ran 7 tests ... OK

PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe -m unittest discover -s mvp/tests
# -> Ran 273 tests ... OK   (日志 var/evidence/roadmap/W3-astra-r1-composition/after/full-regression.log)
```

注意：`discover` 不要加 `-t mvp`（`mvp/tests` 无 `__init__.py`，会报 `Start directory is not importable`）。

## 证据位置

```
var/evidence/roadmap/W3-astra-r1-composition/
  before/                      # git archive 446a6f6 冻结代码（只读）
    harness/findings.json      # 5/5 vulnerable
  after/
    harness/findings.json      # 5/5 fixed（含四态证据）
    full-regression.log        # 273 tests OK, exit 0
```

## 未使用外部资源

`external_calls=0`、`cost_cny=0`、`keys_used=false`；全部交换为本地协议桩（`127.0.0.1:9/stub`），`simulated=True`。
