"""Common SoftLayer Helper Module."""
import os.path
import configparser

import SoftLayer


class ApiClient():
    client = None

    @staticmethod
    def get_client():
        if not ApiClient.client:
            endpoint = SoftLayer.API_PUBLIC_ENDPOINT
            if ApplicationConfig.getboolean("environment", "use_private_network"):
                endpoint = SoftLayer.API_PRIVATE_ENDPOINT

            ApiClient.client = SoftLayer.Client(
                username=ApplicationConfig.get("softlayer_credentials", "username"),
                api_key=ApplicationConfig.get("softlayer_credentials", "api_key"),
                endpoint_url=endpoint
            )
        return ApiClient.client

    @staticmethod
    def get(class_name=None):
        """Return the authenticated SoftLayer client.

        Args:
            class_name (optional): A string of the section of the class to reference
        Returns:
            The string value in the application config
        """
        if class_name:
            return ApiClient.get_client()[class_name]
        return ApiClient.get_client()

class ApplicationConfig():
    config = None

    @staticmethod
    def get_config():
        if not os.path.isfile('monitor.local.cfg'):
            raise FileNotFoundError('monitor.local.cfg')

        if ApplicationConfig.config is None:
            config = configparser.ConfigParser()
            config.read('monitor.local.cfg')
            ApplicationConfig.config = config
        return ApplicationConfig.config

    @staticmethod
    def get(section, key):
        """Return the config value from a section/key.

        Args:
            section: A string of the section of the config to reference
            key: A string of the key value to return
        Returns:
            The string value in the application config
        """
        return ApplicationConfig.get_config().get(section, key)

    @staticmethod
    def getboolean(section, key):
        """Return the boolean config value from a section/key.

        Args:
            section: A string of the section of the config to reference
            key: A string of the key value to return
        Returns:
            The boolean value in the application config
        """
        return ApplicationConfig.get_config().getboolean(section, key)
