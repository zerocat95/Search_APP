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
            
            # Prioritize config from ~/.search_app/
            app_data_dir = os.path.expanduser("~/.search_app")
            user_config_path = os.path.join(app_data_dir, 'sa_config.cfg')

            if os.path.exists(user_config_path):
                self.config.read(user_config_path)
            else:
                # Fallback to the default config_file (e.g., from project root)
                self.config.read(config_file)
            
            self.initialized = True

    def get(self, key, section='database'):
        value = self.config.get(section, key, fallback=None)
        if value and ('PATH' in key or 'DIR' in key):
            # Expand user home directory symbol '~'
            return os.path.expanduser(value)
        return value

config = Config()