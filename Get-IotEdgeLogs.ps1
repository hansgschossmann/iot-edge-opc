<#
.SYNOPSIS
    Show the logs of the IoT Edge agent.
.DESCRIPTION
    Show the logs of the IoT Edge agent.
.PARAMETER Period
    The OS of the containers to run.
#>

[CmdletBinding()]
Param(
[Parameter(Position=0, Mandatory=$false, HelpMessage="Specify the period in minutes to show the logs")]
[int] $Period = 5
)

# Displays logs from last 5 min, newest at the bottom.
Get-WinEvent -ea SilentlyContinue `
  -FilterHashtable @{ProviderName= "iotedged";
    LogName = "application"; StartTime = [datetime]::Now.AddMinutes(-$Period)} |
  select TimeCreated, Message |
  sort-object @{Expression="TimeCreated";Descending=$false} |
  format-table -autosize -wrap