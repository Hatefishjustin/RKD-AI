# 提交与复现引用（测试清理收尾）

## 稳定引用

| 名称 | 值 |
| --- | --- |
| 基线 | `26ae391` |
| 本轮提交（仅测试文件 + 校验脚本 + 状态） | `d5d2d16` |
| 本轮复核包元数据提交 | 见 `git log --oneline -3`（生成时尚未提交，避免写死 HEAD） |
| 分支 | `master` |
| diff | `git diff 26ae391 d5d2d16 -- mvp/tests scripts PROJECT_STATUS.md`（已落盘 `changes.patch`，3 文件 +147/−11） |

## 复现命令（Windows + 项目虚拟环境）

```bash
# 来源记录测试（5/5，输出干净）
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe \
  -m unittest discover -s mvp/tests -p "test_w3_r1r2_source_records.py"

# 重复稳定性回归（5 次子进程，每次 5/5 OK，输出无线程/清理异常）
./.venv/Scripts/python.exe scripts/verify_w3_test_thread_hygiene.py \
  --runs 5 --out "var/evidence/roadmap/W3-test-hygiene/after"

# 全量
PYTHONPATH="mvp;scripts;." ./.venv/Scripts/python.exe -m unittest discover -s mvp/tests
```

`discover` 不要加 `-t mvp`（`mvp/tests` 无 `__init__.py`）。

## 证据位置

```
var/evidence/roadmap/W3-test-hygiene/after/
  test-hygiene.json       # clean_runs=5, dirty_runs=0（逐次退出码/匹配特征）
  full-regression.log     # 278 tests OK, exit 0
```

## 未使用外部资源

`external_calls=0`、`cost_cny=0`、`keys_used=false`。本轮无生产代码改动，无真实模型调用。
