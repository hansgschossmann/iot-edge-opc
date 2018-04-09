#!/bin/bash -x

# install all required linux packages if we are root
if [[ $(whoami) == "root" ]]
then
    source ./iotedgeopc-linux-packages.sh
fi

# create virtual environment if requested
if [ "$1" == "virtual" ]
then
    echo "install virtualenv and create iotedgeopc environment"
    pip install virtualenv
    virtualenv iotedgeopc
    cd iotedgeopc
    source bin/activate
fi

# upgrade pips
pip install --upgrade pip

# install iotedgectl
pip install --upgrade azure-iot-edge-runtime-ctl

# install all script libraries
pip install -r requirements.txt

# fix docker-py version
pip uninstall docker-py -y; pip uninstall docker -y; pip install docker

# patch requires.txt to work with docker-compose
if [ -f /usr/local/lib/python2.7/dist-packages/azure_iot_edge_runtime_ctl-1.0.0*-py2.7.egg/EGG-INFO/requires.txt ]
then
    REQUIRESPATH=$(ls /usr/local/lib/python2.7/dist-packages/azure_iot_edge_runtime_ctl-1.0.0*-py2.7.egg/EGG-INFO/requires.txt)
fi
if [ -f /usr/local/lib/python2.7/dist-packages/azure_iot_edge_runtime_ctl-1.0.0*.dist-info/METADATA ]
then
    REQUIRESPATH=$(ls /usr/local/lib/python2.7/dist-packages/azure_iot_edge_runtime_ctl-1.0.0*.dist-info/METADATA)
fi
sed -i 's/\(docker\[tls\]\).*==.*/\1 > 3.0/g' $REQUIRESPATH


# prep docker on WSL
if grep -q Microsoft /proc/version; then
  echo "Ubuntu on Windows detected. Please ensure your Docker for Windows is reachable on port 2375"
  export DOCKER_HOST=tcp://0.0.0.0:2375
  echo "export DOCKER_HOST=tcp://0.0.0.0:2375" >> ~/.bashrc && source ~/.bashrc
fi