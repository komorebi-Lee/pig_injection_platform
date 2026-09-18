<# .SYNOPSIS 停止本项目自带的便携版 PostgreSQL 实例。 #>
[CmdletBinding()]
param(
    [string]$Runtime = $(if ($env:PG_RUNTIME) { $env:PG_RUNTIME } else { 'C:\pgruntime' })
)
$ErrorActionPreference = 'Stop'
$bin  = Join-Path $Runtime 'pgsql\bin'
$data = Join-Path $Runtime 'pgdata'

if (-not (Test-Path $data)) { throw "找不到数据目录：$data" }

$proc = Start-Process -FilePath (Join-Path $bin 'pg_ctl.exe') `
    -ArgumentList @('-D', $data, '-m', 'fast', '-w', '-t', '60', 'stop') `
    -WindowStyle Hidden -Wait -PassThru

Write-Host "[pg] 停止完成，exit=$($proc.ExitCode)" -ForegroundColor Green
