<# .SYNOPSIS 查看便携版 PostgreSQL 状态与连接信息。 #>
[CmdletBinding()]
param(
    [string]$Runtime = $(if ($env:PG_RUNTIME) { $env:PG_RUNTIME } else { 'C:\pgruntime' }),
    [int]$Port = 55432
)
$bin  = Join-Path $Runtime 'pgsql\bin'
$data = Join-Path $Runtime 'pgdata'

$proc = Start-Process -FilePath (Join-Path $bin 'pg_ctl.exe') `
    -ArgumentList @('-D', $data, 'status') `
    -WindowStyle Hidden -Wait -PassThru
Write-Host "[pg] pg_ctl status exit=$($proc.ExitCode)"

$listening = (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Measure-Object).Count -gt 0
Write-Host "[pg] 端口 $Port 监听中：$listening"

$env:PGPASSWORD = 'piginject2026'
try {
    & (Join-Path $bin 'psql.exe') -h 127.0.0.1 -p $Port -U pigadmin -d pig_injection -c "\dt"
} finally {
    Remove-Item Env:\PGPASSWORD -ErrorAction SilentlyContinue
}
