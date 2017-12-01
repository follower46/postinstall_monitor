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
