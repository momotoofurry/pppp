# report 35.85 (2026-11-24). Paths point to the working folder of that day; change them before reuse.
# Full-stack rehearsal (report 35.82): recorded EMG (fake TCU, T00_d2_G) -> TrignoBridge (--preset s7, report 3)
# -> the real board (rtl_task_s7c, COM6) -> UDP -> udp_tcp_relay.py -> assist_ros.py board (WSL) -> Gen3 in Gazebo.
# Open loop: the recorded gestures drive the arm (the recording does not react to the arm).
$n = "C:\Users\kirit\AppData\Local\Temp\claude\f717a9ffb3f804d0\940361ee-1e88-4b6f-b364-4f25c47f2d6e\scratchpad"
$s7 = "$n\s7pc"
$run = "$s7\reh_fault"
if (Test-Path $run) { Remove-Item $run -Recurse -Force }
New-Item -ItemType Directory $run | Out-Null
$py = "C:\Users\kirit\AppData\Local\Programs\Python\Python310\python.exe"
$cli = 'C:\Users\kirit\AppData\Local\stm32cube\bundles\programmer\2.23.0\bin\STM32_Programmer_CLI.exe'
"reset the board (fresh model)"
& $cli -c port=SWD mode=UR -hardRst 2>&1 | Select-String -Pattern 'reset|Error' | ForEach-Object { "  " + $_.Line.Trim() }
"start Gazebo + assist_ros board in WSL"
$wsl = Start-Process wsl -ArgumentList "-- bash /mnt/c/Users/kirit/AppData/Local/Temp/claude/f717a9ffb3f804d0/940361ee-1e88-4b6f-b364-4f25c47f2d6e/scratchpad/gz_board.sh 330 /tmp/gz_fault" -PassThru -WindowStyle Hidden -RedirectStandardOutput "$run\wsl_out.txt" -RedirectStandardError "$run\wsl_err.txt"
$ok = $false
for ($i = 0; $i -lt 240; $i++) {
    Start-Sleep -Seconds 1
    $l = wsl -- bash -c "ss -ltn 2>/dev/null | grep -c ':50560 '"
    if ($l -and [int]$l -gt 0) { $ok = $true; break }
}
if (!$ok) { "assist_ros never listened"; Get-Content "$run\wsl_out.txt"; exit 1 }
"assist_ros listening after $i s"
$relay = Start-Process $py -ArgumentList "\\wsl.localhost\Ubuntu-22.04\home\momo1234\model-leaf\src\pc\udp_tcp_relay.py --udp 50556 --rtt $run\relay_rtt.csv" -WorkingDirectory $run -PassThru -WindowStyle Hidden -RedirectStandardOutput "$run\relay_out.txt" -RedirectStandardError "$run\relay_err.txt"
$f = Start-Process $py -ArgumentList "$s7\fake_tcu_s7.py --day D:/selftest_data/T00/T00_d2_G --name T00_d2_G --out $run" -PassThru -WindowStyle Hidden -RedirectStandardOutput "$run\fake_out.txt" -RedirectStandardError "$run\fake_err.txt"
Start-Sleep -Seconds 8
(Get-Content "$run\script.txt") -replace '^0\.000 report 1$', '0.000 report 3' | Set-Content "$run\script.txt" -Encoding ASCII
"script first line: " + (Get-Content "$run\script.txt" | Select-Object -First 1)
Set-Location $run
$b = Start-Process "$s7\TrignoBridge.exe" -ArgumentList "run --port COM6 --tcu 127.0.0.2 --firmware lda --classes 9 --preset s7 --fwd-pred 1 --udp 50556,50557 --emg-csv reh_emg.csv --mcu-csv reh_mcu.csv --ops-csv reh_ops.csv --script script.txt" -PassThru -RedirectStandardOutput "$run\bridge_stdout.txt" -RedirectStandardError "$run\bridge_stderr.txt" -WindowStyle Hidden
$u = New-Object System.Net.Sockets.UdpClient 50557
$u.Client.ReceiveTimeout = 200
$ep = New-Object System.Net.IPEndPoint ([System.Net.IPAddress]::Any, 0)
$t0 = Get-Date; $killed = $false
while (!$b.HasExited -and ((Get-Date) - $t0).TotalSeconds -lt 300) {
    try { $d = [Text.Encoding]::ASCII.GetString($u.Receive([ref]$ep)) } catch { continue }
    if (((Get-Date) - $t0).TotalSeconds -gt 120 -and $d -match ',command,\d+,\d+,\w+,(up|down|left|right),') {
        Start-Sleep -Milliseconds 100; $b.Kill(); $killed = $true
        "bridge KILLED 0.1 s after the command: $d  (at $([Math]::Round(((Get-Date) - $t0).TotalSeconds, 1)) s)"
        break
    }
}
$u.Close()
if (!$killed) { "no direction command seen to kill on" }
$b.WaitForExit(10000) | Out-Null
if (!$b.HasExited) { $b.Kill(); "bridge killed" }
"bridge done"
Start-Sleep -Seconds 3
if (!$f.HasExited) { $f.Kill() }
$wsl.WaitForExit(600000) | Out-Null
if (!$relay.HasExited) { $relay.Kill() }
Get-Content "$run\wsl_out.txt" | Select-Object -Last 3
"relay: " + ((Get-Content "$run\relay_out.txt") -join ' | ')
wsl -- bash -c "mkdir -p '/mnt/c/Users/kirit/AppData/Local/Temp/claude/f717a9ffb3f804d0/940361ee-1e88-4b6f-b364-4f25c47f2d6e/scratchpad/s7pc/reh_fault/gz' && cp -r /tmp/gz_fault/. '/mnt/c/Users/kirit/AppData/Local/Temp/claude/f717a9ffb3f804d0/940361ee-1e88-4b6f-b364-4f25c47f2d6e/scratchpad/s7pc/reh_fault/gz/'"
Get-ChildItem "$run\gz" | Format-Table Name, Length



