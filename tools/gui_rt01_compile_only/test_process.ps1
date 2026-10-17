# Isolated regression for the compiler process wrapper only. No compiler/GUI.
[CmdletBinding()]
param([Parameter(Mandatory)][string]$EvidenceRoot)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$OutputRoot = [IO.Path]::GetFullPath($EvidenceRoot)
if (Test-Path -LiteralPath $OutputRoot) { throw 'TEST_OUTPUT_EXISTS' }
[IO.Directory]::CreateDirectory($OutputRoot) | Out-Null
$utf8 = [Text.UTF8Encoding]::new($false)
$tokens = $null; $parseErrors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'compile_only.ps1'), [ref]$tokens, [ref]$parseErrors)
if (@($parseErrors).Count) { throw 'PARSE_FAILURE' }
foreach ($name in @('Write-NewBytes','Write-Json','Hash-File','Run-Process')) {
    $nodes = @($ast.FindAll({param($node) $node -is [Management.Automation.Language.FunctionDefinitionAst] -and $node.Name -ceq $name},$true))
    if ($nodes.Count -ne 1) { throw 'FUNCTION_NOT_UNIQUE' }
    . ([ScriptBlock]::Create($nodes[0].Extent.Text))
}
$child = Join-Path $PSHOME 'pwsh.exe'
$envMap = @{SystemRoot=$env:SystemRoot;TEMP=$env:TEMP;TMP=$env:TMP;PATH=$env:PATH}
$arguments = @('-NoLogo','-NoProfile','-NonInteractive','-Command',"[Console]::Out.Write('owned-child-out');[Console]::Error.Write('owned-child-err');exit 7")
$items = @(Run-Process $child $arguments 'OWNED_CHILD' $envMap)
if ($items.Count -ne 1) { throw "PROCESS_RESULT_CARDINALITY:$($items.Count)" }
$result = $items[0]
if ($result.record.exit_code -ne 7 -or $result.record.timed_out -or $result.record.start_or_io_error) { throw 'NONZERO_EXIT_NOT_PRESERVED' }
if ($utf8.GetString($result.stdout) -cne 'owned-child-out' -or $utf8.GetString($result.stderr) -cne 'owned-child-err') { throw 'RAW_STREAM_CONTENT' }
Write-Json 'TEST_RESULT.json' @{status='PASS'; tests=3; checks=@('one structured result only','nonzero exit preserved','stdout/stderr raw bytes preserved'); compiler_executed=$false; gui_dispatch=$false; child_type='owned no-profile PowerShell console only'; skips=0; relaxed_assertions=0; failure_whitelists=0}
Write-Output '3 process-wrapper regression checks PASS; not compile evidence.'
