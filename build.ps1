# Builds dist\Wallflow\Wallflow.exe and release\Wallflow-Setup-<version>.exe
# Usage:  powershell -ExecutionPolicy Bypass -File build.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$version = (Select-String -Path core.py -Pattern 'VERSION = "(.+)"').Matches[0].Groups[1].Value
Write-Host "Building Wallflow $version"

python -m pip install --quiet -r requirements.txt pyinstaller
python -m PyInstaller --noconfirm --clean --windowed --name Wallflow --icon wallflow.ico `
    --add-data "wallflow.ico;." --collect-data customtkinter --hidden-import pystray._win32 Wallflow.pyw
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }

$iscc = Get-ChildItem "$env:LOCALAPPDATA\Programs\Inno Setup*\ISCC.exe", "C:\Program Files*\Inno Setup*\ISCC.exe" `
    -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup not found. Install it: winget install JRSoftware.InnoSetup" }
& $iscc.FullName "/DMyAppVersion=$version" installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }

Write-Host "Done: release\Wallflow-Setup-$version.exe"
