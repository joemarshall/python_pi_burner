import subprocess
from pathlib import Path
from typing import Any

def shrink_image(filename:Path|str,patch_progress_fn: Any)->None:
    """
    Shrink an image using pishrink.sh via WSL.
    
    Args:
        filename: Path to the image file to shrink
    """
    if type(filename)==str:
        filename=Path(filename).absolute()
    proc = subprocess.Popen(['wsl', '-u','root','bash','pishrink.sh',filename.name],cwd=filename.parent,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    all_lines=[]
    while proc.returncode==None:
        line = proc.stdout.readline()
        if len(line)==0:
            break
        all_lines.append(line)
        if len(all_lines)>20:
            all_lines=all_lines[-20:]
        patch_progress_fn("\n".join(all_lines))

if __name__=="__main__":

    def progress(str):
        print(str)

    shrink_image(Path("raspios_prepatched.img"),progress)
