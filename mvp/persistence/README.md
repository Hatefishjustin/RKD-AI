# 持久化边界参考

本目录保存连续PostgreSQL迁移和本地SQLite迁移。当前PostgreSQL 001—007、SQLite 001—017；计划内业务服务采用显式SQLite/PG Repository复用计算和授权规则，无SQL翻译或隐式回退。真实验证及部署动态只见 [项目台账](../../PROJECT_STATUS.md)。

`postgres_store.py` 负责psycopg连接、租户事务、租约/Inbox；`postgres_repository.py` 保留原子命令/事件内核。`postgres_api_service.py` 显式接项目、文件、需求、设计、地坪生产、采购、变更、任务/问题、预算及参数几何；AccountIdentityProvider通过命名SQL仓储接账号/角色/会话。旧模拟工作流/命令未开放，不把它们伪装为实际业务。

PostgreSQL角色必须非owner、非超级用户且无bypassrls；迁移/维护凭证不提供给Web应用。参考HTTP入口只供回环试点；NAS另用FastAPI/Uvicorn账号模式。

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

`postgres/003_tenant_integrity.sql` 补齐子表租户列和 RLS、项目级项目访问、跨表组织/项目复合外键及收货/分派订单约束；命令增加请求指纹，幂等键按命令类型隔离。

应用连接角色不得是表 owner 或 superuser。迁移角色、应用角色和 break-glass 角色必须分离；组织表和项目表也必须应用 RLS；每个请求在事务开始时设置不可伪造的 `rkd.organization_id` 和 `rkd.project_id`，事务结束时清理上下文。

`postgres/004_production_chain.sql` 保存同基线地坪生产/采购引用；005提供受限项目目录函数；006保存分派行；007保存组织登录限流及最小账号角色目录。SECURITY DEFINER函数固定search_path，撤销PUBLIC执行，仅显式授权应用角色。

## 应用接入顺序

1. 用 `mvp/rkd_mvp/postgres_migrations.py` 或等价部署命令，以迁移角色执行连续版本 SQL migration。
2. 用独立的种子/成员管理流程建立组织、项目和成员。
3. 应用连接使用非 owner 角色，并在每个事务设置租户上下文。
4. 先写 `command_record + aggregate_state + domain_event + audit_event 摘要 + outbox_message`，再提交。
5. 消费者先写 Inbox 去重记录，再处理执行器或工作流结果。
6. 任何外部动作恢复都先查询/对账，不能根据未知状态盲目重发。

迁移器使用启动会话锁和单版本事务，记录 SQL 校验和；拒绝缺号、修改过的迁移、数据库版本高于应用及旧无校验和历史，不能直接给旧历史补盖章。真实数据库检查已覆盖迁移失败回滚、并发启动、RLS、幂等/版本竞争、Outbox 租约、审计及进程重启。

## 本地真实验证与迁移演练

在仓库根目录执行：

```powershell
pwsh -NoProfile -File .\scripts\rkd.ps1 postgres-prepare
pwsh -NoProfile -File .\scripts\rkd.ps1 postgres-test
```

准备命令校验固定版本 ZIP 完整 SHA-256，安装 `mvp/requirements-postgres.txt` 的可选依赖。工具位于 `var/tools/`，不注册系统服务。验证命令创建随机回环端口的隔离实例，建立迁移角色和非 owner 应用角色，显式执行 `mvp/integration/test_postgres_live.py`；测试结束停止自己的实例。日志、快照、逐表摘要和最终检查位于 `var/evidence/m5-postgres/run-*/`。普通回归不会将真实数据库检查标为跳过后算通过。

`postgres_import.py` 只读导入受支持SQLite schema14—17快照，逐行/十进制/修订及文件字节校验；目标非空、未知表或未适配的非空旧快照域拒绝，写入失败整笔回滚。账号和角色保留，旧会话撤销。导入器本身只验证原路径，不负责文件复制；NAS一次性初始化另复制已核对文件，遇既有数据库或运行目录拒绝覆盖。

完整恢复由 `postgres_backup.py` 执行：一致pg_dump及全表摘要、全部引用文件和应用基线打包；校验全部字节后，仅恢复到新目录/空数据库，核对行/文件、撤销会话、修复ACL和授予非owner应用角色。不是以“SQL文件存在”或只读导入替代恢复。实际HTTP下载和应用/数据库重启由 `scripts/verify_postgres.py` 执行，账号专用ASGI入口及NAS初始化由 `scripts/verify_team_transport.py` 隔离验证。
