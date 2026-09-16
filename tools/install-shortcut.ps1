# Creates a desktop shortcut for eDEX-Deck.
#
# Run this once from a normal PowerShell window:
#   powershell -ExecutionPolicy Bypass -File tools\install-shortcut.ps1
#
# It only creates a .lnk on your Desktop; nothing else is touched.

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$launch = Join-Path $root "launch.cmd"

if (-not (Test-Path $launch)) {
    Write-Host "[x] launch.cmd not found next to src/ — is this the project root?" -ForegroundColor Red
    exit 1
}

$desktop = [Environment]::GetFolderPath("Desktop")
$lnkPath = Join-Path $desktop "eDEX-Deck.lnk"

$shell = New-Object -ComObject WScript.Shell
$lnk = $shell.CreateShortcut($lnkPath)
$lnk.TargetPath = $launch
$lnk.WorkingDirectory = $root
$lnk.Description = "eDEX-Deck - non-invasive UI layer for eDEX-UI"

$icon = Join-Path $root "assets\logo.ico"
if (Test-Path $icon) { $lnk.IconLocation = $icon }

$lnk.Save()

Write-Host "[ok] shortcut created:" $lnkPath -ForegroundColor Green
Write-Host "     target:" $launch
