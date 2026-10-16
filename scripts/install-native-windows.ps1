param([switch]$NoLaunch, [switch]$SkipShortcuts)
$ErrorActionPreference = 'Stop'
$trackerRoot = Split-Path $PSScriptRoot -Parent
Set-Location $trackerRoot
$nodeCommand = Get-Command node -ErrorAction SilentlyContinue
$npmCommand = Get-Command npm.cmd -ErrorAction SilentlyContinue
if (-not $nodeCommand -or -not $npmCommand) { throw 'Install Node.js 22.5+ (LTS) first, then rerun this installer.' }
& $nodeCommand.Source -e 'const [a,b]=process.versions.node.split(".").map(Number); process.exit(a>22 || a===22&&b>=5 ? 0 : 1)'
if ($LASTEXITCODE -ne 0) { throw 'Node.js 22.5 or newer is required.' }
$trackerPython = $null
$trackerPythonArgs = @()
foreach ($candidate in @('py', 'python', 'python3')) {
    $command = Get-Command $candidate -ErrorAction SilentlyContinue
    if (-not $command) { continue }
    $testArgs = @()
    if ($candidate -eq 'py') { $testArgs = @('-3') }
    & $command.Source @testArgs -c 'import sys;sys.exit(0 if sys.version_info >= (3,10) else 1)'
    if ($LASTEXITCODE -eq 0) { $trackerPython = $command.Source; $trackerPythonArgs = $testArgs; break }
}
if (-not $trackerPython) { throw 'Install Python 3.10+ from python.org first, then rerun this installer.' }
$venvPython = Join-Path $trackerRoot '.venv-gui\Scripts\python.exe'
$venvPythonw = Join-Path $trackerRoot '.venv-gui\Scripts\pythonw.exe'
if (-not (Test-Path $venvPython)) {
    & $trackerPython @trackerPythonArgs -m venv (Join-Path $trackerRoot '.venv-gui')
    if ($LASTEXITCODE -ne 0) { throw 'Could not create the GUI Python environment.' }
}
& $venvPython -m pip install -r (Join-Path $trackerRoot 'gui\requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Could not install the native Qt GUI dependency.' }
& $npmCommand.Source ci --ignore-scripts --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { throw 'Could not install the local backend dependencies.' }
& $npmCommand.Source run build:native
if ($LASTEXITCODE -ne 0) { throw 'Could not build the local backend.' }
if (-not $SkipShortcuts) {
$shell = New-Object -ComObject WScript.Shell
$desktop = [Environment]::GetFolderPath('Desktop')
$startup = [Environment]::GetFolderPath('Startup')
$nativeScript = Join-Path $trackerRoot 'gui\main.py'
$iconFile = Join-Path $trackerRoot 'public\ai-usage-tracker.ico'
$shortcut = $shell.CreateShortcut((Join-Path $desktop 'Codex Usage Tracker.lnk'))
$shortcut.TargetPath = $venvPythonw
$shortcut.Arguments = '"' + $nativeScript + '"'
$shortcut.WorkingDirectory = $trackerRoot
if (Test-Path $iconFile) { $shortcut.IconLocation = $iconFile }
$shortcut.Save()
$background = $shell.CreateShortcut((Join-Path $startup 'Codex Usage Background.lnk'))
$background.TargetPath = $venvPythonw
$background.Arguments = '"' + $nativeScript + '" --backend-only'
$background.WorkingDirectory = $trackerRoot
$background.Save()
}
Write-Host 'Installed. Desktop shortcut opens the native GUI; background tracking starts at sign-in.'
if (-not $NoLaunch) {
    $nativeScript = Join-Path $trackerRoot 'gui\main.py'
    Start-Process -FilePath $venvPythonw -ArgumentList ('"' + $nativeScript + '"') -WorkingDirectory $trackerRoot
}
