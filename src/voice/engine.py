"""
Voice conversation engine for Neon.

Uses OpenAI Realtime API for speech-to-speech conversation.
Key design decisions:
  - Server-side VAD (not client-side energy detection) for reliable turn detection
  - Function calling (tools) for robot movement and emotion display
  - Single WebSocket connection handles STT + LLM + TTS in one round-trip
  - PCM16 audio at 24kHz output, 16kHz input
"""

import base64
import json
import re
import threading
import time
import unicodedata
from typing import Any, Callable, Dict, Optional

from src.utils.config import get_api_key, get_robot_name, load_personality
from src.utils.logger import log


# ── Tool definitions for function calling ──
# These are exposed to the Realtime API so the LLM can control the robot and eyes.

TOOLS = [
    {
        "type": "function",
        "name": "move_robot",
        "description": (
            "Déplace le corps du robot en ligne droite. "
            "Directions: forward, backward, left (pas de côté gauche), right (pas de côté droit). "
            "Speed de 0.1 (très lent) à 1.0 (rapide). Par défaut 0.5. "
            "Duration en secondes: par défaut 3. "
            "Utilise duration=0 UNIQUEMENT si l'utilisateur dit explicitement "
            "'sans t'arrêter', 'continue d'avancer', ou 'avance jusqu'à ce que je te dise stop'. "
            "Dans tous les autres cas, utilise une durée finie (3s par défaut, "
            "1s pour 'un petit peu', 5s pour 'avance bien')."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["forward", "backward", "left", "right"],
                },
                "speed": {"type": "number", "default": 0.5},
                "duration": {"type": "number", "default": 3},
            },
            "required": ["direction"],
        },
    },
    {
        "type": "function",
        "name": "turn_robot",
        "description": (
            "Fait tourner le robot sur lui-même. "
            "direction: left ou right. "
            "angle: nombre de degrés (30 = un petit peu, 90 = quart de tour, "
            "180 = demi-tour, 360 = tour complet). "
            "Par défaut 90 degrés."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "enum": ["left", "right"],
                },
                "angle": {"type": "number", "default": 90},
            },
            "required": ["direction"],
        },
    },
    {
        "type": "function",
        "name": "do_action",
        "description": (
            "Effectue une action physique ou un geste. "
            "stand_up = se lever, sit = s'asseoir, lie_down = se coucher, "
            "wave_hello = donner la patte/dire bonjour, stretch = s'étirer, "
            "dance = danser (choisit aléatoirement entre 2 danses), "
            "heart = faire un coeur, wiggle = remuer les hanches"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "stand_up", "sit", "lie_down", "wave_hello", "stretch",
                        "dance", "heart", "wiggle",
                    ],
                },
            },
            "required": ["action"],
        },
    },
    {
        "type": "function",
        "name": "stop_robot",
        "description": "Arrête tout mouvement immédiatement.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "set_emotion",
        "description": (
            "Change l'émotion affichée à l'écran (les yeux du robot). "
            "Utilise ceci pour exprimer comment tu te sens. "
            "Ne change pas d'émotion à chaque phrase, seulement quand c'est pertinent."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "emotion": {
                    "type": "string",
                    "enum": [
                        "neutral", "happy", "excited", "curious",
                        "annoyed", "sad", "angry",
                        "love", "sleeping",
                    ],
                },
            },
            "required": ["emotion"],
        },
    },
]


class VoiceEngine:
    """
    Manages the OpenAI Realtime API WebSocket for voice conversation.

    Architecture:
      - A receive thread reads events from the WebSocket
      - Audio chunks from the mic are forwarded via on_audio_chunk()
      - The API handles VAD, STT, LLM, TTS in one pipeline
      - Tool calls trigger callbacks (robot movement, emotion display)
    """

    WS_URL = "wss://api.openai.com/v1/realtime"

    def __init__(
        self,
        config: Dict[str, Any],
        on_audio_output: Optional[Callable[[bytes], None]] = None,
        on_tool_call: Optional[Callable[[str, Dict], Any]] = None,
        on_transcript: Optional[Callable[[str, str], None]] = None,
        on_speech_start: Optional[Callable[[], None]] = None,
        on_speech_end: Optional[Callable[[], None]] = None,
        on_interrupt: Optional[Callable[[], None]] = None,
        is_audio_playing: Optional[Callable[[], bool]] = None,
    ):
        """
        Args:
            config: Full app config dict
            on_audio_output: Called with PCM16 bytes to play through speaker
            on_tool_call: Called with (tool_name, arguments) -> result string
            on_transcript: Called with (role, text) for logging ("user"/"assistant")
            on_speech_start: Called when assistant starts speaking
            on_speech_end: Called when assistant stops speaking
            on_interrupt: Called when user interrupts (barge-in) to flush audio
            is_audio_playing: Returns True if the speaker is still playing audio
        """
        self._config = config
        self._on_audio_output = on_audio_output
        self._on_tool_call = on_tool_call
        self._on_transcript = on_transcript
        self._on_speech_start = on_speech_start
        self._on_speech_end = on_speech_end
        self._on_interrupt = on_interrupt
        self._is_audio_playing = is_audio_playing

        voice_cfg = config.get("voice", {})
        self._model = voice_cfg.get("model", "gpt-4o-realtime-preview")
        self._voice = voice_cfg.get("voice", "alloy")
        self._turn_detection = voice_cfg.get("turn_detection", "server_vad")
        self._vad_threshold = voice_cfg.get("vad_threshold", 0.5)
        self._silence_ms = voice_cfg.get("silence_duration_ms", 600)
        self._energy_threshold = voice_cfg.get("local_energy_threshold", 200)
        self._mute_after_ms = voice_cfg.get("mute_after_speech_ms", 1500) / 1000.0

        self._api_key = get_api_key("openai")

        self._ws = None
        self._running = False
        self._recv_thread: Optional[threading.Thread] = None
        self._is_speaking = False
        self._mute_until = 0.0  # timestamp until which mic is muted (anti-echo)
        self._assistant_text = ""
        self._pending_tool_calls: Dict[str, Dict] = {}
        self._last_send_error_log_ts = 0.0
        self._tts_chunk_count = 0

    @property
    def is_connected(self) -> bool:
        return self._ws is not None and self._running

    @property
    def is_speaking(self) -> bool:
        return self._is_speaking

    def start(self):
        """Connect to the Realtime API and start the receive loop."""
        if self._running:
            return
        self._running = True
        if not self._connect():
            self._running = False
            raise RuntimeError("Failed to connect to OpenAI Realtime API")

        self._recv_thread = threading.Thread(target=self._receive_loop, daemon=True)
        self._recv_thread.start()
        log("Voice engine started", "SUCCESS")

    def stop(self):
        """Disconnect and stop."""
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None
        self._is_speaking = False
        try:
            from src.utils.network import unbind
            unbind()
        except Exception:
            pass
        log("Voice engine stopped")

    def on_audio_chunk(self, pcm16_bytes: bytes):
        """
        Feed a chunk of PCM16 audio from the microphone.
        Fully muted while robot is speaking to prevent echo loop.
        After speech ends, a short mute window prevents echo tail from triggering.
        """
        if not self._ws or not self._running:
            return

        if self._is_speaking:
            return
        if time.time() < self._mute_until:
            return
        if self._is_audio_playing and self._is_audio_playing():
            return

        if self._energy_threshold > 0:
            energy = _estimate_energy(pcm16_bytes)
            if energy < self._energy_threshold:
                return

        try:
            b64 = base64.b64encode(pcm16_bytes).decode("ascii")
            self._ws.send(json.dumps({
                "type": "input_audio_buffer.append",
                "audio": b64,
            }))
        except Exception as e:
            now = time.time()
            if now - self._last_send_error_log_ts > 2.0:
                log(f"Mic audio send failed, reconnecting voice: {e}", "WARNING")
                self._last_send_error_log_ts = now
            try:
                if self._ws:
                    self._ws.close()
            except Exception:
                pass
            self._ws = None

    def interrupt(self):
        """Cancel current response (barge-in)."""
        if self._ws:
            try:
                self._ws.send(json.dumps({"type": "response.cancel"}))
            except Exception:
                pass
        self._is_speaking = False

    # ── Private ──

    def _connect(self) -> bool:
        try:
            import websocket
            import ssl
            import certifi
        except ImportError as e:
            log(f"Missing dependency: {e}", "ERROR")
            return False

        from src.utils.network import bind_to_cellular
        try:
            bind_to_cellular()
        except Exception:
            pass

        url = f"{self.WS_URL}?model={self._model}"
        headers = [
            f"Authorization: Bearer {self._api_key}",
            "OpenAI-Beta: realtime=v1",
        ]

        connected = False
        for ssl_opts in [
            {"cert_reqs": ssl.CERT_REQUIRED, "ca_certs": certifi.where()},
            {"cert_reqs": ssl.CERT_NONE, "check_hostname": False},
        ]:
            try:
                ws = websocket.WebSocket(sslopt=ssl_opts)
                ws.settimeout(10)
                ws.connect(url, header=headers, timeout=10)
                ws.settimeout(None)
                self._ws = ws
                self._tts_chunk_count = 0
                self._configure_session()
                log("Connected to OpenAI Realtime API", "SUCCESS")
                connected = True
                break
            except Exception as e:
                log(f"WebSocket connect attempt failed: {e}", "WARNING")

        if not connected:
            log("All WebSocket connection attempts failed", "ERROR")
        else:
            log("Keeping process bound to cellular for voice stability", "INFO")
        return connected

    def _configure_session(self):
        """Send session configuration with personality, tools, and VAD settings."""
        instructions = self._build_instructions()

        turn_detection_config = {
            "type": self._turn_detection,
            "threshold": self._vad_threshold,
            "silence_duration_ms": self._silence_ms,
        }

        session = {
            "modalities": ["audio", "text"],
            "instructions": instructions,
            "voice": self._voice,
            "input_audio_format": "pcm16",
            "output_audio_format": "pcm16",
            "turn_detection": turn_detection_config,
            "tools": TOOLS,
            "tool_choice": "auto",
            "input_audio_transcription": {
                "model": "gpt-4o-mini-transcribe",
                "language": "fr",
                "prompt": "Conversation en français avec un chien robot nommé Néon. Les interlocuteurs sont des adultes et des enfants de 5 ans. Commandes fréquentes : donne la patte, assis, couché, avance, recule, tourne, danse, fais un cœur, Néon, stop.",
            },
        }

        self._ws.send(json.dumps({"type": "session.update", "session": session}))

    def _build_instructions(self) -> str:
        name = get_robot_name()
        personality = load_personality()
        masters = self._config.get("robot", {}).get("masters", [])
        stop_phrase = self._config.get("behavior", {}).get("emergency_stop_phrase", "STOP")

        identity = personality.get("identity", "Tu es {name}, un chien robot intelligent.")
        identity = identity.replace("{name}", name)
        style = personality.get("speaking_style", "")
        masters_rel = personality.get("masters_relationship", "")
        strangers_rel = personality.get("strangers_relationship", "")

        return (
            f"{identity}\n\n"
            f"Ton nom est {name}. Tu réponds à ton nom.\n"
            f"Tes maîtres sont : {', '.join(masters)}.\n\n"
            f"Style de parole :\n{style}\n\n"
            f"Relation avec tes maîtres :\n{masters_rel}\n\n"
            f"Relation avec les inconnus :\n{strangers_rel}\n\n"
            f"RÈGLES ABSOLUES :\n\n"
            f"1. LANGUE : Tu parles TOUJOURS en français. Tes interlocuteurs parlent français. Si la transcription semble être en anglais, chinois ou autre langue, c'est une erreur de transcription — essaie de deviner ce que la personne voulait dire en français.\n\n"
            f"2. INTERLOCUTEURS : Tu parles avec des adultes ET des enfants (5 ans et plus). Les enfants prononcent moins bien, parlent plus vite et avec des voix aiguës. Fais un effort pour les comprendre même si la transcription est approximative. Si un enfant dit quelque chose qui ressemble à 'donne la patte', 'danse', 'avance', etc., exécute l'ordre.\n\n"
            f"3. LONGUEUR : Réponds en 1 phrase courte maximum. Pas de question en retour.\n\n"
            f"4. CONVERSATION : Quand tu as répondu, tu attends. Tu ne relances pas.\n\n"
            f"   - Si tu n'es pas certain d'avoir entendu une vraie demande humaine, tu te tais.\n"
            f"   - Le bruit de ventilation, les frottements, les syllabes floues et les faux déclenchements ne sont PAS des ordres.\n"
            f"   - En cas de doute, tu ne parles pas et tu ne fais aucun mouvement.\n\n"
            f"5. ACTIONS PHYSIQUES :\n"
            f"   - Quand on te dit 'avance', 'recule', 'va à gauche', 'va à droite' → utilise move_robot.\n"
            f"   - Quand on te dit 'tourne', 'demi-tour', 'tourne à gauche/droite' → utilise turn_robot.\n"
            f"   - Quand on te dit 'danse', 'assis', 'couché', 'donne la patte', 'fais un cœur', 'étire-toi' → utilise do_action.\n"
            f"   - Quand on te dit '{stop_phrase}' ou 'stop' → utilise stop_robot.\n"
            f"   - Tu OBÉIS quand on te donne un ordre. Ne dis pas juste 'je reste tranquille'.\n"
            f"   - Par contre, ne fais JAMAIS d'action de ta propre initiative. Seulement quand on te le demande.\n"
            f"   - N'annonce jamais que tu bouges, danses ou fais un geste si personne ne vient de te le demander clairement.\n"
            f"   - Ne fais JAMAIS de sauts ou de flips (dangereux).\n"
            f"   - Ne te couche pas sauf si on te le demande explicitement.\n\n"
            f"6. DIVERS :\n"
            f"   - Ne lis jamais de JSON ou de données techniques.\n"
            f"   - Utilise set_emotion rarement.\n"
        )

    def _receive_loop(self):
        """Background thread: read events from the Realtime API."""
        backoff = 1.0
        while self._running:
            if not self._ws:
                if not self._connect():
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 8.0)
                    continue
                backoff = 1.0

            try:
                raw = self._ws.recv()
                if raw:
                    self._handle_event(json.loads(raw))
            except Exception as e:
                if self._ws:
                    try:
                        self._ws.close()
                    except Exception:
                        pass
                self._ws = None
                self._is_speaking = False
                log(f"Realtime API disconnected, reconnecting... ({e})", "WARNING")
                time.sleep(backoff)
                backoff = min(backoff * 2, 8.0)

    def _handle_event(self, event: Dict):
        etype = event.get("type", "")

        if etype in ("session.created", "session.updated"):
            return

        # ── Server VAD speech events ──
        if etype in ("input_audio_buffer.speech_started", "input_audio_buffer.speech_stopped"):
            still_playing = self._is_audio_playing and self._is_audio_playing()
            in_mute = time.time() < self._mute_until

            if still_playing or in_mute or self._is_speaking:
                if etype == "input_audio_buffer.speech_stopped":
                    try:
                        self._ws.send(json.dumps({"type": "input_audio_buffer.clear"}))
                    except Exception:
                        pass
                return

            return

        # ── Audio output (TTS) ──
        if etype == "response.audio.delta":
            audio_b64 = event.get("delta", "")
            if audio_b64 and self._on_audio_output:
                if not self._is_speaking:
                    self._is_speaking = True
                    self._tts_chunk_count = 0
                    log("Assistant audio output started", "INFO")
                    # Clear any mic audio buffered server-side to prevent echo barge-in
                    try:
                        self._ws.send(json.dumps({"type": "input_audio_buffer.clear"}))
                    except Exception:
                        pass
                    if self._on_speech_start:
                        try:
                            self._on_speech_start()
                        except Exception:
                            pass
                try:
                    self._tts_chunk_count += 1
                    self._on_audio_output(base64.b64decode(audio_b64))
                except Exception:
                    pass
            return

        if etype == "response.audio.done":
            self._is_speaking = False
            self._mute_until = time.time() + self._mute_after_ms
            log(f"Assistant audio output finished ({self._tts_chunk_count} chunks)", "INFO")
            # Clear server-side audio buffer to prevent echo-triggered responses
            try:
                self._ws.send(json.dumps({"type": "input_audio_buffer.clear"}))
            except Exception:
                pass
            if self._on_speech_end:
                try:
                    self._on_speech_end()
                except Exception:
                    pass
            return

        # ── Text transcript (assistant) ──
        if etype == "response.audio_transcript.delta":
            delta = event.get("delta", "")
            self._assistant_text += delta
            return

        if etype == "response.audio_transcript.done":
            text = event.get("transcript", self._assistant_text)
            if text and self._on_transcript:
                try:
                    self._on_transcript("assistant", text)
                except Exception:
                    pass
            self._assistant_text = ""
            return

        # ── Input transcript (user) ──
        if etype == "conversation.item.input_audio_transcription.completed":
            text = event.get("transcript", "")
            item_id = event.get("item_id", "")
            if text and not self._is_likely_human_request(text):
                log(f"Ignored likely noise transcript: {text}", "INFO")
                self._cancel_spurious_turn(item_id)
                return
            if text and self._on_transcript:
                try:
                    self._on_transcript("user", text)
                except Exception:
                    pass
            return

        # ── Tool calls ──
        if etype == "response.function_call_arguments.done":
            call_id = event.get("call_id", "")
            fn_name = event.get("name", "")
            args_str = event.get("arguments", "{}")

            try:
                args = json.loads(args_str)
            except json.JSONDecodeError:
                args = {}

            log(f"Tool call: {fn_name}({args})", "INFO")

            result = ""
            if self._on_tool_call:
                try:
                    result = self._on_tool_call(fn_name, args)
                    if result is None:
                        result = "ok"
                except Exception as e:
                    result = f"error: {e}"

            # Send tool result back to the API
            self._send_tool_result(call_id, str(result))
            return

        # ── Response done ──
        if etype == "response.done":
            self._is_speaking = False
            self._mute_until = time.time() + self._mute_after_ms
            return

        # ── Error ──
        if etype == "error":
            error = event.get("error", {})
            msg = error.get("message", str(event))
            if "no active response" in msg.lower():
                return
            log(f"Realtime API error: {msg}", "ERROR")
            return

    def _cancel_spurious_turn(self, item_id: str):
        if not self._ws:
            return
        try:
            if item_id:
                self._ws.send(json.dumps({
                    "type": "conversation.item.delete",
                    "item_id": item_id,
                }))
        except Exception:
            pass
        try:
            self._ws.send(json.dumps({"type": "response.cancel"}))
        except Exception:
            pass
        try:
            self._ws.send(json.dumps({"type": "input_audio_buffer.clear"}))
        except Exception:
            pass

    def _is_likely_human_request(self, text: str) -> bool:
        normalized = _normalize_text(text)
        words = [w for w in re.split(r"\s+", normalized) if w]

        if not words:
            return False

        if any(token in normalized for token in (
            "neon", "nion", "stop", "assis", "assis", "couche", "coucher",
            "leve", "debout", "avance", "recule", "tourne", "gauche", "droite",
            "danse", "patte", "coeur", "coeur", "coeur", "bonjour", "salut",
            "merci", "pourquoi", "comment", "quoi", "qui", "peux", "veux",
            "fais", "dis", "raconte", "tu ", "tu?", "t es", "t'es", "es tu",
        )):
            return True

        alpha_chars = sum(1 for c in normalized if "a" <= c <= "z")
        if len(words) <= 2:
            return False
        if alpha_chars < 8:
            return False

        # Long enough French-like utterances are accepted even without a command keyword.
        return len(words) >= 4

    def _send_tool_result(self, call_id: str, result: str):
        """Send function call result back to the API to continue the conversation."""
        if not self._ws:
            return

        try:
            # Add the tool result as a conversation item
            self._ws.send(json.dumps({
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": result,
                },
            }))
            # Trigger a new response so the LLM can react to the tool result
            self._ws.send(json.dumps({"type": "response.create"}))
        except Exception as e:
            log(f"Failed to send tool result: {e}", "ERROR")

def _estimate_energy(pcm16_bytes: bytes) -> int:
    """Quick RMS energy estimate for PCM16 mono audio."""
    if len(pcm16_bytes) < 2:
        return 0
    total = 0
    count = len(pcm16_bytes) // 2
    for i in range(0, len(pcm16_bytes) - 1, 2):
        sample = int.from_bytes(pcm16_bytes[i:i + 2], "little", signed=True)
        total += sample * sample
    if count == 0:
        return 0
    return int((total / count) ** 0.5)


def _normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower().strip()
