@echo off
rem Step 4: cue screen for one condition (PROTOCOL.md 4.1). Usage: task.bat S01 2 A [TaskScreen options]
rem Start run.bat first: it forwards the board's commands to this screen. Writes S01_d2_A_task.csv here.
if "%3"=="" (echo usage: task.bat S01 2 A & pause & exit /b 1)
cd /d "%~dp0"
start "" "%~dp0TaskScreen.exe" --subject %1 --day %2 --cond %3 %4 %5 %6 %7 %8 %9
