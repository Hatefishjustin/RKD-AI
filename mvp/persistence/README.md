# 持久化边界参考

本目录把内存参考实现替换为生产数据库和持久化工作流前必须满足的结构约束。当前迁移面向 PostgreSQL 兼容数据库，但不绑定云厂商；迁移没有在本工作区执行，因为尚未选择数据库实例和部署环境。

`mvp/rkd_mvp/postgres_store.py` 提供 DB-API 事务边界：事务会设置组织/项目 RLS 上下文，Outbox 领取使用 `FOR UPDATE SKIP LOCKED` 和租约，确认消息时必须带 worker lease，Inbox 使用组织/项目/消息/消费者唯一键；`postgres_repository.py` 已补上共享命令/事件内核的原子写路径。它们**还不能直接替换当前 SQLiteStore**：项目及 M1—M4 服务仍存在 SQLite SQL/连接依赖，旧工作流还使用快照。M5-02 后续必须逐域完成 Repository/事务适配并在真实 PostgreSQL 验证，不是仅注入驱动和连接池。

本机现有 SQLite 迁移 001—015 包含 M1—M4 及 M5-01 账号/项目成员/会话/身份审计；它们不是 PostgreSQL 迁移已执行的证明。账号切片与运行数据的 PostgreSQL 迁移状态见唯一台账 `PROJECT_STATUS.md`。

## 迁移内容

`postgres/001_vertical_mvp.sql` 定义：

- 组织、项目和项目成员；
- 命令幂等记录、聚合状态和领域事件；
- Outbox/Inbox 去重；
- 哈希链审计和不可变触发器；
- WorkflowRun/WorkflowActivity；
- ExecutorJob/ExecutorResult 和产物索引；
- 外部动作 `unknown`、对账和人工解决状态；
- Outbox/Inbox 消费失败的显式死信表；
- 项目级 RLS/等价租户隔离、关键索引和状态约束。

`postgres/002_runtime_domains.sql` 继续定义当前本地运行库的完整域表：文件、任务/问题、预算/计算、空间/工程量/报价、需求/设计、采购/收货/分派、变更/验收，以及 M5-01 账号、成员、会话、登录限制和身份审计。它把 JSON 快照字段映射为 `jsonb`，金额/数量仍保留业务层的十进制文本口径；项目级表通过统一 RLS 策略隔离，身份审计和上一层审计均为追加式。

应用连接角色不得是表 owner 或 superuser。迁移角色、应用角色和 break-glass 角色必须分离；组织表和项目表也必须应用 RLS；每个请求在事务开始时设置不可伪造的 `rkd.organization_id` 和 `rkd.project_id`，事务结束时清理上下文。

## 应用接入顺序

1. 用 `mvp/rkd_mvp/postgres_migrations.py` 或等价部署命令，以迁移角色执行连续版本 SQL migration。
2. 用独立的种子/成员管理流程建立组织、项目和成员。
3. 应用连接使用非 owner 角色，并在每个事务设置租户上下文。
4. 先写 `command_record + aggregate_state + domain_event + audit_event 摘要 + outbox_message`，再提交。
5. 消费者先写 Inbox 去重记录，再处理执行器或工作流结果。
6. 任何外部动作恢复都先查询/对账，不能根据未知状态盲目重发。

当前已实现 001/002 的迁移发现、版本记录、单版本事务和失败回滚，并已在假 DB-API 连接上验证；当前机器没有 PostgreSQL 实例，因此不能把这些测试或 SQL 文件视为真实数据库部署证据。`PostgresRepository` 目前覆盖共享命令/事件内核，M1-M4 各业务服务仍使用 SQLite，需在真实实例上逐域迁移并对账后才能替换。
