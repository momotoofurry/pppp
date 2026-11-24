# 2026-11-25 dry run of next week's S7 recording (report 35.96): deployed TrignoBridge / TaskScreen (copies), the real
# board (rtl_task_s7f, COM6), a fake TCU replaying T00_d2_G, the panel's S7 arguments; subject Z99 so nothing collides.
$ErrorActionPreference = 'Stop'
$sp = "C:\Users\kirit\AppData\Local\Temp\claude\f717a9ffb3f804d0\940361ee-1e88-4b6f-b364-4f25c47f2d6e\scratchpad"
$run = "$sp\dry96"
$kit = "C:\Users\kirit\Downloads\lab_kit_selftest"
$py = "C:\Users\kirit\AppData\Local\Programs\Python\Python310\python.exe"
$cli = 'C:\Users\kirit\AppData\Local\stm32cube\bundles\programmer\2.23.0\bin\STM32_Programmer_CLI.exe'
if (Test-Path $run) { Remove-Item $run -Recurse -Force }
New-Item -ItemType Directory $run | Out-Null
Copy-Item "$kit\TrignoBridge.exe", "$kit\TaskScreen.exe" $run
Copy-Item "\\wsl.localhost\Ubuntu-22.04\home\momo1234\model-leaf\src\pc\fake_tcu_s7.py" "$run\fake_tcu_s7.py"
"bridge md5 " + (Get-FileHash "$run\TrignoBridge.exe" -Algorithm MD5).Hash + ", task screen md5 " + (Get-FileHash "$run\TaskScreen.exe" -Algorithm MD5).Hash
& $cli -c port=SWD mode=UR -hardRst 2>&1 | Select-String -Pattern 'Hard reset|Error' | ForEach-Object { "  board: " + $_.Line.Trim() }
Start-Sleep -Seconds 2
$f = Start-Process $py -ArgumentList "$run\fake_tcu_s7.py --day D:/selftest_data/T00/T00_d2_G --name T00_d2_G --out $run --more 480" -PassThru -WindowStyle Hidden -RedirectStandardOutput "$run\fake_out.txt" -RedirectStandardError "$run\fake_err.txt"
for ($i = 0; $i -lt 60 -and -not (Test-Path "$run\script.txt"); $i++) { Start-Sleep -Milliseconds 500 }
Start-Sleep -Seconds 2
$lines = Get-Content "$run\script.txt"
$calT = [double](($lines | Where-Object { $_ -match ' calibrate$' } | Select-Object -First 1).Split(' ')[0])
"script: $($lines.Count) lines, calibrate at $calT s; " + (Get-Content "$run\fake_out.txt" -Raw)
Set-Location $run
$N = 'Z99_d1_S'
$bargs = "run --port COM6 --firmware lda --classes 9 --preset s7 --tcu 127.0.0.2 --emg-csv ${N}_emg.csv --mcu-csv ${N}_mcu.csv --ops-csv ${N}_ops.csv --script script.txt"
"bridge: $bargs"
$b = Start-Process "$run\TrignoBridge.exe" -ArgumentList $bargs -PassThru -WindowStyle Hidden -RedirectStandardOutput "$run\bridge_out.txt" -RedirectStandardError "$run\bridge_err.txt"
$t0 = Get-Date
while (((Get-Date) - $t0).TotalSeconds -lt $calT + 4) { Start-Sleep -Seconds 1 }
$targs = "--subject Z99 --day 1 --cond S --gestures seven --segments labelled,task,labelled,task,labelled --reps 1 --n 12 --postures selftest --auto --windowed"
"task screen at $([int]((Get-Date) - $t0).TotalSeconds) s: $targs"
$ts = Start-Process "$run\TaskScreen.exe" -ArgumentList $targs -WorkingDirectory $run -PassThru
$ts.WaitForExit(900000) | Out-Null
if (!$ts.HasExited) { $ts.Kill(); "task screen killed (timeout)" } else { "task screen done at $([int]((Get-Date) - $t0).TotalSeconds) s, exit $($ts.ExitCode)" }
$b.WaitForExit(900000) | Out-Null
if (!$b.HasExited) { $b.Kill(); "bridge killed" } else { "bridge done, exit $($b.ExitCode)" }
if (!$f.HasExited) { $f.Kill() }
Get-ChildItem $run -Filter "Z99*" | ForEach-Object { "{0,-28} {1,10}" -f $_.Name, $_.Length }
"bridge tail:"; Get-Content "$run\bridge_out.txt" | Select-Object -Last 8
"DRY_RUN_DONE"
