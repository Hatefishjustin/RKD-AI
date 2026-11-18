# 代码差异说明（仅测试文件 + 校验脚本）

基线：`26ae391`。本轮无任何生产模块改动。完整补丁见 `changes.patch`。

## `mvp/tests/test_w3_r1r2_source_records.py`（仅测试）

- `setUp()`：初始化 `self._services` / `self._stores` / `self._thread_exceptions`，安装 `threading.excepthook` 收集器（同时保留原始打印）。
- 新增 `_wait_all_workers()`：等待需求、设计候选、成果三类 worker，并断言 `_active()` 为空。
- `tearDown()`：严格顺序「等 worker → close 全部 store → 删临时目录 → 恢复 excepthook」；收集所有失败并在 `self.fail()` 中一次性暴露。
- `build_service()`：把 service 和新建 store 注册进跟踪列表（修掉 `getattr(..., []).append()` 丢引用的缺陷）。
- `test_phantom_parent_revision_rejected()`：`blocking.release` 加 `addCleanup`；终态轮询后显式等待 owner/shadow 并核对 `failed`，替代固定 sleep。

## `scripts/verify_w3_test_thread_hygiene.py`（新增）

在独立子进程中重复运行来源记录测试，要求每次 5/5 OK、退出码 0、输出中无未处理线程异常与清理异常特征；逐次结果落 `test-hygiene.json`，任一失败退出码 2。

## 未改动

- 所有 `mvp/rkd_mvp/*.py` 生产模块（scope 必填、准入、签发、组合根、成果登记逻辑均保持 `26ae391` 原样）。
- 契约、数据库迁移、配置、启动脚本、AD/阶段文档。
