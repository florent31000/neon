"""
Neon - Robot Dog Brain
Main Kivy Application

This is the entry point. It orchestrates:
  - Eyes display (full-screen emotion rendering)
  - Voice engine (OpenAI Realtime API for conversation)
  - Robot controller (WebRTC to Unitree Go2 body)
  - Audio I/O (mic capture + speaker playback)
  - Logs (copyable for debugging)
"""

import os
import asyncio
import threading
from datetime import datetime

os.environ["KIVY_LOG_LEVEL"] = "warning"

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.core.clipboard import Clipboard
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.textinput import TextInput
from kivy.graphics import Color, Rectangle
from kivy.utils import platform

from src.utils.config import load_config, get_robot_name
from src.utils.logger import log, set_log_callback, get_all_logs
from src.ui.eyes import EyesDisplay
from src.voice.engine import VoiceEngine
from src.voice.audio_io import AudioCapture, AudioPlayer
from src.robot.controller import RobotController


class NeonApp(App):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._config = None
        self._eyes: EyesDisplay = None
        self._voice: VoiceEngine = None
        self._robot: RobotController = None
        self._audio_capture: AudioCapture = None
        self._audio_player: AudioPlayer = None
        self._log_lines = []
        self._log_widget: TextInput = None
        self._status_label: Label = None
        self._conn_label: Label = None
        self._show_logs = False
        self._async_loop: asyncio.AbstractEventLoop = None

    def build(self):
        Window.clearcolor = (0, 0, 0, 1)

        root = FloatLayout()

        # Eyes (full screen, behind everything)
        self._eyes = EyesDisplay(pos_hint={"x": 0, "y": 0}, size_hint=(1, 1))
        root.add_widget(self._eyes)

        # Log overlay (hidden by default, toggleable)
        self._log_widget = TextInput(
            text="",
            readonly=True,
            multiline=True,
            font_size="10sp",
            background_color=(0, 0, 0, 0.85),
            foreground_color=(0.7, 1, 0.7, 1),
            cursor_color=(1, 1, 1, 1),
            selection_color=(0.3, 0.5, 0.8, 0.5),
            padding=[8, 8],
            size_hint=(1, 0.85),
            pos_hint={"x": 0, "y": 0},
            opacity=0,
        )
        root.add_widget(self._log_widget)

        # Top status bar
        bar = BoxLayout(
            size_hint=(1, None),
            height=44,
            spacing=6,
            padding=[8, 4],
            pos_hint={"x": 0, "top": 1},
        )
        with bar.canvas.before:
            Color(0, 0, 0, 0.4)
            self._bar_bg = Rectangle(pos=bar.pos, size=bar.size)
        bar.bind(pos=self._update_bar_bg, size=self._update_bar_bg)

        self._status_label = Label(
            text="Starting...",
            size_hint_x=0.45,
            halign="left",
            font_size="13sp",
            color=(1, 1, 1, 1),
        )
        self._status_label.bind(size=self._status_label.setter("text_size"))

        self._conn_label = Label(
            text="...",
            size_hint_x=0.2,
            font_size="11sp",
            color=(1, 0.8, 0.3, 1),
        )

        btn_logs = Button(text="Logs", size_hint_x=0.15, font_size="11sp")
        btn_logs.bind(on_press=self._toggle_logs)

        btn_copy = Button(text="Copier", size_hint_x=0.15, font_size="11sp")
        btn_copy.bind(on_press=self._copy_logs)

        bar.add_widget(self._status_label)
        bar.add_widget(self._conn_label)
        bar.add_widget(btn_logs)
        bar.add_widget(btn_copy)
        root.add_widget(bar)

        return root

    def on_start(self):
        set_log_callback(self._on_log_message)
        log(f"Neon starting...")

        try:
            self._config = load_config()
        except Exception as e:
            log(f"Config error: {e}", "ERROR")
            self._config = {"robot": {"name": "Néon"}}

        name = get_robot_name()
        log(f"Robot name: {name}")
        self._keep_screen_awake()

        if platform == "android":
            Clock.schedule_once(self._request_permissions, 0.1)
        else:
            Clock.schedule_once(self._init_all, 0.3)

    def _keep_screen_awake(self):
        if platform != "android":
            return
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            LayoutParams = autoclass("android.view.WindowManager$LayoutParams")
            activity = PythonActivity.mActivity
            activity.getWindow().addFlags(LayoutParams.FLAG_KEEP_SCREEN_ON)
            log("Screen keep-awake enabled")
        except Exception as e:
            log(f"Failed to enable keep-awake: {e}", "WARNING")

    def _request_permissions(self, dt):
        from android.permissions import request_permissions, Permission

        def callback(permissions, grants):
            Clock.schedule_once(lambda dt: self._init_all(dt), 0)

        request_permissions(
            [
                Permission.RECORD_AUDIO,
                Permission.CAMERA,
                Permission.INTERNET,
                Permission.ACCESS_FINE_LOCATION,
            ],
            callback,
        )

    def _init_all(self, dt):
        """Initialize all subsystems."""
        self._start_async_loop()

        # Audio player (for voice output) — start the writer thread immediately
        output_rate = self._config.get("voice", {}).get("output_sample_rate", 24000)
        self._audio_player = AudioPlayer(sample_rate=output_rate)
        self._audio_player.start()

        # Start voice immediately so the phone remains useful even if the robot
        # is off or still charging. The body connection keeps retrying in the
        # background and can come up later.
        self._start_voice_and_mic()

        self._robot = RobotController(self._config)
        self._run_async(self._connect_robot_with_retry())

        Clock.schedule_interval(self._update_status_tick, 2.0)

    # ── Async event loop (for robot commands) ──

    def _start_async_loop(self):
        self._async_loop = asyncio.new_event_loop()

        def run():
            asyncio.set_event_loop(self._async_loop)
            self._async_loop.run_forever()

        t = threading.Thread(target=run, daemon=True)
        t.start()

    async def _connect_robot_with_retry(self):
        """Keep trying to connect the robot body without blocking voice.
        Retries are intentionally gentle because WiFi binding attempts can
        temporarily disturb the voice socket on some Android devices."""
        retry_delays = [10, 30, 60, 60, 60]
        for attempt, wait in enumerate(retry_delays, start=1):
            ok = await self._robot.connect()
            if ok:
                Clock.schedule_once(lambda dt: self._restart_voice_after_robot_connect(), 0)
                break
            log(f"Robot connection retry in {wait}s (attempt {attempt}/5)...", "WARNING")
            await asyncio.sleep(wait)
        else:
            log("Could not connect to robot body after 5 attempts", "ERROR")

    def _start_voice_and_mic(self):
        """Start voice engine and audio capture."""
        if self._voice is None:
            self._voice = self._make_voice_engine()
        try:
            self._voice.start()
        except Exception as e:
            log(f"Voice engine failed: {e}", "ERROR")

        if self._audio_capture is None:
            input_rate = self._config.get("voice", {}).get("input_sample_rate", 16000)
            chunk_ms = self._config.get("voice", {}).get("chunk_ms", 60)
            self._audio_capture = AudioCapture(
                sample_rate=input_rate,
                chunk_ms=chunk_ms,
                on_chunk=self._on_mic_chunk,
            )
            self._audio_capture.start()

        self._update_status()
        name = get_robot_name()
        self._set_status(f"{name} is awake!")
        log(f"{name} initialized!", "SUCCESS")

    def _make_voice_engine(self) -> VoiceEngine:
        return VoiceEngine(
            config=self._config,
            on_audio_output=self._on_voice_audio,
            on_tool_call=self._on_tool_call,
            on_transcript=self._on_transcript,
            on_speech_start=self._on_speech_start,
            on_speech_end=self._on_speech_end,
            on_interrupt=self._on_interrupt,
            is_audio_playing=lambda: self._audio_player.is_playing if self._audio_player else False,
        )

    def _restart_voice_after_robot_connect(self):
        """Recreate the OpenAI socket after WiFi binding changed during robot connect."""
        if not self._voice:
            return
        try:
            self._voice.stop()
        except Exception:
            pass
        self._voice = self._make_voice_engine()
        try:
            self._voice.start()
            log("Voice engine restarted after robot connection", "SUCCESS")
        except Exception as e:
            log(f"Voice restart after robot connection failed: {e}", "ERROR")

    def _run_async(self, coro):
        """Schedule a coroutine on the async loop (fire-and-forget)."""
        if self._async_loop and self._async_loop.is_running():
            asyncio.run_coroutine_threadsafe(coro, self._async_loop)

    # ── Voice callbacks ──

    def _on_mic_chunk(self, pcm16: bytes):
        if self._voice:
            self._voice.on_audio_chunk(pcm16)

    def _on_voice_audio(self, pcm16: bytes):
        if self._audio_player:
            self._audio_player.write(pcm16)

    def _on_tool_call(self, name: str, args: dict):
        """
        Handle tool calls from the LLM.
        IMPORTANT: This runs in the WebSocket receive thread, so it must NOT block.
        Robot commands are fired asynchronously via the async loop.
        """
        if name == "set_emotion":
            emotion = args.get("emotion", "neutral")
            Clock.schedule_once(lambda dt: self._eyes.set_emotion(emotion), 0)
            return f"Emotion set to {emotion}"

        if name == "move_robot":
            asyncio.run_coroutine_threadsafe(
                self._robot.move(
                    direction=args.get("direction", "forward"),
                    speed=args.get("speed", 0.5),
                    duration=args.get("duration", 2.0),
                ),
                self._async_loop,
            )
            return f"Moving {args.get('direction', 'forward')}"

        if name == "turn_robot":
            asyncio.run_coroutine_threadsafe(
                self._robot.turn(
                    direction=args.get("direction", "left"),
                    angle=args.get("angle", 90),
                ),
                self._async_loop,
            )
            return f"Turning {args.get('direction', 'left')} {args.get('angle', 90)} degrees"

        if name == "do_action":
            asyncio.run_coroutine_threadsafe(
                self._robot.do_action(args.get("action", "stand_up")),
                self._async_loop,
            )
            return f"Performing {args.get('action', 'stand_up')}"

        if name == "stop_robot":
            asyncio.run_coroutine_threadsafe(
                self._robot.stop(),
                self._async_loop,
            )
            return "Stopped"

        return f"Unknown tool: {name}"

    def _on_transcript(self, role: str, text: str):
        icon = "You" if role == "user" else get_robot_name()
        Clock.schedule_once(
            lambda dt: log(f"[{icon}] {text}", "SPEECH"), 0
        )

    def _on_speech_start(self):
        pass

    def _on_speech_end(self):
        pass

    def _on_interrupt(self):
        """User interrupted the assistant — flush buffered audio immediately."""
        if self._audio_player:
            self._audio_player.flush()

    # ── UI ──

    def _on_log_message(self, message: str, level: str):
        ts = datetime.now().strftime("%H:%M:%S")
        icons = {
            "DEBUG": "~", "INFO": ">", "WARNING": "!", "ERROR": "X",
            "SUCCESS": "+", "SPEECH": "#", "ROBOT": "@",
        }
        line = f"[{ts}] {icons.get(level, '>')} {message}"
        self._log_lines.append(line)
        if len(self._log_lines) > 300:
            self._log_lines = self._log_lines[-300:]

        if self._show_logs:
            Clock.schedule_once(lambda dt: self._refresh_log_display(), 0)

    def _refresh_log_display(self):
        if self._log_widget:
            self._log_widget.text = "\n".join(self._log_lines)
            self._log_widget.cursor = (0, len(self._log_widget.text))

    def _toggle_logs(self, *args):
        self._show_logs = not self._show_logs
        if self._show_logs:
            self._log_widget.opacity = 1
            self._refresh_log_display()
        else:
            self._log_widget.opacity = 0

    def _copy_logs(self, *args):
        text = "\n".join(self._log_lines) if self._log_lines else get_all_logs()
        if not text:
            self._set_status_temp("No logs to copy")
            return
        try:
            Clipboard.copy(text)
            self._set_status_temp("Logs copied!")
        except Exception as e:
            log(f"Clipboard error: {e}", "WARNING")

    def _set_status(self, text: str):
        if self._status_label:
            self._status_label.text = text

    def _set_status_temp(self, text: str, duration: float = 2.0):
        if not self._status_label:
            return
        orig = self._status_label.text
        self._status_label.text = text
        Clock.schedule_once(lambda dt: setattr(self._status_label, "text", orig), duration)

    def _update_bar_bg(self, instance, value):
        self._bar_bg.pos = instance.pos
        self._bar_bg.size = instance.size

    def _update_status(self):
        robot_ok = self._robot.is_connected if self._robot else False
        voice_ok = self._voice.is_connected if self._voice else False

        parts = []
        if robot_ok:
            parts.append("Body OK")
        else:
            parts.append("No body")
        if voice_ok:
            parts.append("Voice OK")
        else:
            parts.append("No voice")

        status = " | ".join(parts)
        color = (0.3, 1, 0.3, 1) if (robot_ok and voice_ok) else (1, 0.8, 0.3, 1)

        if self._conn_label:
            self._conn_label.text = status
            self._conn_label.color = color

    def _update_status_tick(self, dt):
        self._update_status()

    def on_stop(self):
        log("Neon shutting down...")

        if self._eyes:
            self._eyes.set_emotion("sleeping")
            self._eyes.cleanup()

        if self._audio_capture:
            self._audio_capture.stop()

        if self._voice:
            self._voice.stop()

        if self._audio_player:
            self._audio_player.stop()

        if self._robot and self._robot.is_connected:
            self._run_async(self._robot.emergency_stop())
            self._run_async(self._robot.disconnect())

        if self._async_loop:
            self._async_loop.call_soon_threadsafe(self._async_loop.stop)


def main():
    NeonApp().run()


if __name__ == "__main__":
    main()
