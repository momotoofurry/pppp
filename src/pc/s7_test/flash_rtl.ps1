# report 35.82-35.83 (2026-11-24). Paths point to the working folder of that day; change them before reuse.
# Flash build/<New> with the usual checks (report 35.80 / 35.82): read back bank 1 and bank 2 sector 7 first, check the
# board holds build/<Old>, flash + verify, read back again (new program, sector 7 unchanged).
param([Parameter(Mandatory = $true)][string]$Old, [Parameter(Mandatory = $true)][string]$New,
      [Parameter(Mandatory = $true)][string]$Tag)
$ErrorActionPreference = 'Stop'
$cli = 'C:\Users\kirit\AppData\Local\stm32cube\bundles\programmer\2.23.0\bin\STM32_Programmer_CLI.exe'
$oc = 'C:\Users\kirit\AppData\Local\stm32cube\bundles\gnu-tools-for-stm32\14.3.1+st.2\bin\arm-none-eabi-objcopy.exe'
$bl = 'D:\stm32\blink_leaf'
$bk = "$bl\backup"
$w = "C:\Users\kirit\AppData\Local\Temp\claude\f717a9ffb3f804d0\940361ee-1e88-4b6f-b364-4f25c47f2d6e\scratchpad\s7pc\flash_$New"
New-Item -ItemType Directory -Force $w | Out-Null
$bank1 = "$bk\board_bank1_${Old}_$Tag.bin"
$sect = "$bk\board_sector_$Tag.bin"
if ((Test-Path $bank1) -or (Test-Path $sect)) { throw "backup files exist already: $bank1 / $sect" }

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
"2) is it ${Old}?"
& $oc -O binary "$bl\build\$Old\blink.elf" "$w\old.bin"
& $oc -O binary "$bl\build\$New\blink.elf" "$w\new.bin"
$same = SameBytes "$w\old.bin" $bank1
"   board == $Old image ($((Get-Item "$w\old.bin").Length) bytes): $same"
if ($same -ne $true) { throw "the board does not hold ${Old}, stop" }
"3) flash $New"
$log = & $cli -c port=SWD mode=UR reset=HWrst -w "$bl\build\$New\blink.elf" -v -hardRst 2>&1 | Out-String
($log -split "`n" | Where-Object { $_ -match 'verif|Error|File download|complete' }) | ForEach-Object { "   [cli] " + $_.Trim() }
"4) read back again"
Up '0x08000000' '0x100000' "$w\bank1_after.bin"
Up '0x081E0000' '0x20000' "$w\sector_after.bin"
"   board == $New image ($((Get-Item "$w\new.bin").Length) bytes): $(SameBytes "$w\new.bin" "$w\bank1_after.bin")"
"   sector 7 md5 before $(Md5 $sect), after $(Md5 "$w\sector_after.bin")"
