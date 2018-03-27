#!/bin/bash -x
echo "install az CLI"
AZ_REPO=$(lsb_release -cs)
echo "deb [arch=amd64] https://packages.microsoft.com/repos/azure-cli/ $AZ_REPO main" | tee /etc/apt/sources.list.d/azure-cli.list
apt-key adv --keyserver packages.microsoft.com --recv-keys 52E16F86FEE04B979B07E28DB02C46DF417A0893
apt-get install apt-transport-https
apt-get update && apt-get install azure-cli -y

echo "install iot extension"
az extension add --name azure-cli-iot-ext

echo "install docker"
apt-get update
apt-get install apt-transport-https ca-certificates curl software-properties-common -y
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add -
add-apt-repository \
    "deb [arch=amd64] https://download.docker.com/linux/ubuntu \
    $(lsb_release -cs) \
    stable" 
apt-get update
apt-get install docker-ce -y

echo "install docker-compose"
apt install docker-compose -y

echo "install python and pip"
apt-get update
apt-get install python -y
apt-get install python-pip -y

# echo "install virtualenv"
# pip install virtualenv
# virtualenv iotedgeopc
# cd iotedgeopc
# source bin/activate

echo "install all required python libraries"
pip install PyYAML
pip install azure
pip install azure-cli-core
pip install -U azure-iot-edge-runtime-ctl

