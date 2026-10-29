# 大肥鱼看门狗：鱼手崩溃自动拉起，卡死（心跳超时）强杀重启。
# 用法：powershell -File watchdog.ps1（建议放入开机自启，见 docs/deploy-windows.md）
$Hand = Join-Path $PSScriptRoot "fish_hand.py"
$Heartbeat = Join-Path $PSScriptRoot "fish_heartbeat"
$StaleSec = 150          # 心跳超过这么久没更新视为卡死
$CheckEvery = 15         # 看门狗巡视间隔（秒）

Write-Host "[watchdog] 看门狗上线，监视 $Hand"
while ($true) {
    if (Test-Path $Heartbeat) { Remove-Item $Heartbeat -Force }
    $p = Start-Process python -ArgumentList "`"$Hand`"" -PassThru -WorkingDirectory $PSScriptRoot
    Write-Host "[watchdog] $(Get-Date -Format 'MM-dd HH:mm:ss') 鱼手启动 PID=$($p.Id)"
    while (-not $p.HasExited) {
        Start-Sleep $CheckEvery
        if (Test-Path $Heartbeat) {
            $age = ((Get-Date) - (Get-Item $Heartbeat).LastWriteTime).TotalSeconds
            if ($age -gt $StaleSec) {
                Write-Host "[watchdog] $(Get-Date -Format 'MM-dd HH:mm:ss') 心跳超时 $([int]$age)s，强杀重启"
                Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
            }
        }
    }
    Write-Host "[watchdog] $(Get-Date -Format 'MM-dd HH:mm:ss') 鱼手退出（code $($p.ExitCode)），5s 后重启"
    Start-Sleep 5
}
