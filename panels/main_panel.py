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
_PLUGIN_DIR  = Path(__file__).resolve().parent.parent
_DEFAULTS_PATH = _PLUGIN_DIR / "DEFAULTS.JSON"
_SCRIPTS_DIR = (
    Path(os.environ.get("USERPROFILE", "~")).expanduser()
    / ".lichtfeld" / "plugins" / "CamPath_Json" / "Scripts"
)
_FILE_LOG    = _SCRIPTS_DIR / "File.log"
_BACKUP_JSON = _SCRIPTS_DIR / "backup.json"

MODEL_NAME = "campath_json"
MAX_RECOMMENDED_KEYFRAMES = 400

# Built-in fallback -- used for any key missing from (or if there's no)
# DEFAULTS.JSON, so a partial or absent file never breaks the panel.
# (name, is_int, min, max, step)
_FIELD_SPEC_ORDER = [
    ("radius",        False, 0.1,    200.0, 0.1),
    ("loops",         False, 0.1,    20.0,  0.1),
    ("start_radius",  False, 0.0,    200.0, 0.1),
    ("end_radius",    False, 0.0,    200.0, 0.1),
    ("start_height",  False, -100.0, 100.0, 0.1),
    ("end_height",    False, -100.0, 100.0, 0.1),
    ("y_offset",      False, -100.0, 100.0, 0.1),
    ("cx",            False, -500.0, 500.0, 0.1),
    ("cy",            False, -500.0, 500.0, 0.1),
    ("cz",            False, -500.0, 500.0, 0.1),
    ("tx",            False, -500.0, 500.0, 0.1),
    ("ty",            False, -500.0, 500.0, 0.1),
    ("tz",            False, -500.0, 500.0, 0.1),
    ("frames",        True,  1.0,    3000.0, 1.0),
    ("fps",           True,  1.0,    240.0,  1.0),
    ("focal_length",  False, 1.0,    300.0, 0.5),
    ("sensor_size",   False, 1.0,    100.0, 0.5),
    ("precision",     True,  0.0,    10.0,  1.0),
    ("keyframe_step", True,  1.0,    60.0,  1.0),
]
_FIELD_VALUE_DEFAULTS = {
    "radius": 10.0, "loops": 2.0, "start_radius": 5.0, "end_radius": 15.0,
    "start_height": 0.0, "end_height": 10.0, "y_offset": 0.0,
    "cx": 0.0, "cy": 0.0, "cz": 0.0, "tx": 0.0, "ty": 0.0, "tz": 0.0,
    "frames": 180.0, "fps": 24.0, "focal_length": 35.0, "sensor_size": 32.0,
    "precision": 6.0, "keyframe_step": 1.0,
}

_HARDCODED_DEFAULTS = {
    "anim_type": "circular",
    "direction": "clockwise",
    "follow_y": False,
    "auto_target": False,
    "add_start_end_keys": True,
    "output_filename": "camera_path.json",
    "fields": {
        name: {
            "value": _FIELD_VALUE_DEFAULTS[name],
            "min": lo, "max": hi, "step": step, "int": is_int,
        }
        for name, is_int, lo, hi, step in _FIELD_SPEC_ORDER
    },
}


def _load_defaults() -> dict:
    """Load DEFAULTS.JSON from the plugin root if present, filling in any
    missing/invalid keys from the built-in fallback above -- a partial,
    malformed, or absent file never breaks the panel, it just falls back
    field-by-field."""
    merged = json.loads(json.dumps(_HARDCODED_DEFAULTS))  # deep copy

    try:
        with open(_DEFAULTS_PATH, "r", encoding="utf-8") as f:
            user = json.load(f)
    except FileNotFoundError:
        return merged
    except Exception as e:
        lf.log.error(f"CameraPathSC: DEFAULTS.JSON is invalid, using built-in defaults ({e})")
        return merged

    for key in ("anim_type", "direction", "follow_y", "auto_target", "add_start_end_keys", "output_filename"):
        if key in user:
            merged[key] = user[key]

    user_fields = user.get("fields", {})
    if isinstance(user_fields, dict):
        for name, spec in user_fields.items():
            if name not in merged["fields"] or not isinstance(spec, dict):
                continue  # unknown field name or bad shape -- ignore, don't crash
            for k in ("value", "min", "max", "step", "int"):
                if k in spec:
                    merged["fields"][name][k] = spec[k]

    return merged

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


def _compute_frame_indices(frames: int, kstep: int, add_start_end: bool) -> list:
    """Frame indices to place keyframes at: evenly stepped by kstep, plus
    -- if add_start_end is on -- two extra keys just inside the first and
    last generated frame (start+1, finish-1). Those two extra keys pin the
    spline's tangent near the very start/end of the path, which otherwise
    tends to flatten out ("ease") right at the boundary keyframes in a
    spline-interpolated sequencer track. Shared by _generate() and the
    panel's keyframe-count display so they always agree."""
    frame_set = set(range(0, max(1, frames), max(1, kstep)))
    if add_start_end and frame_set:
        first = min(frame_set)
        last = max(frame_set)
        if first + 1 < last:
            frame_set.add(first + 1)
        if last - 1 > first:
            frame_set.add(last - 1)
    return sorted(frame_set)


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
    add_start_end = bool(state.get("add_start_end_keys", True))
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
    for frame_idx in _compute_frame_indices(frames, kstep, add_start_end):
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


# ── Pick-point draw handler ─────────────────────────────────────────────────
# Mirrors the DoF plugin's point_picker viz: a small on-screen marker at the
# last picked position plus a "PICK ..." hint while a pick is in progress.

_draw_handler_registered = False
panel: "MainPanel | None" = None

def _campath_draw_handler(ctx):
    global panel
    if panel is None:
        return

    if panel._centre_marker_pos is not None:
        ctx.draw_point_3d(panel._centre_marker_pos, (0.0, 1.0, 0.5, 1.0), 16.0)
        screen = ctx.world_to_screen(panel._centre_marker_pos)
        if screen:
            ctx.draw_circle_2d(screen, 12.0, (0.0, 1.0, 0.5, 1.0), 2.0)
            ctx.draw_text_2d((screen[0] + 14, screen[1] - 8), "Orbit Centre", (0.0, 1.0, 0.5, 1.0))

    if panel._target_marker_pos is not None:
        ctx.draw_point_3d(panel._target_marker_pos, (1.0, 0.5, 0.0, 1.0), 16.0)
        screen = ctx.world_to_screen(panel._target_marker_pos)
        if screen:
            ctx.draw_circle_2d(screen, 12.0, (1.0, 0.5, 0.0, 1.0), 2.0)
            ctx.draw_text_2d((screen[0] + 14, screen[1] - 8), "Look Target", (1.0, 0.5, 0.0, 1.0))

    if panel._radius_marker_pos is not None:
        ctx.draw_point_3d(panel._radius_marker_pos, (0.4, 0.7, 1.0, 1.0), 16.0)
        # Line from orbit centre out to the picked radius point, so the
        # horizontal (XZ) distance being measured is visually obvious.
        if panel._centre_marker_pos is not None:
            try:
                ctx.draw_line_3d(panel._centre_marker_pos, panel._radius_marker_pos, (0.4, 0.7, 1.0, 0.8), 2.0)
            except Exception:
                pass
        screen = ctx.world_to_screen(panel._radius_marker_pos)
        if screen:
            ctx.draw_circle_2d(screen, 12.0, (0.4, 0.7, 1.0, 1.0), 2.0)
            ctx.draw_text_2d((screen[0] + 14, screen[1] - 8), f"Radius: {panel._radius:.2f}", (0.4, 0.7, 1.0, 1.0))

    # Spiral Start Radius / End Radius markers -- same horizontal-distance-
    # from-centre viz as circular Radius, just a different colour each.
    _SPIRAL_RADIUS_COLORS = {4: (1.0, 0.85, 0.3, 1.0), 5: (1.0, 0.3, 0.7, 1.0)}
    for tnum, color in _SPIRAL_RADIUS_COLORS.items():
        info = panel._RADIUS_TARGETS[tnum]
        marker = getattr(panel, info["marker"])
        if marker is None:
            continue
        ctx.draw_point_3d(marker, color, 16.0)
        if panel._centre_marker_pos is not None:
            try:
                ctx.draw_line_3d(panel._centre_marker_pos, marker, (color[0], color[1], color[2], 0.8), 2.0)
            except Exception:
                pass
        screen = ctx.world_to_screen(marker)
        if screen:
            ctx.draw_circle_2d(screen, 12.0, color, 2.0)
            val = getattr(panel, f"_{info['attr']}")
            ctx.draw_text_2d((screen[0] + 14, screen[1] - 8), f"{info['label']}: {val:.2f}", color)

    if panel._picking_target > 0:
        label = {1: "ORBIT CENTRE", 2: "LOOK TARGET", 3: "RADIUS",
                  4: "START RADIUS", 5: "END RADIUS"}.get(panel._picking_target, "")
        ctx.draw_text_2d(
            (20, 50),
            f"PICK {label}: Click on model  (ESC / Right-click to cancel)",
            (0.0, 1.0, 0.5, 0.95),
        )
    elif panel._editing_target > 0:
        label = {1: "ORBIT CENTRE", 2: "LOOK TARGET", 3: "RADIUS",
                  4: "START RADIUS", 5: "END RADIUS"}.get(panel._editing_target, "")
        ctx.draw_text_2d(
            (20, 50),
            f"EDIT {label}: Drag the gizmo  (click Stop Editing when done)",
            (0.4, 0.7, 1.0, 0.95),
        )

def _ensure_draw_handler():
    global _draw_handler_registered
    if not _draw_handler_registered:
        try:
            lf.remove_draw_handler("campath_pick_overlay")
        except Exception:
            pass
        lf.add_draw_handler("campath_pick_overlay", _campath_draw_handler, "POST_VIEW")
        _draw_handler_registered = True


# ── Edit-gizmo tool registration ────────────────────────────────────────────
# LFS gizmos are driven by the currently ACTIVE TOOL (a ToolDef with
# gizmo="translate"), not by node selection alone -- selecting a node with
# no translate-tool active shows no gizmo at all. So Edit needs its own
# registered tool to switch into while dragging, and switches back to
# whatever was active before on Stop Editing.

_EDIT_TOOL_ID = "CamPath_Json.tools.point_edit"
_edit_tool_registered = False

def _ensure_edit_tool():
    global _edit_tool_registered
    if _edit_tool_registered:
        return
    try:
        from lfs_plugins.tool_defs.definition import ToolDef
        from lfs_plugins.tools import ToolRegistry
        tool = ToolDef(
            id=_EDIT_TOOL_ID,
            label="Edit Camera Path Point",
            icon="translation",
            group="transform",
            order=500,
            description="Drag the gizmo to move the Orbit Centre / Look Target / Radius point.",
            gizmo="translate",
        )
        ToolRegistry.register_tool(tool)
        _edit_tool_registered = True
    except Exception as e:
        lf.log.warning(f"CamPath edit-tool registration error: {e}")

def _unregister_edit_tool():
    global _edit_tool_registered
    if not _edit_tool_registered:
        return
    try:
        from lfs_plugins.tools import ToolRegistry
        ToolRegistry.unregister_tool(_EDIT_TOOL_ID)
    except Exception:
        pass
    _edit_tool_registered = False


def _flip_yz(pos):
    """Convert between pick/world-space (x, y, z) -- used by cx/cy/cz, the
    picked-point markers, and world_to_screen() -- and scene-node transform
    space, which uses a Y/Z convention negated from it. Self-inverse: apply
    the same conversion both when seeding the gizmo node and when reading
    its dragged transform back."""
    x, y, z = pos
    return (x, -y, -z)


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
        global panel
        panel = self

        # Pick Point (Orbit Centre / Look Target / Radius fields) — 0=idle,
        # 1=picking centre, 2=picking look target, 3=circular radius,
        # 4=spiral start_radius, 5=spiral end_radius. Marker positions are
        # kept for the viewport overlay only; cx/cy/cz, tx/ty/tz, radius,
        # start_radius and end_radius remain the source of truth.
        self._picking_target   = 0
        self._centre_marker_pos = None
        self._target_marker_pos = None
        self._radius_marker_pos = None
        self._start_radius_marker_pos = None
        self._end_radius_marker_pos   = None

        # Edit gizmo (Orbit Centre / Look Target / Radius) — same target_num
        # convention as picking. Backed by a throwaway proxy locator node
        # since LFS gizmos bind to real scene-node transforms, not bare
        # floats; created on Edit, deleted on Stop Editing.
        self._editing_target   = 0
        self._editing_node_name = None
        self._prev_tool_id      = None

        d = _load_defaults()
        f = d["fields"]

        # Animation type & direction
        self._anim_type   = d.get("anim_type", "circular")
        self._direction   = d.get("direction", "clockwise")
        self._follow_y    = bool(d.get("follow_y", False))
        self._auto_target = bool(d.get("auto_target", False))
        self._add_start_end_keys = bool(d.get("add_start_end_keys", True))

        # Per-field numeric spec (value/min/max/step/int), keyed by name.
        # Drives both the initial value and the slider's data-attr-bound range.
        self._numeric_specs = {}
        for name, is_int, lo, hi, step in _FIELD_SPEC_ORDER:
            spec = f.get(name, {})
            fis_int = bool(spec.get("int", is_int))
            fmin    = float(spec.get("min", lo))
            fmax    = float(spec.get("max", hi))
            fstep   = float(spec.get("step", step))
            fval    = float(spec.get("value", _FIELD_VALUE_DEFAULTS[name]))
            if fis_int:
                fval = float(int(round(fval)))

            float_attr = f"_{name}"
            text_attr  = f"_{name}_text"
            setattr(self, float_attr, fval)
            setattr(self, text_attr, self._fmt_num(fval, fis_int))

            self._numeric_specs[name] = dict(
                float_attr=float_attr, text_attr=text_attr,
                is_int=fis_int, min=fmin, max=fmax, step=fstep,
            )

        # Output path
        self._output_path = str(_SCRIPTS_DIR / d.get("output_filename", "camera_path.json"))

        # Status
        self._status    = ""
        self._status_ok = True

        # Section collapse state -- everything starts expanded.
        self._sec_anim      = True
        self._sec_centre    = True
        self._sec_target    = True
        self._sec_camera    = True
        self._sec_export    = True
        self._sec_sequencer = True

        self._handle = None

    # ------------------------------------------------------------------
    # Retained data model
    # ------------------------------------------------------------------

    # (model_name, attr, python_type) -- non-numeric fields
    _SIMPLE_FIELDS = [
        ("anim_type", "_anim_type", str),
        ("direction", "_direction", str),
        ("follow_y", "_follow_y", bool),
        ("auto_target", "_auto_target", bool),
        ("add_start_end_keys", "_add_start_end_keys", bool),
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
                pass  # ignore transient/invalid input
        model.bind(name, lambda a=attr: getattr(self, a), setter)

    @staticmethod
    def _fmt_num(v: float, is_int: bool) -> str:
        if is_int:
            return str(int(round(v)))
        v = round(v, 4)
        s = f"{v:.4f}".rstrip("0").rstrip(".")
        return s if s not in ("", "-") else "0"

    def _bind_numeric(self, model, name, float_attr, text_attr, is_int):
        # Slider side: always a valid float, source of truth.
        def slider_get(fa=float_attr):
            return getattr(self, fa)

        def slider_set(v, fa=float_attr, ta=text_attr, ii=is_int, nm=name):
            try:
                fv = float(v)
            except (TypeError, ValueError):
                return
            if ii:
                fv = float(int(round(fv)))
            setattr(self, fa, fv)
            setattr(self, ta, self._fmt_num(fv, ii))
            if self._handle is not None:
                self._handle.dirty(f"{nm}_text")

        model.bind(name, slider_get, slider_set)

        # Text side: freely editable, never reformatted while typing.
        # Only pushes to the numeric/slider side once it parses cleanly.
        def text_get(ta=text_attr):
            return getattr(self, ta)

        def text_set(v, fa=float_attr, ta=text_attr, ii=is_int, nm=name):
            setattr(self, ta, str(v))
            try:
                fv = float(v)
            except (TypeError, ValueError):
                return  # mid-typing (e.g. "-2.") -- leave numeric value alone
            if ii:
                fv = float(int(round(fv)))
            setattr(self, fa, fv)
            if self._handle is not None:
                self._handle.dirty(nm)

        model.bind(f"{name}_text", text_get, text_set)

    def on_bind_model(self, ctx):
        _ensure_draw_handler()
        model = ctx.create_data_model(MODEL_NAME)
        if model is None:
            return

        for name, attr, cast in self._SIMPLE_FIELDS:
            self._bind_two_way(model, name, attr, cast)

        for name, spec in self._numeric_specs.items():
            self._bind_numeric(model, name, spec["float_attr"], spec["text_attr"], spec["is_int"])

        model.bind_func("status", lambda: self._status)
        model.bind_func("status_ok", lambda: self._status_ok)
        model.bind_func("is_spiral", lambda: self._anim_type == "spiral")
        model.bind_func("duration_text", self._duration_text)
        model.bind_func("fov_text", self._fov_text)
        model.bind_func("keyframe_warning_text", self._keyframe_warning_text)

        # ── Pick Point: Orbit Centre / Look Target / Radius fields ──────────
        model.bind_func("picking_centre",     lambda: self._picking_target == 1)
        model.bind_func("not_picking_centre", lambda: self._picking_target != 1)
        model.bind_func("picking_target",     lambda: self._picking_target == 2)
        model.bind_func("not_picking_target", lambda: self._picking_target != 2)
        model.bind_func("picking_radius",     lambda: self._picking_target == 3)
        model.bind_func("not_picking_radius", lambda: self._picking_target != 3)
        model.bind_func("picking_start_radius", lambda: self._picking_target == 4)
        model.bind_func("picking_end_radius",   lambda: self._picking_target == 5)
        model.bind_event("pick_centre",       self._on_pick_centre)
        model.bind_event("pick_target",       self._on_pick_target)
        model.bind_event("pick_radius",       self._on_pick_radius)
        model.bind_event("pick_start_radius", self._on_pick_start_radius)
        model.bind_event("pick_end_radius",   self._on_pick_end_radius)
        model.bind_event("stop_pick_target",  self._on_stop_pick_target)
        model.bind_event("update_centre",     self._on_update_centre_marker)
        model.bind_event("update_target",     self._on_update_target_marker)
        model.bind_event("update_radius",     self._on_update_radius_marker)
        model.bind_event("update_start_radius", self._on_update_start_radius_marker)
        model.bind_event("update_end_radius",   self._on_update_end_radius_marker)

        # ── Edit Gizmo: Orbit Centre / Look Target / Radius fields ──────────
        model.bind_func("editing_centre",     lambda: self._editing_target == 1)
        model.bind_func("editing_target",     lambda: self._editing_target == 2)
        model.bind_func("editing_radius",     lambda: self._editing_target == 3)
        model.bind_func("editing_start_radius", lambda: self._editing_target == 4)
        model.bind_func("editing_end_radius",   lambda: self._editing_target == 5)
        # "idle" == neither picking nor editing this section -- gates the
        # Pick/Update/Edit button row so it hides while either is active.
        model.bind_func("centre_idle",  lambda: self._picking_target != 1 and self._editing_target != 1)
        model.bind_func("target_idle",  lambda: self._picking_target != 2 and self._editing_target != 2)
        model.bind_func("radius_idle",  lambda: self._picking_target != 3 and self._editing_target != 3)
        model.bind_func("start_radius_idle", lambda: self._picking_target != 4 and self._editing_target != 4)
        model.bind_func("end_radius_idle",   lambda: self._picking_target != 5 and self._editing_target != 5)
        model.bind_event("edit_centre",       self._on_edit_centre)
        model.bind_event("edit_target",       self._on_edit_target)
        model.bind_event("edit_radius",       self._on_edit_radius)
        model.bind_event("edit_start_radius", self._on_edit_start_radius)
        model.bind_event("edit_end_radius",   self._on_edit_end_radius)
        model.bind_event("stop_edit_target",  self._on_stop_edit_target)

        self._handle = model.get_handle()

    def _keyframe_count(self) -> int:
        frames = max(1, int(round(self._frames)))
        kstep  = max(1, int(round(self._keyframe_step)))
        return len(_compute_frame_indices(frames, kstep, bool(self._add_start_end_keys)))

    def _keyframe_warning_text(self) -> str:
        kf_count = self._keyframe_count()
        if kf_count > MAX_RECOMMENDED_KEYFRAMES:
            return (f"\u26a0 {kf_count} keyframes exceeds the recommended "
                    f"{MAX_RECOMMENDED_KEYFRAMES} — raise \"Keyframe N Frames\" "
                    f"or reduce Frames.")
        return ""

    def _duration_text(self) -> str:
        frames = max(1, int(round(self._frames)))
        fps    = max(1, int(round(self._fps)))
        duration = frames / fps
        return f"Duration: {duration:.1f}s   |   Keyframes: {self._keyframe_count()}"

    def _fov_text(self) -> str:
        sensor = self._sensor_size
        focal  = self._focal_length
        fov = 2.0 * math.degrees(math.atan(sensor / (2.0 * max(0.1, focal))))
        return f"Horizontal FOV: {fov:.1f}°"

    def _set_status(self, msg: str, ok: bool = True):
        self._status = msg
        self._status_ok = ok
        if self._handle is not None:
            self._handle.dirty_all()

    # ------------------------------------------------------------------
    # Pick Point: Orbit Centre / Look Target / Radius
    # ------------------------------------------------------------------
    # Same _pending_pick / modal-operator pattern as the DoF plugin's
    # Pick Point 1/2: the operator deposits a result on click, on_update()
    # consumes it on the main thread. The modal is single-shot (see
    # operators/point_picker.py) so it finishes itself on the first click --
    # no ESC/right-click needed to "release" control; those still work to
    # back out of a pick before clicking.
    # target_num: 1 = orbit centre, 2 = look target, 3 = radius.

    _PICK_LABELS = {1: "Orbit Centre", 2: "Look Target", 3: "Radius",
                     4: "Start Radius", 5: "End Radius"}

    # target_num -> field this radius pick/update/edit drives. Shared by
    # circular Radius (3) and spiral Start/End Radius (4, 5) -- all three
    # measure horizontal (XZ) distance from the Orbit Centre the same way.
    _RADIUS_TARGETS = {
        3: {"attr": "radius",       "marker": "_radius_marker_pos",       "label": "Radius"},
        4: {"attr": "start_radius", "marker": "_start_radius_marker_pos", "label": "Start Radius"},
        5: {"attr": "end_radius",   "marker": "_end_radius_marker_pos",   "label": "End Radius"},
    }

    def _start_picking_target(self, target_num: int):
        self._picking_target = target_num
        self._set_status(f"Click on model to pick {self._PICK_LABELS.get(target_num, '')}...")
        from ..operators.point_picker import set_pick_callback
        set_pick_callback(self._on_pick_target_result, target_num)
        try:
            lf.ui.ops.invoke(
                "lfs_plugins.CamPath_Json.operators.point_picker.CAMPATH_OT_pick_point"
            )
        except Exception as e:
            lf.log.warning(f"CamPath pick start error: {e}")

    def _cancel_picking_target(self):
        self._picking_target = 0
        from ..operators.point_picker import clear_pick_callback
        clear_pick_callback()
        try:
            lf.ui.ops.cancel_modal()
        except Exception:
            pass
        # sel.pick_at_screen() can select the underlying model/splat as a
        # raycast side effect -- clear it so the Select-tool floating
        # toolbar doesn't linger after picking.
        try:
            lf.deselect_all()
        except Exception:
            pass
        self._set_status("Picking cancelled")

    def _on_pick_target_result(self, world_pos, target_num):
        """Called (indirectly, via on_update) once a click lands on the model."""
        x, y, z = float(world_pos[0]), float(world_pos[1]), float(world_pos[2])
        if target_num == 1:
            self._centre_marker_pos = (x, y, z)
            self._cx, self._cy, self._cz = x, y, z
            self._cx_text = self._fmt_num(x, False)
            self._cy_text = self._fmt_num(y, False)
            self._cz_text = self._fmt_num(z, False)
            self._set_status(f"Orbit Centre picked: ({x:.2f}, {y:.2f}, {z:.2f})")
        elif target_num == 2:
            self._target_marker_pos = (x, y, z)
            self._tx, self._ty, self._tz = x, y, z
            self._tx_text = self._fmt_num(x, False)
            self._ty_text = self._fmt_num(y, False)
            self._tz_text = self._fmt_num(z, False)
            # A picked look target is an explicit choice -- stop overriding
            # it with the orbit centre.
            self._auto_target = False
            self._set_status(f"Look Target picked: ({x:.2f}, {y:.2f}, {z:.2f})")
        elif target_num in self._RADIUS_TARGETS:
            # Radius (circular / spiral start / spiral end): horizontal (XZ)
            # distance from the orbit centre to the picked point, matching
            # how these are actually used in the path math (px = cx + r*sin,
            # pz = cz + r*cos -- Y/height is independent, not part of this).
            info = self._RADIUS_TARGETS[target_num]
            setattr(self, info["marker"], (x, y, z))
            dx = x - self._cx
            dz = z - self._cz
            r = math.hypot(dx, dz)
            spec = self._numeric_specs.get(info["attr"])
            if spec:
                r = max(spec["min"], min(spec["max"], r))
                if spec["is_int"]:
                    r = float(int(round(r)))
            setattr(self, f"_{info['attr']}", r)
            setattr(self, f"_{info['attr']}_text", self._fmt_num(r, bool(spec and spec["is_int"])))
            self._set_status(f"{info['label']} picked: {r:.2f} (from Orbit Centre)")
        self._picking_target = 0
        # sel.pick_at_screen() (in the modal operator) can select the
        # underlying model/splat as a raycast side effect -- clear it so
        # the Select-tool floating toolbar doesn't linger after picking.
        try:
            lf.deselect_all()
        except Exception:
            pass
        if self._handle is not None:
            self._handle.dirty_all()

    def _on_pick_centre(self, h, e, a):
        self._start_picking_target(1)

    def _on_pick_target(self, h, e, a):
        self._start_picking_target(2)

    def _on_pick_radius(self, h, e, a):
        self._start_picking_target(3)

    def _on_pick_start_radius(self, h, e, a):
        self._start_picking_target(4)

    def _on_pick_end_radius(self, h, e, a):
        self._start_picking_target(5)

    def _on_stop_pick_target(self, h, e, a):
        self._cancel_picking_target()
        if self._handle is not None:
            self._handle.dirty_all()

    # ------------------------------------------------------------------
    # Update markers from manually-edited field values (no picking).
    # ------------------------------------------------------------------

    def _on_update_centre_marker(self, h, e, a):
        self._centre_marker_pos = (self._cx, self._cy, self._cz)
        self._set_status(f"Orbit Centre marker updated: ({self._cx:.2f}, {self._cy:.2f}, {self._cz:.2f})")
        if self._handle is not None:
            self._handle.dirty_all()

    def _on_update_target_marker(self, h, e, a):
        self._target_marker_pos = (self._tx, self._ty, self._tz)
        self._set_status(f"Look Target marker updated: ({self._tx:.2f}, {self._ty:.2f}, {self._tz:.2f})")
        if self._handle is not None:
            self._handle.dirty_all()

    def _radius_extrapolated_point(self, r: float, marker_attr: str = "_radius_marker_pos"):
        """Point at horizontal distance r from the Orbit Centre, along the
        same direction as the last picked/updated/edited point for that
        radius field (or a default +Z direction if none exists yet).
        Shared by Update and Edit for Radius / Start Radius / End Radius."""
        cx, cy, cz = self._cx, self._cy, self._cz
        marker = getattr(self, marker_attr)
        if marker is not None:
            dx = marker[0] - cx
            dz = marker[2] - cz
            y  = marker[1]
        else:
            dx, dz, y = 0.0, 1.0, cy

        horiz = math.hypot(dx, dz)
        if horiz < 1e-6:
            dx, dz, horiz = 0.0, 1.0, 1.0
        ux, uz = dx / horiz, dz / horiz
        return (cx + ux * r, y, cz + uz * r)

    def _update_radius_target(self, target_num: int):
        """Rescale a radius marker (Radius / Start Radius / End Radius) to
        its current field value.

        There's no model geometry to re-pick against a bare number, so this
        extrapolates/interpolates along the same horizontal direction as the
        last picked/updated point for that field (or a default +Z direction
        if none exists yet), moving it to the new distance from Orbit Centre.
        """
        info = self._RADIUS_TARGETS[target_num]
        r = getattr(self, f"_{info['attr']}")
        setattr(self, info["marker"], self._radius_extrapolated_point(r, info["marker"]))
        self._set_status(f"{info['label']} marker updated: {r:.2f} (from Orbit Centre)")
        if self._handle is not None:
            self._handle.dirty_all()

    def _on_update_radius_marker(self, h, e, a):
        self._update_radius_target(3)

    def _on_update_start_radius_marker(self, h, e, a):
        self._update_radius_target(4)

    def _on_update_end_radius_marker(self, h, e, a):
        self._update_radius_target(5)

    # ------------------------------------------------------------------
    # Edit Gizmo: Orbit Centre / Look Target / Radius
    # ------------------------------------------------------------------
    # LFS gizmos bind to a real scene-node's transform, not a bare float
    # triple, so "Edit" creates a small throwaway proxy/locator node, seeds
    # its transform, and selects it so the built-in Move gizmo attaches.
    # While editing, on_update() polls the node's transform each tick and
    # mirrors it back into cx/cy/cz (etc). "Stop Editing" deletes the node
    # -- nothing lingers in the Scene tree afterward.

    _EDIT_NODE_NAMES = {
        1: "[CamPath] Orbit Centre (editing)",
        2: "[CamPath] Look Target (editing)",
        3: "[CamPath] Radius Point (editing)",
        4: "[CamPath] Start Radius Point (editing)",
        5: "[CamPath] End Radius Point (editing)",
    }

    def _start_editing_target(self, target_num: int):
        if self._editing_target == target_num:
            return
        if self._editing_target:
            self._stop_editing_target()

        if not lf.has_scene():
            self._set_status("No scene loaded -- can't place an edit gizmo.", ok=False)
            return

        # Capture the currently-active tool BEFORE we touch selection at all --
        # select_node() below may itself auto-switch the active tool to
        # "Select", and if we captured after that we'd just be recording our
        # own side effect and always restoring into Select on Stop Editing.
        try:
            self._prev_tool_id = lf.ui.get_active_tool()
        except Exception:
            self._prev_tool_id = None
        lf.log.info(f"CamPath start-edit: captured prev_tool_id={self._prev_tool_id!r}")

        name = self._EDIT_NODE_NAMES[target_num]
        if target_num == 1:
            pos = (self._cx, self._cy, self._cz)
        elif target_num == 2:
            pos = (self._tx, self._ty, self._tz)
        else:
            info = self._RADIUS_TARGETS[target_num]
            r = getattr(self, f"_{info['attr']}")
            pos = self._radius_extrapolated_point(r, info["marker"])

        try:
            scene = lf.get_scene()
            try:
                # Clean up a stale node from a previous session that didn't
                # get removed (e.g. the app closed mid-edit).
                scene.remove_node(name, keep_children=False)
            except Exception:
                pass
            scene.add_group(name)
            node_pos = _flip_yz(pos)
            matrix = lf.compose_transform(translation=list(node_pos), euler_deg=[0.0, 0.0, 0.0], scale=[1.0, 1.0, 1.0])
            lf.set_node_transform(name, matrix)
            lf.select_node(name)

            # Switch to the translate-gizmo tool -- selection alone doesn't
            # show a gizmo, the active tool has to be one with gizmo="translate".
            _ensure_edit_tool()
            from lfs_plugins.tools import ToolRegistry
            activated = ToolRegistry.set_active(_EDIT_TOOL_ID)
            try:
                now_active = ToolRegistry.get_active_id()
            except Exception:
                now_active = "?"
            lf.log.info(
                f"CamPath start-edit: activate({_EDIT_TOOL_ID!r}) returned "
                f"{activated!r}, active_tool_now={now_active!r}"
            )
            try:
                lf.ui.request_redraw()
            except Exception:
                pass
        except Exception as e:
            lf.log.warning(f"CamPath edit-gizmo start error: {e}")
            self._set_status(f"Couldn't start editing: {e}", ok=False)
            return

        self._editing_target = target_num
        self._editing_node_name = name
        self._set_status(f"Drag the gizmo to move {self._PICK_LABELS.get(target_num, '')}...")
        if self._handle is not None:
            self._handle.dirty_all()

    def _stop_editing_target(self):
        if not self._editing_target:
            return
        name = self._editing_node_name
        # Deselect BEFORE removing the node -- removing it while still
        # selected can leave a stale selection reference behind that the
        # Select-tool's floating toolbar doesn't clear on its own.
        try:
            lf.deselect_all()
        except Exception:
            pass
        try:
            scene = lf.get_scene()
            if scene is not None and name:
                scene.remove_node(name, keep_children=False)
        except Exception as e:
            lf.log.warning(f"CamPath edit-gizmo cleanup error: {e}")

        from lfs_plugins.tools import ToolRegistry
        restored = False
        # NOTE: '' is a legitimate "no tool was active" value (confirmed via
        # logging), not an absence of one -- `if self._prev_tool_id:` would
        # silently skip restoring it since empty string is falsy in Python.
        # `is not None` treats '' as something to actively restore.
        if self._prev_tool_id is not None:
            try:
                restored = ToolRegistry.set_active(self._prev_tool_id)
            except Exception as e:
                lf.log.warning(f"CamPath restore-tool error: {e}")
        try:
            now_active = ToolRegistry.get_active_id()
        except Exception:
            now_active = "?"
        lf.log.info(
            f"CamPath stop-edit: prev_tool_id={self._prev_tool_id!r} "
            f"restore_call_returned={restored} active_tool_now={now_active!r}"
        )

        self._prev_tool_id = None
        self._editing_target = 0
        self._editing_node_name = None
        # Remove the edit tool from the toolbar again -- it should only be
        # visible/selectable there for the duration of an active edit
        # session, not sit around as a standing option.
        _unregister_edit_tool()

    def _poll_editing_target(self):
        """Called every on_update() tick while an edit gizmo is active."""
        if not self._editing_target or not self._editing_node_name:
            return
        try:
            matrix = lf.get_node_transform(self._editing_node_name)
            node_pos = lf.decompose_transform(matrix)["translation"]
            x, y, z = _flip_yz((float(node_pos[0]), float(node_pos[1]), float(node_pos[2])))
        except Exception:
            return

        if self._editing_target == 1:
            self._cx, self._cy, self._cz = x, y, z
            self._cx_text = self._fmt_num(x, False)
            self._cy_text = self._fmt_num(y, False)
            self._cz_text = self._fmt_num(z, False)
            self._centre_marker_pos = (x, y, z)
        elif self._editing_target == 2:
            self._tx, self._ty, self._tz = x, y, z
            self._tx_text = self._fmt_num(x, False)
            self._ty_text = self._fmt_num(y, False)
            self._tz_text = self._fmt_num(z, False)
            self._target_marker_pos = (x, y, z)
            self._auto_target = False
        elif self._editing_target in self._RADIUS_TARGETS:
            info = self._RADIUS_TARGETS[self._editing_target]
            setattr(self, info["marker"], (x, y, z))
            dx = x - self._cx
            dz = z - self._cz
            r = math.hypot(dx, dz)
            spec = self._numeric_specs.get(info["attr"])
            if spec:
                r = max(spec["min"], min(spec["max"], r))
                if spec["is_int"]:
                    r = float(int(round(r)))
            setattr(self, f"_{info['attr']}", r)
            setattr(self, f"_{info['attr']}_text", self._fmt_num(r, bool(spec and spec["is_int"])))

        if self._handle is not None:
            self._handle.dirty_all()

    def _on_edit_centre(self, h, e, a):
        self._start_editing_target(1)

    def _on_edit_target(self, h, e, a):
        self._start_editing_target(2)

    def _on_edit_radius(self, h, e, a):
        self._start_editing_target(3)

    def _on_edit_start_radius(self, h, e, a):
        self._start_editing_target(4)

    def _on_edit_end_radius(self, h, e, a):
        self._start_editing_target(5)

    def _on_stop_edit_target(self, h, e, a):
        self._stop_editing_target()
        self._set_status("Editing stopped")
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

        # Consume any pick result deposited by the modal operator this frame.
        from ..operators.point_picker import was_pick_cancelled, consume_pending_pick
        pending = consume_pending_pick()
        if pending is not None:
            world_pos, target_num = pending
            self._on_pick_target_result(world_pos, target_num)

        # Poll for ESC/right-click cancel from the modal operator.
        if was_pick_cancelled() and self._picking_target > 0:
            self._picking_target = 0
            self._set_status("Picking cancelled")

        # Mirror the edit-gizmo proxy node's transform back into fields.
        self._poll_editing_target()

        # Recorded values (frames/fps/focal length/etc.) can change fields
        # that feed the derived text -- keep those live.
        if self._handle is not None:
            self._handle.dirty("duration_text")
            self._handle.dirty("fov_text")
            self._handle.dirty("is_spiral")
            self._handle.dirty("keyframe_warning_text")
            self._handle.dirty("picking_centre")
            self._handle.dirty("not_picking_centre")
            self._handle.dirty("picking_target")
            self._handle.dirty("not_picking_target")
            self._handle.dirty("picking_radius")
            self._handle.dirty("not_picking_radius")
            self._handle.dirty("picking_start_radius")
            self._handle.dirty("picking_end_radius")
            self._handle.dirty("editing_centre")
            self._handle.dirty("editing_target")
            self._handle.dirty("editing_radius")
            self._handle.dirty("editing_start_radius")
            self._handle.dirty("editing_end_radius")
            self._handle.dirty("centre_idle")
            self._handle.dirty("target_idle")
            self._handle.dirty("radius_idle")
            self._handle.dirty("start_radius_idle")
            self._handle.dirty("end_radius_idle")

    def on_unmount(self, doc):
        del doc
        # Don't leave a stray proxy node behind if the panel closes mid-edit.
        self._stop_editing_target()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _build_state(self) -> dict:
        return dict(
            anim_type=self._anim_type,
            direction=self._direction,
            radius=self._radius,
            loops=self._loops,
            start_radius=self._start_radius,
            end_radius=self._end_radius,
            start_height=self._start_height,
            end_height=self._end_height,
            follow_y=self._follow_y,
            y_offset=self._y_offset,
            cx=self._cx, cy=self._cy, cz=self._cz,
            auto_target=self._auto_target,
            tx=self._tx, ty=self._ty, tz=self._tz,
            frames=max(1, int(round(self._frames))),
            fps=max(1, int(round(self._fps))),
            focal_length=self._focal_length,
            sensor_size=self._sensor_size,
            precision=max(0, int(round(self._precision))),
            keyframe_step=max(1, int(round(self._keyframe_step))),
            add_start_end_keys=self._add_start_end_keys,
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
            msg = f"\u2713 Saved {kf_count} keyframes \u2192 {out}"
            if kf_count > MAX_RECOMMENDED_KEYFRAMES:
                msg += f"  (\u26a0 exceeds recommended {MAX_RECOMMENDED_KEYFRAMES})"
            self._set_status(msg)
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
