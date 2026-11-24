# Run the Utage build and capture the window over time, pressing buttons through the virtual pad's
# automation file (virtual_remote.cpp: generated/b/vpad.txt under the working directory).
#   u-shots.ps1 -Out DIR -Steps "10:shot","12:CL=0018","16:shot",...
# A step is "SECONDS:shot" (window capture to DIR\uNN.png) or "SECONDS:CL=hex" (held 0.4 s, then released).
param([Parameter(Mandatory)][string]$Out, [Parameter(Mandatory)][string[]]$Steps, [int]$Tail = 3)
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
# Runs from generated\win-run (own UserData, exe copied from win-build when newer): a game process
# that hangs in the GPU driver can't be killed and keeps win-build's exe and Dawn cache locked.
$build = Join-Path $root 'generated\win-build'
$bd = Join-Path $root 'generated\win-run'
$src = Get-Item (Join-Path $build 'WiiCompiled.exe') -ErrorAction SilentlyContinue
$dst = Join-Path $bd 'WiiCompiled.exe'
if ($src -and (-not (Test-Path $dst) -or (Get-Item $dst).LastWriteTime -lt $src.LastWriteTime)) { Copy-Item $src.FullName $dst -Force }
$vpadDir = Join-Path $bd 'generated\b'
New-Item -ItemType Directory -Force $vpadDir, $Out | Out-Null
$vpad = Join-Path $vpadDir 'vpad.txt'
Remove-Item $vpad -ErrorAction SilentlyContinue
$p = Start-Process -FilePath (Join-Path $bd 'WiiCompiled.exe') -WorkingDirectory $bd -PassThru `
    -RedirectStandardError (Join-Path $Out 'stderr.txt') -RedirectStandardOutput (Join-Path $Out 'stdout.txt')
$t0 = Get-Date
foreach ($s in $Steps) {
    $at, $what = $s -split ':', 2
    $wait = [double]$at - ((Get-Date) - $t0).TotalSeconds
    if ($wait -gt 0) { Start-Sleep -Milliseconds ([int]($wait * 1000)) }
    if ($p.HasExited) { "exited $($p.ExitCode) before $at s"; break }
    if ($what -eq 'shot') {
        $f = Join-Path $Out ('u{0:D3}.png' -f [int]$at)
        & (Join-Path $PSScriptRoot 'b-shot.ps1') -ProcId $p.Id -Out $f | Out-Null
        "shot $f"
    } elseif ($what -eq 'dump') {
        # The runtime polls for this file and writes MEM1 (+ .mem2) snapshots to the path inside.
        $f = Join-Path ([IO.Path]::GetFullPath($Out)) ('mem_{0:D3}.bin' -f [int]$at)
        Set-Content -Path (Join-Path $vpadDir 'memdump.req') -Value $f -Encoding ascii
        & (Join-Path $PSScriptRoot 'b-shot.ps1') -ProcId $p.Id -Out ($f -replace '\.bin$', '.png') | Out-Null
        "dump $f"
    } elseif ($what -eq 'copies') {
        # The next frame's texture copies are read back and written as <prefix>_NN_WxH_fF_ADDR.raw.
        $f = Join-Path ([IO.Path]::GetFullPath($Out)) ('copy_{0:D3}' -f [int]$at)
        Set-Content -Path (Join-Path $vpadDir 'copydump.req') -Value $f -Encoding ascii
        & (Join-Path $PSScriptRoot 'b-shot.ps1') -ProcId $p.Id -Out "$f.png" | Out-Null
        "copies $f"
    } else {
        # "CL=hex/ms" holds for ms instead of 400 (menus auto-repeat a 400 ms press).
        $hold = 400
        if ($what -match '^(.*)/(\d+)$') { $what = $Matches[1]; $hold = [int]$Matches[2] }
        Set-Content -Path $vpad -Value $what -Encoding ascii
        Start-Sleep -Milliseconds $hold
        Remove-Item $vpad -ErrorAction SilentlyContinue
        "press $what at $at s"
    }
}
Start-Sleep -Seconds $Tail
if (-not $p.HasExited) { Stop-Process -Id $p.Id -Force; 'stopped' } else { "exited $($p.ExitCode)" }
