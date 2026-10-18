# Parses candidate source; NEVER dot-sources or invokes runner_collect.ps1.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
function Read-LiteralAst($Node) {
    if ($Node -is [Management.Automation.Language.StringConstantExpressionAst]) { return $Node.Value }
    if ($Node -is [Management.Automation.Language.StatementBlockAst]) {
        if ($Node.Statements.Count -ne 1) { throw 'LITERAL_STATEMENT_REQUIRED' };return Read-LiteralAst $Node.Statements[0]
    }
    if ($Node -is [Management.Automation.Language.PipelineAst]) {
        if ($Node.PipelineElements.Count -ne 1) { throw 'LITERAL_PIPELINE_REQUIRED' };return Read-LiteralAst $Node.PipelineElements[0]
    }
    if ($Node -is [Management.Automation.Language.CommandExpressionAst]) { return Read-LiteralAst $Node.Expression }
    if ($Node -is [Management.Automation.Language.ArrayExpressionAst]) { return Read-LiteralAst $Node.SubExpression }
    if ($Node -is [Management.Automation.Language.ArrayLiteralAst]) {
        $values=[Collections.Generic.List[object]]::new();foreach ($element in $Node.Elements) { $values.Add((Read-LiteralAst $element)) };return $values.ToArray()
    }
    if ($Node -is [Management.Automation.Language.HashtableAst]) {
        $value=@{}
        foreach ($pair in $Node.KeyValuePairs) {
            $key=Read-LiteralAst $pair.Item1
            if ($value.ContainsKey($key)) { throw 'DUPLICATE_PLAN_KEY' }
            $value[$key]=Read-LiteralAst $pair.Item2
        }
        return $value
    }
    throw ('NONLITERAL_PLAN:'+ $Node.GetType().Name)
}
function Assert-ReadOnlySource([string]$Text) {
    $tokens=$null;$errors=$null
    $tree=[Management.Automation.Language.Parser]::ParseInput($Text,[ref]$tokens,[ref]$errors)
    if ($errors.Count) { throw 'PARSE_ERROR' }
    $allowed=@('Set-StrictMode','UtcStamp','HexHash','SaveNew','CimCmdlets\Get-CimClass','CimCmdlets\Get-CimInstance','Microsoft.PowerShell.Utility\ConvertTo-Json','Microsoft.PowerShell.Utility\Get-FileHash','Microsoft.PowerShell.Utility\Write-Output')
    foreach ($command in $tree.FindAll({param($n) $n -is [Management.Automation.Language.CommandAst]},$true)) {
        $name=$command.GetCommandName()
        if ($null -eq $name -or $name -cnotin $allowed -or $command.InvocationOperator -in @([Management.Automation.Language.TokenKind]::Ampersand,[Management.Automation.Language.TokenKind]::Dot)) { throw 'COMMAND_OUTSIDE_FIXED_READ_PLAN' }
        if ($name -in @('CimCmdlets\Get-CimInstance','CimCmdlets\Get-CimClass')) {
            $want=if($name -ceq 'CimCmdlets\Get-CimInstance'){@('Namespace','ClassName','Property','OperationTimeoutSec','ErrorAction')}else{@('Namespace','ClassName','OperationTimeoutSec','ErrorAction')}
            $params=@($command.CommandElements | Where-Object { $_ -is [Management.Automation.Language.CommandParameterAst] })
            if ($params.Count -ne $want.Count -or @($params | Where-Object { $_.ParameterName -cnotin $want }).Count) { throw 'CIM_PARAMETER_OUTSIDE_FIXED_PLAN' }
            $expected=if($name -ceq 'CimCmdlets\Get-CimInstance'){"CimCmdlets\Get-CimInstance -Namespace 'ROOT/CIMV2' -ClassName `$definition.Class -Property `$definition.Fields -OperationTimeoutSec 5 -ErrorAction Stop"}else{"CimCmdlets\Get-CimClass -Namespace 'ROOT/CIMV2' -ClassName `$definition.Class -OperationTimeoutSec 5 -ErrorAction Stop"}
            if ($command.Extent.Text -cne $expected) { throw 'CIM_EXACT_COMMAND_REQUIRED' }
        }
    }
    $methods=@('new','ToString','Create','ComputeHash','Replace','ToLowerInvariant','Dispose','GetBytes','Open','Combine','Write','Flush','GetFullPath','Exists','CreateDirectory','StartNew','ContainsKey','OpenBaseKey','OpenSubKey','GetValueKind','GetValue','Add','ToUniversalTime','ToBase64String','Stop','GetType','ToArray')
    foreach ($invoke in $tree.FindAll({param($n) $n -is [Management.Automation.Language.InvokeMemberExpressionAst]},$true)) {
        $name=$invoke.Member.Value
        if ($null -eq $name -or $name -cnotin $methods) { throw 'METHOD_OUTSIDE_FIXED_PROFILE' }
    }
    $sensitive=[ordered]@{
        OpenBaseKey=@('[Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine,[Microsoft.Win32.RegistryView]::Registry64)')
        OpenSubKey=@("`$hive.OpenSubKey('SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management',`$false)")
        GetValueKind=@("`$key.GetValueKind('PagingFiles')")
        GetValue=@("`$key.GetValue('PagingFiles',`$null,[Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)")
        Create=@('[Security.Cryptography.SHA256]::Create()')
        CreateDirectory=@('[IO.Directory]::CreateDirectory($Output)')
        Open=@('[IO.File]::Open([IO.Path]::Combine($script:Output,$Name),[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)',"[IO.File]::Open(`$Output+'.intent',[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)")
        Write=@('$file.Write($bytes,0,$bytes.Length)','$intent.Write($bytes,0,$bytes.Length)')
        Flush=@('$file.Flush($true)','$intent.Flush($true)')
    }
    foreach ($key in $sensitive.Keys) {
        $calls=@($tree.FindAll({param($n) $n -is [Management.Automation.Language.InvokeMemberExpressionAst] -and $n.Member.Value -ceq $key},$true))
        if ($calls.Count -ne $sensitive[$key].Count -or @($calls | Where-Object { $_.Extent.Text -cnotin $sensitive[$key] }).Count) { throw 'EXACT_SENSITIVE_CALL_BOUNDARY' }
    }
    foreach ($type in $tree.FindAll({param($n) $n -is [Management.Automation.Language.TypeExpressionAst]},$true)) {
        if ($type.TypeName.FullName -cnotin @('string','DateTime','Globalization.CultureInfo','Security.Cryptography.SHA256','BitConverter','Text.UTF8Encoding','IO.File','IO.Path','IO.FileMode','IO.FileAccess','IO.FileShare','IO.Directory','IO.DirectoryInfo','IO.FileAttributes','Text.Encoding','Collections.Generic.List[object]','Diagnostics.Stopwatch','Microsoft.Win32.RegistryKey','Microsoft.Win32.RegistryHive','Microsoft.Win32.RegistryView','Microsoft.Win32.RegistryValueOptions','DateTimeKind','Convert')) { throw 'TYPE_OUTSIDE_FIXED_PROFILE' }
    }
    if (-not $Text.Contains("`$key=`$hive.OpenSubKey('SYSTEM\CurrentControlSet\Control\Session Manager\Memory Management',`$false)")) { throw 'READ_ONLY_REGISTRY_KEY_REQUIRED' }
    if (-not $Text.Contains("`$values=`$key.GetValue('PagingFiles',`$null,[Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)")) { throw 'RAW_PAGINGFILES_READ_REQUIRED' }
    $defs=@($tree.FindAll({param($n) $n -is [Management.Automation.Language.AssignmentStatementAst] -and $n.Left.Extent.Text -ceq '$definitions'},$true))
    if ($defs.Count -ne 1) { throw 'SINGLE_LITERAL_PLAN_REQUIRED' }
    $value=Read-LiteralAst $defs[0].Right
    $expected=@{
        computer=@('Win32_ComputerSystem','Name|AutomaticManagedPagefile','CIMWin32')
        boot=@('Win32_OperatingSystem','CSName|LastBootUpTime|Version|BuildNumber','CIMWin32')
        product=@('Win32_ComputerSystemProduct','UUID','CIMWin32')
        volumes=@('Win32_Volume','DeviceID|DriveLetter|SerialNumber','MSVDS__PROVIDER')
        settings=@('Win32_PageFileSetting','Name|InitialSize|MaximumSize','CIMWin32')
        usage=@('Win32_PageFileUsage','Name|AllocatedBaseSize|CurrentUsage|PeakUsage|TempPageFile','CIMWin32')
    }
    if ($value.Count -ne $expected.Count) { throw 'SOURCE_PLAN_COUNT' }
    foreach ($key in $expected.Keys) {
        if (-not $value.ContainsKey($key) -or $value[$key].Count -ne 3 -or $value[$key].Class -cne $expected[$key][0] -or ($value[$key].Fields -join '|') -cne $expected[$key][1] -or $value[$key].Provider -cne $expected[$key][2]) { throw 'EXACT_SOURCE_FIELDS_REQUIRED' }
    }
    return $true
}
$source=[IO.File]::ReadAllText([IO.Path]::Combine($PSScriptRoot,'runner_collect.ps1'))
$results=[Collections.Generic.List[object]]::new()
[void](Assert-ReadOnlySource $source);$results.Add(@{id='OriginalFixedReadProfile';status='PASS'})
$mutations=[ordered]@{
    SetCim='Set-CimInstance -ClassName Win32_PageFileSetting'
    NewCim='New-CimInstance -ClassName Win32_PageFileSetting'
    RemoveCim='Remove-CimInstance -ClassName Win32_PageFileSetting'
    SetRegistry='Set-ItemProperty -Path HKLM:\x -Name x -Value 1'
    NewRegistry='New-ItemProperty -Path HKLM:\x -Name x -Value 1'
    RegAdd='reg add HKLM\x'
    RegDelete='reg delete HKLM\x'
    Restart='Restart-Computer'
    InvokeCimMethod='Invoke-CimMethod -ClassName Win32_OperatingSystem -MethodName Reboot'
    NativeLoad='Add-Type -Name X -MemberDefinition x'
    DynamicInvoke='& $injected'
    DeleteEvidence='[IO.File]::Delete("evidence")'
    ExtraWritableRegistry="$null=`$hive.OpenSubKey('Other',`$true)"
    ExtraRawRegistry="$null=`$key.GetValue('Other')"
    PagefileWrite="[IO.File]::Open('D:\pagefile.sys',[IO.FileMode]::OpenOrCreate)"
    FileCreate='[IO.File]::Create("other")'
    StreamWriter='[IO.StreamWriter]::new("other")'
}
foreach ($key in $mutations.Keys) {
    $rejected=$false
    try {[void](Assert-ReadOnlySource ($source+"`n"+$mutations[$key]))} catch {$rejected=$true}
    if (-not $rejected) { throw ('NEGATIVE_ACCEPTED:'+ $key) }
    $results.Add(@{id=$key;status='PASS_REJECTED'})
}
$replacements=[ordered]@{
    RemoteComputer=@('-Property $definition.Fields','-ComputerName other -Property $definition.Fields')
    InputObject=@('-Property $definition.Fields','-InputObject $remote -Property $definition.Fields')
    CimSession=@('-Property $definition.Fields','-CimSession $remote -Property $definition.Fields')
    QueryInjection=@('-Property $definition.Fields','-Query "SELECT * FROM Win32_Process" -Property $definition.Fields')
    ProviderChange=@("Provider='MSVDS__PROVIDER'","Provider='Other'")
    ClassChange=@("Class='Win32_PageFileSetting'","Class='Win32_Process'")
    FieldExpansion=@("Fields=@('UUID')","Fields=@('UUID','Vendor')")
    WritableRegistry=@("Memory Management',`$false)","Memory Management',`$true)")
    OtherRegistry=@("`$values=`$key.GetValue('PagingFiles'","`$values=`$key.GetValue('Other'")
}
foreach ($key in $replacements.Keys) {
    $mutated=$source.Replace($replacements[$key][0],$replacements[$key][1]);if ($mutated -ceq $source) { throw 'INVALID_MUTATION' }
    $rejected=$false
    try {[void](Assert-ReadOnlySource $mutated)} catch {$rejected=$true}
    if (-not $rejected) { throw ('NEGATIVE_ACCEPTED:'+ $key) }
    $results.Add(@{id=$key;status='PASS_REJECTED'})
}
Microsoft.PowerShell.Utility\ConvertTo-Json -InputObject ([ordered]@{status='PASS';checks=$results.Count;results=$results.ToArray();actual_target_queries=0;collector_invoked=$false;limitation='Static source and exact-head review,not a hostile PowerShell sandbox,host attestation or production Permit enforcement.'}) -Depth 6
