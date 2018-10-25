<#
.SYNOPSIS
    Installs Chocolatey and all required tools.
.DESCRIPTION
    Installs Chocolatey and all required tools.
#>

Set-ExecutionPolicy Bypass -Scope Process -Force; iex ((New-Object System.Net.WebClient).DownloadString('https://chocolatey.org/install.ps1'))

choco install python -y
choco install azure-cli -y
choco install vscode -y
choco install git -y
choco install docker-for-windows -y
choco install docker-compose -y
choco install pip -y

Write-Output "Open another PowerShell and:"
Write-Output "md /iiot"
Write-Output "cd /iiot"
Write-Output "git clone https://github.com/hansgschossmann/iot-edge-opc.git"
Write-Output "cd iot-edge-opc"
Write-Output "pip3 install -r requirements.txt"
Write-Output "start Docker for Windows"
Write-Output "Share the drive in docker you are working on"
Write-Output "Login to your azure account with the Azure CLI (az login) and set your subscription (az account)"
Write-Output ""
Write-Output "run: python iiotedge.py gw <gateway-device-id> --lcow --iothubname <your-iothubname> --hostdir <fq-path-to-workdir-for-containers> --force --loglevel=debug"
