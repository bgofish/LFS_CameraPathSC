"""Main panel for CameraPathSC plugin."""

import lichtfeld as lf
import os
import subprocess
import sys
from pathlib import Path


# Path to the standalone GUI script inside the plugin Scripts folder
_SCRIPTS_DIR = Path(os.environ.get("USERPROFILE", "~")).expanduser()     / ".lichtfeld" / "plugins" / "CamPath_Json" / "Scripts"
_GUI_SCRIPT = _SCRIPTS_DIR / "standalone_json_gui.py"


def _find_python():
    """Find a system Python executable that has tkinter available."""
    candidates = [
        "python",
        "python3",
        r"C:\Python312\python.exe",
        r"C:\Python311\python.exe",
        r"C:\Python310\python.exe",
        r"C:\Python39\python.exe",
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python312" / "python.exe"),
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python311" / "python.exe"),
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python310" / "python.exe"),
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python39" / "python.exe"),
    ]
    for exe in candidates:
        try:
            result = subprocess.run(
                [exe, "-c", "import tkinter"],
                capture_output=True, timeout=5
            )
            if result.returncode == 0:
                return exe
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


class MainPanel(lf.ui.Panel):
    """Camera Path SC — standalone JSON camera generator panel."""

    id = "CameraPathSC.main_panel"
    label = "Camera Path SC"
    space = lf.ui.PanelSpace.MAIN_PANEL_TAB
    order = 100
    template = str(Path(__file__).resolve().with_name("main_panel.rml"))

    def __init__(self):
        self._python_exe = None
        self._status = "Click 'Find Python' or 'Open Generator' to start."

    def draw(self, ui):
        ui.heading("Camera Path SC")
        ui.text_disabled("Generate SuperSplat-compatible camera animation JSON files.")
        ui.separator()

        if ui.button("Open Camera Generator"):
            if self._python_exe is None:
                self._python_exe = _find_python()
            if self._python_exe is None:
                self._status = "ERROR: No system Python with tkinter found. Install Python from python.org."
                lf.log.error("CameraPathSC: No system Python with tkinter found")
            else:
                try:
                    subprocess.Popen(
                        [self._python_exe, str(_GUI_SCRIPT)],
                        cwd=str(_SCRIPTS_DIR),
                        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
                    )
                    self._status = f"Launched with: {self._python_exe}"
                    lf.log.info(f"CameraPathSC: Launched GUI via {self._python_exe}")
                except Exception as e:
                    self._status = f"ERROR: {e}"
                    lf.log.error(f"CameraPathSC: Launch failed: {e}")

        ui.separator()
        ui.text_wrapped(self._status)
        ui.text_wrapped(f"Script: {_GUI_SCRIPT}")
