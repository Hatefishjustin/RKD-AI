# 提交号与复现命令（W3 Astra R1—R5 整改）

- 基线（被复核/被复现）：`72442c768c88dcb10fa67f6017e7422842c21aee`
- 整改代码提交：`86e3e363f71bbb1aa57b70bd4cab4cc222b7bbb3`
- 业务代码 diff：`git diff 72442c7..86e3e36 -- mvp/rkd_mvp mvp/tests scripts`
- 完整补丁副本：`changes.patch`（本包，工作树提交前生成）

> 提交号写稳定的业务代码提交，不写会因新增 `commit-reference.md`/`manifest.json` 而变化的最终 HEAD。最终 HEAD 用 `git rev-parse HEAD` 取。

## 复现命令（新隔离目录，均不调用外部模型）

先在冻结基线复现（应输出全部 vulnerable）：

```bash
cd "D:/Github/RKD AI"
mkdir -p var/evidence/roadmap/W3-astra-remediation/before
git archive 72442c7 mvp/rkd_mvp mvp/persistence contracts scripts \
  | tar -x -C var/evidence/roadmap/W3-astra-remediation/before
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe scripts/w3_astra_findings.py \
  --code-root "var/evidence/roadmap/W3-astra-remediation/before" \
  --label before --out "var/evidence/roadmap/W3-astra-remediation/before/harness" \
  --expect vulnerable
```

在修复后的工作树同例复跑（应输出全部 fixed）：

```bash
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe scripts/w3_astra_findings.py \
  --code-root "D:/Github/RKD AI" --label after \
  --out "var/evidence/roadmap/W3-astra-remediation/after/harness" --expect fixed
```

综合验证（12 pass / 0 fail / 1 not_run）：

```bash
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe scripts/verify_w3_astra_remediation.py \
  --evidence "var/evidence/roadmap/W3-astra-remediation/after" \
  --out "deliverables-for-review/roadmap/W3-astra-remediation"
```

回归：

```bash
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe -m unittest discover -s mvp/tests -q
# 266/266 OK (基线 262 + 新增 4)
```

注意：Python 必须用项目虚拟环境 `./.venv/Scripts/python.exe`（托管 Python 无 jsonschema/shapely）。Windows 下 `PYTHONPATH` 分隔符为 `;`。HARNESS 输出为 5 项 R1—R5 的 `vulnerable`/`fixed` 字典，退出码 0 表示符合 `--expect`，2 表示不符。所有来源标注 `simulated`，`stub-not-a-real-key` 仅字符串，外部调用与费用均为 0。
