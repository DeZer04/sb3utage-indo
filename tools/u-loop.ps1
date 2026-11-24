# Boot loop for the Utage port: translate -> build -> run; when the game jumps into an address the
# translation doesn't have ("InvokeIndirectCpu: target 0x... not translated"), add it to
# config/utage/MAP.txt (u_seedmap.py --add) and go again. Stops on any other outcome.
param([int]$Rounds = 5, [int]$Seconds = 60)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$py = 'python'
for ($n = 1; $n -le $Rounds; $n++) {
    "=== round $n"
    & (Join-Path $root 'tools\u-translate.ps1') 2>&1 | Where-Object { $_ -match '^(translate|shards):' }
    $b = & (Join-Path $root 'tools\b-win.ps1') -Mode build -Jobs 10 -TranslatedJobs 6 2>&1 | Select-Object -Last 3
    $b
    if (-not ($b -match 'build exit 0')) { 'build failed'; break }
    $r = & (Join-Path $root 'tools\b-win.ps1') -Mode run -Seconds $Seconds 2>&1
    $log = ($r | Where-Object { $_ -match '^log: ' } | Select-Object -Last 1) -replace '^log: ', ''
    "log: $log"
    if (-not $log -or -not (Test-Path $log)) { $r | Select-Object -Last 5; break }
    $miss = Select-String -Path $log -Pattern 'InvokeIndirectCpu: target 0x([0-9a-fA-F]{8}) not translated' | Select-Object -First 1
    if (-not $miss) {
        Select-String -Path $log -Pattern 'Runtime error|OS::Fatal|still running|Access ?Violation' | Select-Object -First 4 | ForEach-Object { $_.Line.Substring(0, [Math]::Min(220, $_.Line.Length)) }
        'stopped: no missing-function jump'
        break
    }
    $addr = $miss.Matches[0].Groups[1].Value.ToUpper()
    "missing function: $addr"
    & $py -I (Join-Path $root 'tools\u_seedmap.py') --add $addr | Select-Object -First 1
}
