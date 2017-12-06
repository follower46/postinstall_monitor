"""Deployment Monitor Module."""
from time import sleep

import json
import logzero
from logzero import logger
import paramiko
from sqlitedict import SqliteDict

from sl_monitor.common import ApplicationConfig
from sl_monitor.common import ApiClient


def get_all_servers():
    """
    Calls SLAPI to get hardware
    """
    mask = '''
id,
globalIdentifier,
hostname,
hardwareStatus[
    status
],
lastTransaction[
    id,
    createDate,
    statusChangeDate,
    elapsedSeconds,
    transactionStatus.name,
    transactionGroup.name
]
'''
    _filter = {
        'hardwareChassis': {'hardwareFunction': {'code': {'operation': 'WEBSVR'}}},
        'hardwareStatus': {'status': {'operation': 'ACTIVE'}},
    }
    
    devices = ApiClient().get('Account').getHardware(iter=True,
                                                     chunk=500,
                                                     mask=mask,
                                                     filter=_filter)

    for device in devices:
        if 'globalIdentifier' in device:
            yield device


def execute_post_install_script(device_id):
    """
    Downloads and executes post install script on a device
    """
    login_info = get_device_login_credentials(device_id)
    logger.info("SSHing into %s with user '%s'", 
                login_info['ip_address'], 
                login_info['username'])

    ssh_stdin, ssh_stdout, ssh_stderr = run_script(
        ApplicationConfig.get("post_install_scripts", "default_url"), 
        login_info
    )

    return (ssh_stdin, ssh_stdout, ssh_stderr)


def get_device_login_credentials(device_id):
    """
    Gets SSH information via the SLAPI
    """
    mask = '''
id,
globalIdentifier,
hostname,
primaryIpAddress,
primaryBackendIpAddress,
operatingSystemReferenceCode,
operatingSystem[
    passwords[
        username,
        password
    ]
]
'''
    
    device = ApiClient().get('Hardware').getObject(mask=mask, id=device_id)
    root_users = [user for user in device['operatingSystem']['passwords'] if user['username'] == 'root']

    if not root_users:
        return {}

    ip_address = device['primaryBackendIpAddress']
    if not ApplicationConfig.getboolean("environment", "use_private_network"):
        ip_address = device['primaryIpAddress']
    return {
        'username': root_users[0]['username'],
        'password': root_users[0]['password'],
        'ip_address': ip_address
    }

def run_script(url, login_dict):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(login_dict['ip_address'], 
                username=login_dict['username'], 
                password=login_dict['password'])

    logger.info("Building script command for %s", url)

    commands = [
        # Generate a random filename.
        'export PI=$(mktemp post_install.XXXX)',

        # Download the script using headers from the order.
        "wget --retry-connrefused --tries=%s --waitretry=%s --read-timeout=%s --timeout=%s --no-check-certificate -O $PI \"%s\" 2>&1" % (
            ApplicationConfig.get("post_install_scripts", "retries"),
            ApplicationConfig.get("post_install_scripts", "wait_period"),
            ApplicationConfig.get("post_install_scripts", "timeout"),
            ApplicationConfig.get("post_install_scripts", "timeout"),
            url),

        # Make the downloaded script executable.
        'chmod +x $PI',

        # Execute the remote script.
        './$PI 2>&1',
    ]

    if ApplicationConfig.getboolean("post_install_scripts", "nohup"):
        # Wrap all commands in a single nohup and log all output to syslog with the tag post_install
        fullCommand = "nohup sh -c " + escapeshellarg("&&".join(commands)) + " 2>&1 | logger -i -t post_install -p info &"
    else:
        fullCommand = escapeshellarg("&&".join(commands)) + " | logger -i -t post_install -p info"

    logger.info("Running Remote Command on %s", login_dict['ip_address'])
    logger.debug(fullCommand)
    ssh_stdin, ssh_stdout, ssh_stderr = ssh.exec_command(fullCommand)
    logger.info("Remote Command sent")

    return (ssh_stdin, ssh_stdout, ssh_stderr)


def escapeshellarg(arg):
    return "\\'".join("'" + p + "'" for p in arg.split("'"))
