# 提交与复现引用

## 稳定引用

| 名称 | 值 |
| --- | --- |
| 基线（上一轮组合根接线交付） | `f473c92b2ee8f88ed4e7af61adb4d7ad53b07fb8` |
| 本轮代码提交（R1 scope + R2 提交后登记 + 测试 + harness + 状态） | `55602df` |
| 本轮复核包元数据提交（本文件与 `manifest.json`） | 见 `git log --oneline -3`（生成时尚未提交，避免写死易变 HEAD） |
| 分支 | `master` |
| 代码 diff | `git diff f473c92 55602df -- mvp scripts PROJECT_STATUS.md`（已落盘 `changes.patch`，6 文件 +1093/−39） |

## 复现命令（Windows + 项目虚拟环境）

Python 必须用 `./.venv/Scripts/python.exe`；`PYTHONPATH` 用分号分隔。

### 1. 冻结基线

```bash
mkdir -p var/evidence/roadmap/W3-r1r2-source-records/before
git archive f473c92 mvp contracts scripts fixtures "deliverables-for-review/roadmap/W2-R4-表达收口" \
  | tar -x -C var/evidence/roadmap/W3-r1r2-source-records/before
```

必须包含整个 `mvp`（`mvp/persistence/sqlite` 迁移在里面），以及 `contracts`、`fixtures`、`W2-R4-表达收口/basemap`。

### 2. 基线复现（期望 3/3 vulnerable，退出码 0）

```bash
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe scripts/w3_r1r2_findings.py \
  --code-root "var/evidence/roadmap/W3-r1r2-source-records/before" \
  --label before \
  --out "var/evidence/roadmap/W3-r1r2-source-records/before/harness" \
  --expect vulnerable
```

### 3. 修复后同例复跑（期望 3/3 fixed，退出码 0）

```bash
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe scripts/w3_r1r2_findings.py \
  --code-root "." \
  --label after \
  --out "var/evidence/roadmap/W3-r1r2-source-records/after" \
  --expect fixed
```

任一项与 `--expect` 不符返回退出码 2。

### 4. 永久回归

```bash
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe -m unittest discover -s mvp/tests -p "test_w3_r1r2_source_records.py"
# -> Ran 4 tests ... OK

PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe -m unittest discover -s mvp/tests
# -> Ran 277 tests ... OK   (日志 var/evidence/roadmap/W3-r1r2-source-records/after/full-regression.log)
```

注意：`discover` 不要加 `-t mvp`（`mvp/tests` 无 `__init__.py`，会报 `Start directory is not importable`）。

## 证据位置

```
var/evidence/roadmap/W3-r1r2-source-records/
  before/                      # git archive f473c92（只读）
    harness/findings.json      # 3/3 vulnerable
  after/
    findings.json              # 3/3 fixed
    full-regression.log        # 277 tests OK, exit 0
```

## 未使用外部资源

`external_calls=0`、`cost_cny=0`、`keys_used=false`；全部交换为本地协议桩（`127.0.0.1:9/stub`），`simulated=True`，来源 `fixture`。
