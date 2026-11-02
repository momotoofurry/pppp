@echo off
rem Step 1: STM32 only. Usage: replay.bat COM5
if "%1"=="" (echo usage: replay.bat COM5 & pause & exit /b 1)
cd /d "%~dp0"
"%~dp0TrignoBridge.exe" replay --port %1 --dir board_replay
pause
