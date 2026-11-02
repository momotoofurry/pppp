@echo off
rem Step 2: Trigno only. Records 60 s from the Trigno Control Utility (localhost) and reports the sample rate and levels.
cd /d "%~dp0"
"%~dp0TrignoBridge.exe" check --seconds 60 --out emg_check.csv
pause
