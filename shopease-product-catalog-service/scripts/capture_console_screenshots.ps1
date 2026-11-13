# Terminal and editor submission screenshots (Task 12, items 1, 3, 16 and 18).
#
#   powershell -ExecutionPolicy Bypass -File scripts\capture_console_screenshots.ps1 [-Only 03]
#
# For each item a real console window (conhost) opens in the project folder and runs the real
# command. When the command has finished, the window is captured with the Windows PrintWindow API
# and saved as PNG under DELIVERABELS\screenshots\submission\<item folder>\, then the window is closed.
# The MySQL command uses the container's own MYSQL_USER / MYSQL_PASSWORD variables, so no password
# appears on screen or in this script.
# Item 01 starts a separate VS Code instance (its own temporary profile, so your open VS Code window is
# not used or changed), opens the project with app\core\config.py so the Explorer shows the tree,
# captures that window and closes only that instance.
param([string[]]$Only = @("01", "03", "03b", "16", "18"))
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$out = Join-Path $root "DELIVERABELS\screenshots\submission"
$work = Join-Path $env:TEMP "catalog_console_shots"
New-Item -ItemType Directory -Force $work | Out-Null

Add-Type -AssemblyName System.Drawing
Add-Type @"
using System; using System.Runtime.InteropServices;
public static class Win {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr h, IntPtr hdc, uint flags);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
}
"@

$items = @(
  @{ id = "03"; folder = "03_mysql_database_and_tables"; file = "mysql_tables.png"; wait = 60; lines = @(
      '"SELECT DATABASE(); SHOW TABLES;" | docker exec -i shopease-product-catalog-service-catalog-mysql-1 sh -c ''mysql -t -u$MYSQL_USER -p$MYSQL_PASSWORD $MYSQL_DATABASE 2>/dev/null''') },
  @{ id = "03b"; folder = "03_mysql_database_and_tables"; file = "describe_products.png"; wait = 60; lines = @(
      '"DESCRIBE products;" | docker exec -i shopease-product-catalog-service-catalog-mysql-1 sh -c ''mysql -t -u$MYSQL_USER -p$MYSQL_PASSWORD $MYSQL_DATABASE 2>/dev/null''') },
  @{ id = "16"; folder = "16_docker_containers_running"; file = "docker_compose_ps.png"; wait = 60; lines = @(
      'docker compose -f docker-compose.yml -f docker-compose.dev.yml ps --format "table {{.Service}}	{{.Image}}	{{.Status}}	{{.Ports}}"',
      'docker volume ls --filter name=shopease-product-catalog-service') },
  @{ id = "18"; folder = "18_passing_automated_tests"; file = "pytest_passed.png"; wait = 900; lines = @(
      '.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider 2>&1 | Select-Object -Last 12') }
)

if ($Only -contains "01") {
  $profile = Join-Path $work "vscode-profile"
  $code = (Get-Command code.cmd).Source
  $before = @(Get-Process Code -ErrorAction SilentlyContinue | ForEach-Object Id)
  # When this runs inside VS Code, inherited variables (ELECTRON_RUN_AS_NODE, VSCODE_*) would stop a new window opening.
  Get-ChildItem env: | Where-Object Name -match '^(VSCODE_|ELECTRON_RUN_AS_NODE)' | ForEach-Object { Remove-Item "env:$($_.Name)" }
  & $code -n --user-data-dir "$profile" --extensions-dir (Join-Path $profile "ext") --disable-workspace-trust --disable-extensions `
      "$root" (Join-Path $root "app\core\config.py")
  $h = [IntPtr]::Zero
  for ($i = 0; $i -lt 60 -and $h -eq [IntPtr]::Zero; $i++) {
    Start-Sleep -Milliseconds 500
    $new = Get-Process Code -ErrorAction SilentlyContinue | Where-Object { $before -notcontains $_.Id -and $_.MainWindowTitle -like "*config.py*" }
    if ($new) { $h = @($new)[0].MainWindowHandle }
  }
  if ($h -eq [IntPtr]::Zero) { throw "item 01: the VS Code window did not open" }
  [Win]::ShowWindow($h, 3) | Out-Null   # maximize
  Start-Sleep -Seconds 6                # let the Explorer and editor render
  $r = New-Object Win+RECT
  [Win]::GetWindowRect($h, [ref]$r) | Out-Null
  $bmp = New-Object Drawing.Bitmap ($r.R - $r.L), ($r.B - $r.T)
  $g = [Drawing.Graphics]::FromImage($bmp); $hdc = $g.GetHdc()
  [Win]::PrintWindow($h, $hdc, 2) | Out-Null
  $g.ReleaseHdc($hdc); $g.Dispose()
  $dir = Join-Path $out "01_vscode_project_structure"
  New-Item -ItemType Directory -Force $dir | Out-Null
  $bmp.Save((Join-Path $dir "vscode_project_structure.png"), [Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose()
  # Close only the processes of this separate instance (new since the start and using the temporary profile).
  Get-CimInstance Win32_Process -Filter "Name='Code.exe'" | Where-Object { $before -notcontains $_.ProcessId -and $_.CommandLine -like "*$profile*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
  Write-Output "saved 01_vscode_project_structurescode_project_structure.png"
}

foreach ($item in $items | Where-Object { $Only -contains $_.id }) {
  $done = Join-Path $work "$($item.id).done"
  Remove-Item $done -ErrorAction SilentlyContinue
  $script = Join-Path $work "$($item.id).ps1"
  $body = @(
    '$Host.UI.RawUI.WindowTitle = "ShopEase Product Catalog Service - evidence"',
    '$m = $Host.UI.RawUI.MaxPhysicalWindowSize; $w = [Math]::Min(160, $m.Width); $hh = [Math]::Min(50, $m.Height)',
    'try { $Host.UI.RawUI.BufferSize = New-Object Management.Automation.Host.Size($w, 3000) } catch {}',
    'try { $Host.UI.RawUI.WindowSize = New-Object Management.Automation.Host.Size($w, $hh) } catch {}',
    "Set-Location '$root'",
    'Clear-Host',
    'Write-Host ("[" + (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd HH:mm:ss") + " UTC]  " + (Get-Location).Path) -ForegroundColor Cyan'
  )
  foreach ($line in $item.lines) {
    $body += 'Write-Host ("PS> " + ' + "'" + $line.Replace("'", "''") + "'" + ') -ForegroundColor Yellow'
    $body += $line
  }
  $body += 'Add-Type -Name Con -Namespace W -MemberDefinition ''[DllImport("kernel32.dll")] public static extern IntPtr GetConsoleWindow();'''
  $body += "[W.Con]::GetConsoleWindow().ToInt64() | Set-Content '$done'"
  Set-Content -Path $script -Value $body -Encoding UTF8

  $proc = Start-Process conhost.exe -ArgumentList "powershell.exe -NoProfile -NoExit -ExecutionPolicy Bypass -File `"$script`"" -PassThru
  $deadline = (Get-Date).AddSeconds($item.wait)
  while (-not (Test-Path $done) -and (Get-Date) -lt $deadline) { Start-Sleep -Milliseconds 500 }
  if (-not (Test-Path $done)) { Stop-Process -Id $proc.Id -Force; throw "item $($item.id): command did not finish in time" }
  Start-Sleep -Seconds 1
  $h = [IntPtr][long](Get-Content $done)
  if ($h -eq [IntPtr]::Zero) { Stop-Process -Id $proc.Id -Force; throw "item $($item.id): no console window handle" }
  $r = New-Object Win+RECT
  [Win]::ShowWindow($h, 9) | Out-Null  # restore, in case the window was minimized meanwhile
  for ($i = 0; $i -lt 20; $i++) {  # wait until the window has its real size (it can still be opening or resizing)
    [Win]::GetWindowRect($h, [ref]$r) | Out-Null
    if (($r.R - $r.L) -gt 300 -and ($r.B - $r.T) -gt 200) { break }
    Start-Sleep -Milliseconds 500
  }
  if (($r.R - $r.L) -le 300) { Stop-Process -Id $proc.Id -Force; throw "item $($item.id): window too small to capture" }
  $bmp = New-Object Drawing.Bitmap ($r.R - $r.L), ($r.B - $r.T)
  $g = [Drawing.Graphics]::FromImage($bmp)
  $hdc = $g.GetHdc()
  [Win]::PrintWindow($h, $hdc, 2) | Out-Null
  $g.ReleaseHdc($hdc); $g.Dispose()
  $dir = Join-Path $out $item.folder
  New-Item -ItemType Directory -Force $dir | Out-Null
  $file = Join-Path $dir $item.file
  $bmp.Save($file, [Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose()
  Stop-Process -Id $proc.Id -Force
  Write-Output "saved $($item.folder)\$($item.file)"
}
