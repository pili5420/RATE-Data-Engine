# Synthetic-only pure predicate tests. Does not load or execute native_worker.ps1.
Set-StrictMode -Version Latest
$ErrorActionPreference='Stop'
if ($args.Count -ne 0) { throw 'NO_ARGUMENTS' }
. ([IO.Path]::Combine($PSScriptRoot,'descriptor_policy.ps1'))
$tests=@(
    @{id='unpopulated_null_descriptor';flags=536870912;value=$null;expected=$true},
    @{id='populated_extra_property';flags=0;value='SYNTHETIC';expected=$false},
    @{id='contradictory_null_flag_nonnull_value';flags=536870912;value='SYNTHETIC';expected=$false},
    @{id='null_without_null_flag';flags=0;value=$null;expected=$false},
    @{id='framework_key_not_serialized';flags=4096;value='SYNTHETIC';expected=$true}
)
foreach ($t in $tests) { if ((UnrequestedDescriptorSafe $t.flags $t.value) -ne $t.expected) { throw ('DESCRIPTOR_POLICY_FAIL_'+$t.id) } }
Microsoft.PowerShell.Utility\ConvertTo-Json -InputObject @{status='PASS';tests=5;ids=@($tests.id);skips=0;relaxed_assertions=0;failure_whitelists=0;native_dispatches=0;original_host_queries=0;realm='OFFLINE_SYNTHETIC_PREDICATE_ONLY'} -Compress
