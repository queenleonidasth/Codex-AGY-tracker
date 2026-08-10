$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $ProjectRoot

function Find-Python313 {
    try {
        $FromLauncher = & py -3.13 -c "import sys; print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $FromLauncher) {
            return ($FromLauncher | Select-Object -Last 1)
        }
    } catch {
        # The launcher is optional; continue to the per-user installation path.
    }

    $PerUserPython = Join-Path $env:LOCALAPPDATA "Programs\Python\Python313\python.exe"
    if (Test-Path -LiteralPath $PerUserPython) {
        return $PerUserPython
    }
    return $null
}

$Python = Find-Python313
if (-not $Python) {
    Write-Host "Python 3.13 was not found. Installing it for the current user..."
    & winget install --id Python.Python.3.13 --scope user --accept-package-agreements --accept-source-agreements
    if ($LASTEXITCODE -ne 0) {
        throw "Python 3.13 installation failed."
    }
    $Python = Find-Python313
}
if (-not $Python) {
    throw "Python 3.13 is still unavailable after installation."
}

Write-Host "Using $Python"
if (-not (Test-Path -LiteralPath ".venv\Scripts\python.exe")) {
    & $Python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create .venv." }
}

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
& $VenvPython -m pip install --disable-pip-version-check --upgrade pip
if ($LASTEXITCODE -ne 0) { throw "pip upgrade failed." }
& $VenvPython -m pip install --disable-pip-version-check -r requirements.txt -r requirements-dev.txt
if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed." }
& $VenvPython -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed; setup was not completed." }

Write-Host "Setup complete. Run .\run.bat, or build the executable with .\build.ps1."
