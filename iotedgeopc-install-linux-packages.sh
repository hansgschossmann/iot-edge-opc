#!/bin/bash -x
echo "update package lists and repositories"
curl https://packages.microsoft.com/config/ubuntu/16.04/prod.list > ./microsoft-prod.list
sudo cp ./microsoft-prod.list /etc/apt/sources.list.d/
curl https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > microsoft.gpg
sudo cp ./microsoft.gpg /etc/apt/trusted.gpg.d/
sudo apt-get update
sudo apt-get install moby-engine
sudo apt-get install moby-cli
sudo apt-get update
sudo apt-get install iotedge

echo todo for init:
sudo nano /etc/iotedge/config.yaml
echo add connectionstring to config.yaml
sudo systemctl restart iotedge

