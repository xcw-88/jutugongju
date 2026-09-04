$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath 'license_admin/license_private.pem')) {
    throw 'Private signing key is missing. Do not generate a new key unless intentionally rotating every customer license.'
}
python -m pip install -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
python -m pytest -q
if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
python -m PyInstaller --noconfirm EvidenceLicenseManager.spec
if ($LASTEXITCODE -ne 0) { throw 'License manager build failed.' }
Write-Host 'Private owner-only tool ready: dist/聊天软件截屏助手授权管理器.exe'
