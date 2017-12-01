"""Virtual Guest Module."""
from sl_monitor.common import ApiClient


def get_all_servers():
    """
    Calls SLAPI to get virtual guests
    """
    mask = '''
id,
globalIdentifier,
hostname,
lastTransaction[
    id,
    createDate,
    statusChangeDate,
    elapsedSeconds,
    transactionStatus.name,
    transactionGroup.name
]
'''
    
    devices = ApiClient().get('Account').getVirtualGuests(iter=True,
                                                          chunk=500,
                                                          mask=mask)

    for device in devices:
        if 'globalIdentifier' in device:
            yield device
