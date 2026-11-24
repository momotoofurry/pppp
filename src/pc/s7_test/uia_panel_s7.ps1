# report 35.80 (2026-11-24). Paths point to the working folder of that day; change them before reuse.
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$B = "C:\Users\kirit\AppData\Local\Temp\claude\f717a9ffb3f804d0\940361ee-1e88-4b6f-b364-4f25c47f2d6e\scratchpad\s7pc"
$p = Start-Process "$B\ExperimentPanel.exe" -PassThru
Start-Sleep -Seconds 4
$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty, $p.Id)
$win = $root.FindFirst([System.Windows.Automation.TreeScope]::Children, $cond)
$all = $win.FindAll([System.Windows.Automation.TreeScope]::Descendants, [System.Windows.Automation.Condition]::TrueCondition)
foreach ($e in $all) {
    $n = $e.Current.Name
    $t = $e.Current.ControlType.ProgrammaticName
    if ($n -match '^cal |calibrate|S7|T00_d' -or ($t -eq 'ControlType.ComboBox')) {
        $v = ''
        try { $vp = $e.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern); $v = $vp.Current.Value } catch {}
        "{0,-22} offscreen={1} | {2} {3}" -f $t, $e.Current.IsOffscreen, $n, $v
    }
}
$p.Kill()
