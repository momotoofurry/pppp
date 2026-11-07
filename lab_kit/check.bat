@echo off
rem Step 2: Trigno only. Records 60 s from the Trigno Control Utility and reports the sample rate and levels.
rem Usage: check.bat [TCU PC address] (default: this PC)
cd /d "%~dp0"
if "%1"=="" ("%~dp0TrignoBridge.exe" check --seconds 60 --out emg_check.csv) else ("%~dp0TrignoBridge.exe" check --tcu %1 --seconds 60 --out emg_check.csv)
pause
