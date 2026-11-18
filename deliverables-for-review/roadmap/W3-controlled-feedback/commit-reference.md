# 提交与复现引用（受控反馈修订闭环）

## 稳定引用

| 名称 | 值 |
| --- | --- |
| 基线（检查时 HEAD == origin/master，工作区干净） | `902952ed31370852cbae58df2248d79c4d9e2237` |
| 本轮代码提交（本地） | `c5446d9` |
| 本轮复核包元数据提交（本地） | 见 `git log --oneline -3`（生成时尚未提交） |
| 分支 | `master`（本地） |
| 是否推送 | **否**。按用户要求交架构复核，不自行推送 |
| diff | `git diff 902952e c5446d9 -- mvp scripts PROJECT_STATUS.md`（已落盘 `changes.patch`，9 文件 +995/−10） |

## 复现命令（Windows + 项目虚拟环境）

Python 用 `./.venv/Scripts/python.exe`；`PYTHONPATH` 用分号分隔。

### 1. 冻结基线

```bash
mkdir -p var/evidence/roadmap/W3-controlled-feedback/before
git archive 902952e mvp contracts scripts fixtures "deliverables-for-review/roadmap/W2-R4-表达收口" \
  | tar -x -C var/evidence/roadmap/W3-controlled-feedback/before
```

### 2. before（期望 vulnerable，退出码 0）

```bash
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe scripts/w3_feedback_revision_findings.py \
  --code-root "var/evidence/roadmap/W3-controlled-feedback/before" \
  --label before \
  --out "var/evidence/roadmap/W3-controlled-feedback/before/harness" \
  --expect vulnerable
```

### 3. after（期望 fixed，退出码 0）

```bash
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe scripts/w3_feedback_revision_findings.py \
  --code-root "." --label after \
  --out "var/evidence/roadmap/W3-controlled-feedback/after" --expect fixed
```

### 4. 测试

```bash
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe -m unittest discover -s mvp/tests -p "test_w3_controlled_feedback.py"
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe -m unittest discover -s mvp/tests -p "test_w3_composition_root.py"
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe -m unittest discover -s mvp/tests -p "test_ai_design_options.py"
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe -m unittest discover -s mvp/tests -p "test_w3_r1r2_source_records.py"
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe -m unittest discover -s mvp/tests -p "test_w3_astra_remediation.py"
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe -m unittest discover -s mvp/tests
```

`discover` 不要加 `-t mvp`（`mvp/tests` 无 `__init__.py`）。

## 证据完整路径

```
var/evidence/roadmap/W3-controlled-feedback/
  before/                      # git archive 902952e（只读）
    harness/findings.json      # CONTROLLED_FEEDBACK_PATH_UNSUPPORTED / vulnerable
  after/
    findings.json              # 新修订、新 run、父版不变、fresh admission / fixed
    feedback-tests.log         # 9 tests OK, exit 0
    full-regression.log        # 287 tests OK, exit 0
```

## 未使用外部资源

外部模型调用 0、资料外发 0、tokens 0、费用 ¥0、图片 0 张、真实密钥未使用。全部交换为本地协议桩，来源 `fixture`、`simulated=true`。
