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

PLATFORM_CPU = 'amd64'
OPCPUBLISHER_CONTAINER_IMAGE = 'mcr.microsoft.com/iotedge/opc-publisher'
# to test new features in publisher use a local registry
#OPCPUBLISHER_CONTAINER_IMAGE = 'localhost:5000/opc-publisher'
OPCPUBLISHER_CONTAINER_VERSION = ''
OPCPROXY_CONTAINER_IMAGE = 'mcr.microsoft.com/iotedge/opc-proxy'
OPCPROXY_CONTAINER_VERSION = '1.0.4'
OPCTWIN_CONTAINER_IMAGE = 'mcr.microsoft.com/iotedge/opc-twin'
OPCTWIN_CONTAINER_VERSION = ''
OPCPLC_CONTAINER_IMAGE = 'mcr.microsoft.com/iotedge/opc-plc'
OPCPLC_CONTAINER_VERSION = ''

# set module globals
_targetPlatform = ''
_startScript = []
_stopScript = []
_initScript = []
_deinitScript = []
_iotHubOwnerConnectionString = ''
_hostDirHost = ''
_opcPublisherContainer = OPCPUBLISHER_CONTAINER_IMAGE
_opcProxyContainer = OPCPROXY_CONTAINER_IMAGE
_opcTwinContainer = OPCTWIN_CONTAINER_IMAGE
_opcPlcContainer = OPCPLC_CONTAINER_IMAGE
_platformCpu = PLATFORM_CPU
_edgeSite = ''
_dockerBindSource = ''
_outdirConfig = ''

# command line parsing
parser = argparse.ArgumentParser(description="Installs an Industrial IoT gateway based on IoT Edge")

# site to handle
siteParser = argparse.ArgumentParser(add_help=False)
siteParser.add_argument('site', metavar='SITE', default=None,
    help="The site (factory/production line) of the installation. This is not a DNS domain, but a topology site used to address hosts with identical IP addresses from the cloud or build reduntant systems.")

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

# optional arguments valid for all sub commands
commonOptArgsParser = argparse.ArgumentParser(add_help=False)
commonOptArgsParser.add_argument('--dockerregistry', default=None,
    help="The container registry for all used containers.")
commonOptArgsParser.add_argument('--hostdir', default=None,
    help="A directory on the host machine, which containers use for log, config and certificate files. Use the syntax of your targetplatform to specify (for WSL use Windows syntax) If not specified everything is kept in Docker volumes.")
commonOptArgsParser.add_argument('--outdir', default='./out',
    help="The directory where all generated files are created.")
commonOptArgsParser.add_argument('--targetplatform', choices=['windows', 'linux', 'wsl'], default=None,
    help="The scripts created should target a different platform than you are working on. Default: the platform you are working on")
commonOptArgsParser.add_argument('--lcow', action='store_true',
    help="Forces to use Linux Containers On Windows. Only valid for a Windows target platform.")
commonOptArgsParser.add_argument('--force', action='store_true',
    help="Forces deletion of existing IoT Edge deployment and device if they exist.")
commonOptArgsParser.add_argument('--proxyschema', default="http",
    help="Schema for the proxy.")
commonOptArgsParser.add_argument('--proxyhost', default=None,
    help="Hostname of the proxy to enable IoT Edge communication via proxy.")
commonOptArgsParser.add_argument('--proxyport', default=None,
    help="Port tu use for the proxy.")
commonOptArgsParser.add_argument('--proxyusername', default=None,
    help="Username to use for proxy authentication.")
commonOptArgsParser.add_argument('--proxypassword', default=None,
    help="Password to use for proxy authentication.")
commonOptArgsParser.add_argument('--upstreamprotocol', choices=['Amqp', 'AmpqWs'], default='Amqp',
    help="the upstream protocol IoT Edge should use for communication via proxy.")

commonOptArgsParser.add_argument('-s', '--serviceprincipalcert',
    help=".pem containing a service principal cert to login to Azure.")
commonOptArgsParser.add_argument('-t', '--tenantid',
    help="TenantId of the Azure tenant to login.")
commonOptArgsParser.add_argument('-a', '--appid',
    help="AppId of the Azure service principal to login.")

commonOptArgsParser.add_argument('--loglevel', default='info',
    help="The log level. Allowed: debug, info, warning, error, critical")

# add sub commands
subParsers = parser.add_subparsers(dest='subcommand')
subParsers.required = True
gwParser = subParsers.add_parser('gw', parents=[siteParser, commonOptArgsParser, iothubArgsParser, publisherConfigParser], help='Generates scripts for an Azure Industrial IoT gateway deployment.')

_args = parser.parse_args()

#
# configure IoT Edge site
#
def createEdgeSiteConfiguration(siteName):
    #
    # create all IoT Edge azure configuration resoures and settings for the site
    #
    # check if the deployment already exists
    deploymentName = 'iiot-deployment-{0}'.format(siteName)
    logging.info("Check if deployment with id '{0}' exists".format(deploymentName))
    cmd = "az iot edge deployment list --hub-name {0} --query \"[?id=='{1}']\"".format(_args.iothubname, deploymentName)
    deploymentListResult = os.popen(cmd).read()
    deploymentListJson = json.loads(deploymentListResult)

    #
    # create an IoTHub IoT Edge deployment if it is not there
    #
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
    
    #
    # Read our module configuration from a .yml to push it into a deployment manifest in the next step
    #
    if createDeployment:
        logging.info("Creating deployment '{0}'".format(deploymentName))
        twinService = False
        # patch the template to create a docker compose configuration
        ymlFileName = '{0}.yml'.format(siteName)
        ymlOutFileName = '{0}/{1}'.format(_args.outdir, ymlFileName)
        telemetryConfigOption = ''
        try:
            if _args.telemetryconfig:
                telemetryConfigOption = '--tc /d/tc-{0}.json'.format(siteName)
        except AttributeError:
            pass
        with open('{0}/site.yml'.format(_scriptDir), 'r') as setupTemplate, open(ymlOutFileName, 'w+', newline=_targetNewline) as setupOutFile:
            for line in setupTemplate:
                line = line.replace('${OPCPUBLISHER_CONTAINER}', _opcPublisherContainer)
                line = line.replace('${OPCPROXY_CONTAINER}', _opcProxyContainer)
                line = line.replace('${OPCTWIN_CONTAINER}', _opcTwinContainer)
                line = line.replace('${OPCPLC_CONTAINER}', _opcPlcContainer)
                line = line.replace('${TELEMETRYCONFIG_OPTION}', telemetryConfigOption)
                line = line.replace('${IOTHUB_CONNECTIONSTRING}', _iotHubOwnerConnectionString)
                line = line.replace('${OPCTWIN_DEVICECONNECTIONSTRING_OPTION}', '')
                line = line.replace('${SITE}', siteName)
                line = line.replace('${BINDSOURCE}', _dockerBindSource)
                line = line.replace('${EXTRAHOSTS}', "".join(_extraHosts))
                setupOutFile.write(line)
        with open(ymlOutFileName, 'r') as templateStream:
            yamlTemplate = yaml.load(templateStream)
        modulesConfig = {}
        for service in yamlTemplate['services']:
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
                    exposedPorts[exposedPort] = {}
                createOptions['ExposedPorts'] = exposedPorts       
            if 'ports' in serviceConfig:
                portBindings = {}
                for port in serviceConfig['ports']:
                    hostPorts = []
                    if '-' in port or '/' in port:
                        logging.fatal("For ports (in file site.yml) only the single port short syntax without protocol (tcp is used) is supported (HOSTPORT:CONTAINERPORT)")
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
                    if bind[0:1] != '/' and bind[1:2] != ':':
                        bind = '{0}_{1}'.format(siteName, bind)
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
            # map the service name to a site specific service name
            if service.lower() == 'publisher':
                service = 'pub-{0}'.format(siteName)
            elif service.lower() == 'proxy':
                service = 'prx-{0}'.format(siteName)
            elif service.lower() == 'plc':
                service = 'plc-{0}'.format(siteName)
            elif service.lower() == 'twin':
                service = 'twin-{0}'.format(siteName)
                twinService = True
            modulesConfig[service] = moduleConfig

        #
        # todo fetch the deployment content template from a new created deployment, so we can get rid of iiot-edge-deployment-content-template.json
        #

        #
        # create IoTHub IoT Edge deployment manifest
        #
        with open('iiot-edge-deployment-content-template.json', 'r') as deploymentContentTemplateFile, open('{0}/{1}.json'.format(_args.outdir, deploymentName), 'w', newline=_targetNewline) as deploymentContentFile:
            deploymentContent = json.loads(deploymentContentTemplateFile.read())
            # add proxy configuration
            if _args.proxyhost:
                ProxyUrl = _args.proxyschema + "://"
                if _args.proxyusername and _args.proxypassword:
                    ProxyUrl = ProxyUrl + _args.proxyusername + ":" + _args.proxypassword
                ProxyUrl = ProxyUrl + "@" + _args.proxyhost
                if _args.proxyport:
                    ProxyUrl = ProxyUrl + ":" + _args.proxyport
                # configure EdgeHub to use proxy
                if not 'env' in deploymentContent['content']['modulesContent']['$edgeAgent']['properties.desired']['systemModules']['edgeHub']['settings']:
                    deploymentContent['content']['modulesContent']['$edgeAgent']['properties.desired']['systemModules']['edgeHub']['settings']['env'] = {} 
                if not 'https_proxy' in deploymentContent['content']['modulesContent']['$edgeAgent']['properties.desired']['systemModules']['edgeHub']['settings']['env']:
                    deploymentContent['content']['modulesContent']['$edgeAgent']['properties.desired']['systemModules']['edgeHub']['settings']['env']['https_proxy'] = {}
                deploymentContent['content']['modulesContent']['$edgeAgent']['properties.desired']['systemModules']['edgeHub']['settings']['env']['https_proxy'] = { 'value': ProxyUrl }
                # configure EdgeAgent to use proxy
                if not 'env' in deploymentContent['content']['modulesContent']['$edgeAgent']['properties.desired']['systemModules']['edgeAgent']['settings']:
                    deploymentContent['content']['modulesContent']['$edgeAgent']['properties.desired']['systemModules']['edgeAgent']['settings']['env'] = {} 
                if not 'https_proxy' in deploymentContent['content']['modulesContent']['$edgeAgent']['properties.desired']['systemModules']['edgeAgent']['settings']['env']:
                    deploymentContent['content']['modulesContent']['$edgeAgent']['properties.desired']['systemModules']['edgeAgent']['settings']['env']['https_proxy'] = {}
                deploymentContent['content']['modulesContent']['$edgeAgent']['properties.desired']['systemModules']['edgeAgent']['settings']['env']['https_proxy'] = { 'value': ProxyUrl }
            # configure EdgeHub for requested upstream protocol
            if _args.upstreamprotocol != 'Amqp':
                if not 'UpstreamProtocol' in deploymentContent['content']['modulesContent']['$edgeAgent']['properties.desired']['systemModules']['edgeAgent']['settings']['env']:
                    deploymentContent['content']['modulesContent']['$edgeAgent']['properties.desired']['systemModules']['edgeAgent']['settings']['env']['UpstreamProtocol'] = {}
                deploymentContent['content']['modulesContent']['$edgeAgent']['properties.desired']['systemModules']['edgeAgent']['settings']['env']['UpstreamProtocol'] = { 'value': _args.upstreamprotocol }
            # configure IIoT Edge modules config
            deploymentContent['content']['modulesContent']['$edgeAgent']['properties.desired']['modules'] = modulesConfig
            # set default properties for twin
            if twinService:
                deploymentContent['content']['modulesContent']['twin-{0}'.format(siteName)] = { 'properties.desired': {} }
                deploymentContent['content']['modulesContent']['twin-{0}'.format(siteName)]['properties.desired'] = { 'Discovery': "Scan" }
            # todo add scanner configuration from file
            json.dump(deploymentContent, deploymentContentFile, indent=4)
        # todo enable when bool is supported for target condition
        #cmd = 'az iot edge deployment create --config-id {0} --hub-name {1}  --content {2}/{0}.json --target-condition "tags.iiot=true and tags.site=\'{3}\'"'.format(deploymentName, _args.iothubname, _args.outdir, siteName)
        cmd = "az iot edge deployment create --config-id {0} --hub-name {1}  --content {2}/{0}.json --target-condition \"tags.iiot=\'true\' and tags.site=\'{3}\'\"".format(deploymentName, _args.iothubname, _args.outdir, siteName)
        deploymentCreateResult = os.popen(cmd).read()
        if not deploymentCreateResult:
            logging.critical("Can not create deployment. Exiting...")
            sys.exit(1)
        logging.debug(json.dumps(json.loads(deploymentCreateResult), indent=4))
    
    #
    # create an IoTHub device identity for the edge device and set tags
    #
    deviceId = 'iiot-edge-{0}'.format(siteName)
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
        # tags = {"iiot": True, "site": sitename }
        tags = {"iiot": "true", "site": siteName }
        tagsJson = json.dumps(tags)
        # todo need to fix escape and strings for Linux
        tagsJsonOs = tagsJson.replace('\"', '\\"').replace(' ', '')
        cmd = "az iot hub device-twin update --hub-name {0} --device-id {1} --set tags={2}".format(_args.iothubname, deviceId, tagsJsonOs)
        updateTagsResult = os.popen(cmd).read()
        if not updateTagsResult:
            logging.critical("Can not set tags for device. Exiting...")
            sys.exit(1)
        logging.debug(json.dumps(json.loads(updateTagsResult), indent=4))

    #
    # fetch edge device connection string
    #
    logging.info("Fetch connection string for device '{0}'".format(deviceId))
    cmd = "az iot hub device-identity show-connection-string --hub-name {0} --device-id {1}".format(_args.iothubname, deviceId)
    connectionStringResult = os.popen(cmd).read()
    if not connectionStringResult:
        logging.critical("Can not read connection string for device. Exiting...")
        sys.exit(1)
    connectionStringJson = json.loads(connectionStringResult)
    logging.debug(json.dumps(connectionStringJson, indent=4))
    edgeDeviceConnectionString = connectionStringJson['cs']

    #
    # create script commands to start/stop IoT Edge
    #
    if _targetPlatform == 'windows':
        startCmd = "Start-Service iotedge"
        _startScript.append(startCmd + '\n')
        stopCmd = "Stop-Service iotedge"
        _stopScript.append(stopCmd + '\n')

    #
    # create setup scripts
    #
    # patch the init template to create a docker compose configuration
    ymlFileName = '{0}-edge-init.yml'.format(siteName)
    ymlOutFileName = '{0}/{1}'.format(_args.outdir, ymlFileName)
    with open('{0}/site-edge-init.yml'.format(_scriptDir), 'r') as setupTemplate, open(ymlOutFileName, 'w+', newline=_targetNewline) as setupOutFile:
            for line in setupTemplate:
                line = line.replace('${OPCPROXY_CONTAINER}', _opcProxyContainer)
                line = line.replace('${IOTHUB_CONNECTIONSTRING}', _iotHubOwnerConnectionString)
                line = line.replace('${SITE}', siteName)
                line = line.replace('${BINDSOURCE}', _dockerBindSource)
                setupOutFile.write(line)

    # generate our setup script
    # todo add registry credential
    # todo use CA signed cert
    initCmd = "docker volume create {0}_cfappdata".format(siteName)
    _initScript.append(initCmd + '\n')
    initCmd = "docker pull {0}".format(_opcProxyContainer)
    _initScript.append(initCmd + '\n')
    initCmd = "docker-compose -p {0} -f {1} up".format(siteName, ymlFileName)
    _initScript.append(_initScriptCmdPrefix + initCmd + _initScriptCmdPostfix + '\n')
    initCmd = "docker-compose -p {0} -f {1} down".format(siteName, ymlFileName)
    _initScript.append(_initScriptCmdPrefix + initCmd + _initScriptCmdPostfix + '\n')
    if _targetPlatform == 'windows':
        initCmd = '. ./Init-IotEdgeService.ps1 -DeviceConnectionString "{0}" -ContainerOs {1} '.format(edgeDeviceConnectionString, _containerOs)
        if _args.proxyhost:
            if _args.proxyport:
                initCmd = initCmd + ' -Proxy "{0}://{1}:{2}" '.format(_args.proxyschema, _args.proxyhost, _args.proxyport)
            else:
                initCmd = initCmd + ' -Proxy "{0}://{1}" '.format(_args.proxyschema, _args.proxyhost)
            if _args.proxyusername:
                initCmd = initCmd + " -ProxyUsername {0} ".format(_args.proxyusername)               
            if _args.proxypassword:
                initCmd = initCmd + " -ProxyPassword {0} ".format(_args.proxypassword)               
        # todo for extended offline mqtt support is required
        if _args.upstreamprotocol != 'Ampq':
            initCmd = initCmd + " -UpstreamProtocol {0} ".format(_args.upstreamprotocol)               
        _initScript.append(_initScriptCmdPrefix + initCmd + _initScriptCmdPostfix + '\n')
        deinitCmd = ". ./Deinit-IotEdgeService.ps1"
        _deinitScript.append(_deinitScriptCmdPrefix + deinitCmd + _deinitScriptCmdPostfix + '\n')
    else:
        # todo adjust to v1
        initCmd = 'iotedgectl setup --connection-string "{0}" --auto-cert-gen-force-no-passwords {1}'.format(edgeDeviceConnectionString, '--runtime-log-level debug' if (_args.loglevel.lower() == 'debug') else '')
        _initScript.append(_initScriptCmdPrefix + initCmd + _initScriptCmdPostfix + '\n')
    # deinit commands are written in reversed order
    deinitCmd = "docker volume rm {0}_cfappdata".format(siteName)
    _deinitScript.append(_deinitScriptCmdPrefix + deinitCmd + _deinitScriptCmdPostfix + '\n')

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

# CPU specific settings
if 'intel64' in str(platform.processor()).lower():
    _platformCpu = 'amd64'
else:
    _platformCpu = 'arm32v7'

#
# OS specific settings
#
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
    _startScriptFileName = 'start-iiotedge.sh'
    _startScriptCmdPrefix = ''
    _startScriptCmdPostfix = ' &'
    _stopScriptFileName = 'stop-iiotedge.sh'
    _stopScriptCmdPrefix = ''
    _stopScriptCmdPostfix = ''
    _initScriptFileName = 'init-iiotedge.sh'
    _initScriptCmdPrefix = ''
    _initScriptCmdPostfix = ' &'
    _deinitScriptFileName = 'deinit-iiotedge.sh'
    _deinitScriptCmdPrefix = ''
    _deinitScriptCmdPostfix = ' &'
    _targetNewline = '\n'
elif _targetPlatform == 'windows':
    _startScriptFileName = 'Start-IIoTEdge.ps1'
    _startScriptCmdPrefix = 'start '
    _startScriptCmdPostfix = ''
    _stopScriptFileName = 'Stop-IIoTEdge.ps1'
    _stopScriptCmdPrefix = ''
    _stopScriptCmdPostfix = ''
    _initScriptFileName = 'Init-IIoTEdge.ps1'
    _initScriptCmdPrefix = ''
    _initScriptCmdPostfix = ''
    _deinitScriptFileName = 'Deinit-IIoTEdge.ps1'
    _deinitScriptCmdPrefix = ''
    _deinitScriptCmdPostfix = ''
    _targetNewline = '\r\n'

#
# validate common arguments
#
if _args.lcow:
    if _targetPlatform == 'windows':
        _containerOs = 'linux'
    else:
        logging.fatal("-lcow is only allowed for a Winodws target")
        sys.exit(1)
else:
    _containerOs = _targetPlatform if _targetPlatform != 'wsl' else 'linux'

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
    # and need to be transfered manually to the IoT Edge device.
    _dockerBindSource = _args.hostdir = _args.hostdir.strip().replace('\\', '/')
    # The Docker for Windows volume bind syntax has changed over time.
    # With docker ce 18.03.0-ce-win59 (16762), engine 18.03.0-ce the bind syntax for D:/docker needs to be //d/docker

    if _targetPlatform in [ 'windows', 'wsl']:
        # we accept only fully qualified windows syntax (starts with <drive>:)
        if _args.hostdir[1:3] != ':/':
            logging.fatal("The --hostdir parameter must be using a fully qualified Windows directory syntax.")
            sys.exit(1)
    elif _targetPlatform == 'linux':
        if _args.hostdir[0:1] != '/':
            logging.fatal("The --hostdir parameter must be using a fully qualified Linux directory syntax.")
            sys.exit(1)
    else:
        logging.fatal("Target platform '{0}' is not supported.".format(_targetPlatform))
        sys.exit(1)

    if _args.targetplatform:
        # create a directory for the configuration files, if not running on the IoT Edge device
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
        logging.info("--targetplatform was not specified. Assume we run on the IoT Edge device.")
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
    # todo verify correct handling with sites
    _dockerBindSource = 'cfappdata'
    logging.info("Passing '{0}' (docker volume) to docker as source in bind.".format(_dockerBindSource))

if _args.dockerregistry is None:
    _args.dockerregistry = 'microsoft'
else:
    _args.dockerregistry = _args.dockerregistry.strip().lower()
    logging.info("Docker container registry to use: '{0}'".format(_args.dockerregistry))

#
# build container names
#
_opcProxyContainer = OPCPROXY_CONTAINER_IMAGE if '/' in OPCPROXY_CONTAINER_IMAGE else '{0}/{1}'.format(_args.dockerregistry, OPCPROXY_CONTAINER_IMAGE)
_opcProxyContainer = '{0}:'.format(_opcProxyContainer) if not OPCPROXY_CONTAINER_VERSION else '{0}:{1}-'.format(_opcProxyContainer, OPCPROXY_CONTAINER_VERSION)
_opcProxyContainer = '{0}{1}'.format(_opcProxyContainer, 'windows') if _containerOs == 'windows' else '{0}{1}'.format(_opcProxyContainer, 'linux')
_opcProxyContainer = '{0}-{1}'.format(_opcProxyContainer, 'amd64') if _platformCpu == 'amd64' else '{0}-{1}'.format(_opcProxyContainer, 'arm32v7')
_opcTwinContainer = OPCTWIN_CONTAINER_IMAGE if '/' in OPCTWIN_CONTAINER_IMAGE else '{0}/{1}'.format(_args.dockerregistry, OPCTWIN_CONTAINER_IMAGE)
_opcTwinContainer = '{0}:'.format(_opcTwinContainer) if not OPCTWIN_CONTAINER_VERSION else '{0}:{1}-'.format(_opcTwinContainer, OPCTWIN_CONTAINER_VERSION)
_opcTwinContainer = '{0}{1}'.format(_opcTwinContainer, 'windows') if _containerOs == 'windows' else '{0}{1}'.format(_opcTwinContainer, 'linux')
_opcTwinContainer = '{0}-{1}'.format(_opcTwinContainer, 'amd64') if _platformCpu == 'amd64' else '{0}{1}'.format(_opcTwinContainer, 'arm32v7')
_opcPublisherContainer = OPCPUBLISHER_CONTAINER_IMAGE if '/' in OPCPUBLISHER_CONTAINER_IMAGE else '{0}/{1}'.format(_args.dockerregistry, OPCPUBLISHER_CONTAINER_IMAGE)
_opcPublisherContainer = '{0}:'.format(_opcPublisherContainer) if not OPCPUBLISHER_CONTAINER_VERSION else '{0}:{1}-'.format(_opcPublisherContainer, OPCPUBLISHER_CONTAINER_VERSION)
_opcPublisherContainer = '{0}{1}'.format(_opcPublisherContainer, 'windows') if _containerOs == 'windows' else '{0}{1}'.format(_opcPublisherContainer, 'linux')
_opcPublisherContainer = '{0}-{1}'.format(_opcPublisherContainer, 'amd64') if _platformCpu == 'amd64' else '{0}-{1}'.format(_opcPublisherContainer, 'arm32v7')
_opcPlcContainer = OPCPLC_CONTAINER_IMAGE if '/' in OPCPLC_CONTAINER_IMAGE else '{0}/{1}'.format(_args.dockerregistry, OPCPLC_CONTAINER_IMAGE)
_opcPlcContainer = '{0}:'.format(_opcPlcContainer) if not OPCPLC_CONTAINER_VERSION else '{0}:{1}-'.format(_opcPlcContainer, OPCPLC_CONTAINER_VERSION)
_opcPlcContainer = '{0}{1}'.format(_opcPlcContainer, 'windows') if _containerOs == 'windows' else '{0}{1}'.format(_opcPlcContainer, 'linux')
_opcPlcContainer = '{0}-{1}'.format(_opcPlcContainer, 'amd64') if _platformCpu == 'amd64' else '{0}{1}'.format(_opcPlcContainer, 'arm32v7')

logging.info("Using OpcPublisher container: '{0}'".format(_opcPublisherContainer))
logging.info("Using OpcProxy container: '{0}'".format(_opcProxyContainer))
logging.info("Using OpcTwin container: '{0}'".format(_opcTwinContainer))
logging.info("Using OpcPlc container: '{0}'".format(_opcPlcContainer))

#
# azure authentication
#
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

#
# validate all required parameters for gw subcommand
#
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
    _args.site = _args.site.lower() 
    _edgeSite = _args.site

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
# gw operation: create all scripts to (de)init and start/stop the site specified on the command line
# - copy the configuration files
# - create an IoT Edge device and deployment for the site and all OPC components are configured to run as IoT Edge modules
#
if _args.subcommand == 'gw':
    # login to Azure and fetch IoTHub connection string
    azureLogin()
    azureGetIotHubCs()
    # copy configuration files to the right directory if we are running on the target, otherwise copy it to the config file directory
    if _args.targetplatform:
        if _args.nodesconfig:
            nodesconfigFileName = 'pn-' + _args.site + '.json'
            shutil.copyfile(_args.nodesconfig, '{0}/{1}'.format(_outdirConfig, nodesconfigFileName))
        try:
            if _args.telemetryconfig:
                telemetryconfigFileName = 'tc-' + _args.site + '.json'
                shutil.copyfile(_args.telemetryconfig, '{0}/{1}'.format(_outdirConfig, telemetryconfigFileName))
        except AttributeError:
            pass
    else:
        if _args.nodesconfig:
            nodesconfigFileName = 'pn-' + _args.site + '.json'
            shutil.copyfile(_args.nodesconfig, '{0}/{1}'.format(_hostDirHost, nodesconfigFileName))
        if _args.telemetryconfig:
            telemetryconfigFileName = 'tc-' + _args.site + '.json'
            shutil.copyfile(_args.telemetryconfig, '{0}/{1}'.format(_hostDirHost, telemetryconfigFileName))
    # create site/factory scripts
    logging.info("Create the site initialization and configuration for '{0}'".format(_args.site))
    createEdgeSiteConfiguration(_args.site)


# optional: sleep to debug initialization script issues
# _initScript.append('timeout 60\n')

# write the scripts
writeScript(_startScriptFileName, _startScript)
writeScript(_stopScriptFileName, _stopScript, reverse = True)
writeScript(_initScriptFileName, _initScript)
writeScript(_deinitScriptFileName, _deinitScript, reverse = True)

# todo patch config.yaml if proxy is used
# copy prerequisites installation scripts
if _args.targetplatform:
    if _args.targetplatform in [ 'windows' ]:
        shutil.copyfile('{0}/Init-IotEdgeService.ps1'.format(_scriptDir), '{0}/Init-IotEdgeService.ps1'.format(_args.outdir))
        shutil.copyfile('{0}/Deinit-IotEdgeService.ps1'.format(_scriptDir), '{0}/Deinit-IotEdgeService.ps1'.format(_args.outdir))
        shutil.copyfile('{0}Prepare-IIotHost.ps1'.format(_scriptDir), '{0}/Prepare-IIotHost.ps1'.format(_args.outdir))
    if _args.targetplatform in [ 'linux', 'wsl' ]:
        shutil.copyfile('{0}/iiotedge-install-prerequisites.sh'.format(_scriptDir), '{0}/iiotedge-install-prerequisites.sh'.format(_args.outdir))
        shutil.copyfile('{0}/iiotedge-install-linux-packages.sh'.format(_scriptDir), '{0}/iiotedge-install-linux-packages.sh'.format(_args.outdir))
    shutil.copyfile('{0}/requirements.txt'.format(_scriptDir), '{0}/requirements.txt'.format(_args.outdir))
    # inform user when not running on target platform
    logging.info('')
    logging.info("Please copy any required script files from '{0}' to your target system.".format(_args.outdir))
    if _args.hostdir:
        logging.info("Please copy any required configuration files from '{0}' to your target system to directory '{1}'.".format(_outdirConfig, _args.hostdir))
elif _targetPlatform == 'windows':
        shutil.copyfile('{0}/Init-IotEdgeService.ps1'.format(_scriptDir), '{0}/Init-IotEdgeService.ps1'.format(_args.outdir))
        shutil.copyfile('{0}/Deinit-IotEdgeService.ps1'.format(_scriptDir), '{0}/Deinit-IotEdgeService.ps1'.format(_args.outdir))
        shutil.copyfile('{0}/Prepare-WindowsGatewayStep1.ps1'.format(_scriptDir), '{0}/Prepare-WindowsGatewayStep1.ps1'.format(_args.outdir))
        shutil.copyfile('{0}/Prepare-WindowsGatewayStep2.ps1'.format(_scriptDir), '{0}/Prepare-WindowsGatewayStep2.ps1'.format(_args.outdir))

# done
logging.info('')
if _args.targetplatform:
    logging.info("The generated script files can be found in: '{0}'. Please copy them to your target system.".format(_args.outdir))
else:
    logging.info("The generated script files can be found in: '{0}'".format(_args.outdir))
logging.info('')
logging.info("Operation completed.")


