# Candidate acquisition profile for an isolated GitHub hosted runner ONLY.
# Environment guards prevent accidents; they are NOT independent host attestation
# and are NOT an Execution Permit. Never run on the user's original host.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if ($args.Count -ne 0) { throw 'NO_COLLECTOR_ARGUMENTS_ALLOWED' }
if ($env:GITHUB_ACTIONS -cne 'true' -or $env:RUNNER_ENVIRONMENT -cne 'github-hosted' -or $env:RUNNER_OS -cne 'Windows' -or $env:RATE_NONGUI_PROFILE -cne 'READ_ONLY_RUNNER_PROFILE_V1') { throw 'HOSTED_RUNNER_ONLY_NOT_TARGET_AUTHORIZATION' }
if ($env:GITHUB_REPOSITORY -cne 'pili5420/RATE-Data-Engine' -or $env:GITHUB_HEAD_REF -cne 'codex/pagefile-nongui-readonly-evidence-v1') { throw 'EXACT_REPOSITORY_BRANCH_REQUIRED' }
if ($env:GITHUB_RUN_ID -notmatch '^\d+$' -or $env:GITHUB_RUN_ATTEMPT -notmatch '^\d+$' -or $env:RATE_NONGUI_HEAD -cnotmatch '^[0-9a-f]{40}$') { throw 'RUN_CONTEXT_REQUIRED' }

function UtcStamp { [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ss.ffffffZ',[Globalization.CultureInfo]::InvariantCulture) }
function HexHash([byte[]]$Bytes) {
    $h=[Security.Cryptography.SHA256]::Create()
    try { ([BitConverter]::ToString($h.ComputeHash($Bytes))).Replace('-','').ToLowerInvariant() } finally { $h.Dispose() }
}
function SaveNew([string]$Name,[object]$Value) {
    if ($Name -cnotmatch '^[A-Z_]+\.json$') { throw 'FIXED_EVIDENCE_NAME_REQUIRED' }
    $bytes=[Text.UTF8Encoding]::new($false).GetBytes((Microsoft.PowerShell.Utility\ConvertTo-Json -InputObject $Value -Depth 12 -Compress)+"`n")
    $file=[IO.File]::Open([IO.Path]::Combine($script:Output,$Name),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
    try { $file.Write($bytes,0,$bytes.Length);$file.Flush($true) } finally { $file.Dispose() }
}

$root=[IO.Path]::GetFullPath($env:RUNNER_TEMP)
if (-not [IO.Directory]::Exists($root)) { throw 'PHYSICAL_RUNNER_TEMP_REQUIRED' }
$ancestor=[IO.DirectoryInfo]::new($root)
while ($null -ne $ancestor) {
    if (($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'REPARSE_OUTPUT_ROOT_FORBIDDEN' }
    $ancestor=$ancestor.Parent
}
$Output=[IO.Path]::Combine($root,'rate-pagefile-nongui-'+$env:GITHUB_RUN_ID+'-'+$env:GITHUB_RUN_ATTEMPT)
if ([IO.Directory]::Exists($Output) -or [IO.File]::Exists($Output)) { throw 'ATTEMPT_OUTPUT_EXISTS_NO_RESUME' }
$intent=[IO.File]::Open($Output+'.intent',[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
try { $bytes=[Text.Encoding]::UTF8.GetBytes('RUNNER_ONLY_NOT_TARGET_HOST_EVIDENCE');$intent.Write($bytes,0,$bytes.Length);$intent.Flush($true) } finally { $intent.Dispose() }
[void][IO.Directory]::CreateDirectory($Output)
if (([IO.DirectoryInfo]::new($Output).Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'REPARSE_OUTPUT_FORBIDDEN' }
$definitions=@{
    computer=@{Class='Win32_ComputerSystem';Fields=@('Name','AutomaticManagedPagefile');Provider='CIMWin32'}
    boot=@{Class='Win32_OperatingSystem';Fields=@('CSName','LastBootUpTime','Version','BuildNumber');Provider='CIMWin32'}
    product=@{Class='Win32_ComputerSystemProduct';Fields=@('UUID');Provider='CIMWin32'}
    volumes=@{Class='Win32_Volume';Fields=@('DeviceID','DriveLetter','SerialNumber');Provider='MS_VOLUME'}
    settings=@{Class='Win32_PageFileSetting';Fields=@('Name','InitialSize','MaximumSize');Provider='CIMWin32'}
    usage=@{Class='Win32_PageFileUsage';Fields=@('Name','AllocatedBaseSize','CurrentUsage','PeakUsage','TempPageFile');Provider='CIMWin32'}
}
$order=@('computer_before','boot_before','product_before','volumes_before','settings','usage','registry','computer_after','boot_after','product_after','volumes_after')
$records=[Collections.Generic.List[object]]::new();$metadata=[Collections.Generic.List[object]]::new()
$started=UtcStamp;$total=[Diagnostics.Stopwatch]::StartNew();$failed=$false
foreach ($qid in $order) {
    $record=[ordered]@{id=$qid;namespace='ROOT/CIMV2';class='';fields=@();provider='';started_utc=(UtcStamp);ended_utc='';elapsed_ms=0;status='STARTED';error=$null;raw_utf8_b64='';raw_sha256=''}
    $watch=[Diagnostics.Stopwatch]::StartNew();$baseName=$qid.Replace('_before','').Replace('_after','')
    try {
        if ($total.Elapsed.TotalSeconds -gt 120) { throw 'TOTAL_DEADLINE_EXCEEDED_NO_RETRY' }
        if ($qid -ceq 'registry') {
            $record.namespace='REGISTRY64';$record.class='SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management';$record.fields=@('PagingFiles');$record.provider='Microsoft.Win32.RegistryKey'
            $hive=[Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine,[Microsoft.Win32.RegistryView]::Registry64)
            try {
                $key=$hive.OpenSubKey('SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management',$false)
                if ($null -eq $key) { throw 'REGISTRY_KEY_UNAVAILABLE' }
                try {
                    $kind=$key.GetValueKind('PagingFiles').ToString()
                    $values=$key.GetValue('PagingFiles',$null,[Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
                    if ($kind -cne 'MultiString' -or $null -eq $values -or $values.Count -gt 32) { throw 'REGISTRY_TYPE_MISSING_OR_BOUND' }
                    $rawValue=[ordered]@{kind=$kind;PagingFiles=@($values)}
                } finally { $key.Dispose() }
            } finally { $hive.Dispose() }
        } else {
            if (-not $definitions.ContainsKey($baseName)) { throw 'FIXED_PLAN_ONLY' }
            $definition=$definitions[$baseName];$record.class=$definition.Class;$record.fields=$definition.Fields
            $schema=CimCmdlets\Get-CimClass -Namespace 'ROOT/CIMV2' -ClassName $definition.Class -OperationTimeoutSec 5 -ErrorAction Stop
            $provider=[string]$schema.CimClassQualifiers['Provider'].Value;$record.provider=$provider
            if ($provider -cne $definition.Provider) { throw 'UNEXPECTED_PROVIDER_IDENTITY' }
            $metadata.Add([ordered]@{query_id=$qid;namespace='ROOT/CIMV2';class=$definition.Class;provider=$provider;fields=$definition.Fields})
            $instances=@(CimCmdlets\Get-CimInstance -Namespace 'ROOT/CIMV2' -ClassName $definition.Class -Property $definition.Fields -OperationTimeoutSec 5 -ErrorAction Stop)
            if ($instances.Count -gt 64) { throw 'CIM_INSTANCE_BOUND_EXCEEDED' }
            $rows=[Collections.Generic.List[object]]::new()
            foreach ($instance in $instances) {
                $row=[ordered]@{}
                foreach ($field in $definition.Fields) {
                    $value=$instance.CimInstanceProperties[$field].Value
                    if ($field -ceq 'LastBootUpTime') {
                        if ($value -isnot [DateTime] -or $value.Kind -eq [DateTimeKind]::Unspecified) { throw 'UNPROVEN_BOOT_DATETIME_KIND' }
                        $value=$value.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss.ffffffZ',[Globalization.CultureInfo]::InvariantCulture)
                    }
                    if ($value -is [string] -and $value.Length -gt 512) { throw 'CIM_STRING_BOUND_EXCEEDED' }
                    $row[$field]=$value
                }
                $rows.Add($row)
            }
            $rawValue=$rows.ToArray()
        }
        $raw=[Text.UTF8Encoding]::new($false).GetBytes((Microsoft.PowerShell.Utility\ConvertTo-Json -InputObject $rawValue -Depth 8 -Compress))
        if ($raw.Length -gt 98304) { throw 'RAW_BYTE_BOUND_EXCEEDED' }
        $record.raw_utf8_b64=[Convert]::ToBase64String($raw);$record.raw_sha256=HexHash $raw
        if ($watch.ElapsedMilliseconds -gt 10000 -or $total.Elapsed.TotalSeconds -gt 120) { throw 'DEADLINE_EXCEEDED_NO_RETRY' }
        $record.status='OK'
    } catch {
        $failed=$true;$record.status='SOURCE_ERROR';$record.error=$_.Exception.GetType().FullName+':'+$_.Exception.Message
    } finally {
        $watch.Stop();$record.ended_utc=UtcStamp;$record.elapsed_ms=$watch.ElapsedMilliseconds;$records.Add($record)
    }
    if ($failed) { break }
}
$total.Stop()
$packet=[ordered]@{version='PAGEFILE_NON_GUI_V1';realm='RUNNER_ONLY_NOT_TARGET_HOST_EVIDENCE';target_path='D:\pagefile.sys';started_utc=$started;ended_utc=(UtcStamp);runner=[ordered]@{run_id=$env:GITHUB_RUN_ID;run_attempt=$env:GITHUB_RUN_ATTEMPT;head=$env:RATE_NONGUI_HEAD;image_os=$env:ImageOS;image_version=$env:ImageVersion};records=$records.ToArray()}
SaveNew 'RAW_PACKET.json' $packet
SaveNew 'PROVIDER_METADATA.json' $metadata.ToArray()
$sourceIdentity=[Collections.Generic.List[object]]::new()
foreach ($name in @('runner_collect.ps1','evidence.py','fixtures.py','test_evidence.py','run_tests.py','test_collector_boundary.ps1')) {
    $file=[IO.Path]::Combine($PSScriptRoot,$name);$sourceIdentity.Add([ordered]@{name=$name;sha256=(Microsoft.PowerShell.Utility\Get-FileHash -LiteralPath $file -Algorithm SHA256).Hash.ToLowerInvariant()})
}
SaveNew 'ACQUISITION_AUDIT.json' ([ordered]@{realm='RUNNER_ONLY_NOT_TARGET_HOST_EVIDENCE';head=$env:RATE_NONGUI_HEAD;records=$records.Count;source_failure=$failed;source_files=$sourceIdentity.ToArray();runner_os=$env:RUNNER_OS;runner_environment=$env:RUNNER_ENVIRONMENT;image_os=$env:ImageOS;image_version=$env:ImageVersion;pwsh=$PSVersionTable.PSVersion.ToString();provider_cancellation_qualified=$false;host_attestation_qualified=$false;target_queries=0;Pagefile_modification_commands=0;no_retry_resume_fallback=$true;no_next_stage=$true})
if ($failed) { throw 'READ_SOURCE_FAILURE_PRESERVED_NO_RETRY' }
Microsoft.PowerShell.Utility\Write-Output ('RUNNER_ONLY_EVIDENCE_SAVED:'+ $Output)
