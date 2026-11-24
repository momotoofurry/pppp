# report 35.85 (2026-11-24). Paths point to the working folder of that day; change them before reuse.
$S = "C:\Users\kirit\AppData\Local\Temp\claude\f717a9ffb3f804d0\940361ee-1e88-4b6f-b364-4f25c47f2d6e\scratchpad"
$py = "C:\Users\kirit\AppData\Local\Programs\Python\Python310\python.exe"
foreach ($f in 'ack_rtt.csv', 'ack_srv.txt', 'ack_rel.txt', 'ack_rel_err.txt') { if (Test-Path "$S\$f") { Remove-Item "$S\$f" } }
$srv = Start-Process wsl -ArgumentList "-- python3 /mnt/c/Users/kirit/AppData/Local/Temp/claude/f717a9ffb3f804d0/940361ee-1e88-4b6f-b364-4f25c47f2d6e/scratchpad/ack_server.py" -PassThru -WindowStyle Hidden -RedirectStandardOutput "$S\ack_srv.txt"
Start-Sleep -Seconds 2
$rel = Start-Process $py -ArgumentList "$S\relay_copy.py --udp 50566 --to 127.0.0.1:50561 --task 50569 --rtt $S\ack_rtt.csv" -PassThru -WindowStyle Hidden -RedirectStandardOutput "$S\ack_rel.txt" -RedirectStandardError "$S\ack_rel_err.txt"
$lab = New-Object System.Net.Sockets.UdpClient 50569
$lab.Client.ReceiveTimeout = 3000
Start-Sleep -Seconds 3
$u = New-Object System.Net.Sockets.UdpClient
foreach ($i in 1..6) {
    $m = [Text.Encoding]::ASCII.GetBytes("$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()).0,command,$i,0,WristExt,up,,1,,,")
    [void]$u.Send($m, $m.Length, "127.0.0.1", 50566)
    Start-Sleep -Milliseconds 200
}
$ep = New-Object System.Net.IPEndPoint ([System.Net.IPAddress]::Any, 0)
try { "label datagram at the bridge port: " + [Text.Encoding]::ASCII.GetString($lab.Receive([ref]$ep)) } catch { "no label datagram arrived" }
Start-Sleep -Seconds 2
if (!$rel.HasExited) { $rel.Kill() }
$lab.Close()
"rtt file:"; if (Test-Path "$S\ack_rtt.csv") { Get-Content "$S\ack_rtt.csv" } else { "(none)" }
"relay stdout:"; Get-Content "$S\ack_rel.txt"; Get-Content "$S\ack_rel_err.txt"
"server:"; Get-Content "$S\ack_srv.txt"
