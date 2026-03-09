"""
Eyes display for Neon.

Renders animated robot eyes on the phone screen.
The eyes change based on the current emotion, with smooth transitions.
Periodic blinking adds life-like behavior.
"""

import random
from pathlib import Path
from typing import Optional

from kivy.uix.widget import Widget
from kivy.uix.image import Image
from kivy.graphics import Color, Rectangle, Ellipse
from kivy.clock import Clock
from kivy.animation import Animation

from src.utils.logger import log


EMOTIONS = [
    "neutral", "happy", "excited", "curious",
    "annoyed", "sad", "angry",
    "love", "sleeping",
]

EYE_PARAMS = {
    "neutral":     {"pupil": 1.0, "lid_top": 0.10, "lid_bot": 0.05, "brow": 0,    "px": 0, "py": 0,    "r": 0.3, "g": 0.9, "b": 1.0},
    "happy":       {"pupil": 0.9, "lid_top": 0.30, "lid_bot": 0.15, "brow": 5,    "px": 0, "py": 0,    "r": 0.3, "g": 1.0, "b": 0.5},
    "excited":     {"pupil": 1.3, "lid_top": 0.00, "lid_bot": 0.00, "brow": 8,    "px": 0, "py": 0,    "r": 1.0, "g": 0.9, "b": 0.2},
    "curious":     {"pupil": 1.2, "lid_top": 0.05, "lid_bot": 0.00, "brow": -10,  "px": 0.1, "py": 0.1, "r": 0.3, "g": 0.8, "b": 1.0},
    "annoyed":     {"pupil": 0.8, "lid_top": 0.35, "lid_bot": 0.10, "brow": -15,  "px": 0, "py": -0.05, "r": 1.0, "g": 0.4, "b": 0.3},
    "sad":         {"pupil": 0.9, "lid_top": 0.25, "lid_bot": 0.00, "brow": 12,   "px": 0, "py": -0.1,  "r": 0.4, "g": 0.6, "b": 1.0},
    "angry":       {"pupil": 0.7, "lid_top": 0.30, "lid_bot": 0.10, "brow": -20,  "px": 0, "py": 0,     "r": 1.0, "g": 0.1, "b": 0.1},
    "love":        {"pupil": 1.1, "lid_top": 0.15, "lid_bot": 0.10, "brow": 5,    "px": 0, "py": 0,     "r": 1.0, "g": 0.2, "b": 0.5},
    "sleeping":    {"pupil": 0.0, "lid_top": 0.95, "lid_bot": 0.00, "brow": 0,    "px": 0, "py": 0,     "r": 0.3, "g": 0.3, "b": 0.5},
}


class EyesDisplay(Widget):
    """
    Widget that displays Neon's animated eyes.

    Supports two rendering modes:
    1. Image-based: loads PNG/JPG from assets/eyes/{emotion}.png
    2. Procedural: draws stylized eyes using Kivy graphics primitives

    Falls back to procedural if image files are missing.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._assets_path = Path(__file__).parent.parent.parent / "assets" / "eyes"
        self._current_emotion = "neutral"
        self._target_params = dict(EYE_PARAMS["neutral"])
        self._current_params = dict(EYE_PARAMS["neutral"])
        self._eye_image: Optional[Image] = None
        self._use_images = False
        self._blink_event = None
        self._transition_event = None

        with self.canvas.before:
            Color(0, 0, 0, 1)
            self._bg = Rectangle(pos=self.pos, size=self.size)

        self.bind(pos=self._on_layout, size=self._on_layout)

        # Check if we have image assets
        self._use_images = self._has_image("neutral")

        if self._use_images:
            self._load_image("neutral")
        else:
            self._draw_eyes()

        self._start_blink_timer()

    def _has_image(self, emotion: str) -> bool:
        for ext in (".png", ".jpg", ".jpeg"):
            if (self._assets_path / f"{emotion}{ext}").exists():
                return True
        return False

    def _get_image_path(self, emotion: str) -> Optional[Path]:
        for ext in (".png", ".jpg", ".jpeg"):
            p = self._assets_path / f"{emotion}{ext}"
            if p.exists():
                return p
        return None

    def _on_layout(self, *args):
        self._bg.pos = self.pos
        self._bg.size = self.size
        if self._use_images and self._eye_image:
            self._eye_image.pos = self.pos
            self._eye_image.size = self.size
        elif not self._use_images:
            self._draw_eyes()

    def set_emotion(self, emotion: str, duration: float = 0.3):
        """Change the displayed emotion with a smooth transition."""
        if emotion not in EMOTIONS:
            emotion = "neutral"
        if emotion == self._current_emotion:
            return

        log(f"Emotion: {self._current_emotion} -> {emotion}", "INFO")
        self._current_emotion = emotion

        if self._use_images:
            self._transition_image(emotion, duration)
        else:
            self._target_params = dict(EYE_PARAMS.get(emotion, EYE_PARAMS["neutral"]))
            self._animate_transition(duration)

    @property
    def current_emotion(self) -> str:
        return self._current_emotion

    def blink(self):
        """Quick blink animation."""
        if self._use_images:
            self._blink_image()
        else:
            self._blink_procedural()

    # ── Image-based rendering ──

    def _load_image(self, emotion: str):
        path = self._get_image_path(emotion)
        if not path:
            path = self._get_image_path("neutral")
        if not path:
            return

        if self._eye_image:
            self.remove_widget(self._eye_image)

        self._eye_image = Image(
            source=str(path),
            fit_mode="contain",
            pos=self.pos,
            size=self.size,
        )
        self.add_widget(self._eye_image)

    def _transition_image(self, emotion: str, duration: float):
        if not self._eye_image:
            self._load_image(emotion)
            return

        anim_out = Animation(opacity=0, duration=duration / 2)
        def on_fade_out(*args):
            self._load_image(emotion)
            if self._eye_image:
                self._eye_image.opacity = 0
                Animation(opacity=1, duration=duration / 2).start(self._eye_image)
        anim_out.bind(on_complete=on_fade_out)
        anim_out.start(self._eye_image)

    def _blink_image(self):
        if not self._eye_image:
            return
        orig = self._current_emotion
        anim = Animation(opacity=0.1, duration=0.08) + Animation(opacity=1, duration=0.08)
        anim.start(self._eye_image)

    # ── Procedural rendering ──

    def _draw_eyes(self):
        """Draw both eyes using current params."""
        self.canvas.after.clear()
        p = self._current_params
        w, h = self.size
        cx, cy = self.pos[0] + w / 2, self.pos[1] + h / 2

        eye_w = w * 0.18
        eye_h = h * 0.35
        spacing = w * 0.15
        pupil_r = eye_w * 0.35 * p.get("pupil", 1.0)

        for side in (-1, 1):
            ex = cx + side * spacing
            ey = cy

            with self.canvas.after:
                # Eye white (slightly blue-tinted)
                Color(0.15, 0.15, 0.2, 1)
                Ellipse(pos=(ex - eye_w, ey - eye_h), size=(eye_w * 2, eye_h * 2))

                # Iris glow
                Color(p["r"] * 0.3, p["g"] * 0.3, p["b"] * 0.3, 0.5)
                glow_r = pupil_r * 2.0
                gx = ex + p.get("px", 0) * eye_w * side
                gy = ey + p.get("py", 0) * eye_h
                Ellipse(pos=(gx - glow_r, gy - glow_r), size=(glow_r * 2, glow_r * 2))

                # Pupil
                Color(p["r"], p["g"], p["b"], 1)
                px_pos = ex + p.get("px", 0) * eye_w * side
                py_pos = ey + p.get("py", 0) * eye_h
                Ellipse(pos=(px_pos - pupil_r, py_pos - pupil_r), size=(pupil_r * 2, pupil_r * 2))

                # Highlight
                Color(1, 1, 1, 0.7)
                hl_r = pupil_r * 0.25
                Ellipse(
                    pos=(px_pos + pupil_r * 0.3 - hl_r, py_pos + pupil_r * 0.3 - hl_r),
                    size=(hl_r * 2, hl_r * 2),
                )

                # Upper eyelid
                lid_top = p.get("lid_top", 0)
                if lid_top > 0.01:
                    Color(0, 0, 0, 1)
                    lid_h = eye_h * 2 * lid_top
                    Rectangle(
                        pos=(ex - eye_w - 2, ey + eye_h - lid_h),
                        size=(eye_w * 2 + 4, lid_h + 4),
                    )

                # Lower eyelid
                lid_bot = p.get("lid_bot", 0)
                if lid_bot > 0.01:
                    Color(0, 0, 0, 1)
                    lid_h = eye_h * 2 * lid_bot
                    Rectangle(
                        pos=(ex - eye_w - 2, ey - eye_h - 4),
                        size=(eye_w * 2 + 4, lid_h + 4),
                    )

    def _animate_transition(self, duration: float):
        """Smoothly interpolate from current to target eye params."""
        if self._transition_event:
            self._transition_event.cancel()

        steps = max(1, int(duration / 0.033))  # ~30fps
        step_i = [0]
        start = dict(self._current_params)
        target = dict(self._target_params)

        def step(dt):
            step_i[0] += 1
            t = min(1.0, step_i[0] / steps)
            t_smooth = t * t * (3 - 2 * t)  # smoothstep

            for key in start:
                if key in target:
                    self._current_params[key] = start[key] + (target[key] - start[key]) * t_smooth

            self._draw_eyes()

            if t >= 1.0:
                self._transition_event.cancel()
                self._transition_event = None
                return False

        self._transition_event = Clock.schedule_interval(step, 0.033)

    def _blink_procedural(self):
        saved_lid = self._current_params.get("lid_top", 0)
        saved_pupil = self._current_params.get("pupil", 1.0)

        def close(dt):
            self._current_params["lid_top"] = 0.95
            self._current_params["pupil"] = 0.0
            self._draw_eyes()

        def reopen(dt):
            self._current_params["lid_top"] = saved_lid
            self._current_params["pupil"] = saved_pupil
            self._draw_eyes()

        Clock.schedule_once(close, 0)
        Clock.schedule_once(reopen, 0.15)

    # ── Blink timer ──

    def _start_blink_timer(self):
        def maybe_blink(dt):
            if random.random() < 0.3:
                self.blink()
        self._blink_event = Clock.schedule_interval(maybe_blink, 3.5)

    def cleanup(self):
        if self._blink_event:
            self._blink_event.cancel()
        if self._transition_event:
            self._transition_event.cancel()
