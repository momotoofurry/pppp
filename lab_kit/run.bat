@echo off
rem Step 3: Trigno -> PC -> STM32. Usage: run.bat COM5 [S01_d2_A] [--rate 2000] [--tcu <TCU PC address>]
rem Files <name>_emg.csv, <name>_mcu.csv, <name>_ops.csv (name = subject code, day, condition; never a person's name)
if "%1"=="" (echo usage: run.bat COM5 [S01_d2_A] & pause & exit /b 1)
cd /d "%~dp0"
set NAME=%2
if "%NAME%"=="" set NAME=session
if "%NAME:~0,2%"=="--" (echo usage: run.bat COM5 S01_d2_A --rate 1926 & pause & exit /b 1)
if exist %NAME%_emg.csv (echo %NAME%_emg.csv already exists: use another name & pause & exit /b 1)
"%~dp0TrignoBridge.exe" run --port %1 %3 %4 %5 %6 --emg-csv %NAME%_emg.csv --mcu-csv %NAME%_mcu.csv --ops-csv %NAME%_ops.csv
pause
