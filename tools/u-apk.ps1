# Release APK: the native build (generated\android-build: PGO use + ThinLTO), staged into the app, then
# gradle, signed with apk_work/keys. Output: F:\basara_work\apk_work\utage\sb3utage-indo-<version>-arm64.apk.
#   powershell -File tools\u-apk.ps1 -Version 1.0.0 -Code 63
# With -Profile, the release tree is configured to that merged PGO profile first (a new file name, so
# every object is rebuilt with it: ninja does not track the profile's content).
param([string]$Version = '1.0.0', [int]$Code = 1, [int]$Jobs = 6, [int]$TranslatedJobs = 3, [string]$Profile = '')
$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$ndk = 'E:\Installers\andr_1\ndk\28.2.13676358'
$t = Get-Date
if ($Profile) {
    $p = [IO.Path]::GetFullPath($Profile).Replace('\', '/')
    & "$root\tools\b-android.ps1" -Mode configure -TranslatedJobs $TranslatedJobs -Ndk $ndk `
        -Extra @('-DMKW_PGO=use', "-DMKW_PGO_PROFILE=$p", '-DMKW_THINLTO=ON') 2>&1 | Select-Object -Last 1
}
$b = & "$root\tools\b-android.ps1" -Mode build -Jobs $Jobs -TranslatedJobs $TranslatedJobs -Ndk $ndk 2>&1 | Select-Object -Last 2
$b
if (-not ($b -match 'build exit 0')) { 'native build failed'; exit 1 }
& "$root\tools\b-android.ps1" -Mode stage -Ndk $ndk 2>&1 | Select-Object -Last 2
$env:JAVA_HOME = 'E:\Installers\andr\jbr'
Push-Location "$root\app"
$ErrorActionPreference = 'Continue'
& (Join-Path $env:USERPROFILE '.gradle\wrapper\dists\gradle-9.1.0-all\7wzd0jkjit61aq2p43wpjgij9\gradle-9.1.0\bin\gradle.bat') --offline assembleRelease `
    '-PbasaraSigning=F:/basara_work/apk_work/keys/signing.properties' "-PbasaraVersionCode=$Code" "-PbasaraVersionName=$Version" 2>&1 |
    Select-String 'BUILD|error|FAIL|went wrong' | Select-Object -First 8 | ForEach-Object { $_.Line }
Pop-Location
$apk = Get-ChildItem "$root\app\build\outputs\apk\release" -Filter *.apk | Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($apk.LastWriteTime -lt $t) { 'gradle produced no new APK'; exit 1 }
$out = "F:\basara_work\apk_work\utage\sb3utage-indo-$Version-arm64.apk"
Copy-Item $apk.FullName $out -Force
"built $out ($([int]((Get-Date) - $t).TotalMinutes) min) sha256 $((Get-FileHash $out -Algorithm SHA256).Hash)"
