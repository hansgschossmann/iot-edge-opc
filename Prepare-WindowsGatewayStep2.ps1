<#
.SYNOPSIS
    Creates directories and clone repository and run the deployment script.
.DESCRIPTION
    Creates directories and clone repository and run the deployment script.
#>

# check if we are Administrator
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (!$currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))
{
    Read-Host -Propmt "Please run PowerSehll as Administrator and retry. Press a key."
    throw("Please run PowerShell as Administrator and retry.")
}

# Ask user
Read-Host -Propmt "Create a restore point. When done press a key."

# check if c:\iiot exists and stop with instructions if it exists
$IIoTRootPath = "c:\iiot"
$RepoDir = "iot-edge-opc"
$RepoPath ="$IIoTRootPath/$RepoDir"
$ConfigGithubRepo = "https://github.com/hansgschossmann/iot-edge-opc.git"

if (Test-Path $IIoTRootPath)
{
    Write-Output "The directory $IIoTRoot' exists. Please stop IoT Edge and rename or delete it."
    throw "The directory $IIoTRoot' exists. Please stop IoT Edge and rename or delete it."
}

# create root dir
md $IIoTRootPath
# create work directory for all files mapped to the host
md $IIoTRootPath/work

# clone repo
cd $IIoTRootPath
git clone $ConfigGithubRepo $RepoDir
cd $RepoPath

# install all Python requirements
Inovke-Expression "pip3 install -r requirements.txt"

# Start Docker for Windows
Invoke-Expression "Docker for Windows"
Read-Host -Propmt "Share the drive 'C' in the Docker Settings (to open via System Tray). When done press a key."

# run the deployment script
Invoke-Expression "Create-IoTEdgeDeviceAndInstallScripts.ps1"
