# FN NAS 部署操作

该目录为 M5-04 的独立部署配置，不改变本机日常 SQLite 入口。部署状态和实测证据只记在根目录 PROJECT_STATUS.md。

先运行 `scripts/prepare_nas_release.py`：从一致 SQLite 快照生成备份，并隔离恢复、校验全部引用文件和当前应用代码，再打包。将输出 ZIP 和同目录 host_prepare.py 传到 NAS；核对 ZIP SHA-256 后执行：

```sh
python3 host_prepare.py /path/to/rkd-ai-release.zip /home/Justin/rkd-ai
```

脚本只创建独立目录和凭证文件，不启动 Docker。凭证在 NAS 生成且不输出；上层目录仅当前 SSH 用户可进入。数据库管理密码只挂载到数据库及一次性初始化工具；应用仅持有非 owner、非超级用户、无 bypassrls 的独立连接。

检查暂存的 application/scripts/deploy/compose.yaml。Docker 权限具备后，执行：

```sh
python3 RELEASE/application/scripts/deploy/host_deploy.py RELEASE
```

将 RELEASE 替换为 host_prepare 输出的实际目录。脚本先复核暂存文件摘要、配置、Docker 权限、同名项目和端口；再构建、启动独立 PostgreSQL、迁移只读快照并校验字节、启动账号模式 FastAPI/Uvicorn。已存在数据库/运行文件拒绝再次初始化；失败保留候选数据供检查，不自动删除、复用或覆盖。named volume 由 NAS Docker 的持久存储管理。Python/PostgreSQL镜像已固定上游manifest digest，真正构建/拉取后另记录实际平台镜像ID。

应用固定监听 NAS `127.0.0.1:18080`，数据库固定 `127.0.0.1:15432`，不会直接开放 LAN 或公网；宿主机网络用于让两者保持显式回环 DSN，避开现有 NAS 数据库 5432 和网站端口。暂存的 HTTP Origin 仅支持 SSH 加密隧道试验：

```sh
ssh -N -L 127.0.0.1:18080:127.0.0.1:18080 Justin@100.73.240.73
```

个人管理员由用户在可信交互终端创建：

```sh
docker compose --env-file RELEASE/deployment.env -f RELEASE/application/scripts/deploy/compose.yaml exec app python scripts/deploy/container_entry.py accounts
```

密码不写在命令、环境文件、日志或聊天中。未初始化时业务 API 仍拒绝访问，且没有 HTTP 注册/初始化入口。本目录不自动创建个人账号。用于工程验证的随机密码仅存在于隔离测试实例。

团队访问前须检查 NAS 已有 Tailscale Serve/HTTPS 配置，使用独立入口，不覆盖已有代理服务；把 RKD_PUBLIC_ORIGIN 设置为确切 HTTPS Origin，重建应用实例并实测证书、Secure Cookie、Host/Origin/CSRF、角色及下载。应用忽略伪造的代理身份头，不开启 Uvicorn proxy_headers。当前 HTTP 隧道试验不计 HTTPS、多人持续试用或正式切库通过。

容器健康探针和有上限的 Docker 日志已配置；真正启动后还须实测进程故障恢复、重启、完整备份/恢复和告警。数据导入是候选快照，只有实际验证及切换后才可更改日常权威入口。正式报价、施工发布、真实外部下单和付款保持关闭。

服务方式参考 [FastAPI 容器部署](https://fastapi.tiangolo.com/deployment/docker/) 和 [Uvicorn 部署](https://uvicorn.dev/deployment/)，不是部署已验收的证明。

## 已部署 NAS 的操作

实际私有入口为 `https://fnos-nas.tailcca6f8.ts.net:9443/`，访问设备须连接同一 Tailscale 网络。9443 使用 Serve，没有启用 Funnel；保留原有 443/8443 服务。应用与数据库仍只监听回环。

本次 Docker Hub 镜像下载持续失败，因此明确采用 `compose.nas-cache.yaml` 兼容配置：已缓存、固定摘要的官方 MCR Debian Bookworm 基础镜像安装 Python 3.11.2，独立官方 PostgreSQL 16.15 容器。没有修改 NAS 宿主 Python 或其他数据库。Linux 182 项回归、4 项 ASGI 专项、真实 PG16 的 16 内核/45 业务/8 身份检查已通过；原 Python3.12/PG17 配置仍保留，升级另行验证。依赖使用同一锁文件，镜像 ID 和部署证据见状态台账。已存在的部署不要重新运行首次初始化脚本。

首位个人管理员在 Windows PowerShell 执行：

```powershell
ssh -t -i "$env:USERPROFILE\.ssh\id_ed25519_nas" Justin@100.73.240.73 "python3 /home/Justin/rkd-ai/setup-admin.py"
```

该助手自动加载实际 release 和兼容配置，交互询问用户名、显示名及两次密码。密码至少 8 字符，输入时不显示字符；不要把密码发到聊天里。初始化前没有默认账号，业务访问返回401。

`verify_nas_operations.py` 用容器内部进程信号实测自动重启，并实际重启独立数据库。`docker kill` 属于操作员停止，会抑制 restart policy，不能据此断言进程故障恢复失败。`verify_nas_recovery.py` 在首次个人账号启用前短暂停止应用以取得一致快照，归档数据库、全部引用文件和应用源代码，再恢复至新空库/新目录，实际启动归档应用验证。该脚本只适合本次尚无个人账号的部署验收；后续有人使用时应先安排维护窗口。当前备份仍在 NAS 本机，不计异机容灾或告警闭环验收。

## 日常在线备份与健康记录

用户已选择暂用工作台内提示。管理员登录后页面状态条每分钟请求账号保护的运维接口，显示检查和备份时间；异常、读取失败及检查记录超过3分钟会明确提示。普通账号无运维读取权限。宿主probe向 `operations/public` 写可只读挂载的投影文件，接口只返回白名单字段，不返回归档路径。该功能只在打开页面且连接可用时提示，外部通知按用户要求暂缓，不能替代断网/断电时的主动通知。

`nas_maintenance.py` 部署为 `/home/Justin/rkd-ai/nas-maintenance.py`，使用受限部署目录内的维护虚拟环境执行，应用容器不持有Docker权限或owner密码。`backup` 不停止服务，复制容器真实运行文件和实际 `/app` 代码，导出同一数据库只读快照；任何被快照引用的文件缺失/变化都会使备份失败，不能把并发复制结果冒称成功。成功归档再次解包逐成员校验；失败保留诊断目录，最近成功与最近尝试分别记录。没有自动清理旧备份，空间不足2GiB时拒绝并记录失败，后续应按实测容量制定保留策略。

已设置Justin的crontab独立标记段：NAS当地时间每天03:15完整备份，每分钟probe；原crontab保存在 `operations/crontab-before.txt`，其他任务保留。日志写 `operations/backup-cron.log`、`probe-cron.log`；最近状态是 `health.json`、`latest-backup-success.json`、`latest-backup-attempt.json`，异常/恢复仅在变化时追加 `events.jsonl` 并写syslog标签 `rkd-ai-monitor`。不把本机syslog冒称已发给用户的外部通知。

probe检查应用ready、两个容器健康、磁盘至少2GiB、最近成功备份不超过26小时且文件存在、最近尝试是否成功，以及私有Serve9443的实际目标和Funnel关闭。该NAS无法从宿主回连自身Tailscale Serve（用户态网络）；因此NAS检查的是Serve配置，不能替代另一台Tailscale设备的真实HTTPS检查。Windows已执行带证书校验的实际HTTPS验证。外部持续监测/主动通知仍待单独落地。

个人管理员初始化后的新在线备份也已在新空库/新目录恢复，归档应用实际启动、账号初始化状态保留、旧会话撤销、匿名业务401；未替换运行库或让现用会话失效。具体备份时点和哈希以PROJECT_STATUS及对应证据为准，早期无账号备份不能代替当前备份。

`verify_scheduled_recovery.py /home/Justin/rkd-ai` 使用最近成功的实际定时备份，先检查归档摘要，再恢复至独立新库及 `recovery-checks/` 新目录。使用同目录 `nas_maintenance.py` 生成匹配PG客户端工具；全表摘要、全部引用文件、项目、账号初始化和恢复副本无旧会话均检查，实际启动归档应用检查ready和匿名访问拒绝。全过程不停止或替换线上服务，不会自动切库。输出 `operations/latest-scheduled-recovery.json`，失败目标保留检查；恢复成功不代表已获专业批准或已验证人工密码登录。

运行告警排查：先读取 `operations/health.json` 和最近备份尝试，应用/数据库异常查看对应独立容器的health与限量日志，磁盘不足先核对备份大小和可用空间，不自动删除旧数据。备份失败保留上一成功包并检查失败目录；只在新库演练恢复，切换需单独核对当前权威数据。每分钟巡检依赖NAS本身及cron，NAS断电/全机网络故障须由另一台在线设备检测；当前尚未配置外部接收渠道，不冒称已有主动通知。


## Windows 异机副本与恢复

`scripts/sync_nas_backup.py`使用既有SSH信任和个人密钥，复制NAS最近成功的完整备份到`var/backups/nas/`。SHA及归档逐成员校验通过才发布，重复同包只核对，不自动删除旧包；失败记录与最近成功分开。`scripts/verify_offsite_restore.py`实际建立Windows回环PG17独立集群，恢复NAS归档到空库/新目录，核对全表/全部文件、启动归档应用验证账号保护，最后停止测试进程和集群；保留恢复证据，不更改现有运行库。

管理员PowerShell运行 `powershell -NoProfile -ExecutionPolicy Bypass -File "D:\Github\RKD AI\scripts\install_nas_backup_tasks.ps1"` 安装每日04:15复制、周日04:45恢复（Windows当地时间），任务只在当前用户交互登录期间执行，错过后补跑，Tailscale必须可达NAS。脚本使用pythonw避免弹窗，不存密码，保留已有同名匹配任务XML；与既有其他任务重名时拒绝替换。是否实际注册/触发须读取任务状态与`var/backups/nas/latest-*.json`，不能仅凭安装脚本存在宣称成功。
