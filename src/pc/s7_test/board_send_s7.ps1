# report 35.80 (2026-11-24). Paths point to the working folder of that day; change them before reuse.
# Send bridge_out.bin (the S7 end-to-end stream) to the board in real time (a SAMPLES packet = 20 frames = 10 ms;
# control packets at once), store everything the board answers in board_rx.bin.
param([string]$Port = 'COM6')
$d = "C:\Users\kirit\AppData\Local\Temp\claude\f717a9ffb3f804d0\940361ee-1e88-4b6f-b364-4f25c47f2d6e\scratchpad\s7pc\run"
$b = [IO.File]::ReadAllBytes("$d\bridge_out.bin")
$sp = New-Object System.IO.Ports.SerialPort $Port, 921600, 'None', 8, 'One'
$sp.ReadTimeout = 10; $sp.WriteTimeout = 2000; $sp.ReadBufferSize = 1048576
$sp.Open(); $sp.DiscardInBuffer()
$rx = New-Object System.IO.MemoryStream
$buf = New-Object byte[] 65536
$sw = [Diagnostics.Stopwatch]::StartNew()
$frames = 0; $i = 0; $npk = 0
while ($i -lt $b.Length) {
    if ($b[$i] -ne 0xA5 -or $b[$i + 1] -ne 0x5A) { throw "not a packet start at $i" }
    $type = $b[$i + 2]
    $len = $b[$i + 5] + 256 * $b[$i + 6]
    $n = 9 + $len
    if ($type -eq 1) {
        $due = $frames / 2000.0
        while ($sw.Elapsed.TotalSeconds -lt $due) {
            if ($sp.BytesToRead -gt 0) { $k = $sp.Read($buf, 0, [Math]::Min($buf.Length, $sp.BytesToRead)); $rx.Write($buf, 0, $k) }
            else { Start-Sleep -Milliseconds 1 }
        }
        $frames += $len / 16
    }
    $sp.Write($b, $i, $n)
    $i += $n; $npk++
    if ($sp.BytesToRead -gt 0) { $k = $sp.Read($buf, 0, [Math]::Min($buf.Length, $sp.BytesToRead)); $rx.Write($buf, 0, $k) }
}
$t1 = $sw.Elapsed.TotalSeconds
while ($sw.Elapsed.TotalSeconds -lt $t1 + 2) {
    if ($sp.BytesToRead -gt 0) { $k = $sp.Read($buf, 0, [Math]::Min($buf.Length, $sp.BytesToRead)); $rx.Write($buf, 0, $k) }
    else { Start-Sleep -Milliseconds 5 }
}
$sp.Close()
[IO.File]::WriteAllBytes("$d\board_rx.bin", $rx.ToArray())
"sent $npk packets, $frames frames in $([Math]::Round($t1, 1)) s; received $($rx.Length) bytes"
