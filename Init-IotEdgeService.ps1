<#
.SYNOPSIS
    Uninstalls and then installs the IoT Edge security daemon.
.DESCRIPTION
    Uninstalls and then installs the IoT Edge security daemon.
.PARAMETER ContainerOs
    The OS of the containers to run.
.PARAMETER DeviceConnectionString
    The IoTHub device connection string of the IoT Edge device.
.PARAMETER ProxySchema
    The schema of the proxy.
.PARAMETER ProxyHost
    The host of the proxy.
.PARAMETER ProxyPort
    The port of the proxy.
.PARAMETER ProxyUsername
    The username for the proxy.
.PARAMETER ProxyPassword
    The password for the proxy.
.PARAMETER ArchivePath
    The archive path to be used by IoT Edge.
.PARAMETER AgentImage
    The agent image to be used by IoT Edge.
.PARAMETER Username
    The username to fetch the agent image.
.PARAMETER Password
    The password to fetch the agent image.
#>

[CmdletBinding()]
Param(
[Parameter(Position=0, Mandatory=$true, HelpMessage="Specify the device connection string of the IoT Edge device")]
[string] $DeviceConnectionString,
[Parameter(Mandatory=$false, HelpMessage="Specify the OS used in the module containers")]
[string] $ContainerOs = "Windows",
[Parameter(Mandatory=$false, HelpMessage="Specify the schema of the proxy to use.")]
[string] $ProxySchema = "http",
[Parameter(Mandatory=$false, HelpMessage="Specify the proxy URL to use.")]
[string] $ProxyHost = "",
[Parameter(Mandatory=$false, HelpMessage="Specify the port of the proxy to use.")]
[string] $ProxyPort = "",
[Parameter(Mandatory=$false, HelpMessage="Specifiy the username for the proxy.")]
[string] $ProxyUsername = "",
[Parameter(Mandatory=$false, HelpMessage="Specifiy the password for the proxy.")]
[string] $ProxyPassword = "",
[Parameter(Mandatory=$false, HelpMessage="Specify the updstream protocol to use.")]
[string] $UpstreamProtocol = "",
[Parameter(Mandatory=$false, HelpMessage="Specify the IoT Edge archive path")]
[string] $ArchivePath = "",
[Parameter(Mandatory=$false, HelpMessage="Specify the agent container to use.")]
[string] $AgentImage = "",
[Parameter(Mandatory=$false, HelpMessage="Specify a username to fetch the agent container.")]
[string] $Username = "",
[Parameter(Mandatory=$false, HelpMessage="Specifiy the password to fetch the agent container.")]
[string] $Password = "",
[Parameter(Mandatory=$false, HelpMessage="Specifiy the installation mode.")]
[switch] $Manual = $true
)

function ProcessConfigYml([string]$line)
{
    if ($line.Contains("env:"))
    {
        if (![string]::IsNullOrEmpty($script:ProxyUrl) -or ![string]::IsNullOrEmpty($script:UpstreamProtocol))
        {
            $script:patchedConfigYml += "  env:`n"
            if (![string]::IsNullOrEmpty($script:ProxyUrl))
            {
                $script:patchedConfigYml += ("    https_proxy: " + '"' + "$script:ProxyUrl" + '"' + "`n")
            }
            if (![string]::IsNullOrEmpty($script:UpstreamProtocol))
            {
                $script:patchedConfigYml += ("    UpstreamProtocol: " + '"' + "$script:UpstreamProtocol" + '"'  + "`n")
            }
            return
        }
    }
    $script:patchedConfigYml += ($line + "`n")
}

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
    if (![string]::IsNullOrEmpty($ProxyHost))
    {
        $ProxyString = $ProxySchema + "://" + $ProxyHost
        if (![string]::IsNullOrEmpty($ProxyPort))
        {
            $ProxyString += (":" + $ProxyPort)
        }
        if (![string]::IsNullOrEmpty($ProxyUsername) -and ![string]::IsNullOrEmpty($ProxyPassword))
        {
            $BasicAuth = "$($ProxyUsername):$($ProxyPassword)"
            $BasicAuthBytes = [System.Text.Encoding]::ASCII.GetBytes($BasicAuth)
            $BasicAuthBase64 = [System.Convert]::ToBase64String($BasicAuthBytes)
            . { Invoke-Expression ("Invoke-WebRequest -useb aka.ms/iotedge-win -Proxy $ProxyString -Headers @{ Authorization = '" + "$BasicAuthBase64" + "'}") } | Invoke-Expression
        }
        else
        {
            . {Invoke-Expression "Invoke-WebRequest -useb aka.ms/iotedge-win -Proxy $ProxyString"} | Invoke-Expression
        }
    }
    else
    {
        . {Invoke-Expression "Invoke-WebRequest -useb aka.ms/iotedge-win"} | Invoke-Expression
    }
}

# uninstall the security daemon
Write-Output "****************************************************************"
Write-Output "Uninstall IoT Edge"
Write-Output "****************************************************************"
Invoke-Expression "Uninstall-SecurityDaemon -Force -ErrorAction SilentlyContinue"

$script:ProxyUrl = ""
if (![string]::IsNullOrEmpty($DeviceConnectionString))
{
    $DeviceConnectionStringOriginal = $DeviceConnectionString
    $DeviceConnectionString = (" -DeviceConnectionString " + '"' + $DeviceConnectionString + '"')
} 
if ($Manual)
{
    $InstallationMode = " -Manual "
}
else 
{
    $InstallationMode = " -Dps "
}
if (![string]::IsNullOrEmpty($ContainerOs))
{
    $ContainerOs = " -ContainerOs $ContainerOs "
}

if (![string]::IsNullOrEmpty($ProxyHost))
{
    $script:ProxyUrl = ""
    if (![string]::IsNullOrEmpty($ProxyUsername) -and ![string]::IsNullOrEmpty($ProxyPassword))
    {
        $script:ProxyUrl = $ProxySchema + "://" + $ProxyUsername + ":" + $ProxyPassword + "@" + $ProxyHost + ":" + $ProxyPort
    }
    else
    {
        $script:ProxyUrl = $ProxySchema + "://" + $ProxyHost + ":" + $ProxyPort
    }
    $Proxy = " -Proxy $ProxyUrl "
}

if (![string]::IsNullOrEmpty($ArchivePath))
{
    $ArchivePath = " -ArchivePath $ArchivePath "
}

if (![string]::IsNullOrEmpty($AgentImage))
{
    $AgentImage = " -AgentImage $AgentImage "
}

if (![string]::IsNullOrEmpty($Username))
{
    $Username = " -Username $Username "
}

if (![string]::IsNullOrEmpty($Password))
{
    $Password = " -Password $Password "
}

# configure proxy
if ([string]::IsNullOrEmpty($ProxyUrl))
{
    Invoke-Expression "reg delete HKLM\SYSTEM\CurrentControlSet\Services\iotedge /f /v Environment"
}
else 
{
    Invoke-Expression "reg add HKLM\SYSTEM\CurrentControlSet\Services\iotedge /f /v Environment /t REG_MULTI_SZ /d https_proxy=$ProxyUrl"
}

Write-Output "****************************************************************"
Write-Output "Install IoT Edge"
Write-Output "****************************************************************"
Invoke-Expression "Install-SecurityDaemon $DeviceConnectionString $InstallationMode $ContainerOs $Proxy $ArchivePath $AgentImage $Username $Password"

# reconfigure if we need a proxy or a different upstream protocol
if (![string]::IsNullOrEmpty($ProxyUrl) -or ![string]::IsNullOrEmpty($UpstreamProtocol))
{
    Write-Output "****************************************************************"
    Write-Output "Wait till iotedge service is running"
    Write-Output "****************************************************************"
    $stillWait = $true
    while ($stillWait)
    {
        if ((Get-Service iotedge).Status -eq "Running")
        {
            $stillWait = $false
        }
        if ($stillWait)
        {
            Sleep(3)
            Write-Output "...not yet there, wait longer..."    
        }
    }

    Write-Output "****************************************************************"
    Write-Output "Stop IoT Edge"
    Write-Output "****************************************************************"
    Stop-Service iotedge
    
    Write-Output "****************************************************************"
    Write-Output "Wait till iotedge service is stopped"
    Write-Output "****************************************************************"
    $stillWait = $true
    while ($stillWait)
    {
        if ((Get-Service iotedge).Status -eq "Stopped")
        {
            $stillWait = $false
        }
        if ($stillWait)
        {
            Sleep(3)
            Write-Output "...not yet there, wait longer..."    
        }
    }

    Write-Output "****************************************************************"
    Write-Output "Update IoT Edge configuration file"
    Write-Output "****************************************************************"
    $script:patchedConfigYml = ""
    $configYmlPath = "$env:ProgramData/iotedge/config.yaml"
    Get-Content $configYmlPath | ForEach-Object  -Process { ProcessConfigYml($_) }
    Out-File -InputObject $script:patchedConfigYml -FilePath $configYmlPath -Encoding ascii
    
    Write-Output "****************************************************************"
    Write-Output "Start IoT Edge"
    Write-Output "****************************************************************"
    Start-Service iotedge
    
    if (![string]::IsNullOrEmpty($script:ProxyUrl))
    {
        Write-Output "****************************************************************"
        Write-Output "*"
        Write-Output "* You still need to update the Docker for Windows Proxy settings"
        Write-Output "*"
        Write-Output "****************************************************************"
    }
}
