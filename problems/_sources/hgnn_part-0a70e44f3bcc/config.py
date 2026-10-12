"""
Path configuration module - Centralized management of file paths in the project
"""
import os
from pathlib import Path

class PathConfig:
    """Path configuration class for centralized management of project file paths"""
    
    def __init__(self, base_dir=None):
        # Use current working directory as base directory by default
        if base_dir is None:
            base_dir = os.getcwd()
        
        self.BASE_DIR = Path(base_dir)
        
        # Data directory
        self.DATA_DIR = self.BASE_DIR / "data"
        
        # Models directory
        self.MODELS_DIR = self.BASE_DIR / "models"
        
        # Executable files directory
        self.EXEC_DIR = self.BASE_DIR / "exec"
        
        # Ensure necessary directories exist
        self.DATA_DIR.mkdir(exist_ok=True)
        self.MODELS_DIR.mkdir(exist_ok=True)
    
    def get_data_path(self, filename):
        """Get full path for data file"""
        return str(self.DATA_DIR / filename)
    
    def get_model_path(self, filename):
        """Get full path for model file"""
        return str(self.MODELS_DIR / filename)
    
    def get_exec_path(self, filename):
        """Get full path for executable file"""
        return str(self.EXEC_DIR / filename)
    
    def get_partition_file_path(self, filename, suffix="part.2"):
        """Get full path for partition file"""
        return str(self.DATA_DIR / f"{filename}.{suffix}")
    
    def get_partition_file_with_id_path(self, filename, id, suffix="part.2"):
        """Get full path for partition file with ID"""
        return str(self.DATA_DIR / f"{filename}.{suffix}.{id}")

# Global configuration instance
paths = PathConfig()

# Convenience functions for backward compatibility
def get_data_dir():
    """Get data directory path"""
    return str(paths.DATA_DIR)

def get_models_dir():
    """Get models directory path"""
    return str(paths.MODELS_DIR)