# W3 测试清理收尾复核包（来源记录测试线程与临时目录生命周期）

基线提交：`26ae391`（scope 必填收尾）。本轮**不改任何生产业务语义**，只修测试生命周期与新增稳定回归。
本轮提交：见 `commit-reference.md`（提交后生成）。

**这不是设计批准、不是客户成果、不放行真实模型试验、不推进阶段 2/3/W4，不改 AD01—AD08、阶段确认、scope 必填行为、数据库/NAS/PG/真实模型调用范围。**

旧包 `W3-r1r2-scope-required/`、`W3-r1r2-source-records/`、`W3-astra-r1-composition/` 等及证据只读保留。

## 1. 根因

`mvp/tests/test_w3_r1r2_source_records.py` 的 `build_service()` 用：

```python
getattr(self, "_services", []).append(service)
```

但 `setUp()` 从未初始化 `self._services` —— 每次都往一个**临时列表**追加后丢掉引用。`tearDown()` 的 `for service in getattr(self, "_services", [])` 因此是空循环，**任何服务后台 worker 都没有被等待**；`self.store.close()` 和 `TemporaryDirectory.cleanup()` 随即在 worker 仍在写 `layout-*.svg` / SQLite 时执行，于是偶发：

- `FileNotFoundError` 写 layout SVG
- `sqlite3.OperationalError: unable to open database file`

这些发生在后台线程，unittest 仍报 `OK`。此外 `tearDown()` 把 `wait_for_idle()` 的异常全部 `except ... pass`，且 `build_service()` 为 owner/shadow 新建的 `SQLiteStore` 从未 close。

本机连续 15 次运行未复现打印（竞态时序依赖），但上述结构性缺陷确定存在。

## 2. 修复（仅测试文件）

`mvp/tests/test_w3_r1r2_source_records.py`：

| 位置 | 改动 |
| --- | --- |
| `:139-157` | `setUp()` 初始化 `self._services` / `self._stores` / `self._thread_exceptions`，安装 `threading.excepthook` 收集器；线程异常同时保留原始打印 |
| `:173-189` | 新增 `_wait_all_workers()`：等待需求通道、所有服务的 `AIDesignOptionService` 与 `AISpatialOutputService`，并断言 `_active()` 为空（`wait_for_idle` 超时会静默返回，故必须二次确认） |
| `:191-212` | `tearDown()` 按「先等 worker → 再关所有 SQLite 连接 → 再删临时目录」顺序执行；任何未处理线程异常/关闭失败/清理失败都收集并在 `tearDown` 中 `self.fail()`；最后恢复原 excepthook |
| `:215-226` | `build_service()` 把每个 service 与其新建的 store 注册进跟踪列表 |
| `:447` | 幽灵父修订测试给 `blocking.release` 加 `addCleanup`，失败路径也不让 worker 永久阻塞 |
| `:470-474` | 该测试在终态轮询后**显式等待 owner/shadow 的 worker 并核对终态 `failed`**，替代原来的 `time.sleep(0.3)` |

收集器有效性已用一次性探针验证：注入一个故意抛 `RuntimeError` 的后台线程后，测试以 `AssertionError: 后台线程出现未处理异常（1 条）` 失败，而不是 `OK`。探针文件已删除，未进入交付。

## 3. 稳定回归

新增 `scripts/verify_w3_test_thread_hygiene.py`：在独立子进程中重复运行 `test_w3_r1r2_source_records.py`（默认 5 次），每次同时要求：

1. 退出码 0；
2. 输出含 `Ran 5 tests` 且 `OK`；
3. 输出**不得**出现 `Exception in thread` / `Unhandled exception in thread` / `FileNotFoundError` / `OperationalError: unable to open database file` / `Traceback (most recent call last)` / 本测试的收尾失败文案。

任一不满足 → 脚本退出码 2，并把逐次结果写入 `test-hygiene.json`。

实测：`--runs 5` → `{"clean_runs": 5, "dirty_runs": 0}`，每次 5/5 OK、输出干净。证据：`var/evidence/roadmap/W3-test-hygiene/after/test-hygiene.json`。

## 4. 测试

- `test_w3_r1r2_source_records.py`：**5/5 OK**（清理后）
- 重复稳定性检查：**5 次 × 5/5 OK，0 次脏输出**
- 全量单测：**278/278 OK**（日志 `var/evidence/roadmap/W3-test-hygiene/after/full-regression.log`，exit 0）
- **not_run**：HTTP 进程级下载、浏览器 UI、PG 数据面、真实模型调用（本轮无外部调用、无费用、无密钥）；本轮未改生产代码，相关业务回归结果沿用上一批 `W3-r1r2-scope-required` 的证据。

## 5. 残余限制

1. `threading.excepthook` 是进程级全局钩子；本测试类在 `setUp`/`tearDown` 成对安装与恢复，串行 unittest 下安全。若未来并行执行测试类，需改用线程局部或 pytest 插件方式。
2. `_active()` 是服务私有只读状态，仅用于测试收尾断言（不替代产品入口）。
3. `test_w3_composition_root.py` 的 `tearDown()` 同样未集中跟踪它创建的服务；该文件的具体测试已在需要处显式等待（如取消态），本轮按指令范围**未改动**，作为潜在后续清理项记录。
4. 重复运行检查依赖输出文本匹配；若异常被第三方日志框架吞掉且完全不输出，需要额外进程内断言（本测试类已有 excepthook 收集器兜底）。

## 6. 没有做什么

- 未改任何生产模块、scope 必填行为、准入/适配/签发语义。
- 未改 AD01—AD08、阶段确认、W4、数据库 schema/迁移、PG/NAS/账号、真实模型调用口径。
- 未覆盖旧证据与底图原件。
