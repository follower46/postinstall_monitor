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
    ssh.connect(login_dict['ip_address'], 
                username=login_dict['username'], 
                password=login_dict['password'])

    #todo build exec command

    ssh_stdin, ssh_stdout, ssh_stderr = ssh.exec_command('wget %s' % url)
