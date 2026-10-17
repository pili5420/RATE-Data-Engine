# Compile-only evidence collection. This is not a native identity adapter.
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('x86', 'x64')][string]$Architecture,
    [Parameter(Mandatory)][ValidateSet('qualification', 'independent')][string]$Role,
    [Parameter(Mandatory)][ValidatePattern('^[0-9a-f]{40}$')][string]$ExpectedHead,
    [Parameter(Mandatory)][string]$OutputRoot
)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$baseSha = '070faf7783e5b867b995ee3584a61fa71206e2f3'
$repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..'))
$utf8 = [Text.UTF8Encoding]::new($false)
$sourcePins = [ordered]@{
    'windows_abi_compile_only.cpp' = '4b642fdb1b5a165abf7e0fc6ad4f6f351875224048c4857e5d52b5f456bf5299'
    'windows_support_compile_only.cpp' = 'e164e8ba6697568e318fb0103b0f46d1a5aea0c81527f9fa19d064381c950fd9'
}
function Write-NewBytes([string]$Path, [byte[]]$Bytes) {
    $stream = [IO.File]::Open($Path, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::Read)
    try { $stream.Write($Bytes, 0, $Bytes.Length); $stream.Flush($true) } finally { $stream.Dispose() }
}
function Write-Json([string]$Name, $Value) {
    Write-NewBytes (Join-Path $OutputRoot $Name) $utf8.GetBytes(($Value | ConvertTo-Json -Depth 30) + "`n")
}
function Hash-File([string]$Path) { return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
function Run-Process([string]$Exe, [string[]]$Arguments, [string]$Prefix, $EnvironmentMap, [string]$RawArguments = '') {
    $info = [Diagnostics.ProcessStartInfo]::new()
    $info.FileName = $Exe; $info.UseShellExecute = $false; $info.CreateNoWindow = $true
    $info.WorkingDirectory = $OutputRoot; $info.RedirectStandardOutput = $true; $info.RedirectStandardError = $true
    $info.Environment.Clear()
    foreach ($key in $EnvironmentMap.Keys) { $info.Environment[$key] = [string]$EnvironmentMap[$key] }
    if ($RawArguments) { $info.Arguments = $RawArguments } else { foreach ($arg in $Arguments) { $info.ArgumentList.Add($arg) } }
    $started = [DateTimeOffset]::UtcNow
    Write-Json "$Prefix.INTENT.json" @{exe=$Exe; arguments=$Arguments; raw_arguments=$RawArguments; started_utc=$started.ToString('o'); deadline_seconds=60}
    $proc = [Diagnostics.Process]::new(); $proc.StartInfo = $info
    $stdout = [IO.MemoryStream]::new(); $stderr = [IO.MemoryStream]::new()
    $exitCode = $null; $timedOut = $false; $processId = $null; $errorText = $null
    try {
        if (!$proc.Start()) { throw 'PROCESS_START_FALSE' }
        $processId = $proc.Id
        $copyOut = $proc.StandardOutput.BaseStream.CopyToAsync($stdout)
        $copyErr = $proc.StandardError.BaseStream.CopyToAsync($stderr)
        if (!$proc.WaitForExit(60000)) { $timedOut = $true; $proc.Kill($true); $proc.WaitForExit() }
        [void]$copyOut.GetAwaiter().GetResult(); [void]$copyErr.GetAwaiter().GetResult()
        $exitCode = $proc.ExitCode
    } catch { $errorText = $_.ToString() + "`n" + $_.ScriptStackTrace }
    $outBytes = $stdout.ToArray(); $errBytes = $stderr.ToArray()
    Write-NewBytes (Join-Path $OutputRoot "$Prefix.stdout.log") $outBytes
    Write-NewBytes (Join-Path $OutputRoot "$Prefix.stderr.log") $errBytes
    $record = @{exe=$Exe; arguments=$Arguments; raw_arguments=$RawArguments; started_utc=$started.ToString('o'); ended_utc=[DateTimeOffset]::UtcNow.ToString('o'); child_pid=$processId; exit_code=$exitCode; timed_out=$timedOut; start_or_io_error=$errorText; stdout_sha256=Hash-File (Join-Path $OutputRoot "$Prefix.stdout.log"); stderr_sha256=Hash-File (Join-Path $OutputRoot "$Prefix.stderr.log")}
    Write-Json "$Prefix.PROCESS.json" $record
    $proc.Dispose(); $stdout.Dispose(); $stderr.Dispose()
    if ($null -ne $errorText -or $timedOut -or $null -eq $exitCode) { throw "PROCESS_UNKNOWN:$Prefix" }
    return @{record=$record; stdout=$outBytes; stderr=$errBytes}
}
function Snapshot-AcceptedSources {
    $rows = @(& git --no-optional-locks -C $repo ls-tree -r $baseSha)
    if ($LASTEXITCODE -ne 0 -or $rows.Count -ne 701) { throw 'ACCEPTED_TREE_COUNT' }
    $result = [ordered]@{}
    foreach ($row in $rows) {
        if ($row -notmatch '^([0-9]+) blob ([0-9a-f]{40})\t(.+)$') { throw 'TREE_ROW' }
        $mode=$Matches[1]; $oid=$Matches[2]; $path=$Matches[3]
        $bytes = [IO.File]::ReadAllBytes((Join-Path $repo $path))
        $header = [Text.Encoding]::ASCII.GetBytes('blob ' + $bytes.Length + [char]0)
        $full = [byte[]]::new($header.Length + $bytes.Length)
        [Array]::Copy($header, 0, $full, 0, $header.Length); [Array]::Copy($bytes, 0, $full, $header.Length, $bytes.Length)
        $actual = [Convert]::ToHexString([Security.Cryptography.SHA1]::HashData($full)).ToLowerInvariant()
        if ($actual -cne $oid) { throw "ACCEPTED_SOURCE_BYTES:$path" }
        $result[$path] = @{mode=$mode; git_blob=$oid; sha256=Hash-File (Join-Path $repo $path); bytes=$bytes.Length}
    }
    return $result
}
if ($env:GITHUB_ACTIONS -cne 'true' -or $env:RUNNER_OS -cne 'Windows' -or $env:ImageOS -cne 'win22' -or !$env:ImageVersion) { throw 'WINDOWS_2022_HOSTED_RUNNER_REQUIRED' }
if (![Environment]::Is64BitProcess) { throw 'X64_HARNESS_PROCESS_REQUIRED' }
$OutputRoot = [IO.Path]::GetFullPath($OutputRoot)
$tempRoot = [IO.Path]::GetFullPath($env:RUNNER_TEMP)
if ([IO.Path]::GetDirectoryName($OutputRoot) -ine $tempRoot -or [IO.Path]::GetFileName($OutputRoot) -cne "rt01-$Role-$Architecture") { throw 'EXACT_PRIVATE_OUTPUT_ROOT_REQUIRED' }
if (Test-Path -LiteralPath $OutputRoot) { throw 'OUTPUT_ROOT_EXISTS_NO_RETRY' }
if ((Get-Item -LiteralPath $tempRoot).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'TEMP_REPARSE' }
[IO.Directory]::CreateDirectory($OutputRoot) | Out-Null
$scriptFailure = $null
try {
    Write-Json 'ATTEMPT.json' @{mode='COMPILE_ONLY'; architecture=$Architecture; role=$Role; expected_head=$ExpectedHead; accepted_base=$baseSha; time_utc=[DateTimeOffset]::UtcNow.ToString('o'); github_run_id=$env:GITHUB_RUN_ID; github_run_attempt=$env:GITHUB_RUN_ATTEMPT; github_job=$env:GITHUB_JOB; no_retry=$true; runtime_gates='RT01-RT10_BLOCKED'; gate2='BLOCKED'; original_halt_root_cause='UNKNOWN'}
    $actualHead = (& git --no-optional-locks -C $repo rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $actualHead -cne $ExpectedHead) { throw 'EXACT_HEAD_MISMATCH' }
    $changes = @(& git --no-optional-locks -C $repo diff --name-status $baseSha HEAD)
    if ($LASTEXITCODE -ne 0 -or !$changes.Count) { throw 'MISSING_DIFF' }
    foreach ($change in $changes) { if ($change -notmatch '^A\t(\.github/workflows/rate_rt01_compile_only\.yml|tools/gui_rt01_compile_only/[A-Za-z0-9_.\-/]+)$') { throw "UNAUTHORIZED_DIFF:$change" } }
    $gitStatus = @(& git --no-optional-locks -C $repo status --porcelain=v1)
    if ($LASTEXITCODE -ne 0 -or $gitStatus.Count -ne 0) { throw 'DIRTY_OR_UNREADABLE_SOURCE' }
    $before = Snapshot-AcceptedSources
    Write-Json 'ACCEPTED_SOURCE_BEFORE.json' $before
    $runner = @{image_os=$env:ImageOS; image_version=$env:ImageVersion; image_release=$env:ImageRelease; runner_os=$env:RUNNER_OS; runner_arch=$env:RUNNER_ARCH; runner_environment=$env:RUNNER_ENVIRONMENT; runner_name=$env:RUNNER_NAME; os_version=[Environment]::OSVersion.VersionString; powershell_version=$PSVersionTable.PSVersion.ToString(); architecture=$Architecture; exact_head=$actualHead; base_sha=$baseSha; changes=$changes}
    Write-Json 'RUNNER_IDENTITY.json' $runner
    $vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
    if (!(Test-Path -LiteralPath $vswhere -PathType Leaf)) { throw 'VSWHERE_MISSING_NO_INSTALL' }
    $discovery = & $vswhere -latest -products '*' -version '[17.0,18.0)' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -format json -utf8
    if ($LASTEXITCODE -ne 0) { throw 'VSWHERE_FAILED' }
    Write-NewBytes (Join-Path $OutputRoot 'VSWHERE.json') $utf8.GetBytes(($discovery -join "`n") + "`n")
    $instances = @(($discovery -join "`n") | ConvertFrom-Json)
    if ($instances.Count -ne 1 -or !$instances[0].isComplete -or !$instances[0].isLaunchable) { throw 'UNIQUE_COMPLETE_VS2022_REQUIRED' }
    $vcvars = Join-Path $instances[0].installationPath 'VC/Auxiliary/Build/vcvarsall.bat'
    $archArg = if ($Architecture -ceq 'x86') {'amd64_x86'} else {'amd64'}
    $vcvarsLog = Join-Path $OutputRoot 'VCVARS.raw.log'
    foreach ($safePath in @($vcvars, $vcvarsLog)) { if ($safePath -notmatch '^[a-zA-Z0-9_:\\ .()\-]+$') { throw 'UNSAFE_CMD_PATH' } }
    $bootstrapEnv = [ordered]@{}
    foreach ($key in @('SystemRoot','SystemDrive','windir','ComSpec','ProgramFiles','ProgramFiles(x86)','ProgramW6432','USERPROFILE','LOCALAPPDATA','APPDATA','TEMP','TMP','PATH','PROCESSOR_ARCHITECTURE','NUMBER_OF_PROCESSORS')) { $value=[Environment]::GetEnvironmentVariable($key); if ($value) {$bootstrapEnv[$key]=$value} }
    $bootstrapEnv['VSCMD_SKIP_SENDTELEMETRY']='1'; $bootstrapEnv['VSLANG']='1033'
    $raw = '/d /s /c "call "' + $vcvars + '" ' + $archArg + ' > "' + $vcvarsLog + '" 2>&1 && set"'
    # Only selected bootstrap environment is passed: no secrets or CL/_CL_/LINK flags.
    $envResult = Run-Process $env:ComSpec @() 'VCVARS' $bootstrapEnv $raw
    if ($envResult.record.exit_code -ne 0) { throw 'VCVARS_FAILED' }
    $parsed = @{}
    foreach ($line in $utf8.GetString($envResult.stdout) -split "`r?`n") { if ($line -match '^([^=]+)=(.*)$') {$parsed[$Matches[1]]=$Matches[2]} }
    # The full SET output has no credentials because bootstrapEnv was cleared.
    $allowEnv = @('SystemRoot','SystemDrive','windir','ComSpec','ProgramFiles','ProgramFiles(x86)','ProgramW6432','TEMP','TMP','PATH','INCLUDE','LIB','LIBPATH','VCToolsInstallDir','VCToolsVersion','WindowsSdkDir','WindowsSDKVersion','UniversalCRTSdkDir','UCRTVersion','VSCMD_ARG_HOST_ARCH','VSCMD_ARG_TGT_ARCH')
    $compileEnv = [ordered]@{}
    foreach ($key in $allowEnv) { if ($parsed.ContainsKey($key)) {$compileEnv[$key]=$parsed[$key]} }
    $compileEnv['VSLANG']='1033'
    if ($compileEnv['VSCMD_ARG_TGT_ARCH'] -cne $Architecture -or $compileEnv['VSCMD_ARG_HOST_ARCH'] -cne 'x64') { throw 'TARGET_ENVIRONMENT_MISMATCH' }
    foreach ($required in @('INCLUDE','VCToolsInstallDir','VCToolsVersion','WindowsSdkDir','WindowsSDKVersion')) { if (!$compileEnv[$required]) { throw "MISSING_TOOL_ENV:$required" } }
    Write-Json 'CONTROLLED_COMPILER_ENVIRONMENT.json' $compileEnv
    $compiler = Join-Path $compileEnv['VCToolsInstallDir'] "bin/Hostx64/$Architecture/cl.exe"
    $compilerItem = Get-Item -LiteralPath $compiler
    $signature = Get-AuthenticodeSignature -LiteralPath $compiler
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=Microsoft Corporation') { throw 'MICROSOFT_COMPILER_SIGNATURE_REQUIRED' }
    $sdkVersion = $compileEnv['WindowsSDKVersion'].TrimEnd('\')
    if ($sdkVersion -notmatch '^10\.0\.[0-9]+\.[0-9]+$') { throw 'SDK_VERSION_FORMAT' }
    $headerRows = [ordered]@{}
    foreach ($relative in @('um/Windows.h','um/winbase.h','um/winuser.h','um/aclapi.h','um/winnt.h','shared/basetsd.h')) {
        $headerPath = Join-Path $compileEnv['WindowsSdkDir'] "Include/$sdkVersion/$relative"
        $headerRows[$relative] = @{path=$headerPath; sha256=Hash-File $headerPath; bytes=(Get-Item -LiteralPath $headerPath).Length}
    }
    Write-Json 'TOOLCHAIN_IDENTITY.json' @{compiler_path=$compiler; compiler_sha256=Hash-File $compiler; compiler_file_version=$compilerItem.VersionInfo.FileVersion; compiler_product_version=$compilerItem.VersionInfo.ProductVersion; signature_status=[string]$signature.Status; signer_subject=$signature.SignerCertificate.Subject; signer_thumbprint=$signature.SignerCertificate.Thumbprint; vcvars_path=$vcvars; vcvars_sha256=Hash-File $vcvars; vcvars_arch_argument=$archArg; target_architecture=$Architecture; vc_tools_version=$compileEnv['VCToolsVersion']; sdk_root=$compileEnv['WindowsSdkDir']; sdk_version=$sdkVersion; headers=$headerRows; link_invoked=$false; target_execution=$false; native_gui_dispatch=$false}
    $compileResults = @()
    foreach ($name in $sourcePins.Keys) {
        $source = Join-Path $repo "tools/gui_runtime_readiness/$name"
        if ((Hash-File $source) -cne $sourcePins[$name]) { throw "SOURCE_PIN_MISMATCH:$name" }
        $stem = [IO.Path]::GetFileNameWithoutExtension($name)
        $object = Join-Path $OutputRoot "$stem.obj"
        $arguments = @('/nologo','/std:c++17','/W4','/WX','/c','/Bv','/showIncludes',"/Fo$object",$source)
        $result = Run-Process $compiler $arguments $stem $compileEnv
        $objectEvidence = $null
        if (Test-Path -LiteralPath $object -PathType Leaf) {
            $bytes = [IO.File]::ReadAllBytes($object)
            if ($bytes.Length -lt 20) { throw 'OBJECT_TOO_SHORT' }
            $machine = [BitConverter]::ToUInt16($bytes,0)
            $expectedMachine = if ($Architecture -ceq 'x86') {0x014c} else {0x8664}
            if ($machine -ne $expectedMachine -or [BitConverter]::ToUInt16($bytes,16) -ne 0 -or ([BitConverter]::ToUInt16($bytes,18) -band 0x2002)) { throw 'OBJECT_MACHINE_OR_EXECUTABLE_FLAG' }
            $objectEvidence = @{path=$object; sha256=Hash-File $object; bytes=$bytes.Length; coff_machine=$machine; optional_header_size=[BitConverter]::ToUInt16($bytes,16)}
        }
        $case = @{source=$source; source_sha256=Hash-File $source; architecture=$Architecture; role=$Role; exact_head=$actualHead; command_executable=$compiler; command_arguments=$arguments; compiler_exit_code=$result.record.exit_code; object=$objectEvidence; status=if ($result.record.exit_code -eq 0 -and $null -ne $objectEvidence) {'PASS_COMPILE_ONLY'} else {'FAIL'}; no_link=$true; no_target_execution=$true; no_native_GUI_dispatch=$true}
        Write-Json "$stem.RESULT.json" $case
        $compileResults += $case
    }
    $after = Snapshot-AcceptedSources
    Write-Json 'ACCEPTED_SOURCE_AFTER.json' $after
    if (($before | ConvertTo-Json -Depth 10 -Compress) -cne ($after | ConvertTo-Json -Depth 10 -Compress)) { throw 'SOURCE_CHANGED_DURING_COMPILATION' }
    $gitStatus = @(& git --no-optional-locks -C $repo status --porcelain=v1)
    if ($LASTEXITCODE -ne 0 -or $gitStatus.Count -ne 0) { throw 'SOURCE_DIRTY_OR_UNREADABLE_AFTER_COMPILATION' }
    $unexpected = @(Get-ChildItem -LiteralPath $OutputRoot -File | Where-Object { $_.Extension -notin @('.json','.log','.obj') })
    if ($unexpected.Count -or @(Get-ChildItem -LiteralPath $OutputRoot -Directory).Count) { throw 'UNEXPECTED_COMPILER_OUTPUT' }
    Write-Json 'ARCHITECTURE_RESULT.json' @{status=if (@($compileResults | Where-Object {$_.status -ne 'PASS_COMPILE_ONLY'}).Count) {'FAIL'} else {'RT01_COMPILE_ONLY_SUBGATE_PASS'}; architecture=$Architecture; role=$Role; exact_head=$actualHead; cases=$compileResults; unchanged_accepted_source_files=$after.Count; rt01_full='BLOCKED'; runtime_gates='RT01-RT10_BLOCKED'; gate2='BLOCKED'; original_halt_root_cause='UNKNOWN'; no_link=$true; no_target_execution=$true; no_native_GUI_dispatch=$true}
    if (@($compileResults | Where-Object {$_.status -ne 'PASS_COMPILE_ONLY'}).Count) { throw 'COMPILE_FAILURE_PRESERVED_NO_PROMOTION' }
} catch {
    $scriptFailure = $_.ToString() + "`n" + $_.ScriptStackTrace
    Write-Json 'FAILURE.json' @{status='BLOCKED'; error=$scriptFailure; exact_head=$ExpectedHead; architecture=$Architecture; role=$Role; time_utc=[DateTimeOffset]::UtcNow.ToString('o'); no_retry=$true}
} finally {
    $manifest = [ordered]@{}
    foreach ($file in Get-ChildItem -LiteralPath $OutputRoot -File | Sort-Object Name) { $manifest[$file.Name]=@{sha256=Hash-File $file.FullName; bytes=$file.Length} }
    Write-Json 'FILE_SHA256_INDEX.json' @{exact_head=$ExpectedHead; files=$manifest; index_excludes_itself=$true}
}
if ($scriptFailure) { throw $scriptFailure }
