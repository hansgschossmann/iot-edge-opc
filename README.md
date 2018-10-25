# iot-edge-opc

This repository contains a Python script to configure an Industrial IoT Edge gateway.

# Supported scenarios
The `iiotedge.py` script supports the following scenarios:

## Industrial gateway (gw)
Deploy the Industrial IoT components to a IoT Edge gateway devcie. This requires as input the list of nodes to be published by OPC Publisher in its publishednodes.json format as well as a site name. The site name is used for creation of IoTHub IoT Edge device identities as well as tagging of the ApplicationUri value of the ingested telemetry. The output of the iiotedge.py will be a set of scripts and docker-compose configuration files, which can be used to initialize and start the gateway.

# Functionality
The script does the following:
- Create an IoT Edge deployment with all the Industrial IoT Edge components configured as modules. By adding a new module to the corresponding (docker-compose) files (for example site.yml) this module will be picked up by the script and will be configured as an module in the IoT Edge deployment definition.
- Create an IoT Edge device identity with name "iiot-edge-<site>"
- Create init-iiotedge, start-iiotedge, stop-iiotedge and deinit-iiotedge scripts, which will call the IoT Edge runtime and docker-compose to configure and start the installation.

# Usage of `iiotedge.py`
## Preparation
- Ensure you have installed IoT Edge on your device
- Ensure that you have Python 3 installed on your gateway
- Clone this repository to your gateway
- Run pip to install all the required components listed in requirements.txt
- Ensure you are logged in to Azure using `az login`
- Ensure you have selected the correct subscription with `az account set -s <your subscription name>`

Note: for now only Windows is supported by the script

## WSL
Ensure the preparation steps are completed.
Prepare your WSL system by running:
    source iiotedge-install-prerequisites.sh
Now you can run the generation script:
python iiotedge.py .....

## Ubuntu as non root
Ensure the preparation steps are completed.
Prepare your system by chmod'ing all .sh files with +x and running:
    sudo ./iiotedge-install-prerequisites.sh
If you use the --hostdir parameter, you need to create the directory and chown it.
Now you can run the generation script:
python iiotedge.py .....

## Windows
Ensure the preparation steps are completed.
 Then run:
    pip install -r requirements.txt
Now you can run the generation script:
python iiotedge.py .....

# Running the generated scripts on your target platform
Before you run the generated scripts on your target platform:
- in a cross platform scenario, ensure you have copied the generated scripts and configuration files to the correct locations on your target platform
- on WSL/Linux, please run "source target-install-prerequisites.sh"
- on Windows, please install docker

Then change to the directory you have copied the scripts to and run (use sudo on Ubuntu):
- init-iiotedge, to install and initialize the required components
- start-iiotedge, to start ingesting telemetry for your usage scenario

To stop the telemetry ingest run (use sudo on Ubuntu):
- stop-iiotedge

You can start and stop the ingestion as often as you like.

To deinitialze run (use sudo on Ubuntu):
- deinit-iiotedge
