# Builds the Windows app (dist\ThemeForge\), the portable zip and the installer.
#   powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
# Needs Python 3.10+ and Inno Setup 6 (https://jrsoftware.org/isinfo.php, or: choco install innosetup).
$ErrorActionPreference = "Stop"
$root = Resolve-Path "$PSScriptRoot\..\.."
Set-Location $root

$version = (Select-String -Path themeforge.py -Pattern '^VERSION = "([^"]+)"').Matches[0].Groups[1].Value
Write-Host "Building ThemeForge $version"

python -m pip install --upgrade -r requirements-windows.txt pyinstaller
if ($LASTEXITCODE) { throw "pip failed" }

python -m PyInstaller --noconfirm --clean --windowed --name ThemeForge `
    --icon packaging\windows\themeforge.ico `
    --collect-submodules winrt --hidden-import pyaudiowpatch `
    themeforge.py
if ($LASTEXITCODE) { throw "PyInstaller failed" }

Compress-Archive -Path dist\ThemeForge -DestinationPath dist\ThemeForge-Windows.zip -Force

$iscc = Get-Command iscc -ErrorAction SilentlyContinue
$isccPath = if ($iscc) { $iscc.Source } else { "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe" }
if (-not (Test-Path $isccPath)) { throw "Inno Setup 6 not found - install it, then run this again" }
& $isccPath "/DAppVersion=$version" packaging\windows\themeforge.iss
if ($LASTEXITCODE) { throw "Inno Setup failed" }

foreach ($f in "dist\ThemeForge-Setup.exe", "dist\ThemeForge-Windows.zip") {
    $hash = (Get-FileHash $f -Algorithm SHA256).Hash.ToLower()
    "$hash  $(Split-Path $f -Leaf)" | Out-File -Encoding ascii "$f.sha256"
}
Get-ChildItem dist -File | Format-Table Name, Length
