"""Deployment Monitor Module."""
from time import sleep

import json
import logzero
from logzero import logger
import paramiko
from sqlitedict import SqliteDict

from common import ApplicationConfig
from common import ApiClient


def get_all_servers():
    """
    Calls SLAPI to get hardware
    """
    mask = '''
id,
globalIdentifier,
hostname,
lastTransaction,
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

    if not len(root_users):
        return {}

    ip_address = device['primaryIpAddress']
    if ApplicationConfig.getboolean("environment", "use_private_network"):
        ip_address = device['primaryBackendIpAddress']
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
        "wget --no-check-certificate -O $PI \"%s\" 2>&1" % url,

        # Make the downloaded script executable.
        'chmod +x $PI',

        # Execute the remote script.
        './$PI 2>&1',
    ]

    # Wrap all commands in a single nohup and log all output to syslog with the tag post_install
    fullCommand = "nohup sh -c " + escapeshellarg("&&".join(commands)) + " 2>&1 | logger -i -t post_install -p info &"

    logger.info("Running Remote Command on %s", login_dict['ip_address'])
    logger.debug(fullCommand)
    ssh_stdin, ssh_stdout, ssh_stderr = ssh.exec_command(fullCommand)
    logger.info("Remote Command sent")

    return (ssh_stdin, ssh_stdout, ssh_stderr)


def escapeshellarg(arg):
    return "\\'".join("'" + p + "'" for p in arg.split("'"))
