# SPDX-FileCopyrightText: 2025 LichtFeld Studio Authors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Point picker operator - modal operator for picking points on the model.

Ported from the DoF plugin's point_picker.py, unchanged in structure:
the operator deposits a result into module-level state; the panel's
on_update() consumes it on the main thread (do NOT call panel methods
directly from the operator - wrong thread / re-entrancy).
"""

from typing import Optional, Tuple

import lichtfeld as lf
import lichtfeld.selection as sel
from lfs_plugins.types import Operator, Event


# Module-level state for the _pending_pick pattern.
# The operator deposits a result here; on_update() in the panel consumes it.
_on_point_picked_callback = None  # callable(world_pos, target_num) set by the panel
_pick_target_num = 0
_pick_cancelled = False           # Set to True when operator is ESC/right-click cancelled
_pending_pick: Optional[Tuple] = None  # (world_position, target_num) awaiting on_update


def set_pick_callback(callback, target_num: int):
    """Set the module-level callback and arm a fresh pick session."""
    global _on_point_picked_callback, _pick_target_num, _pick_cancelled, _pending_pick
    _on_point_picked_callback = callback
    _pick_target_num = target_num
    _pick_cancelled = False
    _pending_pick = None


def clear_pick_callback():
    """Clear the pick callback and signal cancellation."""
    global _on_point_picked_callback, _pick_target_num, _pick_cancelled, _pending_pick
    _on_point_picked_callback = None
    _pick_target_num = 0
    _pick_cancelled = True
    _pending_pick = None


def was_pick_cancelled():
    """Check if pick was cancelled and clear the flag."""
    global _pick_cancelled
    if _pick_cancelled:
        _pick_cancelled = False
        return True
    return False


def consume_pending_pick() -> Optional[Tuple]:
    """Return and clear the pending pick result, or None if nothing is pending."""
    global _pending_pick
    result, _pending_pick = _pending_pick, None
    return result


def _end_pick_session():
    """Clear callback/target state after a successful single-shot pick.

    Unlike clear_pick_callback(), this does NOT set _pick_cancelled -- the
    pick succeeded, it just doesn't need another click, so the panel's
    on_update() shouldn't treat it as a cancel.
    """
    global _on_point_picked_callback, _pick_target_num
    _on_point_picked_callback = None
    _pick_target_num = 0


class CAMPATH_OT_pick_point(Operator):
    """Modal operator for picking a single point on the gaussian splat model.

    Single-shot: the first successful click deposits the result and ends
    the modal itself (no ESC/right-click needed to "release" control).
    ESC/right-click still works to back out of a pick before clicking.
    """

    # Full dotted ID required by the host: lfs_plugins.<PluginDir>.module.ClassName
    # (the "lfs_plugins." prefix is the host's own namespace for every loaded
    # plugin -- not part of this plugin's pyproject name -- confirmed by the
    # DoF plugin's id "lfs_plugins.DoF.operators.point_picker.DEPTHMAP_OT_pick_point")
    id          = "lfs_plugins.CamPath_Json.operators.point_picker.CAMPATH_OT_pick_point"
    label       = "Pick Camera Path Point"
    description = "Click on the model to pick a point for orbit centre / look target / radius"
    options     = {'BLOCKING'}

    def invoke(self, context, event: Event) -> set:
        """Start modal mode."""
        return {'RUNNING_MODAL'}

    def modal(self, context, event: Event) -> set:
        """Deposit a pick result into _pending_pick; panel's on_update() consumes it."""
        global _pending_pick, _pick_target_num

        if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
            result = sel.pick_at_screen(event.mouse_region_x, event.mouse_region_y)
            if result is not None and _on_point_picked_callback is not None:
                # Deposit the result for on_update() to consume — do NOT call the
                # panel method directly from the operator (wrong thread / re-entrancy).
                _pending_pick = (result.world_position, _pick_target_num)
                _end_pick_session()
                return {'FINISHED'}
            return {'RUNNING_MODAL'}

        elif event.type in {'RIGHTMOUSE', 'ESC'}:
            clear_pick_callback()
            return {'CANCELLED'}

        return {'RUNNING_MODAL'}

    def cancel(self, context):
        """Clean up on cancel."""
        clear_pick_callback()
