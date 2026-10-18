# Pure metadata predicate only. No native API, acquisition, file or environment access.
function UnrequestedDescriptorSafe([long]$flags,[object]$value) {
    # CimFlags.Key=4096 and CimFlags.NullValue=536870912 (Microsoft MI SDK).
    return (($flags -band 4096) -ne 0 -or (($flags -band 536870912) -ne 0 -and $null -eq $value))
}
