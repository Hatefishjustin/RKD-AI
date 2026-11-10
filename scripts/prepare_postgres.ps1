param()
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$toolRoot = Join-Path $projectRoot 'var/tools/postgresql-17.11-5'
$archive = Join-Path $toolRoot 'postgresql-17.11-5-windows-x64-binaries.zip'
$downloadUrl = 'https://get.enterprisedb.com/postgresql/postgresql-17.11-5-windows-x64-binaries.zip'
$expectedHash = '80379b2c04d51c30225532e0ae04509899141e9957ed096fe749d7fd9df8f82f'
New-Item -ItemType Directory -Path $toolRoot -Force | Out-Null
if (-not (Test-Path -LiteralPath $archive) -or (Get-Item -LiteralPath $archive).Length -ne 381531864) {
    & (Join-Path $projectRoot '.venv/Scripts/python.exe') (Join-Path $PSScriptRoot 'download_postgres.py')
    if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL download failed; partial archive retained.' }
}
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $expectedHash) {
    throw 'PostgreSQL archive checksum mismatch; archive retained for inspection.'
}
if (-not (Test-Path -LiteralPath (Join-Path $toolRoot 'provenance.json')) -or -not (Test-Path -LiteralPath (Join-Path $toolRoot 'pgsql/bin/postgres.exe'))) {
    Expand-Archive -LiteralPath $archive -DestinationPath $toolRoot -Force
}
& (Join-Path $toolRoot 'pgsql/bin/postgres.exe') --version
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL binary check failed' }
& (Join-Path $projectRoot '.venv/Scripts/python.exe') -m pip install --disable-pip-version-check -r (Join-Path $projectRoot 'mvp/requirements-postgres.txt')
if ($LASTEXITCODE -ne 0) { throw 'PostgreSQL driver installation failed' }
@{ version = '17.11-5'; url = $downloadUrl; sha256 = $expectedHash } | ConvertTo-Json | Set-Content -Encoding utf8 (Join-Path $toolRoot 'provenance.json')
