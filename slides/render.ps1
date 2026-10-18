param([string]$In, [string]$OutDir)
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force $OutDir | Out-Null
Get-ChildItem $OutDir -Filter *.png | Remove-Item -Force
$app = New-Object -ComObject PowerPoint.Application
try {
  $p = $app.Presentations.Open($In, $true, $false, $false)
  $i = 0
  foreach ($s in $p.Slides) { $i++; $s.Export((Join-Path $OutDir ("s{0:D2}.png" -f $i)), 'PNG', 1600, 900) }
  "slides: $i  size: $($p.PageSetup.SlideWidth) x $($p.PageSetup.SlideHeight) pt"
  $p.Close()
} finally { $app.Quit() }
