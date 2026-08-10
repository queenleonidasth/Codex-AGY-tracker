$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
Set-Location -LiteralPath $ProjectRoot

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$PyInstaller = Join-Path $ProjectRoot ".venv\Scripts\pyinstaller.exe"
if (-not (Test-Path -LiteralPath $VenvPython) -or -not (Test-Path -LiteralPath $PyInstaller)) {
    throw "Development environment is missing. Run .\setup.ps1 first."
}

& $VenvPython -m pytest -q
if ($LASTEXITCODE -ne 0) { throw "Tests failed; executable was not built." }

$Targets = @(
    (Join-Path $ProjectRoot "build"),
    (Join-Path $ProjectRoot "dist\AIUsageTracker")
)
$AllowedPrefix = $ProjectRoot.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
foreach ($Target in $Targets) {
    $ResolvedTarget = [System.IO.Path]::GetFullPath($Target)
    if (-not $ResolvedTarget.StartsWith($AllowedPrefix, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a path outside the project: $ResolvedTarget"
    }
    if (Test-Path -LiteralPath $ResolvedTarget) {
        Remove-Item -LiteralPath $ResolvedTarget -Recurse -Force
    }
}

& $PyInstaller --noconfirm AIUsageTracker.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

$Executable = Join-Path $ProjectRoot "dist\AIUsageTracker\AIUsageTracker.exe"
if (-not (Test-Path -LiteralPath $Executable)) {
    throw "Build finished without the expected executable: $Executable"
}
Write-Host "Built $Executable"
