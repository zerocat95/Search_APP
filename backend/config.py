import configparser
import os

class Config:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(Config, cls).__new__(cls)
        return cls._instance

    def __init__(self, config_file='sa_config.cfg'):
        if not hasattr(self, 'initialized'):
            self.config = configparser.ConfigParser()
            self.config.read(config_file)
            self.initialized = True

    def get(self, key, section='database'):
        value = self.config.get(section, key, fallback=None)
        if value and ('PATH' in key or 'DIR' in key):
            # Expand user home directory symbol '~'
            return os.path.expanduser(value)
        return value

config = Config()