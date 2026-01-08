import subprocess
from pathlib import Path

def shrink_image(filename:Path)->None:
    """
    Shrink an image using pishrink.sh via WSL.
    
    Args:
        filename: Path to the image file to shrink
    """
    subprocess.run(['wsl', 'bash pishrink.sh', '-Z', filename.name],cwd=filename.parent)