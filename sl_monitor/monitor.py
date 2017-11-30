"""Deployment Monitor Module."""
from time import sleep

import json
import logging
import logzero
from logzero import logger
import re
from sqlitedict import SqliteDict

from sl_monitor.common import ApplicationConfig
from sl_monitor.hardware import get_all_servers
from sl_monitor.hardware import execute_post_install_script


transaction_group_re = re.compile(r'(.*reload.*)|(.*provision.*)', re.IGNORECASE)


def run(config_path):
    logger.info('Loading config %s' % config_path)
    ApplicationConfig.load_config(config_path)
    configure_logger()
    logger.info('Starting main program loop')
    program_loop()
    logger.info('Program loop ended')


def program_loop():
    """
    Primary program loop
    """
    with get_datadict('hw_monitor') as hw_dict:
        while(True):
            logger.debug('Checking for work')
            check_for_hardware_changes(hw_dict)
            logger.debug('Processing hardware')
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
    logzero.logfile(ApplicationConfig.get("environment", "log_location"), 
                    maxBytes=5e6, 
                    backupCount=5,
                    loglevel=logging.INFO,)


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
        logger.debug('Checking for new hardware')
        global_identifiers = [server['globalIdentifier'] for server in hw_dict['all_hardware']]
        all_hardware = hw_dict['all_hardware']
        unprocessed_hardware = hw_dict['unprocessed_hardware']
        for server in hardware_objects:
            if server['globalIdentifier'] not in global_identifiers:
                # server new to account
                logger.info("Adding in server %s (%s) to watch.", (server['hostname'], server['globalIdentifier']))
                all_hardware.append(server)
                unprocessed_hardware[server['globalIdentifier']] = server
            else:
                # check if hardware is in same state as previously checked
                hardware_index = global_identifiers.index(server['globalIdentifier'])

                cached_server = hw_dict['all_hardware'][hardware_index]
                if server['lastTransaction']['id'] != cached_server['lastTransaction']['id']:
                    logger.info("Server %s (%s) - has a new transaction (changed from '%s' (%s) to '%s' (%s))", 
                                server['hostname'],
                                server['globalIdentifier'],
                                cached_server['lastTransaction']['transactionGroup']['name'],
                                cached_server['lastTransaction']['id'],
                                server['lastTransaction']['transactionGroup']['name'],
                                server['lastTransaction']['id'],)

                    all_hardware[hardware_index] = server
                    if is_os_install_transaction(server['lastTransaction']):
                        unprocessed_hardware[server['globalIdentifier']] = server
                elif server['lastTransaction']['transactionStatus']['name'] != cached_server['lastTransaction']['transactionStatus']['name']:
                    # transaction has updated
                    logger.info("Server %s (%s) - has an updated transaction (changed from '%s' to '%s')", 
                                server['hostname'],
                                server['globalIdentifier'],
                                cached_server['lastTransaction']['transactionStatus']['name'],
                                server['lastTransaction']['transactionStatus']['name'],)

                    all_hardware[hardware_index] = server
                    if is_os_install_transaction(server['lastTransaction']):
                        unprocessed_hardware[server['globalIdentifier']] = server
        
        hw_dict['all_hardware'] = all_hardware
        hw_dict['unprocessed_hardware'] = unprocessed_hardware
        hw_dict.commit()


def is_os_install_transaction(transaction):
    """
    Checks if the current transaction is one which needs to be acted upon
    """
    return bool(transaction_group_re.match(transaction['transactionGroup']['name']))


def process_hardware(hw_dict):
    unprocessed_hardware = hw_dict['unprocessed_hardware']
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

        try: 
            execute_post_install_script(server['id'])
        except Exception as err:
            logger.error(err, exc_info=True)
            logger.error("Script error occurred, skipping device.")


        # once complete remove from unprocessed
        logger.info("Removing %s (%s) from unprocessed hardware",
                    server['hostname'],
                    globalIdentifier)
        del unprocessed_hardware[globalIdentifier]
    
    hw_dict['unprocessed_hardware'] = unprocessed_hardware
    hw_dict.commit()
