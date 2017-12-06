"""Deployment Monitor Module."""
from time import sleep

import json
import logging
import logzero
from logzero import logger
import re
from sqlitedict import SqliteDict

from sl_monitor.common import ApplicationConfig
from sl_monitor.device import execute_post_install_script
from sl_monitor import hardware
from sl_monitor import virtual


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
    with get_datadict('device_monitor') as device_dict:
        while True:
            logger.debug('Checking for work')
            check_for_all_device_changes(device_dict)
            logger.debug('Processing devices')
            process_all_devices(device_dict)

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


def check_for_all_device_changes(device_dict):
    """
    
    """
    if ApplicationConfig.getboolean("environment", "monitor_hardware"):
        check_for_device_changes(device_dict, 'all_hardware', 'unprocessed_hardware', hardware)
    else:
        logger.debug('Ignoring hardware changes (per config)')

    if ApplicationConfig.getboolean("environment", "monitor_virtual"):
        check_for_device_changes(device_dict, 'all_virtual', 'unprocessed_virtual', virtual)
    else:
        logger.debug('Ignoring virtual changes (per config)')

def check_for_device_changes(device_dict, device_key, unprocessed_key, api_object):
    """
    Checks available devices for changes
    """
    device_type = api_object.api_type
    if device_key not in device_dict:
        logger.info('First Run, adding %s', device_type)
        # populate cached devices
        device_dict[device_key] = list(api_object.get_all_servers())

        logger.debug('Checking for unprocessed %s', device_type)
        prepopulate_unprocessed_devices(device_dict, device_key, unprocessed_key)
    else:
        logger.debug('Checking for changed %s', device_type)
        add_devices_for_changes(api_object.get_all_servers(), 
                                device_dict, 
                                device_key, 
                                unprocessed_key)
    device_dict.commit()


def prepopulate_unprocessed_devices(device_dict, device_key, unprocessed_key):
    unprocessed_dict = {}
    for server in device_dict[device_key]:
        if server['lastTransaction']['transactionStatus']['name'] != 'COMPLETE':
            if is_os_install_transaction(server['lastTransaction']):
                logger.debug("Watching %s (%s) on %s", 
                             server['hostname'], 
                             server['globalIdentifier'],
                             server['lastTransaction']['transactionGroup']['name'])
                unprocessed_dict[server['globalIdentifier']] = server
    device_dict[unprocessed_key] = unprocessed_dict


def add_devices_for_changes(device_list, device_dict, device_key, unprocessed_key):
    global_identifiers = [server['globalIdentifier'] for server in device_dict[device_key]]
    all_devices = device_dict[device_key]
    unprocessed_devices = device_dict[unprocessed_key]
    for server in device_list:
        if server['globalIdentifier'] not in global_identifiers:
            # server new to account
            logger.info("Adding in server %s (%s) to watch.", (server['hostname'], server['globalIdentifier']))
            all_devices.append(server)
            unprocessed_devices[server['globalIdentifier']] = server
        else:
            # check if hardware is in same state as previously checked
            device_index = global_identifiers.index(server['globalIdentifier'])

            cached_server = device_dict[device_key][device_index]
            if server['lastTransaction']['id'] != cached_server['lastTransaction']['id']:
                logger.info("Server %s (%s) - has a new transaction (changed from '%s' (%s) to '%s' (%s))", 
                            server['hostname'],
                            server['globalIdentifier'],
                            cached_server['lastTransaction']['transactionGroup']['name'],
                            cached_server['lastTransaction']['id'],
                            server['lastTransaction']['transactionGroup']['name'],
                            server['lastTransaction']['id'],)

                all_devices[device_index] = server
                if is_os_install_transaction(server['lastTransaction']):
                    unprocessed_devices[server['globalIdentifier']] = server
            elif server['lastTransaction']['transactionStatus']['name'] != cached_server['lastTransaction']['transactionStatus']['name']:
                # transaction has updated
                logger.info("Server %s (%s) - has an updated transaction (changed from '%s' to '%s')", 
                            server['hostname'],
                            server['globalIdentifier'],
                            cached_server['lastTransaction']['transactionStatus']['name'],
                            server['lastTransaction']['transactionStatus']['name'],)

                all_devices[device_index] = server
                if is_os_install_transaction(server['lastTransaction']):
                    unprocessed_devices[server['globalIdentifier']] = server

    device_dict[device_key] = all_devices
    device_dict[unprocessed_key] = unprocessed_devices


def is_os_install_transaction(transaction):
    """
    Checks if the current transaction is one which needs to be acted upon
    """
    return bool(transaction_group_re.match(transaction['transactionGroup']['name']))


def process_all_devices(device_dict):
    logger.debug("%s unprocessed hardware, %s unprocessed virtual",
                len(device_dict['unprocessed_hardware']),
                len(device_dict['unprocessed_virtual']))

    if ApplicationConfig.getboolean("environment", "monitor_hardware"):
        process_devices(device_dict, 'unprocessed_hardware', 'Hardware')
    
    if ApplicationConfig.getboolean("environment", "monitor_virtual"):
        process_devices(device_dict, 'unprocessed_virtual', 'Virtual_Guest')


def process_devices(device_dict, unprocessed_key, device_type):
    logger.debug("Processing %s", device_type)
    unprocessed_devices = device_dict[unprocessed_key]
    for globalIdentifier, server in device_dict[unprocessed_key].items():
        # do not act on hardware with active transactions
        if server['lastTransaction']['transactionStatus']['name'] != 'COMPLETE':
            logger.info("Skipping %s %s (%s) as it still has an active transaction",
                device_type,
                server['hostname'],
                globalIdentifier)
            continue

        logger.info("Logging into %s (%s) to run script",
                    server['hostname'],
                    globalIdentifier)

        try: 
            execute_post_install_script(server['id'], device_type)
        except Exception as err:
            logger.error(err, exc_info=True)
            logger.error("Script error occurred, skipping device.")

        # once complete remove from unprocessed
        logger.info("Removing %s (%s) from unprocessed %s",
                    server['hostname'],
                    globalIdentifier,
                    device_type)
        del unprocessed_devices[globalIdentifier]
    
    device_dict[unprocessed_key] = unprocessed_devices
    device_dict.commit()
