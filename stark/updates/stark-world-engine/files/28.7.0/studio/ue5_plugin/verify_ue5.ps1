<#
.SYNOPSIS
  One command that verifies the Unreal Engine 5 path end to end (owner PC, after installing UE 5.4+ and VS 2022 C++).

.DESCRIPTION
  1. finds the newest UE 5.4+ (launcher list, registry, Program Files)
  2. builds the prebuilt Stark World Engine Runtime for it if missing (build_binaries.ps1)
  3. exports a test game (Firefly Fen from tests\fixtures) with the prebuilt runtime
  4. builds every level headless:   UnrealEditor-Cmd <project> -run=pythonscript -script=stark_build_level.py
  5. runs the C++ rules test:       UnrealEditor-Cmd <project> -ExecCmds="Automation RunTests StarkWorldEngine.Runtime;Quit"
  6. runs the Play-In-Editor smoke test (an editor window opens for a few minutes and closes by itself):
                                    UnrealEditor <project> -ExecutePythonScript=stark_pie_smoke.py
  and prints PASS / FAIL per step, writing ue5_plugin\_verify\last_verify.json.
  Commandlets: https://dev.epicgames.com/documentation/en-us/unreal-engine/python-scripting-in-unreal-engine#commandlet
  Automation:  https://dev.epicgames.com/documentation/en-us/unreal-engine/run-automation-tests-in-unreal-engine

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File ue5_plugin\verify_ue5.ps1
  powershell -ExecutionPolicy Bypass -File ue5_plugin\verify_ue5.ps1 -World "Summit Snack Run" -SkipPie
#>
param(
    [string]$World = 'Firefly Fen',
    [string]$EngineRoot = '',
    [switch]$SkipPie,
    [int]$TimeoutMinutes = 40
)
$ErrorActionPreference = 'Stop'
$Here = Split-Path -Parent $MyInvocation.MyCommand.Path
$Studio = Split-Path -Parent $Here
$Results = [ordered]@{}

function Find-Python {
    foreach ($c in @(@('py', '-3'), @('python'))) {
        try { & $c[0] $c[1..9] -c "import sys; print(sys.version)" *> $null; if ($LASTEXITCODE -eq 0) { return , $c } } catch { }
    }
    throw 'Python 3.10+ not found (needed to export the test project)'
}

function Run-Step([string]$Name, [scriptblock]$Body) {
    Write-Host "== $Name"
    try { $ok = & $Body; $Results[$Name] = [bool]$ok } catch { Write-Warning "$Name failed: $_"; $Results[$Name] = $false }
    Write-Host ("   " + ($(if ($Results[$Name]) { 'PASS' } else { 'FAIL' })))
}

$py = Find-Python
$pyExe = $py[0]
$pyArgs = @($py | Select-Object -Skip 1)

# 1. engine
$find = "import sys, json; sys.path.insert(0, r'$Studio'); import ue5_export as u; e = u.pick_unreal(); print(json.dumps({'root': e['root'], 'version': e['version']}) if e else '')"
if ($EngineRoot) {
    $bv = Get-Content (Join-Path $EngineRoot 'Engine\Build\Build.version') -Raw | ConvertFrom-Json
    $engine = [pscustomobject]@{ root = $EngineRoot; version = "$($bv.MajorVersion).$($bv.MinorVersion)" }
} else {
    $out = & $pyExe @pyArgs -I -c $find
    if (-not $out) { Write-Host 'No Unreal Engine 5.4+ found. Install it from the Epic Games Launcher first.'; exit 2 }
    $engine = $out | ConvertFrom-Json
}
Write-Host "Unreal Engine $($engine.version) at $($engine.root)"
$cmd = Join-Path $engine.root 'Engine\Binaries\Win64\UnrealEditor-Cmd.exe'
$gui = Join-Path $engine.root 'Engine\Binaries\Win64\UnrealEditor.exe'

# 2. prebuilt runtime
Run-Step 'prebuilt runtime' {
    $man = Join-Path $Here "prebuilt\UE_$($engine.version)\manifest.json"
    if (-not (Test-Path $man)) {
        & powershell -ExecutionPolicy Bypass -File (Join-Path $Here 'build_binaries.ps1') -Engine $engine.root
        if ($LASTEXITCODE -ne 0) { return $false }
    }
    & powershell -ExecutionPolicy Bypass -File (Join-Path $Here 'build_binaries.ps1') -Engine $engine.root -VerifyOnly
    return $LASTEXITCODE -eq 0
}

# 3. export
$proj = Join-Path $env:TEMP 'StarkUE5Verify'
Run-Step 'export test project' {
    if (Test-Path $proj) { Remove-Item $proj -Recurse -Force }
    $code = "import sys, json; sys.path.insert(0, r'$Studio'); import ue5_export as u; " +
            "W = json.load(open(r'$Studio\tests\fixtures\nextgen_worlds.json', encoding='utf-8'))['worlds']; " +
            "w = next(x for x in W if x['name'] == r'''$World'''); " +
            "f = u.ue5_project(w, engine='$($engine.version)', with_binaries=True); u.write_project(f, r'$proj'); " +
            "print('runtime', u.runtime_mode('$($engine.version)', True)); print([k for k in f if k.endswith('.uproject')][0])"
    $o = & $pyExe @pyArgs -I -c $code
    Write-Host "   $o"
    return ($LASTEXITCODE -eq 0) -and ($o -match 'runtime prebuilt')
}
$uproject = (Get-ChildItem $proj -Filter '*.uproject' | Select-Object -First 1).FullName
$scripts = Join-Path $proj 'Content\Python'

# 4. headless level build
Run-Step 'headless level build' {
    $p = Start-Process $cmd -ArgumentList @("`"$uproject`"", '-run=pythonscript', "-script=`"$scripts\stark_build_level.py`"",
        '-unattended', '-nosplash', '-nop4', '-NoSound') -PassThru -Wait -NoNewWindow
    $rep = Join-Path $proj 'Saved\Stark\build_report.json'
    if (-not (Test-Path $rep)) { return $false }
    $r = Get-Content $rep -Raw | ConvertFrom-Json
    Write-Host "   levels: $(($r.levels | ForEach-Object { "$($_.map) $($_.terrain)" }) -join ', ')  warnings: $($r.warnings.Count)"
    return [bool]$r.ok -and [bool]$r.runtime
}

# 5. C++ automation test
Run-Step 'automation test StarkWorldEngine.Runtime' {
    $log = Join-Path $proj 'Saved\Stark\automation.log'
    $p = Start-Process $cmd -ArgumentList @("`"$uproject`"", '-ExecCmds="Automation RunTests StarkWorldEngine.Runtime;Quit"',
        '-unattended', '-nullrhi', '-nosplash', '-nop4', '-NoSound', "-abslog=`"$log`"") -PassThru -Wait -NoNewWindow
    if (-not (Test-Path $log)) { return $false }
    $t = Get-Content $log -Raw
    return ($t -match 'Result=\{Success\}') -and -not ($t -match 'Result=\{Fail')
}

# 6. PIE smoke
if (-not $SkipPie) {
    Run-Step 'Play-In-Editor smoke test' {
        $p = Start-Process $gui -ArgumentList @("`"$uproject`"", "-ExecutePythonScript=`"$scripts\stark_pie_smoke.py`"",
            '-StarkNoAutoBuild', '-StarkQuitAfterSmoke', '-unattended', '-nosplash', '-nop4', '-NoSound') -PassThru
        if (-not $p.WaitForExit($TimeoutMinutes * 60000)) { $p.Kill(); Write-Warning 'PIE smoke timed out'; return $false }
        $res = Join-Path $proj 'Saved\Stark\pie_smoke.json'
        if (-not (Test-Path $res)) { return $false }
        $r = Get-Content $res -Raw | ConvertFrom-Json
        $r.steps | ForEach-Object { Write-Host "   $_" }
        return [bool]$r.ok
    }
}

$summary = [ordered]@{ engine = $engine.version; world = $World; when = (Get-Date -Format 'yyyy-MM-dd HH:mm'); results = $Results }
New-Item -ItemType Directory -Force (Join-Path $Here '_verify') | Out-Null
$summary | ConvertTo-Json -Depth 4 | Set-Content -Encoding UTF8 (Join-Path $Here '_verify\last_verify.json')
$allOk = -not ($Results.Values -contains $false)
Write-Host ''
Write-Host ($(if ($allOk) { "UE5 VERIFIED on Unreal Engine $($engine.version)" } else { 'UE5 NOT verified - see FAIL lines above' }))
exit $(if ($allOk) { 0 } else { 1 })
