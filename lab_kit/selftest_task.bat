@echo off
rem Self-test (SELFTEST.md, report 35.35): cue screen P0 T1 P1 T2 P2. Usage: selftest_task.bat T00 1
rem Start run.bat COMx T00_d1_A --firmware lda first. Writes T00_d1_A_task.csv here.
if "%2"=="" (echo usage: selftest_task.bat T00 1 & pause & exit /b 1)
cd /d "%~dp0"
start "" "%~dp0TaskScreen.exe" --subject %1 --day %2 --cond A --segments labelled,task,labelled,task,labelled --reps 2 --n 40 --postures selftest
