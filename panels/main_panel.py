"""Main panel for CameraPathSC plugin — native LFS UI, no external Python needed.

This is a full retained/RML-driven panel: main_panel.rml owns the entire
layout (every field, radio, checkbox, and button lives in the DOM and is
wired through RmlUi data bindings). Python's job is limited to
on_bind_model() (expose state to the template) and on_mount() (wire the
three action buttons). There is no draw(ui)/#im-root immediate-mode
fallback -- the panel actually depends on the RML template rather than
just nominally pointing at one.
"""

import lichtfeld as lf
import json
import math
import os
from pathlib import Path

# ── Paths ────────────────────────────────────────────────────────────────────
_SCRIPTS_DIR = (
    Path(os.environ.get("USERPROFILE", "~")).expanduser()
    / ".lichtfeld" / "plugins" / "CamPath_Json" / "Scripts"
)
_FILE_LOG    = _SCRIPTS_DIR / "File.log"
_BACKUP_JSON = _SCRIPTS_DIR / "backup.json"

MODEL_NAME = "campath_json"

# ── Inline generator (no tkinter, no subprocess) ─────────────────────────────
# Mirrors standalone_camera_json.py — kept here so the plugin is self-contained.

def _normalize(v):
    length = math.sqrt(sum(c * c for c in v))
    if length < 1e-10:
        return (0.0, 0.0, 1.0)
    return tuple(c / length for c in v)


def _look_at_quaternion(position, target):
    """Camera looks down its own LOCAL -Z axis (standard OpenGL/glTF-style
    convention). Returns (qw, qx, qy, qz)."""
    fx = target[0] - position[0]
    fy = target[1] - position[1]
    fz = target[2] - position[2]
    forward = _normalize((fx, fy, fz))

    if abs(forward[1]) > 0.99:
        world_up = (0.0, 0.0, -1.0 if forward[1] > 0 else 1.0)
    else:
        world_up = (0.0, 1.0, 0.0)

    # right = forward × world_up  (standard right-handed camera basis)
    right = _normalize((
        forward[1] * world_up[2] - forward[2] * world_up[1],
        forward[2] * world_up[0] - forward[0] * world_up[2],
        forward[0] * world_up[1] - forward[1] * world_up[0],
    ))
    # up = right × forward
    up = (
        right[1] * forward[2] - right[2] * forward[1],
        right[2] * forward[0] - right[0] * forward[2],
        right[0] * forward[1] - right[1] * forward[0],
    )

    # Local +X = right, +Y = up, local -Z = forward, so the local Z column
    # of the matrix must be -forward. Using +forward here (as the previous
    # version of this function did) was the bug that made every generated
    # camera point 180 degrees away from its target.
    m00, m10, m20 = right
    m01, m11, m21 = up
    m02, m12, m22 = -forward[0], -forward[1], -forward[2]

    trace = m00 + m11 + m22
    if trace > 0:
        s = 0.5 / math.sqrt(trace + 1.0)
        qw = 0.25 / s; qx = (m21 - m12) * s; qy = (m02 - m20) * s; qz = (m10 - m01) * s
    elif m00 > m11 and m00 > m22:
        s = 2.0 * math.sqrt(1.0 + m00 - m11 - m22)
        qw = (m21 - m12) / s; qx = 0.25 * s; qy = (m01 + m10) / s; qz = (m02 + m20) / s
    elif m11 > m22:
        s = 2.0 * math.sqrt(1.0 + m11 - m00 - m22)
        qw = (m02 - m20) / s; qx = (m01 + m10) / s; qy = 0.25 * s; qz = (m12 + m21) / s
    else:
        s = 2.0 * math.sqrt(1.0 + m22 - m00 - m11)
        qw = (m10 - m01) / s; qx = (m02 + m20) / s; qy = (m12 + m21) / s; qz = 0.25 * s

    length = math.sqrt(qw*qw + qx*qx + qy*qy + qz*qz)
    return (qw/length, qx/length, qy/length, qz/length)


def _generate(state: dict) -> dict:
    """Generate keyframe data from the panel state dict."""
    atype      = state["anim_type"]       # "circular" | "spiral"
    direction  = state["direction"]       # "clockwise" | "ccw"
    center     = (state["cx"], state["cy"], state["cz"])
    frames     = max(1, state["frames"])
    fps        = max(1, state["fps"])
    focal_mm   = state["focal_length"]
    precision  = state["precision"]
    kstep      = max(1, state["keyframe_step"])
    angle_sign = -1.0 if direction == "clockwise" else 1.0

    # Target
    if state["auto_target"]:
        explicit_target = None
    else:
        explicit_target = (state["tx"], state["ty"], state["tz"])

    # Spiral follow-Y
    follow_y  = state["follow_y"]
    y_offset  = state["y_offset"]

    keyframes = []
    for frame_idx in range(0, frames, kstep):
        t = frame_idx / max(frames - 1, 1)
        time_sec = round(frame_idx / fps, precision)

        if atype == "circular":
            r      = state["radius"]
            height = center[1]
            angle  = angle_sign * 2.0 * math.pi * t
        else:  # spiral
            r      = state["start_radius"] + (state["end_radius"]   - state["start_radius"]) * t
            height = center[1] + state["start_height"] + (state["end_height"] - state["start_height"]) * t
            angle  = angle_sign * 2.0 * math.pi * state["loops"] * t

        px = center[0] + r * math.sin(angle)
        py = height
        pz = center[2] + r * math.cos(angle)
        position = [px, py, pz]

        if explicit_target is not None:
            look = list(explicit_target)
        else:
            look = [center[0], height if atype == "spiral" else center[1], center[2]]

        if atype == "spiral" and follow_y:
            look[1] = height + y_offset

        qw, qx, qy, qz = _look_at_quaternion(position, look)

        def rv(v): return round(v, precision)
        keyframes.append({
            "easing": 0,
            "focal_length_mm": round(focal_mm, precision),
            "position": [rv(position[0]), rv(position[1]), rv(position[2])],
            "rotation": [rv(qw), rv(qx), rv(qy), rv(qz)],
            "time": rv(time_sec),
        })

    return {"keyframes": keyframes, "version": 3}


def _read_log_path() -> str:
    try:
        text = _FILE_LOG.read_text(encoding="utf-8").strip()
        parts = text.split(None, 2)
        return parts[2].strip() if len(parts) >= 3 else text
    except Exception:
        return ""


# ── Panel ─────────────────────────────────────────────────────────────────────

class MainPanel(lf.ui.Panel):
    """Camera Path SC — native JSON camera path generator."""

    id          = "CameraPathSC.main_panel"
    label       = "Camera Path SC"
    space       = lf.ui.PanelSpace.MAIN_PANEL_TAB
    order       = 100
    template    = str(Path(__file__).resolve().with_name("main_panel.rml"))
    height_mode = lf.ui.PanelHeightMode.CONTENT

    # ── defaults ──────────────────────────────────────────────────────────────
    def __init__(self):
        # Animation type & direction
        self._anim_type = "circular"   # "circular" | "spiral"
        self._direction = "clockwise"  # "clockwise" | "ccw"

        # Circular
        self._radius        = "10"

        # Spiral
        self._loops         = "2"
        self._start_radius  = "5"
        self._end_radius    = "5"
        self._start_height  = "0"
        self._end_height    = "10"
        self._follow_y      = False
        self._y_offset      = "0"

        # Centre
        self._cx = "0"; self._cy = "0"; self._cz = "0"

        # Target
        self._auto_target   = False
        self._tx = "0"; self._ty = "0"; self._tz = "0"

        # Camera / export
        self._frames        = "900"
        self._fps            = "30"
        self._focal_length   = "35"
        self._sensor_size    = "32"
        self._precision      = "6"
        self._keyframe_step  = "15"

        # Output path
        self._output_path   = str(_SCRIPTS_DIR / "camera_path.json")

        # Status
        self._status    = ""
        self._status_ok = True

        # Section collapse state -- everything starts expanded.
        self._sec_anim      = True
        self._sec_centre    = False
        self._sec_target    = False
        self._sec_camera    = True
        self._sec_export    = True
        self._sec_sequencer = True

        self._handle = None

    # ------------------------------------------------------------------
    # Retained data model
    # ------------------------------------------------------------------

    # (model_name, attr, python_type)
    _TWO_WAY_FIELDS = [
        ("anim_type", "_anim_type", str),
        ("direction", "_direction", str),
        ("radius", "_radius", str),
        ("loops", "_loops", str),
        ("start_radius", "_start_radius", str),
        ("end_radius", "_end_radius", str),
        ("start_height", "_start_height", str),
        ("end_height", "_end_height", str),
        ("follow_y", "_follow_y", bool),
        ("y_offset", "_y_offset", str),
        ("cx", "_cx", str),
        ("cy", "_cy", str),
        ("cz", "_cz", str),
        ("auto_target", "_auto_target", bool),
        ("tx", "_tx", str),
        ("ty", "_ty", str),
        ("tz", "_tz", str),
        ("frames", "_frames", str),
        ("fps", "_fps", str),
        ("focal_length", "_focal_length", str),
        ("sensor_size", "_sensor_size", str),
        ("precision", "_precision", str),
        ("keyframe_step", "_keyframe_step", str),
        ("output_path", "_output_path", str),
        ("sec_anim", "_sec_anim", bool),
        ("sec_centre", "_sec_centre", bool),
        ("sec_target", "_sec_target", bool),
        ("sec_camera", "_sec_camera", bool),
        ("sec_export", "_sec_export", bool),
        ("sec_sequencer", "_sec_sequencer", bool),
    ]

    def _bind_two_way(self, model, name, attr, cast):
        def setter(v, a=attr, c=cast):
            try:
                setattr(self, a, c(v))
            except (TypeError, ValueError):
                pass  # ignore transient/invalid text-field input
        model.bind(name, lambda a=attr: getattr(self, a), setter)

    def on_bind_model(self, ctx):
        model = ctx.create_data_model(MODEL_NAME)
        if model is None:
            return

        for name, attr, cast in self._TWO_WAY_FIELDS:
            self._bind_two_way(model, name, attr, cast)

        model.bind_func("status", lambda: self._status)
        model.bind_func("status_ok", lambda: self._status_ok)
        model.bind_func("is_spiral", lambda: self._anim_type == "spiral")
        model.bind_func("duration_text", self._duration_text)
        model.bind_func("fov_text", self._fov_text)

        self._handle = model.get_handle()

    def _f(self, attr: str, default: float = 0.0) -> float:
        """Best-effort float parse of a free-text field. Never raises."""
        try:
            return float(getattr(self, attr))
        except (TypeError, ValueError):
            return default

    def _i(self, attr: str, default: int = 0) -> int:
        """Best-effort int parse of a free-text field (rounds floats). Never raises."""
        try:
            return int(round(float(getattr(self, attr))))
        except (TypeError, ValueError):
            return default

    def _duration_text(self) -> str:
        frames = max(1, self._i("_frames", 180))
        fps    = max(1, self._i("_fps", 24))
        kstep  = max(1, self._i("_keyframe_step", 1))
        duration = frames / fps
        kf_count = math.ceil(frames / kstep)
        return f"Duration: {duration:.1f}s   |   Keyframes: {kf_count}"

    def _fov_text(self) -> str:
        sensor = self._f("_sensor_size", 32.0)
        focal  = self._f("_focal_length", 35.0)
        fov = 2.0 * math.degrees(math.atan(sensor / (2.0 * max(0.1, focal))))
        return f"Horizontal FOV: {fov:.1f}°"

    def _set_status(self, msg: str, ok: bool = True):
        self._status = msg
        self._status_ok = ok
        if self._handle is not None:
            self._handle.dirty_all()

    # ------------------------------------------------------------------
    # DOM wiring
    # ------------------------------------------------------------------

    def on_mount(self, doc):
        gen_btn = doc.get_element_by_id("btn-generate")
        if gen_btn:
            gen_btn.add_event_listener("click", lambda _ev: self._do_generate())

        load_btn = doc.get_element_by_id("btn-load")
        if load_btn:
            load_btn.add_event_listener("click", lambda _ev: self._do_load())

        backup_btn = doc.get_element_by_id("btn-backup")
        if backup_btn:
            backup_btn.add_event_listener("click", lambda _ev: self._do_backup())

        # Select all text when a field gains focus, so it's obvious the
        # existing value can just be typed over.
        try:
            field_inputs = doc.query_selector_all(".field-input")
        except Exception:
            field_inputs = []
        for el in field_inputs:
            def _select_all(_ev, el=el):
                try:
                    el.select()
                except Exception:
                    pass
            el.add_event_listener("focus", _select_all)

    def on_update(self, doc):
        del doc
        # Recorded values (frames/fps/focal length/etc.) can change fields
        # that feed the derived text -- keep those live.
        if self._handle is not None:
            self._handle.dirty("duration_text")
            self._handle.dirty("fov_text")
            self._handle.dirty("is_spiral")

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _build_state(self) -> dict:
        return dict(
            anim_type=self._anim_type,
            direction=self._direction,
            radius=self._f("_radius", 10.0),
            loops=self._f("_loops", 2.0),
            start_radius=self._f("_start_radius", 5.0),
            end_radius=self._f("_end_radius", 15.0),
            start_height=self._f("_start_height", 0.0),
            end_height=self._f("_end_height", 10.0),
            follow_y=self._follow_y,
            y_offset=self._f("_y_offset", 0.0),
            cx=self._f("_cx", 0.0), cy=self._f("_cy", 0.0), cz=self._f("_cz", 0.0),
            auto_target=self._auto_target,
            tx=self._f("_tx", 0.0), ty=self._f("_ty", 0.0), tz=self._f("_tz", 0.0),
            frames=max(1, self._i("_frames", 180)),
            fps=max(1, self._i("_fps", 24)),
            focal_length=self._f("_focal_length", 35.0),
            sensor_size=self._f("_sensor_size", 32.0),
            precision=max(0, self._i("_precision", 6)),
            keyframe_step=max(1, self._i("_keyframe_step", 1)),
        )

    def _do_generate(self):
        try:
            out = self._output_path.strip()
            if not out:
                self._set_status("ERROR: No output path set.", False)
                return
            state = self._build_state()
            data = _generate(state)
            Path(out).parent.mkdir(parents=True, exist_ok=True)
            with open(out, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            # Write File.log so Load into Sequencer works
            _SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
            _FILE_LOG.write_text(f"output path {out}", encoding="utf-8")
            kf_count = len(data["keyframes"])
            self._set_status(f"\u2713 Saved {kf_count} keyframes \u2192 {out}")
            lf.log.info(f"CameraPathSC: wrote {kf_count} keyframes to {out!r}")
        except Exception as e:
            self._set_status(f"ERROR: {e}", False)
            lf.log.error(f"CameraPathSC: generate failed — {e}")

    def _do_load(self):
        out = _read_log_path() or self._output_path.strip()
        if not out:
            self._set_status("No output path — generate first.", False)
            return
        if not Path(out).exists():
            self._set_status(f"File not found: {out}", False)
            return
        try:
            lf.ui.load_camera_path(out)
            self._set_status(f"\u2713 Loaded into sequencer: {out}")
        except Exception as e:
            self._set_status(f"Load failed: {e}", False)

    def _do_backup(self):
        try:
            _SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
            ok = lf.ui.save_camera_path(str(_BACKUP_JSON))
            if ok:
                self._set_status(f"\u2713 Sequencer backed up \u2192 {_BACKUP_JSON}")
            else:
                self._set_status("Backup failed — is there a camera path in the sequencer?", False)
        except Exception as e:
            self._set_status(f"Backup failed: {e}", False)
