<#
.SYNOPSIS
    Uninstalls the IoT Edge security daemon.
.DESCRIPTION
    Uninstalls the IoT Edge security daemon.
#>

#
# start of main script
#

# check if we are Administrator
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (!$currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))
{
    throw("Please run PowerShell as Administrator and retry.")
}

# download the PS module if required
Get-Command Uninstall-SecurityDaemon -ErrorAction SilentlyContinue
if ($? -eq $false)
{
    # download the latest agent
    Write-Output "****************************************************************"
    Write-Output "Download IoT Edge"
    Write-Output "****************************************************************"
    . {Invoke-Expression "Invoke-WebRequest -useb aka.ms/iotedge-win $Proxy"} | Invoke-Expression
}

# uninstall the security daemon
Write-Output "****************************************************************"
Write-Output "Uninstall IoT Edge"
Write-Output "****************************************************************"
Invoke-Expression "Uninstall-SecurityDaemon -Force -ErrorAction SilentlyContinue"