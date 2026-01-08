from winpty import PtyProcess
import re
import threading
import subprocess
import os
import wmi
import pythoncom

from image_edit import add_contents_to_raw_disk
import rawdisk

class ImageBurner:
    def __init__(self):
        self.burns={}
        self.next_id=1
        self.event=threading.Event()
        self.location_cache={}
        self.drive_list={}
        self.drive_scan_thread=threading.Thread(target=self.disk_scan_thread_fn)
        self.drive_scan_thread.daemon=True # we don't care if it is killed
        self.drive_scan_thread.start()


    def get_progress(self,only_updated=False):
        updates=[]
        if len(self.burns)>0:
            for id,data in self.burns.items():
                if only_updated and data["updated"]:
                    data["updated"]=False
                    updates.append((id,data))
                else:
                    updates.append((id,data))
        return updates
    
    def get_burn_ids(self):
        return list(self.burns.keys())

    def wait(self):
        if len(self.burns)>0:
            self.event.wait()
            for id,data in self.burns.items():
                if data["updated"]:
                    data["updated"]=False
                    self.event.clear()
                    return id,data
        return None

    def burning(self):
        return (len(self.burns)>0)

    def _get_disk_path(self,wm,device):
        props,rval=device.GetDeviceProperties(["DEVPKEY_Device_LocationPaths","DEVPKEY_Device_Parent"])
        if rval==0:
            if props[0].type!=0:
                return props[0].data
            if props[1].type!=0:
                for x in wm.query(f"select PNPDeviceID from Win32_PnPEntity WHERE PNPDeviceID='{props[1].data}'"):
                    return self._get_disk_path(wm,x)
        return None

    def _rewrite_location(self,location):
        for path in location:
            parts=re.findall(r"(\w+)\((\d+)\)(?#|$)",path)
            if "USBROOT" in [x for x,y in parts]:
                location=None
                for name,part_num in parts:
                    if name=="USBROOT":
                        location=[int(part_num)]
                    elif location is not None:
                        location.append(int(part_num))
                return location
        return []

    def disk_scan_thread_fn(self):
        pythoncom.CoInitializeEx(0)
        wm = wmi.WMI ()
        raw_wql = "SELECT * FROM __InstanceOperationEvent WITHIN 2 WHERE TargetInstance ISA 'Win32_DiskDrive'"
        new_drive=None
        while True:
            self.rescan_disks(wm,new_drive=new_drive)
            target_instance=None
            watcher = wm.watch_for (raw_wql=raw_wql,wmi_class="__InstanceOperationEvent")
            try:
                while True:
                    change_event=watcher(30000) # full scan every 30 seconds by default
                    if change_event.event_type=='creation':
                        # new drive
                        new_drive=change_event                    
                        print(f"added:{change_event.DeviceID}")
                        break
                    elif change_event.event_type=='deletion':
                        removed_device=change_event.DeviceID
                        print(f"removed: {removed_device}")
                        if removed_device in self.drive_list:
                            del self.drive_list[removed_device]
            except wmi.x_wmi_timed_out as ex:
                pass

    def new_drive(self,wm,disk):
        # 7 = removable drive
        if disk.Capabilities is not None and 7 in disk.Capabilities:
            print("Removable:",disk)

            if disk.Signature in self.location_cache:
                print("Woof")
                location = self.location_cache[disk.Signature]
            else:
                location=(1,1)
                # for x in disk.associators(wmi_result_class="Win32_PnPEntity"):
                #     l=self._get_disk_path(wm,x)
                #     if l!=None:
                #         location=self._rewrite_location(l)                            
                #         self.location_cache[disk.Signature]=location
                #         break
            print("Returning")
            return (disk.DeviceID,disk.Model,location)
        return None


    def rescan_disks(self,wm,new_drive):
        if new_drive==None:
            drive_list={}
            for disk in wm.query(f"select Capabilities,DeviceID,Model,Signature from Win32_DiskDrive"):
                disk_info=self.new_drive(wm,disk)
                if disk_info is not None:
                    drive_list[disk_info[0]]=disk_info
            self.drive_list=drive_list
        else:
            disk_info=self.new_drive(wm,new_drive)
            if disk_info is not None:
                self.drive_list[disk_info[0]]=disk_info
        print("scanned:",self.drive_list)

    def get_all_disks(self):
        return self.drive_list.values()

    def _burn_progress(self,current,total,id):
        if id in self.burns:
            self.burns[id]["bytes_transferred"]=current
            self.burns[id]["updated"]=True
            self.event.set()
            return self.burns[id]["cancelled"]==False
        else:
            return False

    def _burn_thread(self,source_image,target_disk,id,contents_only,prepatched):
        try:
            if not contents_only:
                self.burns[id]["text"]="Burning image"
                rawdisk.copy_to_disk(source_image,target_disk,self._burn_progress,id)
            self.burns[id]["text"]="Copying contents"
            add_contents_to_raw_disk(target_disk,prepatched)
            if not contents_only:
                self.burns[id]["output"]="Burnt and patched successfully"
            else:
                self.burns[id]["output"]="Patched successfully"
            self.burns[id]["result"]=0
        except RuntimeError as r:
            self.burns[id]["result"]=1
            self.burns[id]["output"]=str(r)
        except IOError as r:
            self.burns[id]["result"]=2
            self.burns[id]["output"]=str(r)
        self.burns[id]["finished"]=True
        self.event.set()

    def burn_image_to_disk(self,source_image=None,target_disk=None,contents_only=False,prepatched=False):
        id=self.next_id
        self.next_id+=1
        self.burns[id]={}
        total_size=os.path.getsize(source_image) 
        self.burns[id]["cancelled"]=False
        self.burns[id]["text"]=""
        self.burns[id]["finished"]=False
        self.burns[id]["total_size"]=total_size
        self.burns[id]["target"]=target_disk
        self.burns[id]["thd"]=threading.Thread(target=self._burn_thread,args=[source_image,target_disk,id,contents_only,prepatched],daemon=True)
        self.burns[id]["updated"]=True
        self.burns[id]["bytes_transferred"]=0
        self.burns[id]["thd"].start()
        # should fire event
        self.event.wait()

    def cancel(self):
        for x in self.burns.keys():
            self.burns[x]["cancelled"]=True
        ended=False
        # wait for cancelled transfers to stop
        while not ended:
            ended=True
            for x in self.burns.keys():
                if self.burns[x]["finished"]==False:
                    ended=False
        self.burns={}

    def clear(self):
        self.burns={}


if __name__=="__main__":
    import time

    i=ImageBurner()
    import timeit
    print("GD:",i.get_all_disks())
    time.sleep(2)
    print("GD:",i.get_all_disks())
    time.sleep(2)
    print("GD:",i.get_all_disks())
    time.sleep(2)
    def bp(current,total,id):
        print(f"Progress {id}: {current}/{total} ({(current*100)//total}%)")
        return True        

    for disk,model,location in i.get_all_disks():
         rawdisk.copy_to_disk("raspios.img",disk,progress_callback=bp,id=1)
         break

