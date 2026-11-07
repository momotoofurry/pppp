@echo off
rem End of each day: are the files of one session complete? Usage: verify.bat T00_d1 [--rate 1926]
rem (--rate only when run.bat was started with --rate). OK = copy the files to the USB stick now.
if "%1"=="" (echo usage: verify.bat T00_d1 & pause & exit /b 1)
cd /d "%~dp0"
"%~dp0TrignoBridge.exe" verify --name %1 %2 %3
pause
