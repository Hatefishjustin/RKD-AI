param(
    [ValidateSet("prepare", "check", "test", "start", "start-ai-synthetic", "start-ai-real", "start-secure", "postgres-prepare", "postgres-test", "postgres-api", "postgres-accounts", "postgres-backup", "postgres-restore", "backup", "restore")]
    [string]$Command = "check",
    [string]$Archive,
    [string]$Destination
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BundledPython = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$ProjectPython = Join-Path $Root ".venv\Scripts\python.exe"

function Resolve-BootstrapPython {
    if ($env:RKD_PYTHON -and (Test-Path -LiteralPath $env:RKD_PYTHON)) { return $env:RKD_PYTHON }
    if (Test-Path -LiteralPath $BundledPython) { return $BundledPython }
    $candidate = Get-Command python -ErrorAction SilentlyContinue
    if ($candidate -and $candidate.Source -notlike "*WindowsApps*") { return $candidate.Source }
    throw "找不到可用 Python。请设置 RKD_PYTHON，或保留工作区配套 Python。"
}

function Resolve-ProjectPython {
    if (Test-Path -LiteralPath $ProjectPython) { return $ProjectPython }
    return Resolve-BootstrapPython
}

function Invoke-EnvironmentCheck([switch]$Strict) {
    $python = Resolve-ProjectPython
    $args = @("$Root\scripts\check_environment.py", "--root", $Root)
    if ($Strict) { $args += "--strict" }
    & $python @args
    if ($LASTEXITCODE -ne 0) { throw "本地环境检查失败。请查看 var\logs\environment-check.json。" }
}

function Ensure-Frontend {
    $webRoot = Join-Path $Root "web"
    $npm = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $npm) { throw "找不到 npm。请安装 Node.js 20+ 后重试。" }
    if (-not (Test-Path -LiteralPath (Join-Path $webRoot "node_modules"))) {
        & $npm.Source --prefix $webRoot install --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw "安装前端依赖失败。" }
    }
    & $npm.Source --prefix $webRoot run build
    if ($LASTEXITCODE -ne 0) { throw "构建前端失败。" }
}

switch ($Command) {
    "postgres-backup" {
        $python = Resolve-ProjectPython
        $backupArgs = @((Join-Path $Root "scripts\postgres_backup.py"), "backup")
        if ($Archive) { $backupArgs += @("--archive", $Archive) }
        & $python @backupArgs
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    "postgres-restore" {
        if (-not $Archive -or -not $Destination) { throw "PG 恢复需要 -Archive 和新 -Destination，以及指向空目标数据库的维护 DSN。" }
        $python = Resolve-ProjectPython
        & $python (Join-Path $Root "scripts\postgres_backup.py") restore --archive $Archive --destination $Destination
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    "postgres-accounts" {
        $python = Resolve-ProjectPython
        & $python (Join-Path $Root "scripts\manage_accounts.py") --postgres
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    "postgres-api" {
        $python = Resolve-ProjectPython
        & $python (Join-Path $Root "mvp\run_postgres_api.py")
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    "backup" {
        $python = Resolve-ProjectPython
        & $python (Join-Path $Root "scripts\local_backup.py") backup
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    "restore" {
        if (-not $Archive -or -not $Destination) { throw "恢复需要 -Archive 备份包路径 -Destination 新目录；不会覆盖现有运行库。" }
        $python = Resolve-ProjectPython
        & $python (Join-Path $Root "scripts\local_backup.py") restore $Archive $Destination
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    "postgres-prepare" {
        & (Join-Path $PSScriptRoot "prepare_postgres.ps1")
    }
    "postgres-test" {
        $python = Resolve-ProjectPython
        & $python (Join-Path $PSScriptRoot "verify_postgres.py")
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    "prepare" {
        $bootstrap = Resolve-BootstrapPython
        if (-not (Test-Path -LiteralPath $ProjectPython)) {
            & $bootstrap -m venv (Join-Path $Root ".venv")
            if ($LASTEXITCODE -ne 0) { throw "创建 .venv 失败。" }
        }
        & $ProjectPython -m pip install --disable-pip-version-check --requirement (Join-Path $Root "requirements.lock")
        if ($LASTEXITCODE -ne 0) { throw "安装 requirements.lock 失败。" }
        Ensure-Frontend
        Invoke-EnvironmentCheck -Strict
    }
    "check" {
        $strict = Test-Path -LiteralPath $ProjectPython
        Invoke-EnvironmentCheck -Strict:$strict
    }
    "test" {
        $strict = Test-Path -LiteralPath $ProjectPython
        Invoke-EnvironmentCheck -Strict:$strict
        Ensure-Frontend
        $python = Resolve-ProjectPython
        $env:PYTHONPATH = Join-Path $Root "mvp"
        & $python -m unittest discover -s (Join-Path $Root "mvp\tests") -v
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    }
    "start" {
        Invoke-EnvironmentCheck
        Ensure-Frontend
        $python = Resolve-ProjectPython
        $env:PYTHONPATH = Join-Path $Root "mvp"
        & $python (Join-Path $Root "mvp\run_api_server.py")
    }
    "start-ai-synthetic" {
        Invoke-EnvironmentCheck
        Ensure-Frontend
        $python = Resolve-ProjectPython
        $env:RKD_AI_PROVIDER = "synthetic"
        $env:RKD_AI_DESIGN_PROVIDER = "synthetic"
        $env:RKD_AI_EXTERNAL_CONTEXT = "false"
        $env:PYTHONPATH = Join-Path $Root "mvp"
        & $python (Join-Path $Root "mvp\run_api_server.py")
    }
    "start-ai-real" {
        if (-not $env:RKD_AI_API_KEY) { throw "请先在终端设置 RKD_AI_API_KEY（仅当前会话，不要写入任何文件）后重试。" }
        Invoke-EnvironmentCheck -Strict
        Ensure-Frontend
        $python = Resolve-ProjectPython
        $env:RKD_AI_PROVIDER = "openai-compatible"
        $env:RKD_AI_DESIGN_PROVIDER = "openai-compatible"
        if (-not $env:RKD_AI_BASE_URL) { $env:RKD_AI_BASE_URL = "https://api.codelink.chat/v1" }
        if (-not $env:RKD_AI_MODEL) { $env:RKD_AI_MODEL = "gpt-5.6-sol" }
        if (-not $env:RKD_AI_EXTERNAL_CONTEXT) { $env:RKD_AI_EXTERNAL_CONTEXT = "false" }
        if (-not $env:RKD_AI_RUN_LOG_DIR) { $env:RKD_AI_RUN_LOG_DIR = Join-Path $Root "var\ai-model-runs" }
        $env:PYTHONPATH = Join-Path $Root "mvp"
        & $python (Join-Path $Root "mvp\run_api_server.py")
    }
    "start-secure" {
        Invoke-EnvironmentCheck -Strict
        Ensure-Frontend
        $python = Resolve-ProjectPython
        & $python (Join-Path $Root "scripts\manage_accounts.py")
        if ($LASTEXITCODE -ne 0) { throw "账号初始化未完成。" }
        $env:RKD_AUTH_MODE = "accounts"
        $env:PYTHONPATH = Join-Path $Root "mvp"
        & $python (Join-Path $Root "mvp\run_api_server.py")
    }
}
