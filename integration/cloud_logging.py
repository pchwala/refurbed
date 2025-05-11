import logging
import json
import os

class JsonFormatter(logging.Formatter):
    def __init__(self, instance_id):
        super().__init__()
        self.instance_id = instance_id

    def format(self, record):
        log_obj = {
            "message": record.getMessage(),
            "severity": record.levelname,
            "instance": self.instance_id
        }
        return json.dumps(log_obj)

class CloudLogger:
    def __init__(self, instance_id="default", log_level=logging.INFO):
        self.instance_id = instance_id
        self.logger = logging.getLogger(f"cloud_logger_{instance_id}")
        self.logger.setLevel(log_level)
        
        # Only add handler if not already present
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(JsonFormatter(instance_id))
            self.logger.addHandler(handler)
    
    def get_logger(self):
        return self.logger
    
    def info(self, message):
        self.logger.info(message)
    
    def error(self, message):
        self.logger.error(message)
    
    def warning(self, message):
        self.logger.warning(message)
    
    def debug(self, message):
        self.logger.debug(message)
    
    def critical(self, message):
        self.logger.critical(message)