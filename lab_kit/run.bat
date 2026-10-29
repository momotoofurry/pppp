@echo off
rem Step 3: Trigno -> PC -> STM32. Usage: run.bat COM5 [--rate 2000]
if "%1"=="" (echo usage: run.bat COM5 & pause & exit /b 1)
cd /d "%~dp0"
TrignoBridge.exe run --port %1 %2 %3 --emg-csv emg.csv --mcu-csv mcu.csv
pause
