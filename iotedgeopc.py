import sys
_python3 = False
if (sys.version_info > (3, 0)):
    _python3 = True
import os
import platform
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
import requests

# const values
ASSEMBLY_PORT = 51210
TEST_PORT = 51211
PACKAGING_PORT = 51212

OPCPUBLISHER_CONTAINER_IMAGE='iot-edge-opc-publisher:iotedge'
OPCPROXY_CONTAINER_IMAGE='iot-edge-opc-proxy:1.0.4'
OPCGDS_CONTAINER_IMAGE='mregen/edgegds:latest'
OPCTWIN_CONTAINER_IMAGE='marcschier/iot-opc-twin-edge-service:latest'
CFMES_CONTAINER_IMAGE='azure-iot-connected-factory-cfmes:latest'
CFSTATION_CONTAINER_IMAGE='azure-iot-connected-factory-cfsta:latest'


# set module globals
_targetPlatform = ''
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
_opcGdsContainer = OPCGDS_CONTAINER_IMAGE
_opcTwinContainer = OPCTWIN_CONTAINER_IMAGE
_cfMesContainer = CFMES_CONTAINER_IMAGE
_cfStationContainer = CFSTATION_CONTAINER_IMAGE
_edgeDomain = ''
_dockerBindSource = ''
_outdirConfig = ''

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

# publisher configuration files
publisherConfigParser = argparse.ArgumentParser(add_help=False)
publisherConfigParser.add_argument('--nodesconfig', default=None,
    help="The configuration file specifying the OPC UA nodes to publish. Requires the hostdir parameter to be set to a directory.")
publisherConfigParser.add_argument('--telemetryconfig', default=None,
    help="The configuration file specifying the format of the telemetry to be ingested by OPC Publisher. Requires the hostdir parameter to be set to a directory.")

# iothub name
iothubArgsParser = argparse.ArgumentParser(add_help=False)
iothubArgsParser.add_argument('--iothubname', default=None, required=True,
    help="Name of the IoTHub to use.")

# iotcentral connection string
iotccsArgsParser = argparse.ArgumentParser(add_help=False)
iotccsArgsParser.add_argument('--iotcentralcs', default=None, required=True,
    help="IoT Central connection string")

# optional arguments valid for all sub commands
commonOptArgsParser = argparse.ArgumentParser(add_help=False)
commonOptArgsParser.add_argument('--dockerregistry', default=None,
    help="The container registry for all used containers.")
commonOptArgsParser.add_argument('--hostdir', default=None,
    help="A directory on the host machine, which containers use for log, config and certificate files. Use the syntax of your targetplatform to specify (for WSL use Windows syntax) If not specified everything is kept in Docker volumes.")
commonOptArgsParser.add_argument('--dockerpipesyntax', action='store_true', default=False,
    help="Older Docker for Windows versions use a pipe syntax (starting with //) to reference Windows directories. This switch enables using this syntax.")
commonOptArgsParser.add_argument('--outdir', default='./out',
    help="The directory where all generated files are created.")
commonOptArgsParser.add_argument('--targetplatform', choices=['windows', 'linux', 'wsl'], default=None,
    help="The scripts created should target a different platform than you are working on.")

commonOptArgsParser.add_argument('-s', '--serviceprincipalcert',
    help=".pem containing a service principal cert to login to Azure.")
commonOptArgsParser.add_argument('-t', '--tenantid',
    help="TenantId of the Azure tenant to login.")
commonOptArgsParser.add_argument('-a', '--appid',
    help="AppId of the Azure service principal to login.")

commonOptArgsParser.add_argument('--force', action='store_true',
    help="Forces deletion of existing IoTEdge deployment and device if they exist.")
commonOptArgsParser.add_argument('--loglevel', default='info',
    help="The log level. Allowed: debug, info, warning, error, critical")

# add sub commands
subParsers = parser.add_subparsers(dest='subcommand')
subParsers.required = True
cfsimParser = subParsers.add_parser('cfsim', parents=[topologyParser, iothubArgsParser, commonOptArgsParser], help='Generates scripts for the Connectedfactory simulation.')
cfParser = subParsers.add_parser('cf', parents=[topologyParser, domainParser, iothubArgsParser, commonOptArgsParser], help='Generates scripts for a Connectedfactory domain/factory.')
gwParser = subParsers.add_parser('gw', parents=[domainParser, commonOptArgsParser, iothubArgsParser, publisherConfigParser], help='Generates scripts for an Azure Industrial IoT gateway deployment.')
iotcsimParser = subParsers.add_parser('iotcsim', parents=[topologyParser, domainParser, iotccsArgsParser, commonOptArgsParser], help='Generates scripts to ingest data of the Connectedfactory simulation into Azure IoT Central.')

_args = parser.parse_args()

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
        twinService = False
        # patch the template to create a docker compose configuration
        ymlFileName = '{0}.yml'.format(domainName)
        ymlOutFileName = '{0}/{1}'.format(_args.outdir, ymlFileName)
        telemetryConfigOption = ''
        try:
            if _args.telemetryconfig:
                telemetryConfigOption = '--tc /d/tc-{0}.json'.format(domainName)
        except AttributeError:
            pass
        with open('{0}/domain.yml'.format(_scriptDir), 'r') as setupTemplate, open(ymlOutFileName, 'w+', newline=_targetNewline) as setupOutFile:
            for line in setupTemplate:
                line = line.replace('${OPCPUBLISHER_CONTAINER}', _opcPublisherContainer)
                line = line.replace('${OPCPROXY_CONTAINER}', _opcProxyContainer)
                line = line.replace('${OPCGDS_CONTAINER}', _opcGdsContainer)
                line = line.replace('${OPCTWIN_CONTAINER}', _opcTwinContainer)
                line = line.replace('${TELEMETRYCONFIG_OPTION}', telemetryConfigOption)
                line = line.replace('${IOTHUB_CONNECTIONSTRING}', _iotHubOwnerConnectionString)
                line = line.replace('${OPCTWIN_DEVICECONNECTIONSTRING_OPTION}', '')
                line = line.replace('${DOMAIN}', domainName)
                line = line.replace('${BINDSOURCE}', _dockerBindSource)
                line = line.replace('${EXTRAHOSTS}', "".join(_extraHosts))
                setupOutFile.write(line)
        with open(ymlOutFileName, 'r') as templateStream:
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
            if 'command' in serviceConfig and serviceConfig['command'] is not None:
                cmdList = []
                cmdArgs = filter(lambda arg: arg.strip() != '', serviceConfig['command'].split(" "))
                cmdList.extend(cmdArgs)
                createOptions['Cmd'] = cmdList
            hostConfig = {}
            if 'expose' in serviceConfig:
                exposedPorts = {}
                for port in serviceConfig['expose']:
                    exposedPort = str(port) + "/tcp"
                    exposedPorts[exposedPort] = '{}' 
                createOptions['ExposedPorts'] = exposedPorts       
            if 'ports' in serviceConfig:
                portBindings = {}
                for port in serviceConfig['ports']:
                    hostPorts = []
                    if '-' in port or '/' in port:
                        logging.fatal("For ports (in file domain.yml) only the single port short syntax without protocol (tcp is used) is supported (HOSTPORT:CONTAINERPORT)")
                        sys.exit(1)
                    if ':' in port:
                        delim = port.find(':')
                        hostPort = port[:delim]
                        containerPort = port[delim+1:] + '/tcp'
                    else:
                        hostPort = port
                        containerPort = port + '/tcp'
                    hostPorts.append( { "HostPort": str(hostPort) } )
                    portBindings[containerPort] = hostPorts
                hostConfig['PortBindings'] = portBindings
            if 'volumes' in serviceConfig:
                binds = []
                for bind in serviceConfig['volumes']:
                    # on Docker for Windows the API interface used by the edgeAgent needs pipe syntax
                    if not _args.dockerpipesyntax and bind[1:2] == ':' and _targetPlatform in [ 'windows', 'wsl' ]:
                        bind = '//' + bind[0:1] + bind[2:]
                    # if a container is used, make it domain specific
                    if bind[0:1] != '/':
                        bind = '{0}_{1}'.format(domainName, bind)
                    binds.append(bind)
                hostConfig['Binds'] = binds
            if 'extra_hosts' in serviceConfig and serviceConfig['extra_hosts']:
                extraHosts = []
                for extraHost in serviceConfig['extra_hosts']:
                    extraHosts.append(extraHost)
                hostConfig['ExtraHosts'] = extraHosts
            if len(hostConfig) != 0:
                createOptions['HostConfig'] = hostConfig
            settings['createOptions'] = json.dumps(createOptions)
            moduleConfig['settings'] = settings
            # map the service name to a domain specific service name
            if service.lower() == 'publisher':
                service = 'pub-{0}'.format(domainName)
            elif service.lower() == 'proxy':
                service = 'prx-{0}'.format(domainName)
            elif service.lower() == 'gds':
                service = 'gds-{0}'.format(domainName)
            elif service.lower() == 'twin':
                service = 'twin-{0}'.format(domainName)
                twinService = True
            modulesConfig[service] = moduleConfig

        # create the deployment
        with open('iot-edge-opc-deployment-content-template.json', 'r') as deploymentContentTemplateFile, open('{0}/{1}.json'.format(_args.outdir, deploymentName), 'w', newline=_targetNewline) as deploymentContentFile:
            deploymentContent = json.loads(deploymentContentTemplateFile.read())
            deploymentContent['content']['moduleContent']['$edgeAgent']['properties.desired']['modules'] = modulesConfig
            # set default properties for twin
            if twinService:
                deploymentContent['content']['moduleContent']['twin-{0}'.format(domainName)] = { 'properties.desired': {} }
                deploymentContent['content']['moduleContent']['twin-{0}'.format(domainName)]['properties.desired'] = { 'Discovery': "Scan" }
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
    cmd = "az iot hub device-identity show --hub-name {0} --device-id {1}".format(_args.iothubname, deviceId)
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
        cmd = "az iot hub device-identity create --hub-name {0} --device-id {1} --edge-enabled".format(_args.iothubname, deviceId)
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
            logging.critical("Can not set tags for device. Exiting...")
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
    startCmd = "docker rm pub-{0}".format(domainName)
    _startScript.append(startCmd + '\n')
    startCmd = "docker rm prx-{0}".format(domainName)
    _startScript.append(startCmd + '\n')
    startCmd = "docker rm gds-{0}".format(domainName)
    _startScript.append(startCmd + '\n')
    startCmd = "docker rm twin-{0}".format(domainName)
    _startScript.append(startCmd + '\n')
    startCmd = "iotedgectl start"
    _startScript.append(_startScriptCmdPrefix + startCmd + _startScriptCmdPostfix + '\n')
    # stop commands are written in reversed order
    stopCmd = "iotedgectl stop"
    _stopScript.append(_stopScriptCmdPrefix + stopCmd + _stopScriptCmdPostfix + '\n')

    #
    # create all local initialization resources of the domaidn
    #
    # patch the init template to create a docker compose configuration
    ymlFileName = '{0}-edge-init.yml'.format(domainName)
    ymlOutFileName = '{0}/{1}'.format(_args.outdir, ymlFileName)
    with open('{0}/domain-edge-init.yml'.format(_scriptDir), 'r') as setupTemplate, open(ymlOutFileName, 'w+', newline=_targetNewline) as setupOutFile:
            for line in setupTemplate:
                line = line.replace('${OPCPROXY_CONTAINER}', _opcProxyContainer)
                line = line.replace('${IOTHUB_CONNECTIONSTRING}', _iotHubOwnerConnectionString)
                line = line.replace('${DOMAIN}', domainName)
                line = line.replace('${BINDSOURCE}', _dockerBindSource)
                setupOutFile.write(line)
    # generate script
    # todo add registry credential
    # iotedgectl login --address <your container registry address> --username <username> --password <password> 
    # todo use CA signed cert
    initCmd = "docker volume create {0}_cfx509certstores".format(domainName)
    _initScript.append(initCmd + '\n')
    initCmd = "docker volume create {0}_cfappdata".format(domainName)
    _initScript.append(initCmd + '\n')
    initCmd = 'iotedgectl setup --connection-string "{0}" --auto-cert-gen-force-no-passwords {1}'.format(edgeDeviceConnectionString, '--runtime-log-level debug' if (_args.loglevel.lower() == 'debug') else '')
    _initScript.append(_initScriptCmdPrefix + initCmd + _initScriptCmdPostfix + '\n')
    initCmd = "docker pull {0}".format(_opcProxyContainer)
    _initScript.append(initCmd + '\n')
    initCmd = "docker-compose -p {0} -f {1} up".format(domainName, ymlFileName)
    _initScript.append(_initScriptCmdPrefix + initCmd + _initScriptCmdPostfix + '\n')
    # deinit commands are written in reversed order
    deinitCmd = "iotedgectl uninstall"
    _deinitScript.append(_deinitScriptCmdPrefix + deinitCmd + _deinitScriptCmdPostfix + '\n')
    deinitCmd = "docker volume rm {0}_cfappdata".format(domainName)
    _deinitScript.append(_deinitScriptCmdPrefix + deinitCmd + _deinitScriptCmdPostfix + '\n')
    deinitCmd = "docker volume rm {0}_cfx509certstores".format(domainName)
    _deinitScript.append(_deinitScriptCmdPrefix + deinitCmd + _deinitScriptCmdPostfix + '\n')
    # todo the certstore volume can not be cleaned up yet
    deinitCmd = "docker-compose -p {0} -f {1} down".format(domainName, ymlFileName)
    _deinitScript.append(_deinitScriptCmdPrefix + deinitCmd + _deinitScriptCmdPostfix + '\n')


# create the configuration for the domain in a deployment without IoTEdge
def createNonEdgeDomainConfiguration(domainName):
    #
    # create everything for the initialization of the domain
    #
    # patch the init template to create a docker compose configuration
    ymlFileName = '{0}-init.yml'.format(domainName)
    ymlOutFileName = '{0}/{1}'.format(_args.outdir, ymlFileName)
    with open('{0}/domain-init.yml'.format(_scriptDir), 'r') as setupTemplate, open(ymlOutFileName, 'w+', newline=_targetNewline) as setupOutFile:
            for line in setupTemplate:
                line = line.replace('${OPCPROXY_CONTAINER}', _opcProxyContainer)
                line = line.replace('${OPCPUBLISHER_CONTAINER}', _opcPublisherContainer)
                line = line.replace('${DOMAIN}', domainName)
                line = line.replace('${BINDSOURCE}', _dockerBindSource)
                line = line.replace('${IOTHUB_CONNECTIONSTRING}', _iotHubOwnerConnectionString)
                setupOutFile.write(line)
    # generate script
    initCmd = "docker volume create {0}_cfx509certstores".format(domainName)
    _initScript.append(initCmd + '\n')
    initCmd = "docker volume create {0}_cfappdata".format(domainName)
    _initScript.append(initCmd + '\n')
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
    # todo the certstore volume can not be cleaned up yet
    deinitCmd = "docker-compose -p {0} -f {1} down".format(domainName, ymlFileName)
    _deinitScript.append(_deinitScriptCmdPrefix + deinitCmd + _deinitScriptCmdPostfix + '\n')

    # the twin needs a device to report scanner results create it
    deviceId = 'iot-opc-twin-{0}'.format(domainName)
    logging.info("Check if device '{0}' already exists".format(deviceId))
    cmd = "az iot hub device-identity show --hub-name {0} --device-id {1}".format(_args.iothubname, deviceId)
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
        cmd = "az iot hub device-identity create --hub-name {0} --device-id {1}".format(_args.iothubname, deviceId)
        deviceCreateResult = os.popen(cmd).read()
        if not deviceCreateResult:
            logging.critical("Can not create device. Exiting...")
            sys.exit(1)
        logging.debug(json.dumps(json.loads(deviceCreateResult), indent=4))

        logging.info("Setting Discover mode for device '{0}'".format(deviceId))
        cmd = 'az iot hub device-twin update --hub-name {0} --device-id {1} --set properties.desired.Discover="Scan"'.format(_args.iothubname, deviceId)
        updatePropertiesResult = os.popen(cmd).read()
        if not updatePropertiesResult:
            logging.critical("Can not set properties for device. Exiting...")
            sys.exit(1)
        logging.debug(json.dumps(json.loads(updatePropertiesResult), indent=4))

    # fetch device connection string
    logging.info("Fetch connection string for device '{0}'".format(deviceId))
    cmd = "az iot hub device-identity show-connection-string --hub-name {0} --device-id {1}".format(_args.iothubname, deviceId)
    connectionStringResult = os.popen(cmd).read()
    if not connectionStringResult:
        logging.critical("Can not read connection string for device. Exiting...")
        sys.exit(1)
    connectionStringJson = json.loads(connectionStringResult)
    logging.debug(json.dumps(connectionStringJson, indent=4))
    opcTwinDeviceConnectionString = connectionStringJson['cs']
    opcTwinDeviceConnectionStringOption = 'EdgeHubConnectionString="{0}"'.format(opcTwinDeviceConnectionString)

    #
    # create everything to start all required components for the domain
    #
    # patch the template
    ymlFileName = '{0}.yml'.format(domainName)
    ymlOutFileName = '{0}/{1}'.format(_args.outdir, ymlFileName)
    telemetryConfigOption = ''
    try:
        if _args.telemetryconfig:
            telemetryConfigOption = '--tc /d/tc-{0}.json'.format(domainName)
    except AttributeError:
        pass
    with open('{0}/domain.yml'.format(_scriptDir), 'r') as template, open(ymlOutFileName, 'w+', newline=_targetNewline) as outFile:
        for line in template:
            line = line.replace('${OPCPUBLISHER_CONTAINER}', _opcPublisherContainer)
            line = line.replace('${OPCPROXY_CONTAINER}', _opcProxyContainer)
            line = line.replace('${OPCGDS_CONTAINER}', _opcGdsContainer)
            line = line.replace('${OPCTWIN_CONTAINER}', _opcTwinContainer)
            line = line.replace('${TELEMETRYCONFIG_OPTION}', telemetryConfigOption)
            line = line.replace('${IOTHUB_CONNECTIONSTRING}', _iotHubOwnerConnectionString)
            line = line.replace('${OPCTWIN_DEVICECONNECTIONSTRING_OPTION}', opcTwinDeviceConnectionStringOption)
            line = line.replace('${DOMAIN}', domainName)
            line = line.replace('${BINDSOURCE}', _dockerBindSource)
            line = line.replace('${EXTRAHOSTS}', "".join(_extraHosts))
            outFile.write(line)

    # generate script
    startCmd = "docker pull {0}".format(_opcPublisherContainer)
    _startScript.append(startCmd + '\n')
    startCmd = "docker pull {0}".format(_opcProxyContainer)
    _startScript.append(startCmd + '\n')
    startCmd = "docker pull {0}".format(_opcGdsContainer)
    _startScript.append(startCmd + '\n')
    startCmd = "docker pull {0}".format(_opcTwinContainer)
    _startScript.append(startCmd + '\n')
    startCmd = "docker rm pub-{0}".format(domainName)
    _startScript.append(startCmd + '\n')
    startCmd = "docker rm prx-{0}".format(domainName)
    _startScript.append(startCmd + '\n')
    startCmd = "docker rm gds-{0}".format(domainName)
    _startScript.append(startCmd + '\n')
    startCmd = "docker rm twin-{0}".format(domainName)
    _startScript.append(startCmd + '\n')
    startCmd = "docker-compose -p {0} -f {1} up".format(domainName, ymlFileName)
    _startScript.append(_startScriptCmdPrefix + startCmd + _startScriptCmdPostfix + '\n')
    startCmd = "{0} 10".format("timeout" if _targetPlatform == "windows" else "sleep")
    _startScript.append(startCmd + '\n')
    # stop commands are written in reversed order
    stopCmd = "docker-compose -p {0} -f {1} down".format(domainName, ymlFileName)
    _stopScript.append(_stopScriptCmdPrefix + stopCmd + _stopScriptCmdPostfix + '\n')


# create the configuration for the domain in a deployment without IoTEdge for IoT Central
def createIotCentralDomainConfiguration(domainName):
    #
    # create everything for the initialization of the domain
    #
    # patch the init template to create a docker compose configuration
    ymlFileName = '{0}-init.yml'.format(domainName)
    ymlOutFileName = '{0}/{1}'.format(_args.outdir, ymlFileName)
    with open('{0}/domain-iotcentral-init.yml'.format(_scriptDir), 'r') as setupTemplate, open(ymlOutFileName, 'w+', newline=_targetNewline) as setupOutFile:
            for line in setupTemplate:
                line = line.replace('${OPCPUBLISHER_CONTAINER}', _opcPublisherContainer)
                line = line.replace('${DOMAIN}', domainName)
                line = line.replace('${BINDSOURCE}', _dockerBindSource)
                line = line.replace('${IOTCENTRAL_CONNECTIONSTRING}', _args.iotcentralcs)
                setupOutFile.write(line)
    # generate script
    initCmd = "docker volume create {0}_cfx509certstores".format(domainName)
    _initScript.append(initCmd + '\n')
    initCmd = "docker volume create {0}_cfappdata".format(domainName)
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
    # todo the certstore volume can not be cleaned up yet
    deinitCmd = "docker-compose -p {0} -f {1} down".format(domainName, ymlFileName)
    _deinitScript.append(_deinitScriptCmdPrefix + deinitCmd + _deinitScriptCmdPostfix + '\n')

    #
    # create everything to start all required components for the domain
    #
    # patch the template
    ymlFileName = '{0}.yml'.format(domainName)
    ymlOutFileName = '{0}/{1}'.format(_args.outdir, ymlFileName)
    telemetryConfigOption = ''
    try:
        if _args.telemetryconfig:
            telemetryConfigOption = '--tc /d/tc-{0}.json'.format(domainName)
    except AttributeError:
        pass
    with open('{0}/domain-iotcentral.yml'.format(_scriptDir), 'r') as template, open(ymlOutFileName, 'w+', newline=_targetNewline) as outFile:
        for line in template:
            line = line.replace('${OPCPUBLISHER_CONTAINER}', _opcPublisherContainer)
            line = line.replace('${TELEMETRYCONFIG_OPTION}', telemetryConfigOption)
            line = line.replace('${DOMAIN}', domainName)
            line = line.replace('${BINDSOURCE}', _dockerBindSource)
            line = line.replace('${EXTRAHOSTS}', "".join(_extraHosts))
            outFile.write(line)

    # generate script
    startCmd = "docker pull {0}".format(_opcPublisherContainer)
    _startScript.append(startCmd + '\n')
    startCmd = "docker rm pub-{0}".format(domainName)
    _startScript.append(startCmd + '\n')
    startCmd = "docker-compose -p {0} -f {1} up".format(domainName, ymlFileName)
    _startScript.append(_startScriptCmdPrefix + startCmd + _startScriptCmdPostfix + '\n')
    startCmd = "{0} 10".format("timeout" if _targetPlatform == "windows" else "sleep")
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
    with open('{0}/cfproductionline.yml'.format(_scriptDir), 'r') as template, open(ymlOutFileName, 'w+', newline=_targetNewline) as outFile:
            for line in template:
                line = line.replace('${CFMES_CONTAINER}', _cfMesContainer)
                line = line.replace('${CFSTATION_CONTAINER}', _cfStationContainer)
                line = line.replace('${DOMAIN_NETWORK}', domainNetworkName)
                line = line.replace('${DOMAIN}', domainName)
                line = line.replace('${PRODUCTIONLINE}', productionLineName)
                line = line.replace('${MES_HOSTNAME}', "{0}-mes".format(domainProductionLineName))
                line = line.replace('${BINDSOURCE}', _dockerBindSource)
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
    startCmd = "{0} 10".format("timeout" if _targetPlatform == "windows" else "sleep")
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
                elif 'OpcApplicationUri' in station:
                    productionLineOfStation[station['OpcApplicationUri']] = productionLineName
    if 'Stations' in factory:
        stations += factory['Stations']
    if stations.count == 0:
        return

    # generate nodes file name
    nodesconfigFileName = 'pn-' + domainName + '.json'
    nodesOutFileName = '{0}/{1}'.format(_args.outdir, nodesconfigFileName)
    
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
        if 'OpcNodes' in station:
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

    with open(nodesOutFileName, 'w', newline=_targetNewline) as nodesFile:
        if len(opcNodeIdNodes):
            json.dump(opcNodeIdNodes, nodesFile, indent=4)
        elif len(publishedNodes):
            json.dump(publishedNodes, nodesFile, indent=4)
        else:
            logging.warning("There are no nodes configured to publish for domain {0}".format(domainName))
    # copy configuration files to the right directory if we are running on the target, otherwise copy it to the config file directory
    if _args.targetplatform:
        if os.path.exists(nodesOutFileName):
                nodesconfigFileName = 'pn-' + domainName + '.json'
                shutil.copyfile(nodesOutFileName, '{0}/{1}'.format(_outdirConfig, nodesconfigFileName))
        try:
            if _args.telemetryconfig:
                telemetryconfigFileName = 'tc-' + domainName + '.json'
                shutil.copyfile(_args.telemetryconfig, '{0}/{1}'.format(_outdirConfig, telemetryconfigFileName))
        except AttributeError:
            pass
    else:
        if os.path.exists(nodesOutFileName):
            nodesconfigFileName = 'pn-' + domainName + '.json'
            shutil.copyfile(nodesOutFileName, '{0}/{1}'.format(_hostDirHost, nodesconfigFileName))
        if _args.telemetryconfig:
            telemetryconfigFileName = 'tc-' + _args.domain + '.json'
            shutil.copyfile(_args.telemetryconfig, '{0}/{1}'.format(_hostDirHost, telemetryconfigFileName))


def validateTopology():
    global _topologyFileName

    # topology source validation
    topology = None
    if _args.topourl is not None:
        topologyUrl = _args.topourl.strip()
        if not topologyUrl:
            logging.critical("The URL argument is empty. Exiting...")
            sys.exit(2)
        logging.info("Loading topology file from '{0}'".format(topologyUrl))
        topology = requests.get(topologyUrl).json()
    else:
        if _args.topofile is not None:
            _topologyFileName = _args.topofile.strip()
        if os.path.isfile(_topologyFileName):
            with open(_topologyFileName, 'r') as topologyFile:
                logging.info("Loading topology file from '{0}'".format(_topologyFileName))
                topology = json.loads(topologyFile.read())
        else:
            logging.critical("The file {0} with the topology description does not exist. Exiting...".format(_topologyFileName))
            sys.exit(2)
    if not topology:
            logging.critical("Can not read the topology description. Pls check. Exiting...")
            sys.exit(2)

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
    if os.path.exists("{0}/extrahosts".format(_scriptDir)) and os.path.isfile("{0}/extrahosts".format(_scriptDir)):
        with open("{0}/extrahosts".format(_scriptDir), "r") as hostsfile:
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
    logging.debug("Write '{0}'{1}".format(scriptFileName, ' in reversed order.' if reverse else '.'))
    if reverse:
        scriptBuffer = scriptBuffer[::-1]
    with open(scriptFileName, 'w+', newline=_targetNewline) as scriptFile: 
        for command in scriptBuffer:
            scriptFile.write(command)   
    os.chmod(scriptFileName, os.stat(scriptFileName).st_mode | stat.S_IXOTH | stat.S_IXGRP | stat.S_IXUSR)


def azureLogin():
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


def azureGetIotHubCs():
    global _iotHubOwnerConnectionString
    
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
    logging.debug("IoTHub connection string is '{0}'".format(_iotHubOwnerConnectionString))
    

###############################################################################
#
# Main script
#
###############################################################################

# configure script logging
try:
    logLevel = getattr(logging, _args.loglevel.upper())
except:
    logLevel = logging.INFO
if not isinstance(logLevel, int):
    raise( ValueError('Invalid log level: {0}'.format(logLevel)))
logging.basicConfig(level=logLevel)

# get path of script
_scriptDir = sys.path[0]

# OS specific settings
if not _args.targetplatform:
    _targetPlatform = str(platform.system()).lower()
    if _targetPlatform == 'linux':
        # check if we are on WSL
        for line in open('/proc/version'):
            if 'Microsoft' in line:
                _targetPlatform = 'wsl'
    elif _targetPlatform == 'windows':
         pass
    else:
        logging.critical("OS is not supported. Exiting...")
        sys.exit(1)
else:
    _targetPlatform = _args.targetplatform
logging.info("Using targetplatform '{0}'".format(_targetPlatform))

if _targetPlatform == 'linux' or _targetPlatform == 'wsl':
    _startScriptFileName = 'start-edgeopc.sh'
    _startScriptCmdPrefix = ''
    _startScriptCmdPostfix = ' &'
    _stopScriptFileName = 'stop-edgeopc.sh'
    _stopScriptCmdPrefix = ''
    _stopScriptCmdPostfix = ''
    _initScriptFileName = 'init-edgeopc.sh'
    _initScriptCmdPrefix = ''
    _initScriptCmdPostfix = ' &'
    _deinitScriptFileName = 'deinit-edgeopc.sh'
    _deinitScriptCmdPrefix = ''
    _deinitScriptCmdPostfix = ' &'
    _targetNewline = '\n'
elif _targetPlatform == 'windows':
    _startScriptFileName = 'start-edgeopc.bat'
    _startScriptCmdPrefix = 'start '
    _startScriptCmdPostfix = ''
    _stopScriptFileName = 'stop-edgeopc.bat'
    _stopScriptCmdPrefix = ''
    _stopScriptCmdPostfix = ''
    _initScriptFileName = 'init-edgeopc.bat'
    _initScriptCmdPrefix = ''
    _initScriptCmdPostfix = ''
    _deinitScriptFileName = 'deinit-edgeopc.bat'
    _deinitScriptCmdPrefix = ''
    _deinitScriptCmdPostfix = ''
    _targetNewline = '\r\n'

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
    # the --hostdir parameter specifies where on the docker host the configuration files should be stored.
    # during docker configuration a volume bind is configured, which points to this directory.
    # in case of a cross platform generation, the files are put into a config subdirectory of the specified --outdir
    # and need to be transfered manually to the IoTEdge device.
    _dockerBindSource = _args.hostdir = _args.hostdir.strip().replace('\\', '/')
    # The Docker for Windows volume bind syntax has changed over time.
    # With docker ce 18.03.0-ce-win59 (16762), engine 18.03.0-ce the bind syntax for D:/docker needs to be //d/docker

    if _targetPlatform in [ 'windows', 'wsl']:
        # we accept only fully qualified windows syntax (starts with <drive>:)
        if _args.hostdir[1:3] != ':/':
            logging.fatal("The --hostdir parameter must be using a fully qualified Windows directory syntax.")
            sys.exit(1)
        # Docker for Windows bind source syntax can be using pipe syntax (starts with // as well)
        if _args.dockerpipesyntax:
            _dockerBindSource = '//' + _args.hostdir[0:1] + _args.hostdir[2:]
    elif _targetPlatform == 'linux':
        if _args.hostdir[0:1] != '/':
            logging.fatal("The --hostdir parameter must be using a fully qualified Linux directory syntax.")
            sys.exit(1)
    else:
        logging.fatal("Target platform '{0}' is not supported.".format(_targetPlatform))
        sys.exit(1)

    if _args.targetplatform:
        # create a directory for the configuration files, if not running on the IoTEdge device
        _outdirConfig = _args.outdir + '/config'
        if not os.path.exists(_outdirConfig):
            os.mkdir(_outdirConfig)
            logging.info("Create directory '{0}' for target system configuration files.".format(_outdirConfig))
        elif not os.path.isdir(_outdirConfig):
            logging.critical("'{0}' is expected to be a directory to provide configuration files, but it is not. Pls check. Exiting...".format(_outdirConfig))
            sys.exit(2)
        logging.info("Create all generated configuration files in directory '{0}'.".format(_outdirConfig))
        logging.info("Passing '{0}' to docker as source in bind, maps to '{1}'.".format(_dockerBindSource, _args.hostdir))
        _hostDirHost = _args.hostdir
    else:
        logging.info("--targetplatform was not specified. Assume we run on the IoTEdge device.")
        if _targetPlatform in [ 'windows', 'linux' ]:
            _hostDirHost = _args.hostdir
        if _targetPlatform == 'wsl':
            _hostDirHost = '/mnt/' + _args.hostdir[0:1] + '/' + _args.hostdir[3:]
        if not os.path.exists(_hostDirHost):
            logging.info("Directory '{0}' specified via --hostdir does not exist. Creating it...".format(_args.hostdir))
            os.mkdir(_hostDirHost)
        logging.info("Passing '{0}' to docker as source in bind, maps to '{1}'.".format(_dockerBindSource, _hostDirHost))
else:
    # use a docker volume
    # todo verify correct hanling with domains
    _dockerBindSource = 'cfappdata'
    logging.info("Passing '{0}' (docker volume) to docker as source in bind.".format(_dockerBindSource))

if _args.dockerregistry is None:
    _args.dockerregistry = 'microsoft'
else:
    _args.dockerregistry = _args.dockerregistry.strip().lower()
    logging.info("Docker container registry to use: '{0}'".format(_args.dockerregistry))
_cfMesContainer = CFMES_CONTAINER_IMAGE if '/' in CFMES_CONTAINER_IMAGE else '{0}/{1}'.format(_args.dockerregistry, CFMES_CONTAINER_IMAGE)
_cfStationContainer = CFSTATION_CONTAINER_IMAGE if '/' in CFSTATION_CONTAINER_IMAGE else '{0}/{1}'.format(_args.dockerregistry, CFSTATION_CONTAINER_IMAGE)
_opcProxyContainer = OPCPROXY_CONTAINER_IMAGE if '/' in OPCPROXY_CONTAINER_IMAGE else '{0}/{1}'.format(_args.dockerregistry, OPCPROXY_CONTAINER_IMAGE)
_opcGdsContainer = OPCGDS_CONTAINER_IMAGE if '/' in OPCGDS_CONTAINER_IMAGE else '{0}/{1}'.format(_args.dockerregistry, OPCGDS_CONTAINER_IMAGE)
_opcTwinContainer = OPCTWIN_CONTAINER_IMAGE if '/' in OPCTWIN_CONTAINER_IMAGE else '{0}/{1}'.format(_args.dockerregistry, OPCTWIN_CONTAINER_IMAGE)
_opcPublisherContainer = OPCPUBLISHER_CONTAINER_IMAGE if '/' in OPCPUBLISHER_CONTAINER_IMAGE else '{0}/{1}'.format(_args.dockerregistry, OPCPUBLISHER_CONTAINER_IMAGE)
logging.info("Using OpcPublisher container: '{0}'".format(_opcPublisherContainer))
logging.info("Using OpcProxy container: '{0}'".format(_opcProxyContainer))
logging.info("Using OpcGds container: '{0}'".format(_opcGdsContainer))
logging.info("Using OpcTwin container: '{0}'".format(_opcTwinContainer))
logging.info("Using CfMes container: '{0}'".format(_cfMesContainer))
logging.info("Using CfStation container: '{0}'".format(_cfStationContainer))

if _args.serviceprincipalcert is not None:
    _args.serviceprincipalcert = _args.serviceprincipalcert.strip()
    if _targetPlatform == 'windows' and not _args.serviceprincipalcert[1:2] == ':' or _targetPlatform == 'linux' and not _args.serviceprincipalcert.startswith('/'):
        _args.serviceprincipalcert = '{0}/{1}'.format(os.getcwd(), _args.serviceprincipalcert)
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
    if not _args.hostdir:
        logging.critical("Subcommand cfsim requires --hostdir as well. Exiting...")
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
    # we need a topology configuration file with the specified domain being not of type 'Simulation'
    domainFound = False
    for factory in _topology['Factories']:
        if 'Domain' in factory and factory['Domain'].lower() == _args.domain:
            # we are good to continue and use this domain/factory to run in in IoTEdge
            domainFound = True
            break
    if not domainFound:
        logging.critical("The specified domain '{0}' was not found in the topology description. Pls check. Exiting...")
        sys.exit(2) 
    

# validate all required parameters for gw subcommand
if _args.subcommand == 'gw':
    # validate the nodesconfig file 
    if _args.nodesconfig:
        # check if file exists
        if not os.path.exists(_args.nodesconfig) or not os.path.isfile(_args.nodesconfig):
            logging.critical("The nodesconfig file '{0}' can not be found or is not a file. Exiting...".format(_args.nodesconfig))
            sys.exit(2) 
        # to access it we need access to host file system and need a hostdir parameter
        if not _args.hostdir:
            logging.critical("If --nodesconfig is specified you need to specify a host directory for --hostdir as well. Exiting...")
            sys.exit(2) 
    try:
        if _args.telemetryconfig:
            # check if file exists
            if not os.path.exists(_args.telemetryconfig) or not os.path.isfile(_args.telemetryconfig):
                logging.critical("The telemetryconfig file '{0}' can not be found or is not a file. Exiting...".format(_args.telemetryconfig))
                sys.exit(2) 
            # to access it we need access to host file system and need a hostdir parameter
            if not _args.hostdir:
                logging.critical("If --telemetryconfig requires --hostdir as well. Exiting...")
                sys.exit(2) 
    except AttributeError:
        pass
    _args.domain = _args.domain.lower() 
    _edgeDomain = _args.domain

# validate all required parameters for iotcsim subcommand
if _args.subcommand == 'iotcsim':
    _topology = validateTopology()
    _args.domain = _args.domain.lower()
    # to create a Cf simulation, we keep all logs and shared secrets in the host file system and need a hostdir parameter
    if not _args.hostdir:
        logging.critical("Subcommand iotcsim requires --hostdir as well. Exiting...")
        sys.exit(2) 
    # for the simulation we need a topology configuration file with the specified domain beiing of type 'Simulation'
    simulationDomainFound = False
    for factory in _topology['Factories']:
        if 'Domain' in factory and factory['Domain'].lower() == _args.domain and  'Shopfloor' in factory and 'Type' in factory['Shopfloor'] and factory['Shopfloor']['Type'].lower() == 'simulation':
            # we are good to continue and use this domain/factory to run in in IoTEdge
            simulationDomainFound = True
            break
    if not simulationDomainFound:
        logging.critical("The specified domain '{0}' must be configured in the topology description and must be of type 'Simulation'. Pls check. Exiting...".format(_args.domain))
        sys.exit(2) 

# build the list of hostname/IP address mapping to allow the containers to access the local and external hosts, in case there is no DNS (espacially on Windows)
# add localhost info if we run on the targetplatform
_additionalHosts = []
if not _args.targetplatform:
    ipAddress = getLocalIpAddress()
    if ipAddress is None:
        logging.critical("There is not network connection available.")
        sys.exit(1)
    hostName = socket.gethostname()
    fqdnHostName = socket.getfqdn()
    _additionalHosts.append({ "host": hostName, "ip": ipAddress })
    if hostName.lower() != fqdnHostName.lower():
        _additionalHosts.append({ "host": fqdnHostName, "ip": ipAddress })
    else:
        print("FQDN '{0}' is equal to hostname '{1}'".format(fqdnHostName, hostName))
_additionalHosts.extend(getExtraHosts()[:])
_extraHosts = []
if len(_additionalHosts) > 0:
    _extraHosts.extend('- "{0}:{1}"\n'.format(host['host'], host['ip']) for host in _additionalHosts[0:1])
    if len(_additionalHosts) > 2:
        _extraHosts.extend('            - "{0}:{1}"\n'.format(host['host'], host['ip']) for host in _additionalHosts[1:-1])
    if len(_additionalHosts) >= 2:
        _extraHosts.extend('            - "{0}:{1}"'.format(host['host'], host['ip']) for host in _additionalHosts[-1:])

#
# cfsim operation: create all scripts to (de)init and start/stop the Cf simulation as configured in the topology configuration
# - for the first domain in the topology an IoTEdge device and deployment is created and all OPC components are configured to run as IoTEdge modules
# - for all other domains the OPC components run in separate docker-compose environments
# - all production lines run in own docker-compose environments and sit on the same docker network as the OPC components of the domain
#
if _args.subcommand == 'cfsim':
    # login to Azure and fetch IoTHub connection string
    azureLogin()
    azureGetIotHubCs()
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
    # login to Azure and fetch IoTHub connection string
    azureLogin()
    azureGetIotHubCs()
    domainProcessed = False
    for factory in _topology['Factories']:
        currentDomain = normalizedCfDomainName(factory['Domain'])
        # only handle the specified domain
        if (currentDomain == _args.domain):
            domainProcessed = True
            # create OPC Publisher nodes configuration
            generateCfPublishedNodesConfig(factory)
            # create domain/factory scripts
            logging.info("Create the domain initialization and configuration for '{0}'".format(factory['Name']))
            createEdgeDomainConfiguration(currentDomain)
    if not domainProcessed:
        logging.fatal("The specified domain '{0}' was not found in the topology description.".format(_args.domain))
        sys.exit(1)


#
# gw operation: create all scripts to (de)init and start/stop the domain specified on the command line
# - copy the configuration files
# - create an IoTEdge device and deployment for the domain and all OPC components are configured to run as IoTEdge modules
#
if _args.subcommand == 'gw':
    # login to Azure and fetch IoTHub connection string
    azureLogin()
    azureGetIotHubCs()
    # copy configuration files to the right directory if we are running on the target, otherwise copy it to the config file directory
    if _args.targetplatform:
        if _args.nodesconfig:
            nodesconfigFileName = 'pn-' + _args.domain + '.json'
            shutil.copyfile(_args.nodesconfig, '{0}/{1}'.format(_outdirConfig, nodesconfigFileName))
        try:
            if _args.telemetryconfig:
                telemetryconfigFileName = 'tc-' + _args.domain + '.json'
                shutil.copyfile(_args.telemetryconfig, '{0}/{1}'.format(_outdirConfig, telemetryconfigFileName))
        except AttributeError:
            pass
    else:
        if _args.nodesconfig:
            nodesconfigFileName = 'pn-' + _args.domain + '.json'
            shutil.copyfile(_args.nodesconfig, '{0}/{1}'.format(_hostDirHost, nodesconfigFileName))
        if _args.telemetryconfig:
            telemetryconfigFileName = 'tc-' + _args.domain + '.json'
            shutil.copyfile(_args.telemetryconfig, '{0}/{1}'.format(_hostDirHost, telemetryconfigFileName))
    # create domain/factory scripts
    logging.info("Create the domain initialization and configuration for '{0}'".format(_args.domain))
    createEdgeDomainConfiguration(_args.domain)


#
# iotcsim operation: create all scripts to (de)init and start/stop the domain specified on the command line to ingest data into IoT Central
# - create a docker-compose environment for the specified domain to run the OPC components
# - create docker-compose environments for all the production lines in that domain
#
if _args.subcommand == 'iotcsim':
    domainProcessed = False
    for factory in _topology['Factories']:
        currentDomain = normalizedCfDomainName(factory['Domain'])
        # only handle the specified domain
        if (currentDomain == _args.domain):
            domainProcessed = True
            # create OPC Publisher nodes configuration
            generateCfPublishedNodesConfig(factory)
            # create domain/factory scripts
            logging.info("Create the domain initialization and configuration for '{0}'".format(factory['Name']))
            createIotCentralDomainConfiguration(currentDomain)
            # create production line scripts
            for productionLine in factory['ProductionLines']:
                logging.info("Create a production line '{0}' in factory '{1}' for Cf simulation".format(productionLine['Name'], factory['Name']))
                generateCfProductionLine(factory, productionLine)
    if not domainProcessed:
        logging.fatal("The specified domain '{0}' was not found in the topology description.".format(_args.domain))
        sys.exit(1)

# optional: sleep to debug initialization script issues
# _initScript.append('timeout 60\n')

# write the scripts
writeScript(_startScriptFileName, _startScript)
writeScript(_stopScriptFileName, _stopScript, reverse = True)
writeScript(_initScriptFileName, _initScript)
writeScript(_deinitScriptFileName, _deinitScript, reverse = True)

# copy prerequisites installation scripts
if _args.targetplatform:
    if _args.targetplatform in [ 'linux', 'wsl' ]:
        shutil.copyfile('{0}/iotedgeopc-install-prerequisites.sh'.format(_scriptDir), '{0}/iotedgeopc-install-prerequisites.sh'.format(_args.outdir))
        shutil.copyfile('{0}/iotedgeopc-install-linux-packages.sh'.format(_scriptDir), '{0}/iotedgeopc-install-linux-packages.sh'.format(_args.outdir))
    shutil.copyfile('{0}/requirements.txt'.format(_scriptDir), '{0}/requirements.txt'.format(_args.outdir))
    # inform user when not running on target platform
    logging.info('')
    logging.info("Please copy any required script files from '{0}' to your target system.".format(_args.outdir))
    if _args.hostdir:
        logging.info("Please copy any required configuration files from '{0}' to your target system to directory '{1}'.".format(_outdirConfig, _args.hostdir))
    
# done
logging.info('')
if _args.targetplatform:
    logging.info("The generated script files can be found in: '{0}'. Please copy them to your target system.".format(_args.outdir))
else:
    logging.info("The generated script files can be found in: '{0}'".format(_args.outdir))
logging.info('')
logging.info("Operation completed.")


