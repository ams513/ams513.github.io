<#
.SYNOPSIS
  Builds the Stark World Engine Runtime plugin for every installed Unreal Engine 5.x so buyers never need a C++ compiler.

.DESCRIPTION
  Owner PC only, once per engine version (re-run after changing the plugin's C++).
  Needs: Unreal Engine 5.4+ (Epic Games Launcher) and Visual Studio 2022 with "Game development with C++".
  For each engine it runs   RunUAT BuildPlugin -Plugin=StarkRuntime.uplugin -Package=<temp> -TargetPlatforms=Win64
  (https://dev.epicgames.com/documentation/en-us/unreal-engine/plugins-in-unreal-engine#buildingplugins),
  checks the editor DLL and the .modules BuildId against the engine, then copies Binaries + Intermediate + the
  descriptor into ue5_plugin\prebuilt\UE_5.x\StarkRuntime and writes manifest.json (sha256 of every file).
  ue5_export.py only ships prebuilt files whose hashes still match the manifest.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File ue5_plugin\build_binaries.ps1
  powershell -ExecutionPolicy Bypass -File ue5_plugin\build_binaries.ps1 -Engine "C:\Program Files\Epic Games\UE_5.4"
  powershell -ExecutionPolicy Bypass -File ue5_plugin\build_binaries.ps1 -VerifyOnly
#>
param(
    [string[]]$Engine = @(),
    [switch]$VerifyOnly
)
$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Plugin = Join-Path $Here 'StarkRuntime\StarkRuntime.uplugin'
$PrebuiltRoot = Join-Path $Here 'prebuilt'

function Get-EngineRoots {
    $roots = New-Object System.Collections.Generic.List[string]
    $dat = Join-Path $env:ProgramData 'Epic\UnrealEngineLauncher\LauncherInstalled.dat'
    if (Test-Path $dat) {
        try {
            foreach ($it in (Get-Content $dat -Raw | ConvertFrom-Json).InstallationList) {
                if ($it.AppName -like 'UE_5*' -and $it.InstallLocation) { $roots.Add($it.InstallLocation) }
            }
        } catch { Write-Warning "LauncherInstalled.dat unreadable: $_" }
    }
    foreach ($key in @('HKLM:\SOFTWARE\EpicGames\Unreal Engine', 'HKLM:\SOFTWARE\WOW6432Node\EpicGames\Unreal Engine')) {
        if (Test-Path $key) {
            foreach ($sub in Get-ChildItem $key) {
                try { $p = (Get-ItemProperty $sub.PSPath).InstalledDirectory; if ($p) { $roots.Add($p) } } catch { }
            }
        }
    }
    $epic = Join-Path $env:ProgramFiles 'Epic Games'
    if (Test-Path $epic) { Get-ChildItem $epic -Directory -Filter 'UE_5*' | ForEach-Object { $roots.Add($_.FullName) } }
    $seen = @{}
    foreach ($r in $roots) {
        $full = [System.IO.Path]::GetFullPath($r)
        if (-not $seen.ContainsKey($full.ToLower()) -and (Test-Path (Join-Path $full 'Engine\Binaries\Win64\UnrealEditor.exe'))) {
            $seen[$full.ToLower()] = $true
            $full
        }
    }
}

function Get-EngineVersion([string]$Root) {
    $bv = Get-Content (Join-Path $Root 'Engine\Build\Build.version') -Raw | ConvertFrom-Json
    return "$($bv.MajorVersion).$($bv.MinorVersion)"
}

function Get-BuildId([string]$ModulesFile) {
    if (-not (Test-Path $ModulesFile)) { return $null }
    return (Get-Content $ModulesFile -Raw | ConvertFrom-Json).BuildId
}

function Write-Manifest([string]$Dest, [string]$Version, [string]$BuildId) {
    $plug = Join-Path $Dest 'StarkRuntime'
    $files = [ordered]@{}
    Get-ChildItem $plug -Recurse -File | Sort-Object FullName | ForEach-Object {
        $rel = $_.FullName.Substring($plug.Length + 1).Replace('\', '/')
        $files[$rel] = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
    }
    $man = [ordered]@{ format = 'stark-prebuilt/1'; engine = $Version; build_id = $BuildId;
        built = (Get-Date -Format 'yyyy-MM-dd'); files = $files }
    $man | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 (Join-Path $Dest 'manifest.json')
    return $files.Count
}

function Test-Prebuilt([string]$Dest, [string]$EngineRoot) {
    $man = Get-Content (Join-Path $Dest 'manifest.json') -Raw | ConvertFrom-Json
    $plug = Join-Path $Dest 'StarkRuntime'
    $bad = 0
    foreach ($p in $man.files.PSObject.Properties) {
        $f = Join-Path $plug ($p.Name.Replace('/', '\'))
        if (-not (Test-Path $f) -or (Get-FileHash $f -Algorithm SHA256).Hash.ToLower() -ne $p.Value) { $bad++ }
    }
    $dll = Join-Path $plug 'Binaries\Win64\UnrealEditor-StarkRuntime.dll'
    $engineId = Get-BuildId (Join-Path $EngineRoot 'Engine\Binaries\Win64\UnrealEditor.modules')
    $ok = ($bad -eq 0) -and (Test-Path $dll) -and ((-not $engineId) -or ($engineId -eq $man.build_id))
    return [pscustomobject]@{ ok = $ok; bad_files = $bad; dll = (Test-Path $dll); build_id = $man.build_id; engine_build_id = $engineId }
}

$roots = if ($Engine.Count -gt 0) { $Engine } else { @(Get-EngineRoots) }
if ($roots.Count -eq 0) {
    Write-Host 'No Unreal Engine 5 found. Install UE 5.4+ from the Epic Games Launcher (and Visual Studio 2022 C++), then re-run.'
    exit 2
}
$failed = 0
foreach ($root in $roots) {
    $v = Get-EngineVersion $root
    $dest = Join-Path $PrebuiltRoot "UE_$v"
    if ($VerifyOnly) {
        if (Test-Path (Join-Path $dest 'manifest.json')) { $r = Test-Prebuilt $dest $root; Write-Host "UE ${v} prebuilt: $($r | ConvertTo-Json -Compress)"; if (-not $r.ok) { $failed++ } }
        else { Write-Host "UE ${v}: no prebuilt yet"; $failed++ }
        continue
    }
    $uat = Join-Path $root 'Engine\Build\BatchFiles\RunUAT.bat'
    $pkg = Join-Path $env:TEMP "StarkRuntime_UE_$v"
    if (Test-Path $pkg) { Remove-Item $pkg -Recurse -Force }
    Write-Host "== Building Stark World Engine Runtime for UE $v"
    & $uat BuildPlugin "-Plugin=$Plugin" "-Package=$pkg" -TargetPlatforms=Win64 -HostPlatforms=Win64
    if ($LASTEXITCODE -ne 0) { Write-Warning "BuildPlugin failed for UE $v (exit $LASTEXITCODE)"; $failed++; continue }
    $dll = Join-Path $pkg 'Binaries\Win64\UnrealEditor-StarkRuntime.dll'
    if (-not (Test-Path $dll)) { Write-Warning "UE ${v}: $dll missing after BuildPlugin"; $failed++; continue }
    $buildId = Get-BuildId (Join-Path $pkg 'Binaries\Win64\UnrealEditor.modules')
    if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
    $plug = Join-Path $dest 'StarkRuntime'
    New-Item -ItemType Directory -Force $plug | Out-Null
    foreach ($part in @('Binaries', 'Intermediate')) {
        $src = Join-Path $pkg $part
        if (Test-Path $src) { Copy-Item $src (Join-Path $plug $part) -Recurse -Force }
    }
    Copy-Item (Join-Path $pkg 'StarkRuntime.uplugin') (Join-Path $plug 'StarkRuntime.uplugin') -Force
    Get-ChildItem $plug -Recurse -Include '*.pdb' | Remove-Item -Force   # debug symbols stay on the owner PC
    $n = Write-Manifest $dest $v $buildId
    $check = Test-Prebuilt $dest $root
    Write-Host "UE ${v}: $n files, BuildId $buildId, verify ok=$($check.ok)"
    if (-not $check.ok) { $failed++ }
}
if ($failed -gt 0) { Write-Host "$failed engine(s) failed"; exit 1 }
Write-Host 'All prebuilt Stark World Engine Runtime binaries are ready (ue5_plugin\prebuilt). Re-export from Stark World Engine to ship them.'
exit 0
