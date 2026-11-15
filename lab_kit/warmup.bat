@echo off
rem Warm-up before the self-test recording (not analysed): 6 cues + 10 commands with the real board, code W00.
rem Run AFTER the cued pass (cal 0-5, calibrate) and BEFORE selftest_task.bat. Usage: warmup.bat 1   (the day number)
rem Writes W00_d<day>_A_task.csv; selftest_analysis.py and verify.bat T00_d1_A never read it. Run it again if needed.
if "%1"=="" (echo usage: warmup.bat 1 & pause & exit /b 1)
cd /d "%~dp0"
start "" "%~dp0TaskScreen.exe" --subject W00 --day %1 --cond A --segments labelled,task --reps 1 --n 10 --postures selftest
