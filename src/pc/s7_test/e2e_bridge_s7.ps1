# report 35.80 (2026-11-24). Paths point to the working folder of that day; change them before reuse.
# S7 end-to-end test of TrignoBridge.exe without the board: fake TCU on 127.0.0.2 streams T00_d2_G, the bridge runs
# --firmware lda --classes 9 --preset s7 with the day's cal / calibrate timing and writes the serial bytes to a file.
$n = "C:\Users\kirit\AppData\Local\Temp\claude\f717a9ffb3f804d0\940361ee-1e88-4b6f-b364-4f25c47f2d6e\scratchpad\s7pc"
$run = "$n\run"
if (Test-Path $run) { Remove-Item $run -Recurse -Force }
New-Item -ItemType Directory $run | Out-Null
$py = "C:\Users\kirit\AppData\Local\Programs\Python\Python310\python.exe"
$f = Start-Process $py -ArgumentList "$n\fake_tcu_s7.py --day D:/selftest_data/T00/T00_d2_G --name T00_d2_G --out $run" -PassThru -WindowStyle Hidden -RedirectStandardOutput "$run\fake_out.txt" -RedirectStandardError "$run\fake_err.txt"
Start-Sleep -Seconds 8
Set-Location $run
$b = Start-Process "$n\TrignoBridge.exe" -ArgumentList "run --port file:$run\bridge_out.bin --tcu 127.0.0.2 --firmware lda --classes 9 --preset s7 --udp 0 --emg-csv e2e_emg.csv --mcu-csv e2e_mcu.csv --ops-csv e2e_ops.csv --script script.txt" -PassThru -RedirectStandardOutput "$run\bridge_stdout.txt" -RedirectStandardError "$run\bridge_stderr.txt" -WindowStyle Hidden
$b.WaitForExit(600000) | Out-Null
if (!$b.HasExited) { $b.Kill(); "bridge killed" }
Start-Sleep -Seconds 2
if (!$f.HasExited) { $f.Kill() }
"bridge exit $($b.ExitCode)"
Get-Content "$run\fake_out.txt"
Get-Content "$run\bridge_stdout.txt" | Select-Object -First 30
(Get-Item "$run\bridge_out.bin").Length
