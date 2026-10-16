@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-native-windows.ps1"
if errorlevel 1 pause
