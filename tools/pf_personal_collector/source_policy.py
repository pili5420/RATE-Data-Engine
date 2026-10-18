"""Offline source invariants; complements independent AST/source review, not an OS sandbox."""
import re
class Refused(ValueError):pass
def check_powershell(text):
 forbidden=('Set-CimInstance','New-CimInstance','Remove-CimInstance','Invoke-CimMethod','Get-CimClass','New-CimSession','Invoke-Command','Invoke-Expression','Start-Process','Restart-Computer','Set-ItemProperty','SetValue','CreateSubKey','AdjustTokenPrivileges','EnablePrivileges','ComputerName','CimSession','Add-Type','Import-Module','ScriptBlock')
 for word in forbidden:
  if re.search(r'(?i)\b'+word+r'\b',text):raise Refused('FORBIDDEN_SOURCE_TOKEN')
 for required in ("CimCmdlets\\Get-CimInstance @options","OperationTimeoutSec=5","Property=$spec.fields","Namespace=$spec.namespace","ClassName=$spec.class","$options['Filter']=$spec.filter","OpenSubKey('SYSTEM\\CurrentControlSet\\Control\\Session Manager\\Memory Management',$false)","RegistryView]::Registry64","DoNotExpandEnvironmentNames","$scope.order","'SIGNED_RUNNER_PROOF_REQUIRED'","$rsa.VerifyData"):
  if required not in text:raise Refused('FIXED_READ_INVARIANT_MISSING')
 if text.count('CimCmdlets\\Get-CimInstance')!=1:raise Refused('EXTRA_READ_PATH')
 # ConvertTo-Json has an unrelated InputObject parameter. Only its one fixed conversion site is allowed.
 if len(re.findall(r'(?i)-InputObject\b',text))!=1 or 'ConvertTo-Json -InputObject (SortValue $v)' not in text:raise Refused('CIM_INPUTOBJECT_FORBIDDEN')
 return 'FIXED_REVIEWED_SOURCE_INVARIANTS'
