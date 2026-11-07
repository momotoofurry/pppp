@echo off
rem Step 0 (once, before the first session): what the Trigno Control Utility answers. Usage: probe.bat [TCU PC address]
rem Asks questions only (no setting is changed); writes tcu_probe.txt: bring it back if anything looks wrong.
cd /d "%~dp0"
if "%1"=="" ("%~dp0TrignoBridge.exe" probe --out tcu_probe.txt) else ("%~dp0TrignoBridge.exe" probe --tcu %1 --out tcu_probe.txt)
pause
