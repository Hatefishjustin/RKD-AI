param(
    [ValidateSet("prepare", "check", "test", "start", "start-secure")]
    [string]$Command = "check"
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
