<#
.SYNOPSIS
    Installs Chocolatey and all required tools.
.DESCRIPTION
    Installs Chocolatey and all required tools.
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

# Ask user
Write-Output "Uninstall any of those apps if they are installed manually:"
Write-Output "Python"
Write-Output "Azure CLI for Python"
Write-Output "Visual Studio Code"
Write-Output "Git"
Write-Output "Docker for Windows"
Write-Output "Docker compose"
Write-Output "pip"
Read-Host -Propmt "When done, create a restore point and press a key."

Set-ExecutionPolicy Bypass -Scope Process -Force; iex ((New-Object System.Net.WebClient).DownloadString('https://chocolatey.org/install.ps1'))

choco install python -y
choco install azure-cli -y
choco install vscode -y
choco install git -y
choco install docker-for-windows -y
choco install docker-compose -y
choco install pip -y

Write-Output "Open another PowerShell as Administrator and:"
Write-Output "md c:\iiot"
Write-Output "cd c:\iiot"
Write-Output "git clone https://github.com/hansgschossmann/iot-edge-opc.git"
Write-Output "cd iot-edge-opc"
Write-Output "pip3 install -r requirements.txt"
Write-Output "start Docker for Windows"
Write-Output "Share the drive in docker you are working on"
Write-Output "Login to your azure account with the Azure CLI (az login) and set your subscription (az account)"
Write-Output "Create a workdir like "c:\iiot\workdir"
Write-Output "Install the Azure CLI IoT extension: az extension add --name azure-cli-iot-ext"
Write-Output ""
Write-Output "run: python iiotedge.py gw <gateway-device-id> --lcow --iothubname <your-iothubname> --hostdir <fq-path-to-workdir-for-containers> --force --loglevel=debug"
