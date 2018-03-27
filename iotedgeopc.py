import os
import platform
import sys
import urllib
import json
import subprocess
import shlex
import argparse
import time
import shutil
import socket
import yaml
import logging
from azure.mgmt.resource import ResourceManagementClient
from azure.common.client_factory import get_client_from_cli_profile
import stat

# const values
ASSEMBLY_PORT = 51210
TEST_PORT = 51211
PACKAGING_PORT = 51212
OPCPUBLISHER_CONTAINER_IMAGE='iot-edge-opc-publisher:iotedge'
OPCPROXY_CONTAINER_IMAGE='iot-edge-opc-proxy:1.0.4'
CFMES_CONTAINER_IMAGE='azure-iot-connected-factory-cfmes:latest'
CFSTATION_CONTAINER_IMAGE='azure-iot-connected-factory-cfsta:latest'


# set module globals
_platformType = str(platform.system())
_topologyFileName = 'topology.json'
_topologyUrl = 'https://raw.githubusercontent.com/Azure/azure-iot-connected-factory/master/WebApp/Contoso/Topology/ContosoTopologyDescription.json"'
_startScript = []
_stopScript = []
_initScript = []
_deinitScript = []
_iotHubOwnerConnectionString = ''
_hostDirHost = ''
_opcPublisherContainer = OPCPUBLISHER_CONTAINER_IMAGE
_opcProxyContainer = OPCPROXY_CONTAINER_IMAGE
_cfMesContainer = CFMES_CONTAINER_IMAGE
_cfStationContainer = CFSTATION_CONTAINER_IMAGE
_edgeDomain = ''

# command line parsing
parser = argparse.ArgumentParser(description="Generates and if requested start the shopfloor simulation of Connectedfactory")

# topology configuration info
topologyParser = argparse.ArgumentParser(add_help=False)
topoGroup = topologyParser.add_mutually_exclusive_group(required=True)
topoGroup.add_argument('--topofile', default=None,
    help="The location of the Connectedfactory topology configuration file.")
topoGroup.add_argument('--topourl', default=None,
    help="The URL of the Connectedfactory topology configuration file.")

# domain to handle
domainParser = argparse.ArgumentParser(add_help=False)
domainParser.add_argument('domain', metavar='DOMAIN', default=None,
    help="The domain of the iotedgeopc installation. This is not a DNS domain, but a topology domain used to address hosts with identical hostnames from the cloud.")

# publishednodes.json file
# todo eval and use it
nodesConfigParser = argparse.ArgumentParser(add_help=False)
nodesConfigParser.add_argument('--nodesconfig', default=None,
    help="The configuration file specifying the OPC UA nodes to publish. Requires the hostdir parameter to be set to a directory.")

# IoTHub name
# iotHubParser = argparse.ArgumentParser(add_help=False)
# iotHubParser.add_argument('--iothubname', default=None, required=True,
#     help="Name of the IoTHub to use.")

# optional arguments valid for all sub commands
commonOptArgsParser = argparse.ArgumentParser(add_help=False)
commonOptArgsParser.add_argument('--iothubname', default=None, required=True,
    help="Name of the IoTHub to use.")
commonOptArgsParser.add_argument('--dockerregistry', default=None,
    help="The container registry for all used containers.")
commonOptArgsParser.add_argument('--hostdir', default=None,
    help="A directory on the host machine, which containers use for log, config and certificate files. If not specified everything is kept in Docker volumes.")
commonOptArgsParser.add_argument('--outdir', default='./out',
    help="The directory where all generated files are created.")

commonOptArgsParser.add_argument('-s', '--serviceprincipalcert',
    help=".pem containing a service principal cert to login to Azure.")
commonOptArgsParser.add_argument('-t', '--tenantid',
    help="TenantId of the Azure tenant to login.")
commonOptArgsParser.add_argument('-a', '--appid',
    help="AppId of the Azure service principal to login.")

commonOptArgsParser.add_argument('--force', action='store_true',
    help="Forces deletion of existing IoTEdge deployment and device if they exist.")
commonOptArgsParser.add_argument('--loglevel', default='INFO',
    help="The log level. Allowed: debug, info, warning, error, critical")

# add sub commands
subParsers = parser.add_subparsers(dest='subcommand')
cfsimParser = subParsers.add_parser('cfsim', parents=[topologyParser, commonOptArgsParser], help='Generates scripts for the Connectedfactory simulation.')
cfParser = subParsers.add_parser('cf', parents=[topologyParser, domainParser, commonOptArgsParser], help='Generates scripts for a Connectedfactory domain/factory.')
gwParser = subParsers.add_parser('gw', parents=[domainParser, commonOptArgsParser, nodesConfigParser], help='Generates scripts for an Azure Industrial IoT gateway deployment.')

_args = parser.parse_args()

# todo complete it
def scriptPrerequisites():
    # sudo apt-get update
    # sudo apt install python -y
    # sudo apt install python-pip -y
    #
    # sudo pip install virtualenv
    # virtualenv mytestenv
    # cd mytestenv
    # source bin/activate
    #
    # pip install PyYAML
    # pip install azure
    # pip install azure-cli-core
    #
    # install az as explained here: https://docs.microsoft.com/en-us/cli/azure/install-azure-cli?view=azure-cli-latest
    # az extension add --name azure-cli-iot-ext
    #
    # sudo apt-get update
    # sudo apt-get install \
    #   apt-transport-https \
    #   ca-certificates \
    #   curl \
    #   software-properties-common -y
    # curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo apt-key add -
    # sudo add-apt-repository \
    # "deb [arch=amd64] https://download.docker.com/linux/ubuntu \
    #   $(lsb_release -cs) \
    #   stable" 
    # sudo apt-get update
    # sudo apt-get install docker-ce -y
    #
    #


    # sudo apt install docker-compose -y
    #
    # pip install -U azure-iot-edge-runtime-ctl
    #
    #
    #     # for the azure cli we need: Python, libffi, openssl 1.0.2
    initCmd = "python get-pip.py"
    _initScript.append(_startScriptCmdPrefix + initCmd + _startScriptCmdPostfix + '\n')
    initCmd = "az extension add --name azure-cli-iot-ext"
    _initScript.append(_startScriptCmdPrefix + initCmd + _startScriptCmdPostfix + '\n')


# remove not allowed chars from a domain name and lower it
def normalizedCfDomainName(name):
    return name.replace(' ', '').replace('.', '').lower()


def createEdgeDomainConfiguration(domainName):
    #
    # create all IoTEdge configuration resoures and settings for the domain
    #
    # check if the deployment already exists
    deploymentName = 'opc-deployment-{0}'.format(domainName)
    logging.info("Check if deployment with id '{0}' exists".format(deploymentName))
    cmd = "az iot edge deployment list --hub-name {0} --query \"[?id=='{1}']\"".format(_args.iothubname, deploymentName)
    deploymentListResult = os.popen(cmd).read()
    deploymentListJson = json.loads(deploymentListResult)

    # create an OPC deployment if it is not there
    createDeployment = False
    if not deploymentListResult or len(deploymentListJson) == 0:
        createDeployment = True
    else:
        if _args.force:
            # delete deployment and trigger creation
            logging.info("Deployment '{0}' found. Deleting it...".format(deploymentName))
            cmd = "az iot edge deployment delete --hub-name {0} --config-id {1}".format(_args.iothubname, deploymentName)
            os.popen(cmd).read()
            createDeployment = True
        else:
            logging.info("Deployment '{0}' found. Using it...".format(deploymentName))
            logging.debug(json.dumps(deploymentListJson, indent=4))
    
    if createDeployment:
        logging.info("Creating deployment '{0}'".format(deploymentName))
        # patch the template to create a docker compose configuration
        ymlFileName = '{0}.yml'.format(domainName)
        ymlOutFileName = '{0}/{1}'.format(_args.outdir, ymlFileName)
        with open('domain.yml', 'r') as setupTemplate, open(ymlOutFileName, 'w+') as setupOutFile:
                for line in setupTemplate:
                    line = line.replace('${OPCPROXY_CONTAINER}', _opcProxyContainer)
                    line = line.replace('${OPCPUBLISHER_CONTAINER}', _opcPublisherContainer)
                    line = line.replace('${DOMAIN}', domainName)
                    line = line.replace('${HOSTDIR}', _args.hostdir)
                    line = line.replace('${EXTRAHOSTS}', "".join(_extraHosts))
                    setupOutFile.write(line)
        templateStream = file(ymlOutFileName, 'r')
        yamlTemplate = yaml.load(templateStream)
        modulesConfig = {}
        for service in yamlTemplate['services']:
            # todo find out where the container_name of the yml goes. 
            serviceConfig = yamlTemplate['services'][service]
            moduleConfig = {}
            moduleConfig['version'] = '1.0'
            moduleConfig['type'] = 'docker'
            moduleConfig['status'] = 'running'
            moduleConfig['restartPolicy'] = serviceConfig['restart']
            settings = {}
            settings['image'] = serviceConfig['image']
            createOptions = {}
            if 'hostname' in serviceConfig:
                createOptions['Hostname'] = serviceConfig['hostname']
            if 'environment' in serviceConfig:
                env = []
                for envVar in serviceConfig['environment']:
                    env.append('"{0}"'.format(envVar))
                createOptions['Env'] = env
            if 'command' in serviceConfig:
                cmdList = []
                cmdList.append(serviceConfig['command'])
                createOptions['Cmd'] = cmdList
            hostConfig = {}
            if 'expose' in serviceConfig:
                portBindings = {}
                hostPort = []
                for port in serviceConfig['expose']:
                    portProto = port + '/tcp'
                    hostPort.append( { "HostPort": str(port) } )
                    portBindings[portProto] = hostPort
                hostConfig['PortBindings'] = portBindings
            if 'volumes' in serviceConfig:
                binds = []
                for bind in serviceConfig['volumes']:
                    binds.append(bind)
                hostConfig['Binds'] = binds
            if 'extra_hosts' in serviceConfig:
                extraHosts = []
                for extraHost in serviceConfig['extra_hosts']:
                    extraHosts.append(extraHost)
                hostConfig['ExtraHosts'] = extraHosts
            if len(hostConfig) != 0:
                createOptions['HostConfig'] = hostConfig
            settings['createOptions'] = json.dumps(createOptions)
            moduleConfig['settings'] = settings
            modulesConfig[service] = moduleConfig

        # create the deployment
        with open('iot-edge-opc-deployment-content-template.json', 'r') as deploymentContentTemplateFile, open('{0}/{1}.json'.format(_args.outdir, deploymentName), 'w') as deploymentContentFile:
            deploymentContent = json.loads(deploymentContentTemplateFile.read())
            deploymentContent['content']['moduleContent']['$edgeAgent']['properties.desired']['modules'] = modulesConfig
            json.dump(deploymentContent, deploymentContentFile, indent=4)
        # todo enable when bool is supported for target condition
        #cmd = 'az iot edge deployment create --config-id {0} --hub-name {1}  --content {2}/{0}.json --target-condition "tags.opc=true and tags.domain=\'{3}\'"'.format(deploymentName, _args.iothubname, _args.outdir, domainName)
        cmd = "az iot edge deployment create --config-id {0} --hub-name {1}  --content {2}/{0}.json --target-condition \"tags.opc=\'true\' and tags.domain=\'{3}\'\"".format(deploymentName, _args.iothubname, _args.outdir, domainName)
        deploymentCreateResult = os.popen(cmd).read()
        if not deploymentCreateResult:
            logging.critical("Can not create deployment. Exiting...")
            sys.exit(1)
        logging.debug(json.dumps(json.loads(deploymentCreateResult), indent=4))
        
    # create device identity for the edge and set tags
    deviceId = 'iot-edge-{0}'.format(domainName)
    logging.info("Check if device '{0}' already exists".format(deviceId))
    cmd = "az iot hub device-identity show --device-id {0} --hub-name {1} ".format(deviceId, _args.iothubname)
    deviceShowResult = os.popen(cmd).read()
    createDevice = False
    if not deviceShowResult:
        createDevice = True
    else:
        if _args.force:
            # delete device and trigger creation
            logging.info("Device '{0}' found. Deleting it...".format(deviceId))
            cmd = "az iot hub device-identity delete --hub-name {0} --device-id {1}".format(_args.iothubname, deviceId)
            os.popen(cmd).read()
            createDevice = True
        else:
            logging.info("Device '{0}' found. Using it...".format(deviceId))
            logging.debug(json.dumps(json.loads(deviceShowResult), indent=4))

    if createDevice:
        logging.info("Creating device '{0}'".format(deviceId))
        cmd = "az iot hub device-identity create --device-id {0} --hub-name {1} --edge-enabled".format(deviceId, _args.iothubname)
        deviceCreateResult = os.popen(cmd).read()
        if not deviceCreateResult:
            logging.critical("Can not create device. Exiting...")
            sys.exit(1)
        logging.debug(json.dumps(json.loads(deviceCreateResult), indent=4))

        logging.info("Setting tags for device '{0}'".format(deviceId))
        # todo enable when bool is supported for target condition
        # tags = {"opc": True, "domain": domainname }
        tags = {"opc": "true", "domain": domainName }
        tagsJson = json.dumps(tags)
        # todo need to fix escape and strings for Linux
        tagsJsonOs = tagsJson.replace('\"', '\\"').replace(' ', '')
        cmd = "az iot hub device-twin update --hub-name {0} --device-id {1} --set tags={2}".format(_args.iothubname, deviceId, tagsJsonOs)
        updateTagsResult = os.popen(cmd).read()
        if not updateTagsResult:
            logging.critical("Can not create device. Exiting...")
            sys.exit(1)
        logging.debug(json.dumps(json.loads(updateTagsResult), indent=4))

    # fetch edge device connection string
    logging.info("Fetch connection string for device '{0}'".format(deviceId))
    cmd = "az iot hub device-identity show-connection-string --hub-name {0} --device-id {1}".format(_args.iothubname, deviceId)
    connectionStringResult = os.popen(cmd).read()
    if not connectionStringResult:
        logging.critical("Can not read connection string for device. Exiting...")
        sys.exit(1)
    connectionStringJson = json.loads(connectionStringResult)
    logging.debug(json.dumps(connectionStringJson, indent=4))
    edgeDeviceConnectionString = connectionStringJson['cs']

    # create script commands to start/stop IoTEdge
    startCmd = "iotedgectl start"
    _startScript.append(_startScriptCmdPrefix + startCmd + _startScriptCmdPostfix + '\n')
    # stop commands are written in reversed order
    stopCmd = "iotedgectl stop"
    _stopScript.append(_stopScriptCmdPrefix + stopCmd + _stopScriptCmdPostfix + '\n')

    #
    # create all local initialization resources of the domain
    #
    # patch the init template to create a docker compose configuration
    ymlFileName = '{0}-edge-init.yml'.format(domainName)
    ymlOutFileName = '{0}/{1}'.format(_args.outdir, ymlFileName)
    with open('domain-edge-init.yml', 'r') as setupTemplate, open(ymlOutFileName, 'w+') as setupOutFile:
            for line in setupTemplate:
                line = line.replace('${OPCPROXY_CONTAINER}', _opcProxyContainer)
                line = line.replace('${DOMAIN}', domainName)
                line = line.replace('${HOSTDIR}', _args.hostdir)
                line = line.replace('${IOTHUB_CONNECTIONSTRING}', _iotHubOwnerConnectionString)
                setupOutFile.write(line)
    # generate script
    # todo add registry credential
    # iotedgectl login --address <your container registry address> --username <username> --password <password> 
    # todo use CA signed cert
    initCmd = 'iotedgectl setup --connection-string "{0}" --auto-cert-gen-force-no-passwords {1}'.format(edgeDeviceConnectionString, '--runtime-log-level debug' if (_args.loglevel.lower() == 'debug') else '')
    _initScript.append(_initScriptCmdPrefix + initCmd + _initScriptCmdPostfix + '\n')
    initCmd = "docker pull {0}".format(_opcProxyContainer)
    _initScript.append(initCmd + '\n')
    initCmd = "docker-compose -p {0} -f {1} up".format(domainName, ymlFileName)
    _initScript.append(_initScriptCmdPrefix + initCmd + _initScriptCmdPostfix + '\n')
    # deinit commands are written in reversed order
    deinitCmd = "docker volume rm {0}_cfappdata".format(domainName)
    _deinitScript.append(_deinitScriptCmdPrefix + deinitCmd + _deinitScriptCmdPostfix + '\n')
    deinitCmd = "docker volume rm {0}_cfx509certstores".format(domainName)
    _deinitScript.append(_deinitScriptCmdPrefix + deinitCmd + _deinitScriptCmdPostfix + '\n')
    deinitCmd = "docker-compose -p {0} -f {1} down".format(domainName, ymlFileName)
    _deinitScript.append(_deinitScriptCmdPrefix + deinitCmd + _deinitScriptCmdPostfix + '\n')
    deinitCmd = "iotedgectl uninstall"
    _deinitScript.append(_deinitScriptCmdPrefix + deinitCmd + _deinitScriptCmdPostfix + '\n')


# create the configuration for the domain in a deployment without IoTEdge
def createNonEdgeDomainConfiguration(domainName):
    #
    # create everything for the initialization of the domain
    #
    # patch the init template to create a docker compose configuration
    ymlFileName = '{0}-init.yml'.format(domainName)
    ymlOutFileName = '{0}/{1}'.format(_args.outdir, ymlFileName)
    with open('domain-init.yml', 'r') as setupTemplate, open(ymlOutFileName, 'w+') as setupOutFile:
            for line in setupTemplate:
                line = line.replace('${OPCPROXY_CONTAINER}', _opcProxyContainer)
                line = line.replace('${OPCPUBLISHER_CONTAINER}', _opcPublisherContainer)
                line = line.replace('${DOMAIN}', domainName)
                line = line.replace('${HOSTDIR}', _args.hostdir)
                line = line.replace('${IOTHUB_CONNECTIONSTRING}', _iotHubOwnerConnectionString)
                setupOutFile.write(line)
    # generate script
    initCmd = "docker pull {0}".format(_opcProxyContainer)
    _initScript.append(initCmd + '\n')
    initCmd = "docker pull {0}".format(_opcPublisherContainer)
    _initScript.append(initCmd + '\n')
    initCmd = "docker-compose -p {0} -f {1} up".format(domainName, ymlFileName)
    _initScript.append(_initScriptCmdPrefix + initCmd + _initScriptCmdPostfix + '\n')
    # deinit commands are written in reversed order
    deinitCmd = "docker volume rm {0}_cfappdata".format(domainName)
    _deinitScript.append(_deinitScriptCmdPrefix + deinitCmd + _deinitScriptCmdPostfix + '\n')
    deinitCmd = "docker volume rm {0}_cfx509certstores".format(domainName)
    _deinitScript.append(_deinitScriptCmdPrefix + deinitCmd + _deinitScriptCmdPostfix + '\n')
    deinitCmd = "docker-compose -p {0} -f {1} down".format(domainName, ymlFileName)
    _deinitScript.append(_deinitScriptCmdPrefix + deinitCmd + _deinitScriptCmdPostfix + '\n')

    #
    # create everything to start all required components for the domain
    #
    # patch the template
    ymlFileName = '{0}.yml'.format(domainName)
    ymlOutFileName = '{0}/{1}'.format(_args.outdir, ymlFileName)
    with open('domain.yml', 'r') as template, open(ymlOutFileName, 'w+') as outFile:
            for line in template:
                line = line.replace('${OPCPROXY_CONTAINER}', _opcProxyContainer)
                line = line.replace('${OPCPUBLISHER_CONTAINER}', _opcPublisherContainer)
                line = line.replace('${DOMAIN}', domainName)
                line = line.replace('${HOSTDIR}', _args.hostdir)
                line = line.replace('${EXTRAHOSTS}', "".join(_extraHosts))
                outFile.write(line)

    # generate script
    startCmd = "docker pull {0}".format(_opcProxyContainer)
    _startScript.append(startCmd + '\n')
    startCmd = "docker pull {0}".format(_opcPublisherContainer)
    _startScript.append(startCmd + '\n')
    startCmd = "docker rm proxy-{0}".format(domainName)
    _startScript.append(startCmd + '\n')
    startCmd = "docker rm publisher-{0}".format(domainName)
    _startScript.append(startCmd + '\n')
    startCmd = "docker-compose -p {0} -f {1} up".format(domainName, ymlFileName)
    _startScript.append(_startScriptCmdPrefix + startCmd + _startScriptCmdPostfix + '\n')
    startCmd = "{0} 10".format("timeout" if _platformType == "Windows" else "sleep")
    _startScript.append(startCmd + '\n')
    # stop commands are written in reversed order
    stopCmd = "docker-compose -p {0} -f {1} down".format(domainName, ymlFileName)
    _stopScript.append(_stopScriptCmdPrefix + stopCmd + _stopScriptCmdPostfix + '\n')



# generate a Cf simulation production line yml
def generateCfProductionLine(factory, productionLine):

    domainName = normalizedCfDomainName(factory['Domain'])
    productionLineName = productionLine['Name'].replace(' ', '').lower()
    # patch the template
    domainProductionLineName = '{0}-{1}'.format(domainName, productionLineName)
    # put the production line on the right network
    if _edgeDomain == domainName:
        domainNetworkName = 'azure-iot-edge'
    else:
        domainNetworkName = '{0}_default'.format(domainName)
    ymlFileName = '{0}.yml'.format(domainProductionLineName)
    ymlOutFileName = '{0}/{1}'.format(_args.outdir, ymlFileName)
    with open('cfproductionline.yml', 'r') as template, open(ymlOutFileName, 'w+') as outFile:
            for line in template:
                line = line.replace('${CFMES_CONTAINER}', _cfMesContainer)
                line = line.replace('${CFSTATION_CONTAINER}', _cfStationContainer)
                line = line.replace('${DOMAIN_NETWORK}', domainNetworkName)
                line = line.replace('${DOMAIN}', domainName)
                line = line.replace('${PRODUCTIONLINE}', productionLineName)
                line = line.replace('${MES_HOSTNAME}', "{0}-mes".format(domainProductionLineName))
                line = line.replace('${HOSTDIR}', _args.hostdir)
                # patch station type specific parameters
                for station in productionLine['Stations']:
                    stationArgs = None
                    stationEndpoint = None
                    if 'Simulation' in station and 'Args' in station['Simulation']:
                        stationArgs = station['Simulation']['Args']
                    if 'OpcEndpointUrl' in station:
                        stationEndpoint = station['OpcEndpointUrl']
                    if 'Simulation' in station and 'Type' in station['Simulation'] and station['Simulation']['Type'].lower() == 'assembly':
                        if stationArgs is None:
                            stationArgs = "200 8 yes"
                        if stationEndpoint is None:
                            stationEndpoint = "opc.tcp://{0}-assembly:{1}".format(domainProductionLineName, ASSEMBLY_PORT)
                        line = line.replace('${ASSEMBLY_HOSTNAME}', "{0}-assembly".format(domainProductionLineName))
                        line = line.replace('${ASSEMBLY_ENDPOINT}', stationEndpoint)
                        line = line.replace('${ASSEMBLY_PORT}', str(ASSEMBLY_PORT))
                        line = line.replace('${ASSEMBLY_POWERCONSUMPTION}', "--pc " + stationArgs.split(' ')[0])
                        line = line.replace('${ASSEMBLY_CYCLETIME}', "--ct " + stationArgs.split(' ')[1])
                        line = line.replace('${ASSEMBLY_GENERATEALERTS}', "--ga" if stationArgs.split(' ')[2].lower() == "yes" else "")
                    if 'Simulation' in station and 'Type' in station['Simulation'] and station['Simulation']['Type'].lower() == 'test':
                        if stationArgs is None:
                            stationArgs = "100 10 no"
                        if stationEndpoint is None:
                            stationEndpoint = "opc.tcp://{0}-test:{1}".format(domainProductionLineName, TEST_PORT)
                        line = line.replace('${TEST_HOSTNAME}', "{0}-test".format(domainProductionLineName))
                        line = line.replace('${TEST_ENDPOINT}', stationEndpoint)
                        line = line.replace('${TEST_PORT}', str(TEST_PORT))
                        line = line.replace('${TEST_POWERCONSUMPTION}', "--pc " + stationArgs.split(' ')[0])
                        line = line.replace('${TEST_CYCLETIME}', "--ct " + stationArgs.split(' ')[1])
                        line = line.replace('${TEST_GENERATEALERTS}', "--ga" if stationArgs.split(' ')[2].lower() == "yes" else "")
                    if 'Simulation' in station and 'Type' in station['Simulation'] and station['Simulation']['Type'].lower() == 'packaging':
                        if stationArgs is None:
                                stationArgs = "150 6 no"
                        if stationEndpoint is None:
                            stationEndpoint = "opc.tcp://{0}-packaging:{1}".format(domainProductionLineName, PACKAGING_PORT)
                        line = line.replace('${PACKAGING_HOSTNAME}', "{0}-packaging".format(domainProductionLineName))
                        line = line.replace('${PACKAGING_ENDPOINT}', stationEndpoint)
                        line = line.replace('${PACKAGING_PORT}', str(PACKAGING_PORT))
                        line = line.replace('${PACKAGING_POWERCONSUMPTION}', "--pc " + stationArgs.split(' ')[0])
                        line = line.replace('${PACKAGING_CYCLETIME}', "--ct " + stationArgs.split(' ')[1])
                        line = line.replace('${PACKAGING_GENERATEALERTS}', "--ga" if stationArgs.split(' ')[2].lower() == "yes" else "")
                outFile.write(line)
    # generate script
    startCmd = "docker pull {0}".format(_cfMesContainer)
    _startScript.append(startCmd + '\n')
    startCmd = "docker pull {0}".format(_cfStationContainer)
    _startScript.append(startCmd + '\n')
    startCmd = "docker rm {0}-mes".format(domainProductionLineName)
    _startScript.append(startCmd + '\n')
    startCmd = "docker rm {0}-assembly".format(domainProductionLineName)
    _startScript.append(startCmd + '\n')
    startCmd = "docker rm {0}-test".format(domainProductionLineName)
    _startScript.append(startCmd + '\n')
    startCmd = "docker rm {0}-packaging".format(domainProductionLineName)
    _startScript.append(startCmd + '\n')
    startCmd = "docker-compose -p {0} -f {1} up".format(domainProductionLineName, ymlFileName)
    _startScript.append(_startScriptCmdPrefix + startCmd + _startScriptCmdPostfix + '\n')
    startCmd = "{0} 10".format("timeout" if _platformType == "Windows" else "sleep")
    _startScript.append(startCmd + '\n')
    # stop commands are written in reversed order
    stopCmd = "docker-compose -p {0} -f {1} down".format(domainProductionLineName, ymlFileName)
    _stopScript.append(_stopScriptCmdPrefix + stopCmd + _stopScriptCmdPostfix + '\n')


# generate the OPC Publisher publishednodes configuration file
def generateCfPublishedNodesConfig(factory):
    domainName = normalizedCfDomainName(factory['Domain'])    
    # check if there is anything to generate
    stations = []
    productionLineOfStation = {}
    if 'ProductionLines' in factory:
        for productionLine in factory['ProductionLines']:
            stations += productionLine['Stations']
            productionLineName = 'productionline'
            if 'Simulation' in productionLine and 'Id' in productionLine['Simulation']:
                productionLineName = productionLine['Simulation']['Id']
            elif 'Name' in productionLine:
                productionLineName = productionLine['Name'].strip().lower()
            for station in productionLine['Stations']:
                if 'OpcUri' in station:
                    productionLineOfStation[station['OpcUri']] = productionLineName
                elif 'ApplicationUri' in station:
                    productionLineOfStation[station['ApplicationUri']] = productionLineName
    if 'Stations' in factory:
        stations += factory['Stations']
    if stations.count == 0:
        return

    # generate nodes file name
    nodesFileName = 'publishednodes-' + domainName + '.json'
    nodesOutFileName = '{0}/publishednodes-'.format(_args.outdir) + domainName + '.json'
    
    # generate the configuration file
    publishedNodes = []
    opcNodeIdNodes = []
    for station in stations:
        stationObj = {}
        if 'OpcEndpointUrl' in station:
            endpointUrl = stationObj['EndpointUrl'] = station['OpcEndpointUrl'] 
        else:
            logging.critical("Station must have a property OpcEndpointUrl or OpcUri")
            logging.critical("{0}".format(station))
            sys.exit(1)
        if 'OpcUseSecurity' in station:
            stationObj['UseSecurity'] = station['OpcUseSecurity']
        opcExpandedNodeIdNodes = []
        for stationnode in station['OpcNodes']:
            opcNode = {}
            if 'ExpandedNodeId' in stationnode:
                opcNode['ExpandedNodeId'] = stationnode['ExpandedNodeId']
            elif 'NodeId' in stationnode:
                    opcNode['NodeId'] = stationnode['NodeId']
                    opcNode['EndpointUrl'] = endpointUrl
                    opcNodeIdNodes.append(opcNode)
                    continue
            else:
                continue   
            if 'OpcPublishRecursive' in stationnode:
                opcNode['OpcPublishRecursive'] = stationnode['OpcPublishRecursive']
            if 'OpcPublishingInterval' in stationnode:
                opcNode['OpcPublishingInterval'] = stationnode['OpcPublishingInterval']
            if 'OpcSamplingInterval' in stationnode:
                opcNode['OpcSamplingInterval'] = stationnode['OpcSamplingInterval']
            opcExpandedNodeIdNodes.append(opcNode)
        if len(opcExpandedNodeIdNodes):
            stationObj['OpcNodes'] = opcExpandedNodeIdNodes
            publishedNodes.append(stationObj)

    with open(nodesOutFileName, 'w') as nodesFile:
        if len(opcNodeIdNodes):
            json.dump(opcNodeIdNodes, nodesFile, indent=4)
        elif len(publishedNodes):
            json.dump(publishedNodes, nodesFile, indent=4)
        else:
            logging.warning("There are not nodes configured to publish for domain {0}".format(domainName))
    if os.path.exists(nodesOutFileName):
        shutil.copyfile(nodesOutFileName, '{0}/{1}'.format(_hostDirHost, nodesFileName))

def validateTopology():
    # topology source validation
    if _args.topourl is not None:
        topologyUrl = _args.topourl.strip()
        if not topologyUrl:
            logging.critical("The URL argument is empty. Exiting...")
            sys.exit(2)
        logging.info("Loading topology file from '{0}'".format(topologyUrl))
        topologyJson = urllib.urlopen(topologyUrl).read().decode('utf-8')
    else:
        if _args.topofile is not None:
            _topologyFileName = _args.topofile.strip()
        if os.path.isfile(_topologyFileName):
            with open(_topologyFileName, 'r') as topologyFile:
                logging.info("Loading topology file from '{0}'".format(_topologyFileName))
                topologyJson = topologyFile.read()
        else:
            logging.critical("The file {0} with the topology description does not exist. Exiting...".format(_topologyFileName))
            sys.exit(2)
    topology = json.loads(topologyJson)

    # check topology version
    topologyFileVersion = topology.get('Version')
    if topologyFileVersion is None:
        logging.critical("The description file format is not supported. Please update to a newer version. Exiting...")
        sys.exit(1)
    return topology

def getLocalIpAddress():
    ipAddress = None
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # doesn't even have to be reachable
        sock.connect(('8.8.8.8', 1))
        ipAddress = sock.getsockname()[0]
    except:
        ipAddress = None
    finally:
        sock.close()
    return ipAddress

def getExtraHosts():
    hosts = []
    if os.path.exists("extrahosts") and os.path.isfile("extrahosts"):
        with open("extrahosts", "r") as hostsfile:
            hostlines = hostsfile.readlines()
        hostlines = [line.strip() for line in hostlines
                    if not line.startswith('#') and line.strip() != '']
        for line in hostlines:
            linesplit = line.split('#')[0].split()[:]
            ipAddress = linesplit[0]
            try:
                socket.inet_aton(ipAddress)
            except:
                exceptionInfo = sys.exc_info()
                logging.warning("Exception info:")
                logging.warning("{0}".format(exceptionInfo))
                logging.warning("There is an entry in extrahosts with invalid IP address syntax: '{0}'. Ignoring...".format(ipAddress))            
                continue
            hostNames = linesplit[1:]
            for hostName in hostNames:
                hosts.append({ "host": hostName, "ip": ipAddress })
    return hosts

def writeScript(scriptFileBaseName, scriptBuffer, reverse = False):
    scriptFileName = '{0}/{1}'.format(_args.outdir, scriptFileBaseName)
    with open(scriptFileName, 'w+') as scriptFile:   
        for command in scriptBuffer:
            scriptFile.write(command)   
    os.chmod(scriptFileName, os.stat(scriptFileName).st_mode | stat.S_IXOTH | stat.S_IXGRP | stat.S_IXUSR)


###############################################################################
#
# Main script
#
###############################################################################

# configure script logging
logLevel = getattr(logging, _args.loglevel.upper(), None)
if not isinstance(logLevel, int):
    raise( ValueError('Invalid log level: {0}'.format(_args.loglevel)))
logging.basicConfig(level=logLevel)

# validate arguments
if _args.outdir is not None:
    _args.outdir = _args.outdir.strip()
    if not os.path.exists(_args.outdir):
        os.mkdir(_args.outdir)
    elif not os.path.isdir(_args.outdir):
        logging.critical("Given outdir '{0} is not a directory. Please check. Exiting...".format(_args.outdir))
        sys.exit(2)
    logging.info("Create all generated files in directory '{0}'.".format(_args.outdir))

if _args.hostdir is not None:
    _args.hostdir = _args.hostdir.strip()
    # docker-compose 1.18/docker 17.12.0-ce uses //c/ notation for Windows C:/
    # we convert the hostdir parameter
    if _platformType == 'Windows' and _args.hostdir.startswith('//'):
        _hostDirHost = _args.hostdir[2:3] + ':' + _args.hostdir[3:]
    else:
        if _args.hostdir.startswith('/'):
            _hostDirHost = '{0}'.format(_args.hostdir)
        else:
            _hostDirHost = '{0}/{1}'.format(os.getcwd(), _args.hostdir)
    if _hostDirHost:
        # ensure the directory exists
        if not os.path.exists(_hostDirHost):
            os.mkdir(_hostDirHost)
        elif not os.path.isdir(_hostDirHost):
            logging.critical("Given hostdir '{0}' is not a directory. Please check. Exiting...".format(_args.hostdir))
            sys.exit(2)       
        logging.info("Passing '{0}' to docker as source in bind, maps to '{1}' on host machine.".format(_args.hostdir, _hostDirHost))
else:
    # use a docker volume
    # todo verify correct hanling with domains
    _args.hostdir = 'cfappdata'

if _args.dockerregistry is None:
    _args.dockerregistry = 'microsoft'
else:
    _args.dockerregistry = _args.dockerregistry.strip().lower()
    logging.info("Docker container registry to use: '{0}'".format(_args.dockerregistry))
_cfMesContainer = CFMES_CONTAINER_IMAGE if '/' in CFMES_CONTAINER_IMAGE else '{0}/{1}'.format(_args.dockerregistry, CFMES_CONTAINER_IMAGE)
_cfStationContainer = CFSTATION_CONTAINER_IMAGE if '/' in CFSTATION_CONTAINER_IMAGE else '{0}/{1}'.format(_args.dockerregistry, CFSTATION_CONTAINER_IMAGE)
_opcProxyContainer = OPCPROXY_CONTAINER_IMAGE if '/' in OPCPROXY_CONTAINER_IMAGE else '{0}/{1}'.format(_args.dockerregistry, OPCPROXY_CONTAINER_IMAGE)
_opcPublisherContainer = OPCPUBLISHER_CONTAINER_IMAGE if '/' in OPCPUBLISHER_CONTAINER_IMAGE else '{0}/{1}'.format(_args.dockerregistry, OPCPUBLISHER_CONTAINER_IMAGE)
logging.info("Using OpcPublisher container: '{0}'".format(_opcPublisherContainer))
logging.info("Using OpcProxy container: '{0}'".format(_opcProxyContainer))
logging.info("Using CfMes container: '{0}'".format(_cfMesContainer))
logging.info("Using CfStation container: '{0}'".format(_cfStationContainer))

if _args.serviceprincipalcert is not None:
    _args.serviceprincipalcert = _args.serviceprincipalcert.strip()
    logging.info("Setup using service principal cert in file '{0}'".format(_args.serviceprincipalcert))

if _args.tenantid is not None:
    _args.tenantid = _args.tenantid.strip()
    logging.info("Setup using tenant id '{0}' to login".format(_args.tenantid))

if _args.appid is not None:
    _args.appid = _args.appid.strip()
    logging.info("Setup using AppId '{0}' to login".format(_args.appid))

if ((_args.serviceprincipalcert is not None or _args.tenantid is not None or _args.appid is not None) and
    (_args.serviceprincipalcert is None or _args.tenantid is None or _args.appid is None)):
     logging.critical("serviceprincipalcert, tennantid and appid must all be specified. Exiting...")
     sys.exit(2)

_args.subcommand = _args.subcommand.lower()

# validate all required parameters for cfsim subcommand
if _args.subcommand == 'cfsim':
    _topology = validateTopology()
    # to create a Cf simulation, we keep all logs and shared secrets in the host file system and need a hostdir parameter
    if not _hostDirHost:
        logging.critical("Subcommand cfsim requires specification of a host directory for --hostdir. Exiting...")
        sys.exit(2) 
    # for the simulation we need a topology configuration file with at least one domain/factory of type 'Simulation'
    for factory in _topology['Factories']:
        if 'Shopfloor' in factory and 'Type' in factory['Shopfloor'] and factory['Shopfloor']['Type'].lower() == 'simulation':
            # we are good to continue and use this domain/factory to run in in IoTEdge
            _edgeDomain = normalizedCfDomainName(factory['Domain'])
            break
    if not _edgeDomain:
        logging.critical("Subcommand cfsim requires a topology with at least one domain/factory of type 'Simulation'. Exiting...")
        sys.exit(2) 
    # set the domain to None
    _args.domain = None

# validate all required parameters for cf subcommand
if _args.subcommand == 'cf':
    _topology = validateTopology()
    _args.domain = _args.domain.lower() 
    _edgeDomain = _args.domain

# validate all required parameters for gw subcommand
if _args.subcommand == 'gw':
    # validate the nodesconfig file 
    if _args.nodesconfig:
        # check if file exists
        if not os.path.exists(_args.nodesconfig) or not os.path.isfile(_args.nodesconfig):
            logging.critical("The nodesconfig file '{0}' can not be found or is not a file. Exiting...".format(_args.nodesconfig))
            sys.exit(2) 
        # to access it we need access to host file system and need a hostdir parameter
        if not _hostDirHost:
            logging.critical("If --nodesconfig is specified you need to specify a host directory for --hostdir as well. Exiting...")
            sys.exit(2) 
    _args.domain = _args.domain.lower() 
    _edgeDomain = _args.domain
   
# OS specific settings
if _platformType == 'Linux':
    _startScriptFileName = "start-edgeopc.sh"
    _startScriptCmdPrefix = ""
    _startScriptCmdPostfix = " &"
    _stopScriptFileName = "stop-edgeopc.sh"
    _stopScriptCmdPrefix = ""
    _stopScriptCmdPostfix = ""
    _initScriptFileName = "init-edgeopc.sh"
    _initScriptCmdPrefix = ""
    _initScriptCmdPostfix = " &"
    _deinitScriptFileName = "deinit-edgeopc.sh"
    _deinitScriptCmdPrefix = ""
    _deinitScriptCmdPostfix = " &"
elif _platformType == 'Windows':
    _startScriptFileName = "start-edgeopc.bat"
    _startScriptCmdPrefix = "start "
    _startScriptCmdPostfix = ""
    _stopScriptFileName = "stop-edgeopc.bat"
    _stopScriptCmdPrefix = ""
    _stopScriptCmdPostfix = ""
    _initScriptFileName = "init-edgeopc.bat"
    _initScriptCmdPrefix = ""
    _initScriptCmdPostfix = ""
    _deinitScriptFileName = "deinit-edgeopc.bat"
    _deinitScriptCmdPrefix = ""
    _deinitScriptCmdPostfix = ""
else:
    logging.critical("OS is not supported. Exiting...")
    sys.exit(1)

# build the list of hostname/IP address mapping to allow the containers to access the local and external hosts, in case there is no DNS (espacially on Windows)
_additionalHosts = []
ipAddress = getLocalIpAddress()
if ipAddress is None:
    logging.critical("There is not network connection available.")
    sys.exit(1)
hostName = socket.gethostname()
fqdnHostName = socket.getfqdn()
_additionalHosts.append({ "host": hostName, "ip": ipAddress })
_additionalHosts.append({ "host": fqdnHostName, "ip": ipAddress })
_additionalHosts.extend(getExtraHosts()[:])
_extraHosts = []
_extraHosts.extend('- "{0}:{1}"\n'.format(host['host'], host['ip']) for host in _additionalHosts[0:1])
_extraHosts.extend('            - "{0}:{1}"\n'.format(host['host'], host['ip']) for host in _additionalHosts[1:-1])
_extraHosts.extend('            - "{0}:{1}"'.format(host['host'], host['ip']) for host in _additionalHosts[-1:])

# todo generate IoTEdge prerequisites
# scriptPrerequisites()

# login via service principal if login info is provided
logging.info("Login to Azure")
if _args.serviceprincipalcert:
    # auto login
    cmd = "az login --service-principal -u {0} -p {1} --tenant {2}".format(_args.appid, _args.serviceprincipalcert, _args.tenantid)
    cmdResult = os.popen(cmd).read()
else:
    try:
        client = get_client_from_cli_profile(ResourceManagementClient)
    except:
        exceptionInfo = sys.exc_info()
        logging.critical("Exception info:")
        logging.critical("{0}".format(exceptionInfo))
        logging.critical("Please login to Azure with 'az login' and set the subscription which contains IoTHub '{0}' with 'az account set'.".format(_args.iothubname))
        sys.exit(1)

# verify IoTHub existence
cmd = "az iot hub show --name {0}".format(_args.iothubname)
iotHubShowResult = os.popen(cmd).read()
if not iotHubShowResult:
    logging.critical("IoTHub '{0}' can not be found. Please verify your Azure login and account settings. Exiting...".format(_args.iothubname))
    sys.exit(1)
logging.debug(json.dumps(json.loads(iotHubShowResult), indent=4))           

# fetch the connectionstring
logging.info("Read IoTHub connectionstring")
cmd = "az iot hub show-connection-string --hub-name {0}".format(_args.iothubname)
connectionStringResult = os.popen(cmd).read()
if not connectionStringResult:
    logging.critical("Can not read IoTHub owner connection string. Please verify your configuration. Exiting...")
    sys.exit(1)
connectionStringJson = json.loads(connectionStringResult)
logging.debug(json.dumps(connectionStringJson, indent=4))
_iotHubOwnerConnectionString = connectionStringJson['cs']

#
# cfsim operation: create all scripts to (de)init and start/stop the Cf simulation as configured in the topology configuration
# - for the first domain in the topology an IoTEdge device and deployment is created and all OPC components are configured to run as IoTEdge modules
# - for all other domains the OPC components run in separate docker-compose environments
# - all production lines run in own docker-compose environments and sit on the same docker network as the OPC components of the domain
#
if _args.subcommand == 'cfsim':
    for factory in _topology['Factories']:
        currentDomain = normalizedCfDomainName(factory['Domain'])
        # only handle domain/factories of type simulation
        if 'Shopfloor' in factory and 'Type' in factory['Shopfloor'] and factory['Shopfloor']['Type'].lower() == 'simulation':
            # create OPC Publisher nodes configuration
            generateCfPublishedNodesConfig(factory)
            # create domain/factory scripts
            logging.info("Create the domain initialization and configuration for '{0}'".format(factory['Name']))
            if currentDomain == _edgeDomain:
                createEdgeDomainConfiguration(currentDomain)
            else:
                createNonEdgeDomainConfiguration(currentDomain) 
            # create production line scripts
            for productionLine in factory['ProductionLines']:
                logging.info("Create a production line '{0}' in factory '{1}' for Cf simulation".format(productionLine['Name'], factory['Name']))
                generateCfProductionLine(factory, productionLine)


#
# cf operation: create all scripts to (de)init and start/stop the domain specified on the command line, the domain must be part of the topology configuration
# - create an IoTEdge device and deployment for the domain and all OPC components are configured to run as IoTEdge modules
# - create nodes configuration file for OPC Publisher base on input from the topology configuration
#
if _args.subcommand == 'cf':
    for factory in _topology['Factories']:
        currentDomain = normalizedCfDomainName(factory['Domain'])
        # only handle the specified domain
        if (currentDomain == _args.domain):
            # create OPC Publisher nodes configuration
            generateCfPublishedNodesConfig(factory)
            # create domain/factory scripts
            logging.info("Create the domain initialization and configuration for '{0}'".format(factory['Name']))
            createEdgeDomainConfiguration(currentDomain)


#
# gw operation: create all scripts to (de)init and start/stop the domain specified on the command line
# - create an IoTEdge device and deployment for the domain and all OPC components are configured to run as IoTEdge modules
#
if _args.subcommand == 'gw':
    # copy OPC Publisher nodes configuration
    if _args.nodesconfig:
        nodesFileName = 'publishednodes-' + _args.domain + '.json'
        shutil.copyfile(_args.nodesconfig, '{0}/{1}'.format(_hostDirHost, nodesFileName))
    # create domain/factory scripts
    logging.info("Create the domain initialization and configuration for '{0}'".format(_args.domain))
    createEdgeDomainConfiguration(_args.domain)


# optional: sleep to debug initialization script issues
# _initScript.append('timeout 60\n')

# write the scripts
writeScript(_startScriptFileName, _startScript)
writeScript(_stopScriptFileName, _stopScript, reverse = True)
writeScript(_initScriptFileName, _initScript)
writeScript(_deinitScriptFileName, _deinitScript, reverse = True)

# done
logging.info("Operation completed.")


