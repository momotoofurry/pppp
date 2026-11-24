# report 35.80 (2026-11-24). Paths point to the working folder of that day; change them before reuse.
# Flash build/rtl_task_s7b (report 35.80) with the usual checks: read back bank 1 and bank 2 sector 7 first, check
# the board holds rtl_task_9c2, flash + verify, read back again (new program, sector 7 unchanged).
$ErrorActionPreference = 'Stop'
$cli = 'C:\Users\kirit\AppData\Local\stm32cube\bundles\programmer\2.23.0\bin\STM32_Programmer_CLI.exe'
$oc = 'C:\Users\kirit\AppData\Local\stm32cube\bundles\gnu-tools-for-stm32\14.3.1+st.2\bin\arm-none-eabi-objcopy.exe'
$bl = 'D:\stm32\blink_leaf'
$bk = "$bl\backup"
$w = "C:\Users\kirit\AppData\Local\Temp\claude\f717a9ffb3f804d0\940361ee-1e88-4b6f-b364-4f25c47f2d6e\scratchpad\s7pc\flash"
New-Item -ItemType Directory -Force $w | Out-Null
$bank1 = "$bk\board_bank1_rtl_task_9c2_2026-11-24.bin"
$sect = "$bk\board_sector_2026-11-24.bin"
if ((Test-Path $bank1) -or (Test-Path $sect)) { throw "backup files exist already" }

function Up([string]$addr, [string]$size, [string]$file) {
    $log = & $cli -c port=SWD mode=UR -u $addr $size $file 2>&1 | Out-String
    if (!(Test-Path $file)) { throw "read back failed: $log" }
}
function Md5([string]$f) { (Get-FileHash $f -Algorithm MD5).Hash.ToLower() }
function SameBytes([string]$img, [string]$dump) {
    $a = [IO.File]::ReadAllBytes($img); $b = [IO.File]::ReadAllBytes($dump)
    if ($b.Length -lt $a.Length) { return $false }
    for ($i = 0; $i -lt $a.Length; $i++) { if ($a[$i] -ne $b[$i]) { return "first difference at byte $i" } }
    return $true
}

"1) read back bank 1 (1 MB) and bank 2 sector 7 (128 KB)"
Up '0x08000000' '0x100000' $bank1
Up '0x081E0000' '0x20000' $sect
"   bank 1 md5 $(Md5 $bank1), sector 7 md5 $(Md5 $sect)"

"2) is it rtl_task_9c2?"
& $oc -O binary "$bl\build\rtl_task_9c2\blink.elf" "$w\rtl_task_9c2.bin"
& $oc -O binary "$bl\build\rtl_task_s7b\blink.elf" "$w\rtl_task_s7b.bin"
"   board == rtl_task_9c2 image ($((Get-Item "$w\rtl_task_9c2.bin").Length) bytes): $(SameBytes "$w\rtl_task_9c2.bin" $bank1)"

"3) flash rtl_task_s7b"
$log = & $cli -c port=SWD mode=UR reset=HWrst -w "$bl\build\rtl_task_s7b\blink.elf" -v -hardRst 2>&1 | Out-String
($log -split "`n" | Where-Object { $_ -match 'verif|Error|File download|complete' }) | ForEach-Object { "   [cli] " + $_.Trim() }

"4) read back again"
Up '0x08000000' '0x100000' "$w\bank1_after.bin"
Up '0x081E0000' '0x20000' "$w\sector_after.bin"
"   board == rtl_task_s7b image ($((Get-Item "$w\rtl_task_s7b.bin").Length) bytes): $(SameBytes "$w\rtl_task_s7b.bin" "$w\bank1_after.bin")"
"   sector 7 md5 before $(Md5 $sect), after $(Md5 "$w\sector_after.bin")"
