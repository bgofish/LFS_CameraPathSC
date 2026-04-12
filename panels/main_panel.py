"""Main panel for CameraPathSC  plugin."""

import lichtfeld as lf
import os
import subprocess
from pathlib import Path


# Paths
_SCRIPTS_DIR = Path(os.environ.get("USERPROFILE", "~")).expanduser()     / ".lichtfeld" / "plugins" / "CamPath_Json" / "Scripts"
_GUI_SCRIPT  = _SCRIPTS_DIR / "standalone_json_gui.py"
_FILE_LOG    = _SCRIPTS_DIR / "File.log"
_BACKUP_JSON = _SCRIPTS_DIR / "backup.json"


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
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Python" / "Python39"  / "python.exe"),
    ]
    for exe in candidates:
        try:
            result = subprocess.run([exe, "-c", "import tkinter"],
                                    capture_output=True, timeout=5)
            if result.returncode == 0:
                return exe
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return None


def _read_log_path() -> str:
    """Read the last-saved JSON path from File.log. Returns empty string on any failure."""
    try:
        text = _FILE_LOG.read_text(encoding="utf-8").strip()
        parts = text.split(None, 2)
        return parts[2].strip() if len(parts) >= 3 else text
    except Exception:
        return ""


class MainPanel(lf.ui.Panel):
    """Camera Path SC — standalone JSON camera generator panel."""

    id     = "CameraPathSC.main_panel"
    label  = "Camera Path SC"
    space  = lf.ui.PanelSpace.MAIN_PANEL_TAB
    order  = 100
    template = str(Path(__file__).resolve().with_name("main_panel.rml"))

    def __init__(self):
        self._python_exe = None
        self._status     = ""

    def draw(self, ui):
        # --- Launch GUI button ---
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
                        creationflags=subprocess.CREATE_NO_WINDOW
                            if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
                    )
                    self._status = "GUI launched."
                    lf.log.info(f"CameraPathSC: Launched GUI via {self._python_exe}")
                except Exception as e:
                    self._status = f"ERROR: {e}"
                    lf.log.error(f"CameraPathSC: Launch failed: {e}")

        ui.same_line()

        # --- Load into sequencer button ---
        if ui.button("Load into Sequencer"):
            output_path = _read_log_path()
            if not output_path:
                self._status = "No file found in log — generate a JSON file first."
                lf.log.error("CameraPathSC: File.log missing or empty")
            elif not Path(output_path).exists():
                self._status = f"File not found: {output_path}"
                lf.log.error(f"CameraPathSC: File not found — {output_path}")
            else:
                try:
                    lf.ui.load_camera_path(output_path)
                    self._status = f"Loaded: {output_path}"
                    lf.log.info(f"CameraPathSC: Loaded into sequencer from {output_path!r}")
                except Exception as e:
                    self._status = f"Load failed: {e}"
                    lf.log.error(f"CameraPathSC: Load into sequencer failed — {e}")

        ui.same_line()

        # --- Backup sequencer button ---
        if ui.button("Backup Sequencer Path"):
            try:
                _SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
                result = lf.ui.save_camera_path(str(_BACKUP_JSON))
                if result:
                    self._status = f"Backup saved: {_BACKUP_JSON}"
                    lf.log.info(f"CameraPathSC: Sequencer path backed up to {_BACKUP_JSON}")
                else:
                    self._status = "Backup failed — is there a camera path in the sequencer?"
                    lf.log.error("CameraPathSC: save_camera_path returned False")
            except Exception as e:
                self._status = f"Backup failed: {e}"
                lf.log.error(f"CameraPathSC: Backup failed — {e}")

        ui.separator()
        if self._status:
            ui.text_wrapped(self._status)
