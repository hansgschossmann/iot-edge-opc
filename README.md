# iot-edge-opc

This repository contains a Python script to generate script for installation and configuration of OPC UA modules running in IoTEdge.

# Supported scenarios
The `iotedgeopc.py` script supports different scenarios:

## Connectedfactory simulation (cfsim)
Deploy a simulation which could be used by Connectedfactory PCS. This requires a topology description file as input. This file will be parsed. The output of the iotedgeopc.py will be a set of scripts and docker-compose configuration files, which could be used to initialize and run the compelete Connectedfactory production line and factory simulation.

##  Connectedfactory site onboarding (cf)
Deploy the OPC Edge components to a real world site. This requires a topology descriptoin file as input as well as the domain name of the Connectedfactory domain. This domain needs to be configured in the topology description. The output of the iotedgeopc.py will be a set of scripts and docker-compose configuration files, which could be used to initialize and run the compelete Connectedfactory production line and factory simulation.

## Industrial gateway (gw)
Deploy the OPC Edge components to a real world side. This requires as input the list of nodes to be published by OPC Publisher in its publishednodes.json format as well as a domain name. The domain name is used for creation of IoTHub IoTEdge device identities as well as tagging of the ApplicationUri value of t the ingested telemetry. The output of the iotedgeopc.py will be a set of scripts and docker-compose configuration files, which could be used to initialize and run the OPC Edge components.

## Azure IoTCentral onboarding (iotcsim)
Create scripts to ingest data of a simulated OPC UA server into IoTCentral.


# Functionality
All scenarios (except iotcsim) will use IoTEdge as runtime environment for the OPC modules, which run as docker container:
- Create an IoTEdge deployment with all the OPC Edge components configures as modules. By adding a new module to the corresponding yml files this module will be picked up by the script and will become part of the IoTEdge deployment definition.
- Create an IoTEdge device identity with name "iot-edge-<domain>"
- Create init-opcedge, start-edgeopc, stop-edgeopc and deinit-edgeopc scripts, which will call iotedgectl and docker-compose to configure and create the required components.

# Usage of `iotedgeopc.py`
The `iotedgeopc.py`script could be used in cross platform fashion. To use it this way, just use the `--targetplatform` parameter and specify your target platform. In this case you need to copy all scripts and configuration files to your target platform.

When using with the `--targetplatform` parameter you still need to do the system preparation as outlined below on your targetsystem.

## WSL
Prepare your WSL system by running:
    source iotedgeopc-install-prerequisites.sh
Now you can run the generation script:
python iotedgeopc.py .....

## Ubuntu as non root
Prepare your system by chmod'ing all .sh files with +x and running:
    sudo ./iotedgeopc-install-prerequisites.sh
If you use the --hostdir parameter, you need to create the directory and chown it.
Now you can run the generation script:
python iotedgeopc.py .....

## Windows
Prepare your system by installing python and Docker for Windows. Then run:
    pip install -r requirements.txt
Now you can run the generation script:
python iotedgeopc.py .....

# Running the generated scripts on your target platform
Before you run the generated scripts on your target platform:
- in a cross platform scenario, ensure you have copied the generated scripts and configuration files to the correct locations on your target platform
- on WSL/Linux, please run "source target-install-prerequisites.sh"
- on Windows, please install docker

Then change to the directory you have copied the scripts to and run (use sudo on Ubuntu):
- init-opcedge, to initialize the required components
- start-opcedge, to start ingesteing telemetry for your usage scenario

To stop the telemetry ingest run (use sudo on Ubuntu):
- stop-iotedge

You could start and stop the ingestion as often as you like.

To deinitialze run (use sudo on Ubuntu):
- deinit-iotedge

# Connectedfactory simulation (cfsim)

Here is a sample command line, which will generate scripts to create factories, production lines and stations as configured in the Connectedfactory ContosoTopologyDescription.json file.

    python iotedgeopc.py cfsim -topofile=testdata/ContosoTopologyDescription.json --iothubname=<your IoTHub name> --hostdir=d:/dockercf 

This will generate scripts in the subdirectory out of your current directory.

To start ingesting data into Connectedfactory change to
 the out directory and run:
- init-opcedge, to init all required components.
- start-opcedge, to run IoTEdge as well as all Cf factories and domains as configured.

To stop ingesting data and deinitialize all components, change to the out directory and run:
- stop-opcedge, to stop ingesting data.
- deinit-opcedge, to deinit all required components.

# Azure IoTCentral onboarding (iotcsim)

Here is a sample command line, which will generate scripts to send data of a simulated OPC UA server to IoTCentral:

    python iotedgeopc.py iotcsim --topofile=testdata/ContosoTopologyDescription_iotcentral.json munich --iotcentralcs=HostName=<IoTCentral device connection string> --hostdir=d:/dockercf 

This will generate scripts in the subdirectory out of your current directory. 

To start ingesting data into IoTCentral change to the out directory and run:
- init-opcedge, to init all required components. For this use case it is only needed to configure OPC Publisher with the IoTCentral connection string.
- start-opcedge, to run all required components and start ingesting data into IoTCentral.

To stop ingesting data, change to the out directory and run:
- stop-opcedge, to stop ingesting data into IoTCentral.
- deinit-opcedge, to deinit all required components.

Currently the Azure IoTCentral use case is limited to sending only telemetry of the assembly station of one production line simulation to IoTCentral.

To visualize data in IoTCentral, use the following Field names:
- EnergyConsumption
- NumberOfDiscardedProducts
- NumberOfManufacturedProducts
- Pressure




More documentation will follow....


