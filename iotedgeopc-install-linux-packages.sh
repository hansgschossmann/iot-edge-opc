#!/bin/bash -x
echo "update package lists and repositories"
curl -fsSL https://download.docker.com/linux/ubuntu/gpg | apt-key add -
add-apt-repository \
    "deb [arch=amd64] https://download.docker.com/linux/ubuntu \
    $(lsb_release -cs) \
    stable" 
AZ_REPO=$(lsb_release -cs)
echo "deb [arch=amd64] https://packages.microsoft.com/repos/azure-cli/ $AZ_REPO main" | tee /etc/apt/sources.list.d/azure-cli.list
apt-key adv --keyserver packages.microsoft.com --recv-keys 52E16F86FEE04B979B07E28DB02C46DF417A0893
apt-get update

echo "install utilities"
apt-get install apt-transport-https ca-certificates curl software-properties-common -y

echo "install docker"
apt-get remove docker docker-engine docker.io -y
apt-get install docker-ce -y

echo "install docker-compose"
#apt-get install docker-compose -y
apt-get remove docker-compose -y
curl -L https://github.com/docker/compose/releases/download/1.21.0/docker-compose-$(uname -s)-$(uname -m) -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose

echo "install azure cli"
apt-get remove azure-cli -y
apt-get install azure-cli -y

echo "install iot extension"
az extension add --name azure-cli-iot-ext

echo "install python and pip"
apt-get remove python -y
apt-get remove python-pip -y
apt-get install python -y
apt-get install python-pip -y

