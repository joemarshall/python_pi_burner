from asciimatics.widgets import (
    Frame,
    TextBox,
    Layout,
    Label,
    Divider,
    Text,
    CheckBox,
    RadioButtons,
    Button,
    PopUpDialog,
    TimePicker,
    DatePicker,
    DropdownList,
    PopupMenu,
)
from asciimatics.widgets.filebrowser import FileBrowser
from asciimatics.screen import Screen
from asciimatics.event import KeyboardEvent
from asciimatics.scene import Scene
from asciimatics.exceptions import (
    ResizeScreenError,
    NextScene,
    StopApplication,
    InvalidFields,
)

from dataclasses import dataclass
from burn import ImageBurner
from rawdisk import copy_from_disk
import image_edit
from image_shrink import shrink_image
import os
from pathlib import Path
from lzma import LZMADecompressor, LZMACompressor
from zipfile import ZipFile
import shutil
import sys
from datetime import date


@dataclass
class DataHolder:
    burner: ImageBurner
    labimage: bool = True
    # if this is true, we only copy contents to existing image sd
    contents_only: bool = False
    wifipw: str = ""
    wifiname: str = ""
    uniname: str = ""
    unipw: str = ""
    patch_image: bool = False  # used when copying image and patching it
    hash: bool = True  # hash uni password
    prepatched_image = False  # if this is true, use raspios_prepatched.img


class EscapeFrame(Frame):
    def process_event(self, event):
        if isinstance(event, KeyboardEvent) and event.key_code == -1:
            self.cancel()
        else:
            super().process_event(event)

    def cancel(self):
        # do nothing by default
        pass


class WifiFrame(EscapeFrame):
    def __init__(self, screen, holder):
        super().__init__(screen=screen, height=screen.height, width=screen.width)
        self.dataholder = holder
        layout = Layout([100], True)
        self.add_layout(layout)
        layout.add_widget(
            Text(
                "University username (e.g. psxwy2):", "uniname", validator=r"[0-9a-z]+$"
            )
        )
        layout.add_widget(
            Text(
                "University password",
                "unipw",
                hide_char="*",
                validator=lambda x: len(x) >= 1,
            )
        )
        layout.add_widget(Text("Home wifi name", "wifiname", validator=r"\w|\s"))
        layout.add_widget(
            Text(
                "Home wifi password:",
                "wifipw",
                hide_char="*",
                validator=lambda x: len(x) >= 8,
            )
        )
        layout2 = Layout([1, 1, 1, 1])
        self.add_layout(layout2)
        self.ok_button = layout2.add_widget(Button("OK", self.ok), 0)
        self.cancel_button = layout2.add_widget(Button("Cancel", self.cancel), 3)
        self.fix()

    @property
    def frame_update_count(self):
        return 1

    def update(self, frame_no):
        try:
            self.save(validate=True)
            self.ok_button.disabled = False
        except InvalidFields:
            self.ok_button.disabled = True
        super().update(frame_no)

    def ok(self):
        self.dataholder.hash = True  # hash uni password
        self.save(validate=True)
        for x in self.data.keys():
            setattr(self.dataholder, x, self.data[x])
        raise NextScene("burn_ready")

    def cancel(self):
        raise NextScene("menu")


# on startup - a) set us as the burn callback for the burner
#              b) if we are burning, then show progress and disable cancel button
#                  and show N many progress bars
#              c) otherwise show warning message saying how
#                  many cards will be written and wait for okay


class BurnReadyFrame(EscapeFrame):
    def __init__(self, screen, dataholder):
        super().__init__(screen=screen, height=screen.height, width=screen.width)
        self.dataholder = dataholder
        layout = Layout([100], True)
        self.add_layout(layout)
        self.burn_info = layout.add_widget(Label("!", height=15), 0)
        layout2 = Layout([1, 1, 1, 1], False)
        self.add_layout(layout2)
        self.okbutton = layout2.add_widget(Button("OK", self.ok), 0)
        layout2.add_widget(Button("Cancel", self.cancel), 3)
        self.fix()

    @property
    def frame_update_count(self):
        # update 4 times a second
        return 5

    def update(self, frame):
        disk_count = 0
        newtext = ""
        all_disks = self.dataholder.burner.get_all_disks()
        # enumerate them as if they are on one hub
        # in order: 1,2, subhub (1,2,3,4), subhub (1,2,3,4)
        # i.e. lower levels go first, then higher depths
        # this is hardcoded for our particular 10 port hub
        LOCATION_ORDER = [1, 2, (3, 4, 5, 6), (7, 8, 9, 10)]

        if len(all_disks) != 0:
            location_len_max = max(len(location) for _, _, location in all_disks)

        for disk, model, location in all_disks:
            if len(location) == location_len_max - 1:
                # main hub port, disk num = x
                location_index = location[-1]
            elif len(location) == location_len_max:
                # sub-hub port, disk num = (x1 - 2)*4,y
                location_index = location[-1] + 2 + (location[-2] - 3) * 4

            newtext += f"{disk}:{model} @ Port {location_index}\n"
            disk_count += 1
        if disk_count == 0:
            self.okbutton.disabled = True
            newtext = "You need to insert an sd card before burning can begin"
            self.okbutton.text = ""
        else:
            newtext = (
                f"About to burn {disk_count} sd cards to the following drives:\n"
                + newtext
            )
            if self.burn_info.text != newtext:
                self.okbutton.disabled = False
                self.okbutton.text = "Ok"
        if self.burn_info.text != newtext:
            self.burn_info.text = newtext
        super().update(frame)

    def ok(self):
        # make image
        # start burn (on first drive or on all drives depending on type)
        self.dataholder.burner.clear()
        image_edit.create_init_files(self.dataholder)
        for disk, model, location in self.dataholder.burner.get_all_disks():
            if self.dataholder.prepatched_image:
                source = "raspios_prepatched.img"
            else:
                source = "raspios.img"
            self.dataholder.burner.burn_image_to_disk(
                source_image=source,
                target_disk=disk,
                contents_only=self.dataholder.contents_only,
                prepatched=self.dataholder.prepatched_image,
            )
        raise NextScene("burn")

    def cancel(self):
        # back to menu
        raise NextScene("menu")


class BurnDoneFrame(EscapeFrame):
    def __init__(self, screen, dataholder):
        super().__init__(screen=screen, height=screen.height, width=screen.width)
        self.dataholder = dataholder
        layout = Layout([100], False)
        self.add_layout(layout)
        layout.add_widget(Label("Burn complete"), 0)

        self.progress_layout = Layout([1, 4], True)
        self.progresses = {}
        self.add_layout(self.progress_layout)

        layout2 = Layout([1, 1, 1, 1], False)
        self.add_layout(layout2)

        layout2.add_widget(Button("Menu", self.menu), 0)
        layout2.add_widget(Button("Repeat", self.repeat), 3)
        self.fix()

    def update(self, frame):
        for id, data in self.dataholder.burner.get_progress():
            if id not in self.progresses:
                dev_id = data["target"]
                output = data["output"]
                result = data["result"]
                self.progress_layout.add_widget(Label(dev_id + ":"), 0)
                label2 = self.progress_layout.add_widget(
                    Label(
                        output,
                    ),
                    1,
                )
                self.progresses[id] = label2
                if result != 0:
                    label2.custom_colour = "invalid"
        self.fix()
        super().update(frame)

    def repeat(self):
        # make image
        # start burn (on first drive or on all drives depending on type)
        dataholder.burner.cancel()
        self.progress_layout.clear_widgets()
        self.progresses = {}
        raise NextScene("burn_ready")

    def menu(self):
        # back to menu
        self.progress_layout.clear_widgets()
        self.progresses = {}
        dataholder.burner.cancel()
        raise NextScene("menu")

    def cancel(self):
        # back to menu
        self.progress_layout.clear_widgets()
        dataholder.burner.cancel()
        self.progress_layout.clear_widgets()
        self.progresses = {}
        raise NextScene("menu")


class BurnFrame(EscapeFrame):
    def __init__(self, screen, dataholder):
        super().__init__(screen=screen, height=screen.height, width=screen.width)
        self.dataholder = dataholder
        layout = Layout([100], False)
        self.add_layout(layout)
        self.progresses = {}
        progress_layout = Layout([1, 4], True)
        self.add_layout(progress_layout)
        self.burncount_widget = layout.add_widget(
            Label("Burning 0 cards - press cancel to stop"), 0
        )

        self.progress_layout = progress_layout
        for id, data in self.dataholder.burner.get_progress():
            dev_id = data["target"]
            progress_layout.add_widget(Label(dev_id + ":"), 0)
            self.progresses[dev_id] = progress_layout.add_widget(Label("."), 1)
        layout2 = Layout([1, 1, 1, 1], False)
        self.add_layout(layout2)
        layout2.add_widget(Button("Cancel", self.cancel), 3)
        self.fix()

    @property
    def frame_update_count(self):
        return 1

    def update(self, frame):
        progress = self.dataholder.burner.get_progress(only_updated=False)
        burns_left = False
        for _, data in progress:
            dev_id = data["target"]
            if dev_id not in self.progresses:
                self.progress_layout.add_widget(Label(dev_id + ":"), 0)
                self.progresses[dev_id] = self.progress_layout.add_widget(Label("."), 1)
                if self.dataholder.contents_only == True:
                    self.burncount_widget.text = (
                        "Repatching %d card(s) - press cancel to stop"
                        % len(self.progresses)
                    )
                else:
                    self.burncount_widget.text = (
                        "Burning %d card(s) - press cancel to stop"
                        % len(self.progresses)
                    )
                self.fix()
            if data["finished"] == True:
                if data["result"] != 0:
                    self.progresses[dev_id].text = "Failed: " + data["output"]
            else:
                burns_left = True
                bytes_transferred = data["bytes_transferred"]
                total_size = data["total_size"]
                progress_text = data["text"]
                percent_sent = bytes_transferred / total_size
                PROGRESS_LENGTH = 40
                progress_count = int(PROGRESS_LENGTH * percent_sent)
                self.progresses[dev_id].text = (
                    "|"
                    + "." * progress_count
                    + " " * (PROGRESS_LENGTH - progress_count)
                    + "| "
                    + progress_text
                    + " | %d/%d MB"
                    % (bytes_transferred // 1048576, total_size // 1048576)
                )
                self.screen.force_update()
        #                self.progresses[dev_id].refresh()
        if not burns_left:
            self.progress_layout.clear_widgets()
            self.progresses.clear()
            raise NextScene("burn_done")
        super().update(frame)

    def cancel(self):
        # are you sure?
        dlg = PopUpDialog(
            self.screen,
            text="Cancel burn, are you sure?",
            buttons=["keep going", "stop"],
            on_close=self.cancel_popup,
        )
        self._scene.add_effect(dlg)

    def cancel_popup(self, index):
        if index == 1:
            # cancel any pending burns
            self.dataholder.burner.cancel()
            # back to menu
            self.progresses.clear()
            self.progress_layout.clear_widgets()
            raise NextScene("menu")


class MenuFrame(EscapeFrame):
    def __init__(self, screen, dataholder):
        super().__init__(screen=screen, height=screen.height, width=screen.width)
        self.dataholder = dataholder
        menu_items = [
            ("Burn lab image to SD card(s)", self.burn_lab),
            ("Burn student image to single SD card", self.burn_student),
            ("Set SD card to lab image", self.set_lab),
            ("Set SD card to student image", self.set_student),
            ("Update base image", self.update_base_image),
            ("Create patched image file", self.patch_base_image),
            ("Capture prepatched image", self.capture_prepatched_image),
            ("Burn prepatched image", self.burn_prepatched_image),
        ]
        layout = Layout([100], True)
        self.add_layout(layout)
        self.widgets = []
        for label, cb in menu_items:
            self.widgets.append(
                layout.add_widget(
                    Button(text=label, add_box=False, on_click=cb, name=label), 0
                )
            )
        self.fix()

    def burn_lab(self):
        if not os.path.exists("networks.lab.conf"):
            dlg = PopUpDialog(
                self.screen,
                text="You need to create networks.lab.conf before you can burn lab images",
                buttons=["OK"],
            )
            self._scene.add_effect(dlg)
        else:
            self.dataholder.prepatched_image = False
            self.dataholder.contents_only = False
            self.dataholder.labimage = True
            raise NextScene("burn_ready")

    def burn_student(self):
        self.dataholder.prepatched_image = False
        self.dataholder.contents_only = False
        self.dataholder.labimage = False
        raise NextScene("wifi")

    def set_lab(self):
        if not os.path.exists("networks.lab.conf"):
            dlg = PopUpDialog(
                self.screen,
                text="You need to create networks.lab.conf before you can burn lab images",
                buttons=["OK"],
            )
            self._scene.add_effect(dlg)
        else:
            self.dataholder.prepatched_image = False
            self.dataholder.contents_only = True
            self.dataholder.labimage = True
            raise NextScene("burn_ready")

    def set_student(self):
        self.dataholder.prepatched_image = False
        self.dataholder.labimage = False
        self.dataholder.contents_only = True
        raise NextScene("wifi")

    def update_base_image(self):
        self.dataholder.prepatched_image = False
        self.dataholder.patch_image = False
        raise NextScene("update_image")

    def patch_base_image(self):
        self.dataholder.prepatched_image = False
        self.dataholder.patch_image = True
        raise NextScene("update_image")

    def burn_prepatched_image(self):
        self.dataholder.prepatched_image = True
        self.dataholder.labimage = True
        raise NextScene("burn_ready")

    def capture_prepatched_image(self):
        raise NextScene("capture_prepatched")

    def cancel(self):
        raise StopApplication("User terminated app")


class CapturePrepatchedFrame(EscapeFrame):
    def __init__(self, screen, dataholder):
        super().__init__(screen=screen, height=screen.height, width=screen.width)
        self.dataholder = dataholder
        progress_layout = Layout([100], False)
        self.add_layout(progress_layout)
        self.progress = Label("Progress: " + ("." * 40))
        progress_layout.add_widget(self.progress, 0)
        self.capturing=False
        layout2 = Layout([1, 1, 1, 1])
        self.add_layout(layout2)
        layout2.add_widget(Button("Cancel", self.cancel), 3)
        self.cancelled=False
        self.fix()

    def update(self, frame):
        if not self.capturing:
            self.capture_image()
        super().update(frame)

    def _burn_progress(self, data_written, in_size, id):
        progress = int(40 * data_written / in_size)
        new_progress_text = (
            "Progress: "
            + ("*" * progress)
            + (
                "." * (40 - progress)
                + "Capturing image %d/%d MB"
                % (data_written / 1048576, in_size / 1048576)
            )
        )
        if self.progress.text != new_progress_text:
            self.progress.text = new_progress_text
            self.screen.refresh()
            self.screen.force_update()
            self.screen.draw_next_frame()
        return not self.cancelled

    def _patch_progress(self,task_out):
        new_progress_text = task_out
        if self.progress.text != new_progress_text:
            self.progress.text = new_progress_text
            self.screen.refresh()
            self.screen.force_update()
            self.screen.draw_next_frame()
        return not self.cancelled


    def cancel(self):
        self.cancelled=True

    def capture_image(self):
        self.capturing=True
        all_disks = self.dataholder.burner.get_all_disks()
        if len(all_disks) != 1:
            dlg = PopUpDialog(
                self.screen,
                text=f"Needs exactly one sd card",
                buttons=["OK"],
                on_close=self.done,
            )
        else:
            self.cancelled=False
            try:
                for disk, model, location in self.dataholder.burner.get_all_disks():
                    copy_from_disk(
                        disk, "raspios_prepatched.img", self._burn_progress, 1
                    )
                    shrink_image("raspios_prepatched.img",self._patch_progress)
            except RuntimeError:
                pass            
            if self.cancelled:
                dlg = PopUpDialog(
                    self.screen,
                    text=f"Image capture cancelled",
                    buttons=["OK"],
                    on_close=self.done,
                )
            else:
                dlg = PopUpDialog(
                    self.screen,
                    text=f"Image captured successfully",
                    buttons=["OK"],
                    on_close=self.done,
                )
        self._scene.add_effect(dlg)

    def done(self, val=None):
        self.reset()
        self.capturing=False
        raise NextScene("menu")


class UpdateImageFrame(EscapeFrame):
    def __init__(self, screen, dataholder):
        super().__init__(screen=screen, height=screen.height, width=screen.width)
        self.writing = False
        self.dataholder = dataholder
        self.info_layout = Layout([100], False)
        self.add_layout(self.info_layout)
        self.info_label = self.info_layout.add_widget(
            Label("Select base image to copy.")
        )
        self.file_layout = Layout([100], True)
        self.add_layout(self.file_layout)
        self.file_chooser = FileBrowser(
            root=".",
            height=screen.height - 4,
            name="image_file_chooser",
            file_filter=".*(.xz|.zip|.img)$",
            on_select=self.copy_image,
        )
        progress_layout = Layout([100], False)
        self.add_layout(progress_layout)
        self.progress = Label("Progress: " + ("." * 40))
        progress_layout.add_widget(self.progress, 0)
        self.file_layout.add_widget(self.file_chooser, 0)
        self.fix()

    def update(self, frame):
        if self.dataholder.patch_image:
            if self.writing:
                self.info_label.text = "Patching image"
            else:
                self.info_label.text = "Select image to create patched .img file"
        else:
            if self.writing:
                self.info_label.text = "Getting base image"
            else:
                self.info_label.text = "Select image to use as base image"

        super().update(frame)

    def copy_image(self):
        self.writing = True
        img = self.file_chooser.value
        img = os.path.abspath(img)
        if self.dataholder.patch_image:
            target_path = os.path.splitext(img)[0] + ".patched.%s.img" % (
                date.today().strftime("%y%m%d")
            )
        else:
            target_path = "raspios.img"
        self.file_layout.clear_widgets()
        if img.endswith(".img"):
            if os.path.abspath(img) != os.path.abspath(target_path):
                shutil.copyfile(img, target_path)
        elif img.endswith(".zip"):
            # assume biggest file in zip is image
            f_size = 0
            f_img = ""
            with ZipFile(img) as z:
                for info in z.infolist():
                    if info.file_size > f_size:
                        f_size = info.file_size
                        f_img = info.filename
                with z.open(f_img) as zf:
                    with open(target_path, "wb") as outfile:
                        shutil.copyfileobj(zf, outfile)
        elif img.endswith(".xz"):
            with open(img, "rb") as infile:
                with open(target_path, "wb") as outfile:
                    dc = LZMADecompressor()
                    total_len = os.stat(img).st_size
                    current_len = 0
                    try:
                        while current_len < total_len:
                            data = infile.read(1048576)  # 16mb at a time
                            if len(data) > 0:
                                outfile.write(dc.decompress(data))
                            current_len += len(data)

                            progress = int(40 * (current_len / total_len))
                            new_progress_text = (
                                "Progress: "
                                + ("*" * progress)
                                + (
                                    "." * (40 - progress)
                                    + " Unpacking %d/%d MB"
                                    % (current_len / 1048576, total_len / 1048576)
                                )
                            )
                            print(new_progress_text)
                            if self.progress.text != new_progress_text:
                                self.progress.text = new_progress_text
                                self.screen.refresh()
                                self.screen.force_update()
                                self.screen.draw_next_frame()
                    except EOFError:
                        pass
        else:
            dlg = PopUpDialog(
                self.screen,
                text=f"Bad image file format {img}",
                buttons=["OK"],
                on_close=self.done,
            )
            self._scene.add_effect(dlg)
            return
        if self.dataholder.patch_image:
            # mount as vhd and write contents, then unmount
            self.dataholder.labimage = False
            self.dataholder.wifipw = "<YOUR_WIFI_PASSWORD>"
            self.dataholder.wifiname = "<YOUR WIFI NAME>"
            self.dataholder.uniname = "<YOUR_UNI_NAME e.g. pszjm2>@nottingham.ac.uk"
            self.dataholder.unipw = "<YOUR UNI PASSWORD>"
            self.dataholder.hash = False
            image_edit.create_init_files(self.dataholder)
            image_edit.add_contents_to_raw_disk(target_path)
            dlg = PopUpDialog(
                self.screen,
                text=f"Image patched successfully: {target_path}",
                buttons=["OK"],
                on_close=self.done,
            )
        else:
            dlg = PopUpDialog(
                self.screen,
                text=f"Image copied successfully: {img}",
                buttons=["OK"],
                on_close=self.done,
            )
        self._scene.add_effect(dlg)

    def done(self, val=None):
        self.reset()
        raise NextScene("menu")


def main(screen, scene, holder):
    # Define your Scenes here
    # 1) Menu to choose what to do
    # 2) Form to input wifi + passwords
    # 3) Burn progress screen
    our_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(our_dir)
    scenes = [
        Scene([MenuFrame(screen, holder)], name="menu"),
        Scene([WifiFrame(screen, holder)], name="wifi"),
        Scene([BurnReadyFrame(screen, holder)], name="burn_ready"),
        Scene([BurnFrame(screen, holder)], name="burn"),
        Scene([BurnDoneFrame(screen, holder)], name="burn_done"),
        Scene([UpdateImageFrame(screen, holder)], name="update_image"),
        Scene([CapturePrepatchedFrame(screen, holder)], name="capture_prepatched"),
    ]

    # Run your program
    screen.play(scenes, stop_on_resize=True, start_scene=scene)


if __name__ == "__main__":

    # this is just used in curses programs so escape key works
    os.environ.setdefault("ESCDELAY", "25")
    dataholder = DataHolder(burner=ImageBurner())
    last_scene = None
    while True:
        try:
            Screen.wrapper(main, arguments=[last_scene, dataholder])
            sys.exit(0)
        except ResizeScreenError as e:
            last_scene = e.scene
