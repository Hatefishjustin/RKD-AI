# 提交与复现引用（scope 必填收尾）

## 稳定引用

| 名称 | 值 |
| --- | --- |
| 基线（上一批来源记录整改交付） | `9dca78bc0166a696e71bf65eddf8c665eb3436e4` |
| 本轮代码提交 | `26ae391` |
| 本轮复核包元数据提交 | 见 `git log --oneline -3`（生成时尚未提交，避免写死易变 HEAD） |
| 分支 | `master` |
| 代码 diff | `git diff 9dca78b 26ae391 -- mvp scripts PROJECT_STATUS.md`（已落盘 `changes.patch`，6 文件 +317/−18） |

## 复现命令（Windows + 项目虚拟环境）

Python 用 `./.venv/Scripts/python.exe`；`PYTHONPATH` 用分号分隔。

### 1. 冻结基线

```bash
mkdir -p var/evidence/roadmap/W3-r1r2-scope-required/before
git archive 9dca78b mvp contracts scripts fixtures "deliverables-for-review/roadmap/W2-R4-表达收口" \
  | tar -x -C var/evidence/roadmap/W3-r1r2-scope-required/before
```

### 2. 基线（期望 vulnerable，退出码 0）

```bash
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe scripts/w3_scope_required_findings.py \
  --code-root "var/evidence/roadmap/W3-r1r2-scope-required/before" \
  --label before \
  --out "var/evidence/roadmap/W3-r1r2-scope-required/before/harness" \
  --expect vulnerable
```

### 3. 修复后（期望 fixed + 产品路径通过，退出码 0）

```bash
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe scripts/w3_scope_required_findings.py \
  --code-root "." \
  --label after \
  --out "var/evidence/roadmap/W3-r1r2-scope-required/after/harness" \
  --expect fixed
```

任一项不符返回退出码 2。

### 4. 回归

```bash
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe -m unittest discover -s mvp/tests -p "test_w3_r1r2_source_records.py"   # 5/5 OK
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe -m unittest discover -s mvp/tests -p "test_w3_composition_root.py"     # 7/7 OK
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe -m unittest discover -s mvp/tests                                      # 278/278 OK
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe scripts/w3_astra_findings.py \
  --code-root "." --label scope-required-recheck \
  --out "var/evidence/roadmap/W3-r1r2-scope-required/after/legacy-recheck2" --expect fixed   # 5/5 fixed
```

`discover` 不要加 `-t mvp`（`mvp/tests` 无 `__init__.py`）。旧 harness 输出目录必须每次换新的（`register_revision` 会持久化，重跑同目录会 `REVISION_ALREADY_REGISTERED`）。

## 证据位置

```
var/evidence/roadmap/W3-r1r2-scope-required/
  before/                      # git archive 9dca78b（只读）
    harness/findings.json      # vulnerable：4 条省略/None 调用全部 accepted
  after/
    harness/findings.json      # fixed：全部拒绝 + 产品路径通过
    full-regression.log        # 278 tests OK, exit 0
    legacy-recheck2/           # w3_astra_findings 5/5 fixed
```

## 未使用外部资源

`external_calls=0`、`cost_cny=0`、`keys_used=false`；全部交换为本地协议桩，来源 `fixture`、`simulated=True`。
