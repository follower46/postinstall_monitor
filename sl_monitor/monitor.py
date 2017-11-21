"""Deployment Monitor Module."""
from time import sleep

import json
import logzero
from logzero import logger
from sqlitedict import SqliteDict

from common import ApplicationConfig
from common import ApiClient

def program_loop():
    """
    Primary program loop
    """
    with get_datadict('hw_monitor') as hw_dict:
        """
        mydict['some_key'] = "first value"
        mydict['another_key'] = list(range(10))
        mydict.commit()
        """

        while(True):
            logger.debug('Checking for work')
            check_for_hardware_changes(hw_dict)
            process_hardware(hw_dict)

            # wait
            logger.debug('Sleeping')
            sleep(int(ApplicationConfig.get("environment", "poll_rate")))


def configure_logger():
    """
    Logging was updated to give time values with milliseconds
    """
    log_format = '%(color)s[%(levelname)1.1s ' \
                 '%(asctime)s.%(msecs)03d %(module)s:%(lineno)d]' \
                 '%(end_color)s %(message)s'
    formatter = logzero.LogFormatter(fmt=log_format)
    logzero.setup_default_logger(formatter=formatter)
    logzero.logfile("monitor.log") # this needs to be updated to roll the log


def get_datadict(name):
    """
    Returns sqlite connection via sqlitedict
    """
    return SqliteDict(ApplicationConfig.get("environment", "db"), 
                      tablename=name,
                      encode=json.dumps, 
                      decode=json.loads)


def check_for_hardware_changes(hw_dict):
    """
    Checks available hardware for changes
    """
    hardware_objects = get_all_servers()

    if 'all_hardware' not in hw_dict:
        logger.info('First Run, adding hardware')
        # populate cached hardware
        hw_dict['all_hardware'] = list(hardware_objects)

        # do not run against completed hardware on first start
        hw_dict['unprocessed_hardware'] = {}
        for server in hw_dict['all_hardware']:
            if server['lastTransaction']['transactionStatus']['name'] != 'COMPLETE':
                hw_dict['unprocessed_hardware'][server['globalIdentifier']] = server
        hw_dict.commit()
    else:
        logger.info('Checking for new hardware')
        global_identifiers = [server['globalIdentifier'] for server in hw_dict['all_hardware']]
        for server in hardware_objects:
            if server['globalIdentifier'] not in global_identifiers:
                # server new to account
                logger.info("Adding in server %s (%s) to watch.", (server['hostname'], server['globalIdentifier']))
                hw_dict['all_hardware'].append(server)
                hw_dict['unprocessed_hardware'][server['globalIdentifier']] = server
                hw_dict.commit()
            else:
                # check if hardware is in same state as previously checked
                cached_server = hw_dict['all_hardware'][global_identifiers.index(server['globalIdentifier'])]
                if server['lastTransaction']['id'] != cached_server['lastTransaction']['id']:
                    logger.info("Server %s (%s) has a new transaction (changed from %s(%s) to %s(%s)", 
                                server['hostname'],
                                server['globalIdentifier'],
                                server['lastTransaction']['transactionGroup'],
                                server['lastTransaction']['id'],
                                server['lastTransaction']['transactionGroup'],
                                server['lastTransaction']['id'],)
                    hw_dict['all_hardware'][global_identifiers.index(server['globalIdentifier'])] = server
                    hw_dict['unprocessed_hardware'][server['globalIdentifier']] = server
                    hw_dict.commit()
                elif server['lastTransaction']['statusChangeDate'] != cached_server['lastTransaction']['statusChangeDate']:
                    pass


def process_hardware(hw_dict):
    for globalIdentifier, server in hw_dict['unprocessed_hardware'].items():
        # do not act on hardware with active transactions
        if server['lastTransaction']['transactionStatus']['name'] != 'COMPLETE':
            logger.info("Skipping server %s (%s) as it still has an active transaction",
                server['hostname'],
                globalIdentifier)
            continue

        logger.info("Logging into %s (%s) to run script",
                    server['hostname'],
                    globalIdentifier)

        #todo

        # once complete remove from unprocessed
        del hw_dict['unprocessed_hardware'][globalIdentifier]
        hw_dict.commit()


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


if __name__ == "__main__":
    configure_logger()
    logger.info('Starting main program loop')
    program_loop()
    logger.info('Program loop ended')