<#
.SYNOPSIS
  启动本项目自带的便携版 PostgreSQL 17 实例（不注册 Windows 服务、不需要管理员）。

.NOTES
  PostgreSQL 运行时与数据目录刻意放在纯 ASCII 路径（默认 C:\pgruntime），
  因为 initdb / postgres 在中文路径下会出现编码错误。
  可用环境变量 PG_RUNTIME 覆盖。
#>
[CmdletBinding()]
param(
    [string]$Runtime = $(if ($env:PG_RUNTIME) { $env:PG_RUNTIME } else { 'C:\pgruntime' }),
    [int]$Port = 55432
)

$ErrorActionPreference = 'Stop'
$bin  = Join-Path $Runtime 'pgsql\bin'
$data = Join-Path $Runtime 'pgdata'
$log  = Join-Path $data   'server.log'

if (-not (Test-Path (Join-Path $bin 'pg_ctl.exe'))) {
    throw "找不到 PostgreSQL 运行时：$bin`n请先按 docs/03_快速开始.md 下载并解压官方 binaries 包。"
}

$running = (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count -gt 0
if ($running) {
    Write-Host "[pg] 已经在 $Port 端口运行，无需重复启动。" -ForegroundColor Yellow
    exit 0
}

# 注意：必须用 Start-Process 启动 pg_ctl，直接在 shell 里调用会因为子进程继承
# 标准输出句柄而导致命令永不返回（Windows 特有问题）。
$proc = Start-Process -FilePath (Join-Path $bin 'pg_ctl.exe') `
    -ArgumentList @('-D', $data, '-l', $log, '-w', '-t', '60', 'start') `
    -WindowStyle Hidden -Wait -PassThru

if ($proc.ExitCode -ne 0) {
    Write-Host "[pg] 启动失败，最后 30 行日志：" -ForegroundColor Red
    Get-Content $log -Tail 30
    exit $proc.ExitCode
}

Write-Host "[pg] 已启动：127.0.0.1:$Port" -ForegroundColor Green
Write-Host "[pg] 数据目录：$data"
Write-Host "[pg] 连接串：postgresql+psycopg://pigadmin:piginject2026@127.0.0.1:$Port/pig_injection"
