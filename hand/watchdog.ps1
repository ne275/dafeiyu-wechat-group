# 大肥鱼看门狗：鱼手崩溃自动拉起，卡死（心跳超时）强杀重启。
# 用法：powershell -File watchdog.ps1（建议放入开机自启，见 docs/deploy-windows.md）
$Hand = Join-Path $PSScriptRoot "fish_hand.py"
$Heartbeat = Join-Path $PSScriptRoot "fish_heartbeat"
$StaleSec = 150          # 心跳超过这么久没更新视为卡死
$CheckEvery = 15         # 看门狗巡视间隔（秒）

$LogFile = Join-Path $PSScriptRoot "watchdog.log"

# 防待机：UIA 需要活跃桌面（RPA 标准做法）
Add-Type -AssemblyName System.Windows.Forms
Add-Type @"
using System; using System.Runtime.InteropServices;
public class Win32 {
  [DllImport("user32.dll")] public static extern bool ShowWindowAsync(IntPtr hWnd, int nCmdShow);
  [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
}
"@

function Keep-Alive {
    # 微信窗口被最小化则还原（最小化时停止渲染消息列表）
    foreach ($name in @("Weixin", "WeChat")) {
        $proc = Get-Process $name -ErrorAction SilentlyContinue
        if ($proc -and $proc.MainWindowHandle -ne [IntPtr]::Zero) {
            if ([Win32]::IsIconic($proc.MainWindowHandle)) {
                [Win32]::ShowWindowAsync($proc.MainWindowHandle, 9) | Out-Null  # SW_RESTORE
                wlog "检测到微信窗口最小化，已还原"
            }
        }
    }
    # 鼠标微动 1px：防 Windows 空闲降级渲染管线
    $p = [System.Windows.Forms.Cursor]::Position
    [System.Windows.Forms.Cursor]::Position = New-Object System.Drawing.Point(($p.X + 1), $p.Y)
    [System.Windows.Forms.Cursor]::Position = $p
}

function wlog($msg) {
    $line = "[watchdog] $(Get-Date -Format 'MM-dd HH:mm:ss') $msg"
    Write-Host $line
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

wlog "看门狗上线，监视 $Hand"
while ($true) {
    if (Test-Path $Heartbeat) { Remove-Item $Heartbeat -Force }
    $p = Start-Process python -ArgumentList "`"$Hand`"" -PassThru -WorkingDirectory $PSScriptRoot
    wlog "鱼手启动 PID=$($p.Id)"
    while (-not $p.HasExited) {
        Start-Sleep $CheckEvery
        Keep-Alive
        if (Test-Path $Heartbeat) {
            $age = ((Get-Date) - (Get-Item $Heartbeat).LastWriteTime).TotalSeconds
            if ($age -gt $StaleSec) {
                wlog "心跳超时 $([int]$age)s，强杀重启"
                Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue
            }
        }
    }
    wlog "鱼手退出（code $($p.ExitCode)），5s 后重启"
    Start-Sleep 5
}
