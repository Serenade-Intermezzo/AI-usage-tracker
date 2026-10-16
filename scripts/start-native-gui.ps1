$ErrorActionPreference = 'Stop'
$trackerRoot = Split-Path $PSScriptRoot -Parent
$nativePython = Join-Path $trackerRoot '.venv-gui\Scripts\pythonw.exe'
if (-not (Test-Path $nativePython)) { throw 'Run scripts\install-native-windows.cmd first.' }
$nativeScript = Join-Path $trackerRoot 'gui\main.py'
Start-Process -FilePath $nativePython -ArgumentList ('"' + $nativeScript + '"') -WorkingDirectory $trackerRoot
