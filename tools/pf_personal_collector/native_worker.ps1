# Fixed Runner-only child. No Owner Consent, script/query or target arguments.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
if ($args.Count -ne 0) { throw 'NO_ARGUMENTS_OR_CONSENT_ACCEPTED' }
if ($env:PF002_AUTH_PIPE -cnotmatch '^[0-9]+$' -or $env:PF002_RUN_ID -cnotmatch '^[0-9]+$' -or $env:PF002_RUN_ATTEMPT -cne '1' -or $env:PF002_HEAD -cnotmatch '^[0-9a-f]{40}$') { throw 'SIGNED_RUNNER_PIPE_REQUIRED' }
function Hash256([byte[]]$b) { [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($b)).ToLowerInvariant() }
function DecodeUrl([string]$s) {
    if ($s -cnotmatch '^[A-Za-z0-9_-]+$') { throw 'JWT_ENCODING' }
    $b=[Convert]::FromBase64String($s.Replace('-','+').Replace('_','/')+('='*((4-$s.Length%4)%4)))
    if ([Convert]::ToBase64String($b).TrimEnd('=').Replace('+','-').Replace('/','_') -cne $s) { throw 'JWT_ENCODING' }
    return ,$b
}
function ReadDoc([byte[]]$b) {
    $doc=[Text.Json.JsonDocument]::Parse([Text.UTF8Encoding]::new($false,$true).GetString($b))
    if ($doc.RootElement.ValueKind -ne [Text.Json.JsonValueKind]::Object) { throw 'JWT_OBJECT' }
    $keys=[Collections.Generic.HashSet[string]]::new([StringComparer]::Ordinal)
    foreach ($p in $doc.RootElement.EnumerateObject()) { if (-not $keys.Add($p.Name)) { throw 'DUPLICATE_JWT_KEY' } }
    return $doc
}
$pipe=[IO.Pipes.AnonymousPipeClientStream]::new([IO.Pipes.PipeDirection]::In,$env:PF002_AUTH_PIPE)
try {
    $reader=[IO.StreamReader]::new($pipe,[Text.UTF8Encoding]::new($false,$true),$false,1024,$true)
    try { $jwt=$reader.ReadLine();if ($null -eq $jwt -or $jwt.Length -gt 16384 -or $null -ne $reader.ReadLine()) { throw 'SIGNED_RUNNER_PROOF_REQUIRED' } } finally { $reader.Dispose() }
} finally { $pipe.Dispose() }
$parts=$jwt.Split('.');if ($parts.Count -ne 3) { throw 'SIGNED_RUNNER_PROOF_REQUIRED' }
$hd=ReadDoc (DecodeUrl $parts[0]);$cd=ReadDoc (DecodeUrl $parts[1])
try {
    $h=$hd.RootElement;$c=$cd.RootElement
    foreach ($prop in $h.EnumerateObject()) { if ($prop.Name -cnotin @('alg','kid','typ','x5t')) { throw 'JOSE_HEADER' } }
    if ($h.GetProperty('alg').GetString() -cne 'RS256' -or $h.GetProperty('typ').GetString() -cne 'JWT') { throw 'JOSE_HEADER' }
    $jb=[IO.File]::ReadAllBytes([IO.Path]::Combine($PSScriptRoot,'GITHUB_OIDC_JWKS_PINNED.json'))
    if ((Hash256 $jb) -cne '5f8164c9696c27837ad18c5fe7c7022a433bd5390183e8ff15c74d82233270f4') { throw 'GITHUB_KEYS_PIN' }
    $j=[Text.Encoding]::UTF8.GetString($jb) | Microsoft.PowerShell.Utility\ConvertFrom-Json -AsHashtable
    $keys=@($j.keys | Where-Object { $_.kid -ceq $h.GetProperty('kid').GetString() })
    if ($keys.Count -ne 1 -or $keys[0].kty -cne 'RSA' -or $keys[0].use -cne 'sig') { throw 'UNKNOWN_KEY_NO_REFRESH' }
    $rsa=[Security.Cryptography.RSA]::Create()
    try {
        $rp=[Security.Cryptography.RSAParameters]::new();$rp.Modulus=DecodeUrl $keys[0].n;$rp.Exponent=DecodeUrl $keys[0].e;$rsa.ImportParameters($rp)
        if ($rsa.KeySize -lt 2048 -or $rsa.KeySize -gt 4096) { throw 'RSA_STRENGTH' }
        if (-not $rsa.VerifyData([Text.Encoding]::ASCII.GetBytes($parts[0]+'.'+$parts[1]),(DecodeUrl $parts[2]),[Security.Cryptography.HashAlgorithmName]::SHA256,[Security.Cryptography.RSASignaturePadding]::Pkcs1)) { throw 'RUNNER_SIGNATURE' }
    } finally { $rsa.Dispose() }
    $repo='pili5420/RATE-Data-Engine';$ref='refs/heads/codex/pf-personal-readonly-collector-v1'
    $required=@{iss='https://token.actions.githubusercontent.com';aud='rate-pf-personal-002-runner-only';repository=$repo;repository_id='1370145728';repository_owner_id='325481386';ref=$ref;event_name='push';runner_environment='github-hosted';sha=$env:PF002_HEAD;workflow_sha=$env:PF002_HEAD;workflow_ref=($repo+'/.github/workflows/rate_pf_personal_collector.yml@'+$ref);run_id=$env:PF002_RUN_ID;run_attempt='1'}
    foreach ($key in $required.Keys) { if ($c.GetProperty($key).GetString() -cne $required[$key]) { throw 'RUNNER_CLAIM_BINDING' } }
    if ($c.GetProperty('sub').GetString() -cnotin @(('repo:'+$repo+':ref:'+$ref),('repo:pili5420@325481386/RATE-Data-Engine@1370145728:ref:'+$ref))) { throw 'RUNNER_SUBJECT' }
    $now=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds();$iat=$c.GetProperty('iat').GetInt64();$nbf=$c.GetProperty('nbf').GetInt64();$exp=$c.GetProperty('exp').GetInt64()
    if ($nbf -gt $now -or $now -ge $exp -or $iat -gt $now -or $exp-$iat -le 0 -or $exp-$iat -gt 900 -or $now-$iat -gt 600) { throw 'RUNNER_PROOF_EXPIRED' }
} finally { $hd.Dispose();$cd.Dispose();$jwt=$null }
# Signed bearer proves workflow provenance, not physical machine attestation or OriginalHost authorization.
$scopePath=[IO.Path]::Combine($PSScriptRoot,'..','pf_personal_trust','READ_SCOPE_V1.json');$sb=[IO.File]::ReadAllBytes($scopePath)
if ((Hash256 $sb) -cne 'f96d742c5da542e1f2cd99cc6d49cd1b751ac0cb999c10d159ecb3f283ec5bd3') { throw 'ACCEPTED_SCOPE_CHANGED' }
$scope=[Text.Encoding]::UTF8.GetString($sb) | Microsoft.PowerShell.Utility\ConvertFrom-Json -AsHashtable
. ([IO.Path]::Combine($PSScriptRoot,'descriptor_policy.ps1')) # fixed pinned pure predicate, no dynamic target
$root=[IO.Path]::GetFullPath($env:PF002_PRIVATE_ROOT)
if ($env:PF002_ROLE -cnotin @('qualification','reproduction')) { throw 'FIXED_RUNNER_ROLE' }
$runnerRoot=[IO.Path]::GetFullPath($env:PF002_RUNNER_ROOT)
$expectedRoot=[IO.Path]::Combine($runnerRoot,('PF-PERSONAL-002-'+$env:PF002_RUN_ID+'-1-'+$env:PF002_ROLE),'private')
if ($runnerRoot -cne $env:PF002_RUNNER_ROOT -or $root -cne $env:PF002_PRIVATE_ROOT -or $root -cne $expectedRoot -or -not [IO.Directory]::Exists($root)) { throw 'PRIVATE_ROOT' }
$ancestor=[IO.DirectoryInfo]::new($root)
while ($null -ne $ancestor) { if (($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw 'PRIVATE_REPARSE' };$ancestor=$ancestor.Parent }
function Stamp { [DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ',[Globalization.CultureInfo]::InvariantCulture) }
function SortValue([object]$v) {
    if ($null -eq $v) { return $null }
    if ($v -is [Collections.IDictionary]) {
        $r=[Collections.Generic.SortedDictionary[string,object]]::new([StringComparer]::Ordinal)
        foreach ($k in $v.Keys) { $r[$k]=SortValue $v[$k] };return ,$r
    }
    if ($v -is [Array] -or $v -is [Collections.Generic.List[object]]) {
        $r=[Collections.Generic.List[object]]::new()
        foreach ($x in $v) { $r.Add((SortValue $x)) };return ,$r.ToArray()
    }
    return $v
}
function JsonBytes([object]$v) { return ,[Text.UTF8Encoding]::new($false,$true).GetBytes((Microsoft.PowerShell.Utility\ConvertTo-Json -InputObject (SortValue $v) -Depth 16 -Compress)+([string][char]10)) }
function SavePrivate([string]$name,[byte[]]$bytes) {
    if ($name -cnotmatch '^(record_[0-9]{2}|error_[0-9]{2}|PRIVATE_PACKET)\.json$') { throw 'FIXED_PRIVATE_FILE_REQUIRED' }
    $f=[IO.File]::Open([IO.Path]::Combine($root,$name),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
    try { $f.Write($bytes,0,$bytes.Length);$f.Flush($true) } finally { $f.Dispose() }
}
$records=[Collections.Generic.List[object]]::new();$total=[Diagnostics.Stopwatch]::StartNew();$started=Stamp;$halt=$false
foreach ($id in $scope.order) {
    $q=$id.Replace('_before','').Replace('_after','');$spec=$scope.queries[$q]
    $record=@{sequence=($records.Count+1);id=$id;query=$spec;status='STARTED';started_utc=(Stamp);ended_utc='';elapsed_ms=0;raw_base64=$null;raw_sha256=$null;error_kind=$null;hresult=$null;provider_availability='UNDETERMINED'}
    $watch=[Diagnostics.Stopwatch]::StartNew()
    try {
        if ($total.Elapsed.TotalSeconds -gt 120) { throw 'TOTAL_DEADLINE' }
        $rows=[Collections.Generic.List[object]]::new()
        if ($q -ceq 'account') {
            $identity=[Security.Principal.WindowsIdentity]::GetCurrent()
            try { $rows.Add(@{UserSID=$identity.User.Value;SessionId=[Diagnostics.Process]::GetCurrentProcess().SessionId}) } finally { $identity.Dispose() }
        } elseif ($q -ceq 'registry') {
            $hive=[Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine,[Microsoft.Win32.RegistryView]::Registry64)
            try {
                $key=$hive.OpenSubKey('SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management',$false)
                if ($null -eq $key) { throw 'REGISTRY_KEY_UNAVAILABLE' }
                try { $value=$key.GetValue('PagingFiles',$null,[Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames) } finally { $key.Dispose() }
                if ($null -eq $value -or $value -isnot [string[]] -or $value.Count -gt 16) { throw 'REGISTRY_VALUE_TYPE_OR_BOUND' }
                foreach ($v in $value) { if ($v.Length -gt 512) { throw 'REGISTRY_STRING_BOUND' } }
                $rows.Add(@{PagingFiles=@($value)})
            } finally { $hive.Dispose() }
        } else {
            $options=@{Namespace=$spec.namespace;ClassName=$spec.class;Property=$spec.fields;OperationTimeoutSec=5;ErrorAction='Stop'}
            if ($null -ne $spec.filter) { $options['Filter']=$spec.filter }
            CimCmdlets\Get-CimInstance @options | ForEach-Object {
                $instance=$_
                if ($rows.Count -ge 1) { throw 'SINGLE_ROW_BOUND' }
                if ($instance.CimSystemProperties.Namespace.Replace('\','/') -ine $spec.namespace -or $instance.CimSystemProperties.ClassName -cne $spec.class) { throw 'RESPONSE_SOURCE_MISMATCH' }
                foreach ($property in $instance.CimInstanceProperties) {
                    if ($property.Name -cnotin $spec.fields -and ($property.Flags -band [Microsoft.Management.Infrastructure.CimFlags]::Key) -eq 0) {
                        # -Property leaves unpopulated class descriptors. Only explicit null metadata may be discarded.
                        if (-not (UnrequestedDescriptorSafe ([long]$property.Flags) $property.Value)) { throw 'EXTRA_NONKEY_PROPERTY' }
                    }
                }
                $row=@{}
                foreach ($field in $spec.fields) {
                    $value=$instance.CimInstanceProperties[$field].Value
                    if ($null -eq $value) { throw 'NULL_REQUIRED_FIELD' }
                    if ($field -ceq 'LastBootUpTime') {
                        if ($value -isnot [DateTime] -or $value.Kind -eq [DateTimeKind]::Unspecified) { throw 'BOOT_DATETIME_KIND' }
                        $value=$value.ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ssZ',[Globalization.CultureInfo]::InvariantCulture)
                    }
                    if ($value -is [string] -and $value.Length -gt 512) { throw 'STRING_BOUND' }
                    $row[$field]=$value
                };$rows.Add($row)
            }
        }
        $raw=JsonBytes $rows.ToArray()
        if ($raw.Length -gt 16384) { throw 'RAW_BYTE_BOUND' }
        $record.raw_base64=[Convert]::ToBase64String($raw);$record.raw_sha256=Hash256 $raw
        $record.status=if ($rows.Count -eq 0) { 'SOURCE_ABSENT' } else { 'OBSERVED' }
        $record.provider_availability=if ($rows.Count -eq 0) { 'QUERY_SUCCEEDED_NO_INSTANCE' } else { 'RESPONSE_RECEIVED_NOT_PROVIDER_BINARY_ATTESTATION' }
    } catch {
        $record.hresult=[int]$_.Exception.HResult;$record.error_kind=$_.Exception.GetType().Name
        $err=@{exception_type=$_.Exception.GetType().FullName;hresult=[int]$_.Exception.HResult;message=$_.Exception.Message;error_record=$_.ToString();script_stack=$_.ScriptStackTrace;cim_status=$null;native_error=$null}
        if ($_.Exception -is [Microsoft.Management.Infrastructure.CimException]) { $err.cim_status=$_.Exception.StatusCode.ToString();$err.native_error=$_.Exception.NativeErrorCode }
        $errorBytes=JsonBytes $err
        if ($errorBytes.Length -gt 65536) { $errorBytes=JsonBytes @{exception_type=$err.exception_type;hresult=$err.hresult;cim_status=$err.cim_status;native_error=$err.native_error;oversized_error_sha256=(Hash256 $errorBytes);details='PRIVATE_ERROR_TOO_LARGE_NOT_PUBLIC'} }
        SavePrivate ('error_{0:D2}.json' -f ($records.Count+1)) $errorBytes
        $missing=($_.Exception -is [Microsoft.Management.Infrastructure.CimException]) -and ($_.Exception.StatusCode.ToString() -cin @('InvalidClass','InvalidNamespace','NotFound'))
        if ($q -ceq 'tpm' -and $missing) { $record.status='UNAVAILABLE';$record.provider_availability='OPTIONAL_PROVIDER_UNAVAILABLE' }
        else { $record.status='HALT';$record.provider_availability='SOURCE_ERROR';$halt=$true }
    } finally {
        $watch.Stop();$record.elapsed_ms=$watch.ElapsedMilliseconds;$record.ended_utc=Stamp
        if ($watch.ElapsedMilliseconds -gt 5000 -or $total.ElapsedMilliseconds -gt 120000) { $record.status='HALT';$record.error_kind='DEADLINE_EXCEEDED';$halt=$true }
        $records.Add($record);SavePrivate ('record_{0:D2}.json' -f $records.Count) (JsonBytes $record)
    }
    if ($halt) { break }
}
$total.Stop()
$packet=@{version='PF_PERSONAL_002_NATIVE_PRIVATE_V1';realm='RUNNER_ONLY_NOT_ORIGINAL_HOST_EVIDENCE';head=$env:PF002_HEAD;run_id=$env:PF002_RUN_ID;run_attempt=$env:PF002_RUN_ATTEMPT;started_utc=$started;ended_utc=(Stamp);elapsed_ms=$total.ElapsedMilliseconds;status=$(if($halt){'HALT'}else{'COMPLETED'});records=$records.ToArray();powershell_version=$PSVersionTable.PSVersion.ToString()}
SavePrivate 'PRIVATE_PACKET.json' (JsonBytes $packet)
if ($halt) { exit 2 };exit 0

