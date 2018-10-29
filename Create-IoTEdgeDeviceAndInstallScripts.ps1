<#
.SYNOPSIS
    Run the script to create an IoT Edge device and deployment manifest and create scripts to install and start IoT Edge.
.DESCRIPTION
    Run the script to create an IoT Edge device and deployment manifest and create scripts to install and start IoT Edge.
#>

# check if we are Administrator
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (!$currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator))
{
    Read-Host -Propmt "Please run PowerSehll as Administrator and retry. Press a key."
    throw("Please run PowerShell as Administrator and retry.")
}

# check if c:\iiot exists and stop with instructions if it exists
$IIoTRootPath = "c:\iiot"
$RepoDir = "iot-edge-opc"
$RepoPath ="$IIoTRootPath/$RepoDir"

if (!(Test-Path $IIoTRootPath) -or !(Test-Path $RepoPath))
{
    Write-Output "The directory '$IIoTRoot' or '$RepoPath' does not exist. Please ensure you have been running the preparation scripts."
    throw "The directory '$IIoTRoot' does not exist. Please ensure you have been running the preparation scripts."
}
cd $RepoPath

# login to Azure, set subscription and install required extension
Write-Output "Login to your azure account"
$AzResult = Invoke-Expression "az login"
if ($? -eq $false)
{
    Write-Output "Login to Azure failed."
    throw "Login to Azure failed."
}
$SubscriptionList = @()
$Subscriptions = $AzResult | ConvertFrom-Json
if ($Subscriptions.Count -eq 1)
{
    $SubscriptionName = $Subscriptions[0].name
}
else 
{
    foreach ($Subscription in $Subscriptions)
    {
        $SubscriptionList += $Subscription.name
    }
    while ($true)
    {
        Write-Output "Which subscription should be used? Please enter one of those subscription names."
        $SubscriptionList | ForEach-Object { $_ }
        $SubscriptionName = Read-Host -Prompt "Which subscription should be used? Enter the name"
        if ($SubscriptionName -in $SubscriptionList)
        {
            break;
        }
    }
}
Write-Output "Use subscription '$SubscriptionName' for deployment."
$AzResult = Invoke-Expression "az account set --subscription $SubscriptionName"
if ($? -eq $false)
{
    Write-Output "Selection of subscription $SubscriptionName failed."
    throw "Selection of subscription $SubscriptionName failed."
}
az extension add --name azure-cli-iot-ext

# select IoTHub to use
Write-Output "Select the IoTHub to use."
$AzResult = Invoke-Expression "az iot hub list --query [*].name"
if ($? -eq $false)
{
    Write-Output "Can not list available IoTHubs."
    throw "Can not list available IoTHubs."
}
$IoTHubList = @()
$IoTHubs = $AzResult | ConvertFrom-Json
if ($IoTHubs.Count -eq 1)
{
    $IoTHubName = $IoTHubs[0]
}
else 
{
    foreach ($IoTHub in $IoTHubs)
    {
        $IoTHubList += $IoTHub
    }
    while ($true)
    {
        Write-Output "Which IoTHub should be used? Please enter one of those IoTHub names."
        $IoTHubList | ForEach-Object { $_ }
        $IoTHubName = Read-Host -Prompt "Which IoTHub should be used? Enter the name"
        if ($IoTHubName -in $IoTHubList)
        {
            break;
        }
    }
}
Write-Output "Use IoTHub '$IoTHubName' for deployment."

$IoTEdgeDeviceName = Read-Host -Prompt "Please enter the name of the IoT Edge device name"

Invoke-Expression "python iiotedge.py gw $IoTEdgeDeviceName --lcow --iothubname $IoTHubName --hostdir $IIoTConfigPath --force --loglevel=debug"
