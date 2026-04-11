#!/usr/bin/env python3
"""
Standalone Camera JSON Generator
Generates camera path JSON files in LichtfeldStudio keyframe format (version 3).

Output format:
{
  "keyframes": [
    {
      "easing": 0,
      "focal_length_mm": 35.0,
      "position": [x, y, z],
      "rotation": [qw, qx, qy, qz],
      "time": 0.0
    },
    ...
  ],
  "version": 3
}
"""

import json
import math
from pathlib import Path


def focal_length_to_fov(focal_length_mm: float, sensor_size_mm: float = 32.0) -> float:
    """Convert focal length (mm) to horizontal field of view (degrees)."""
    return 2.0 * math.degrees(math.atan(sensor_size_mm / (2.0 * focal_length_mm)))


def normalize_vector(v):
    """Normalize a 3D vector."""
    length = math.sqrt(sum(c * c for c in v))
    if length < 1e-10:
        return (0.0, 0.0, 1.0)
    return tuple(c / length for c in v)


def look_at_quaternion(position, target):
    """
    Compute a quaternion that rotates from the default camera orientation
    (looking down -Z, Y up) to look from `position` toward `target`.

    Returns (qw, qx, qy, qz).
    """
    # Forward vector (from position toward target)
    fx = target[0] - position[0]
    fy = target[1] - position[1]
    fz = target[2] - position[2]
    forward = normalize_vector((fx, fy, fz))

    # Choose a world-up vector; if forward is nearly parallel to Y, use Z instead
    if abs(forward[1]) > 0.99:
        world_up = (0.0, 0.0, -1.0 if forward[1] > 0 else 1.0)
    else:
        world_up = (0.0, 1.0, 0.0)

    # Right vector: world_up x forward  (LichtfeldStudio convention)
    right = normalize_vector((
        world_up[1] * forward[2] - world_up[2] * forward[1],
        world_up[2] * forward[0] - world_up[0] * forward[2],
        world_up[0] * forward[1] - world_up[1] * forward[0],
    ))

    # Recompute up orthogonally: forward x right
    up = (
        forward[1] * right[2] - forward[2] * right[1],
        forward[2] * right[0] - forward[0] * right[2],
        forward[0] * right[1] - forward[1] * right[0],
    )

    # Build rotation matrix with +Z = forward (LichtfeldStudio convention)
    # Column 0 = right, Column 1 = up, Column 2 = +forward
    m00, m10, m20 = right
    m01, m11, m21 = up
    m02, m12, m22 = forward[0], forward[1], forward[2]

    # Convert 3x3 rotation matrix to quaternion
    trace = m00 + m11 + m22
    if trace > 0:
        s = 0.5 / math.sqrt(trace + 1.0)
        qw = 0.25 / s
        qx = (m21 - m12) * s
        qy = (m02 - m20) * s
        qz = (m10 - m01) * s
    elif m00 > m11 and m00 > m22:
        s = 2.0 * math.sqrt(1.0 + m00 - m11 - m22)
        qw = (m21 - m12) / s
        qx = 0.25 * s
        qy = (m01 + m10) / s
        qz = (m02 + m20) / s
    elif m11 > m22:
        s = 2.0 * math.sqrt(1.0 + m11 - m00 - m22)
        qw = (m02 - m20) / s
        qx = (m01 + m10) / s
        qy = 0.25 * s
        qz = (m12 + m21) / s
    else:
        s = 2.0 * math.sqrt(1.0 + m22 - m00 - m11)
        qw = (m10 - m01) / s
        qx = (m02 + m20) / s
        qy = (m12 + m21) / s
        qz = 0.25 * s

    # Normalise and return
    length = math.sqrt(qw * qw + qx * qx + qy * qy + qz * qz)
    return (qw / length, qx / length, qy / length, qz / length)


class StandaloneCameraGenerator:
    """Generates camera animations and writes them in LichtfeldStudio keyframe JSON format."""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_camera_animation(
        self,
        animation_type: str = "spiral",
        direction: str = "clockwise",
        center: tuple = (0.0, 0.0, 0.0),
        target: tuple = None,
        target_distance: float = None,
        radius: float = 10.0,
        start_radius: float = 5.0,
        end_radius: float = 5.0,
        start_height: float = 0.0,
        end_height: float = 10.0,
        spiral_loops: float = 2.0,
        frames: int = 180,
        fps: int = 24,
        focal_length: float = 35.0,
        sensor_size: float = 32.0,
        convert_coords: bool = False,
        precision: int = 6,
        keyframe_step: int = 10,
        spiral_follow_y: bool = True,
        spiral_y_offset: float = 0.0,
        orient_offset_pitch: int = 2,
        orient_offset_yaw: int = 0,
        orient_offset_roll: int = 2,
    ) -> dict:
        """
        Generate camera animation data in LichtfeldStudio keyframe format.

        Parameters
        ----------
        animation_type : "circular" or "spiral"
        direction      : "clockwise" or "counterclockwise"
        center         : (x, y, z) centre of the orbit/spiral
        target         : (x, y, z) point the camera looks at; if None,
                         auto-calculated from target_distance
        target_distance: used when target is None
        radius         : orbit radius for circular animation
        start_radius   : starting radius for spiral animation
        end_radius     : ending radius for spiral animation
        start_height   : starting height (Y axis) for spiral
        end_height     : ending height (Y axis) for spiral
        spiral_loops   : number of full rotations in spiral
        frames         : total number of frames
        fps            : frames per second (used to compute keyframe time values)
        focal_length   : camera focal length in mm
        sensor_size    : sensor width in mm (used for FOV display only)
        convert_coords : if True, swaps Y/Z axes (Z-up → Y-up)
        precision      : decimal places for floating-point values
        keyframe_step  : emit a keyframe every N frames
        spiral_follow_y: if True (spiral only), the look-target Y tracks the
                         camera's current height instead of staying fixed
        spiral_y_offset: added to the look-target Y when spiral_follow_y is on
                         (positive = look above camera height, negative = below)
        orient_offset_pitch: pitch offset in 90-degree increments (-3..3), applied
                         after look-at quaternion as a post-multiply
        orient_offset_yaw  : yaw offset in 90-degree increments (-3..3)
        orient_offset_roll : roll offset in 90-degree increments (-3..3)

        Returns
        -------
        dict  ready to be serialised as JSON
        """
        keyframes = []
        total_duration = frames / fps  # seconds

        # Angle multiplier for direction
        angle_sign = -1.0 if direction == "clockwise" else 1.0

        # Build the list of frame indices to emit.
        # Always start at 0 and end at frames-1.
        # When keyframe_step > 1, also insert frame 1 (start+1) and
        # frames-2 (end-1) so interpolation at the ends is smooth.
        frame_indices = list(range(0, frames, keyframe_step))
        last_frame = frames - 1
        if keyframe_step > 1:
            extra = {1, last_frame - 1, last_frame}
            frame_indices = sorted(set(frame_indices) | extra)
        elif last_frame not in frame_indices:
            frame_indices.append(last_frame)

        for frame_idx in frame_indices:
            t_norm = frame_idx / max(frames - 1, 1)  # 0.0 → 1.0
            time_sec = round(frame_idx / fps, precision)

            angle = angle_sign * 2.0 * math.pi * t_norm

            # --- Compute camera position ---
            if animation_type == "circular":
                r = radius
                height = center[1]
                angle_full = angle  # one full revolution
            else:
                # Spiral: interpolate radius and height, multiple loops
                r = start_radius + (end_radius - start_radius) * t_norm
                height = center[1] + start_height + (end_height - start_height) * t_norm
                angle_full = angle_sign * 2.0 * math.pi * spiral_loops * t_norm

            px = center[0] + r * math.sin(angle_full)
            py = height
            pz = center[2] + r * math.cos(angle_full)

            position = [px, py, pz]

            # --- Compute look-at target ---
            if target is not None:
                # Fixed target: always use exactly as supplied, never overridden
                look_target = list(target)
            else:
                # Auto target: look toward centre XZ, Y depends on mode
                if target_distance is not None:
                    look_target = [
                        center[0],
                        center[1] if animation_type == "circular" else height,
                        center[2],
                    ]
                else:
                    look_target = list(center)

                # spiral_follow_y: override Y to track camera height (+ offset)
                # Applied whenever no fixed target is set
                if animation_type == "spiral" and spiral_follow_y:
                    look_target[1] = height + spiral_y_offset

            # --- Optional coordinate conversion (Z-up → Y-up) ---
            if convert_coords:
                position = [position[0], position[2], -position[1]]
                look_target = [look_target[0], look_target[2], -look_target[1]]

            # --- Quaternion ---
            qw, qx, qy, qz = look_at_quaternion(position, look_target)

            # Apply orientation offsets (each in 90-degree steps) as post-multiplies
            # Order: pitch first, then yaw, then roll
            def _q_rot(axis, steps):
                """Quaternion for steps*90 degrees around axis (0=X,1=Y,2=Z)."""
                angle = math.radians(steps * 90.0)
                c, s = math.cos(angle / 2), math.sin(angle / 2)
                axes = [(c, s, 0, 0), (c, 0, s, 0), (c, 0, 0, s)]
                return axes[axis]

            def _qmul(a, b):
                aw, ax, ay, az = a; bw, bx, by, bz = b
                return (
                    aw*bw - ax*bx - ay*by - az*bz,
                    aw*bx + ax*bw + ay*bz - az*by,
                    aw*by - ax*bz + ay*bw + az*bx,
                    aw*bz + ax*by - ay*bx + az*bw,
                )

            q = (qw, qx, qy, qz)
            if orient_offset_pitch != 0:
                q = _qmul(q, _q_rot(0, orient_offset_pitch))
            if orient_offset_yaw != 0:
                q = _qmul(q, _q_rot(1, orient_offset_yaw))
            if orient_offset_roll != 0:
                q = _qmul(q, _q_rot(2, orient_offset_roll))
            # Re-normalise after offset multiplications
            ql = math.sqrt(sum(v*v for v in q))
            qw, qx, qy, qz = (v/ql for v in q)

            def r_val(v):
                return round(v, precision)

            keyframes.append({
                "easing": 0,
                "focal_length_mm": round(focal_length, precision),
                "position": [r_val(position[0]), r_val(position[1]), r_val(position[2])],
                "rotation": [r_val(qw), r_val(qx), r_val(qy), r_val(qz)],
                "time": r_val(time_sec),
            })

        return {
            "keyframes": keyframes,
            "version": 3,
        }

    def save_json(self, data: dict, output_path: str) -> None:
        """Write the animation data to a JSON file, then log the filename."""
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        self._write_file_log(output_path)

    def _write_file_log(self, output_path: str) -> None:
        """Append the saved filename and timestamp to File.log in the Scripts folder."""
        import datetime
        import os

        scripts_dir = (
            Path(os.environ.get("USERPROFILE", "~")).expanduser()
            / ".lichtfeld" / "plugins" / "CamPath_Json" / "Scripts"
        )
        log_path = scripts_dir / "File.log"

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"{timestamp}  {output_path}\n"

        try:
            scripts_dir.mkdir(parents=True, exist_ok=True)
            with open(log_path, "w", encoding="utf-8") as lf:
                lf.write(entry)
        except Exception:
            pass  # Never let logging break the main workflow
