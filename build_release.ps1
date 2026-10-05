$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python is required to build this release."
}
python -m PyInstaller --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "Install PyInstaller with: python -m pip install pyinstaller"
}

$releaseDirectory = Join-Path $PSScriptRoot "dist\v1.1.1"
$workDirectory = Join-Path $PSScriptRoot "build\release\v1.1.1"
New-Item -ItemType Directory -Force $releaseDirectory | Out-Null
New-Item -ItemType Directory -Force $workDirectory | Out-Null
Remove-Item -LiteralPath (Join-Path $releaseDirectory "BlytheEyeMaker.exe"), (Join-Path $releaseDirectory "BlytheEyeMakerAssets.zip") -Force -ErrorAction SilentlyContinue

python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --windowed `
    --name BlytheEyeMaker `
    --icon "app\branding\BlytheEyeMaker.ico" `
    --add-data "app\branding\BlytheEyeMaker.ico;branding" `
    --collect-all tkinterdnd2 `
    --hidden-import blythe_ai `
    --hidden-import customer_portal `
    --workpath $workDirectory `
    --distpath $releaseDirectory `
    "app\blythe_a4_maker.pyw"
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed."
}

$assetSource = Join-Path $workDirectory "asset-package\cover_assets"
$templateSource = "app\cover_assets\templates_gpt_blank"
New-Item -ItemType Directory -Force (Join-Path $assetSource "templates_gpt_blank") | Out-Null
Copy-Item -LiteralPath "app\cover_assets\doll_cover_base.png" -Destination $assetSource
Copy-Item -LiteralPath "app\cover_assets\doll_cover_overlay.png" -Destination $assetSource
Copy-Item -LiteralPath (Join-Path $templateSource "manifest.json") -Destination (Join-Path $assetSource "templates_gpt_blank")
Copy-Item -Path (Join-Path $templateSource "template_*.png") -Destination (Join-Path $assetSource "templates_gpt_blank")
Compress-Archive -Path $assetSource -DestinationPath (Join-Path $releaseDirectory "BlytheEyeMakerAssets.zip") -CompressionLevel Optimal
if (-not (Test-Path (Join-Path $releaseDirectory "BlytheEyeMaker.exe")) -or -not (Test-Path (Join-Path $releaseDirectory "BlytheEyeMakerAssets.zip"))) {
    throw "The EXE or first-run asset package is missing."
}

Write-Host "Release files are ready in $releaseDirectory"
