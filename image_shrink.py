import subprocess
from pathlib import Path
from typing import Any

def shrink_image(filename:Path|str,patch_progress_fn: Any)->None:
    """
    Shrink an image using pishrink.sh via WSL.
    
    Args:
        filename: Path to the image file to shrink
    """
    if type(filename)==Path:
        filename=filename.name
    proc = subprocess.Popen(['wsl', '-u','root','bash','pishrink.sh',filename],cwd=filename.parent,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    while proc.returncode==None:
        line = proc.stdout.readline()
        if len(line)==0:
            break
        patch_progress_fn(line)

if __name__=="__main__":

    def progress(str):
        print(str)

    shrink_image(Path("raspios_prepatched.img"),progress)
