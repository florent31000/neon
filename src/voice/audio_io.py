"""
Audio I/O for Neon.

Handles microphone capture and speaker playback on Android (via jnius/AudioRecord/AudioTrack)
and desktop (via sounddevice for testing).

Key design: AudioPlayer uses a dedicated writer thread with a queue so that
the WebSocket receive thread is never blocked by AudioTrack.write().
Without this, blocking writes cause chunks to pile up and audio cuts out.
"""

import queue
import threading
import time
from typing import Callable, Optional

from kivy.utils import platform

from src.utils.logger import log


class SpectralGateFilter:
    """Adaptive spectral-gating noise reduction using only numpy.

    Works like noise-cancelling headphones:
    1. During the first ~1s of audio (calibration phase), learns the
       spectral profile of the ambient noise (fan, motor, etc.).
    2. For all subsequent audio, performs STFT, subtracts the learned
       noise floor (with a safety margin), and reconstructs clean audio.

    This removes *any* stationary background noise, not just a specific
    frequency — much more effective than notch or high-pass filters.
    """

    def __init__(self, sample_rate: int = 16000, fft_size: int = 512,
                 hop_size: int = 256, calibration_chunks: int = 10,
                 noise_gain: float = 1.5, smoothing: float = 0.02):
        self._sr = sample_rate
        self._fft_size = fft_size
        self._hop_size = hop_size
        self._calibration_chunks = calibration_chunks
        self._noise_gain = noise_gain
        self._smoothing = smoothing

        self._chunk_count = 0
        self._noise_profile = None
        self._calibration_frames = []
        self._prev_tail = None

    def process(self, pcm16_bytes: bytes) -> bytes:
        import numpy as np

        input_samples = np.frombuffer(pcm16_bytes, dtype=np.int16).astype(np.float64)
        n_input = len(input_samples)
        if n_input == 0:
            return pcm16_bytes

        self._chunk_count += 1

        if self._chunk_count <= self._calibration_chunks:
            self._calibration_frames.append(input_samples.copy())
            if self._chunk_count == self._calibration_chunks:
                self._build_noise_profile(np.concatenate(self._calibration_frames))
                self._calibration_frames = []
            return pcm16_bytes

        if self._noise_profile is None:
            return pcm16_bytes

        if self._prev_tail is not None and len(self._prev_tail) > 0:
            samples = np.concatenate([self._prev_tail, input_samples])
        else:
            samples = input_samples

        fft_size = self._fft_size
        hop = self._hop_size
        total = len(samples)
        n_frames = max(0, (total - fft_size) // hop + 1)

        if n_frames == 0:
            self._prev_tail = samples
            return pcm16_bytes

        window = np.hanning(fft_size)
        out_len = n_frames * hop + fft_size
        out = np.zeros(out_len, dtype=np.float64)
        win_sum = np.zeros(out_len, dtype=np.float64)

        noise_mag = self._noise_profile
        gain = self._noise_gain
        floor_frac = self._smoothing

        for i in range(n_frames):
            start = i * hop
            frame = samples[start:start + fft_size] * window
            spectrum = np.fft.rfft(frame)
            mag = np.abs(spectrum)
            phase = np.angle(spectrum)

            clean_mag = mag - gain * noise_mag
            clean_mag = np.maximum(clean_mag, floor_frac * mag)

            clean_frame = np.fft.irfft(clean_mag * np.exp(1j * phase), n=fft_size)

            out[start:start + fft_size] += clean_frame * window
            win_sum[start:start + fft_size] += window * window

        win_sum = np.maximum(win_sum, 1e-8)
        out /= win_sum

        consumed = n_frames * hop
        self._prev_tail = samples[consumed:].copy() if consumed < total else None

        tail_offset = len(samples) - n_input
        clean = out[tail_offset:tail_offset + n_input]

        if len(clean) < n_input:
            padded = np.zeros(n_input, dtype=np.float64)
            padded[:len(clean)] = clean
            clean = padded

        return np.clip(clean, -32768, 32767).astype(np.int16).tobytes()

    def _build_noise_profile(self, noise_samples):
        import numpy as np
        from src.utils.logger import log
        fft_size = self._fft_size
        hop = self._hop_size
        window = np.hanning(fft_size)
        total = len(noise_samples)
        n_frames = max(1, (total - fft_size) // hop + 1)

        mag_sum = np.zeros(fft_size // 2 + 1, dtype=np.float64)
        for i in range(n_frames):
            start = i * hop
            end = start + fft_size
            if end > total:
                break
            frame = noise_samples[start:end] * window
            mag_sum += np.abs(np.fft.rfft(frame))

        self._noise_profile = mag_sum / n_frames
        peak_bin = np.argmax(self._noise_profile)
        peak_freq = peak_bin * self._sr / fft_size
        log(f"Noise profile calibrated: {n_frames} frames, peak at ~{peak_freq:.0f} Hz", "INFO")


class AudioCapture:
    """
    Captures PCM16 mono audio from the microphone.
    Applies spectral-gating noise reduction (learns ambient noise, then subtracts it).
    Calls on_chunk(bytes) with each audio chunk.
    """

    def __init__(
        self,
        sample_rate: int = 16000,
        chunk_ms: int = 100,
        on_chunk: Optional[Callable[[bytes], None]] = None,
    ):
        self._sample_rate = sample_rate
        self._chunk_size = int(sample_rate * chunk_ms / 1000) * 2
        self._on_chunk = on_chunk
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._filter = SpectralGateFilter(sample_rate=sample_rate)

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        log("Audio capture started", "SUCCESS")

    def stop(self):
        self._running = False

    def _capture_loop(self):
        if platform == "android":
            self._capture_android()
        else:
            self._capture_desktop()

    def _capture_android(self):
        try:
            from jnius import autoclass

            AudioRecord = autoclass("android.media.AudioRecord")
            AudioFormat = autoclass("android.media.AudioFormat")
            AudioSource = autoclass("android.media.MediaRecorder$AudioSource")

            channel = AudioFormat.CHANNEL_IN_MONO
            encoding = AudioFormat.ENCODING_PCM_16BIT
            source = AudioSource.MIC

            min_buf = AudioRecord.getMinBufferSize(self._sample_rate, channel, encoding)
            buf_size = max(min_buf * 2, self._chunk_size * 4)

            recorder = AudioRecord(source, self._sample_rate, channel, encoding, buf_size)
            recorder.startRecording()
            log(f"Android AudioRecord started (rate={self._sample_rate}, buf={buf_size})")

            while self._running:
                buf = bytearray(self._chunk_size)
                read = recorder.read(buf, 0, len(buf))
                if read > 0 and self._on_chunk:
                    filtered = self._filter.process(bytes(buf[:read]))
                    self._on_chunk(filtered)

            recorder.stop()
            recorder.release()
        except Exception as e:
            log(f"Android audio capture error: {e}", "ERROR")

    def _capture_desktop(self):
        try:
            import sounddevice as sd
            import numpy as np

            def callback(indata, frames, time_info, status):
                if self._on_chunk and self._running:
                    pcm = (indata[:, 0] * 32767).astype(np.int16).tobytes()
                    self._on_chunk(pcm)

            with sd.InputStream(
                samplerate=self._sample_rate,
                channels=1,
                dtype="float32",
                blocksize=self._chunk_size // 2,
                callback=callback,
            ):
                while self._running:
                    time.sleep(0.1)
        except ImportError:
            log("sounddevice not available — no mic capture on desktop", "WARNING")
            while self._running:
                time.sleep(1)
        except Exception as e:
            log(f"Desktop audio capture error: {e}", "ERROR")


class AudioPlayer:
    """
    Plays PCM16 mono audio through the speaker.

    Uses an internal queue + dedicated writer thread so that callers (the
    WebSocket receive thread) are never blocked by AudioTrack.write().
    This prevents audio cutting out when the AudioTrack buffer is full.
    """

    QUEUE_MAX = 200  # ~200 chunks ≈ several seconds of audio buffer

    def __init__(self, sample_rate: int = 24000):
        self._sample_rate = sample_rate
        self._track = None
        self._lock = threading.Lock()
        self._queue: queue.Queue = queue.Queue(maxsize=self.QUEUE_MAX)
        self._running = False
        self._writer_thread: Optional[threading.Thread] = None
        self._playing = False  # True while audio is being written to AudioTrack

    @property
    def is_playing(self) -> bool:
        """True if audio is currently being played or queued for playback."""
        return self._playing or not self._queue.empty()

    def start(self):
        if self._running:
            return
        self._running = True
        self._writer_thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._writer_thread.start()

        if platform == "android":
            threading.Thread(target=self._eager_init_track, daemon=True).start()

    def _eager_init_track(self):
        """Pre-initialize AudioTrack so the first audio chunk plays instantly."""
        try:
            with self._lock:
                if self._track is None:
                    self._init_android_track()
        except Exception as e:
            log(f"Early AudioTrack init failed (will retry on first write): {e}", "WARNING")

    def write(self, pcm16_bytes: bytes):
        """Enqueue PCM16 audio data — never blocks the caller for long."""
        if not self._running:
            self.start()
        try:
            self._queue.put_nowait(pcm16_bytes)
        except queue.Full:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                pass
            try:
                self._queue.put_nowait(pcm16_bytes)
            except queue.Full:
                pass

    def flush(self):
        """Drop all queued audio (used on barge-in / interrupt)."""
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break

    def _writer_loop(self):
        """Dedicated thread that drains the queue into AudioTrack."""
        while self._running:
            try:
                data = self._queue.get(timeout=0.1)
            except queue.Empty:
                self._playing = False
                continue

            self._playing = True
            if platform == "android":
                self._write_android(data)
            else:
                self._write_desktop(data)

            if self._queue.empty():
                self._playing = False

    def _write_android(self, data: bytes):
        with self._lock:
            if self._track is None:
                try:
                    self._init_android_track()
                except Exception as e:
                    log(f"AudioTrack init error: {e}", "ERROR")
                    return
            if self._track:
                try:
                    jdata = bytearray(data)
                    self._track.write(jdata, 0, len(jdata))
                except Exception as e:
                    log(f"AudioTrack write error: {e}", "ERROR")
                    self._track = None

    def _init_android_track(self):
        from jnius import autoclass

        AudioTrack = autoclass("android.media.AudioTrack")
        AudioFormat = autoclass("android.media.AudioFormat")
        AudioManager = autoclass("android.media.AudioManager")
        PythonActivity = autoclass("org.kivy.android.PythonActivity")
        Context = autoclass("android.content.Context")

        activity = PythonActivity.mActivity
        audio = activity.getSystemService(Context.AUDIO_SERVICE)
        if audio is not None:
            try:
                max_vol = audio.getStreamMaxVolume(AudioManager.STREAM_MUSIC)
                current = audio.getStreamVolume(AudioManager.STREAM_MUSIC)
                target = max(1, int(max_vol * 0.7))
                if current < target:
                    audio.setStreamVolume(AudioManager.STREAM_MUSIC, target, 0)
                    current = target
                log(f"Android media volume {current}/{max_vol}")
            except Exception as e:
                log(f"Could not adjust media volume: {e}", "WARNING")

        min_buf = AudioTrack.getMinBufferSize(
            self._sample_rate,
            AudioFormat.CHANNEL_OUT_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
        )

        buf_size = max(min_buf * 4, 16384)

        self._track = AudioTrack(
            AudioManager.STREAM_MUSIC,
            self._sample_rate,
            AudioFormat.CHANNEL_OUT_MONO,
            AudioFormat.ENCODING_PCM_16BIT,
            buf_size,
            AudioTrack.MODE_STREAM,
        )
        self._track.play()
        log(f"Android AudioTrack initialized (buf={buf_size}, state={self._track.getState()}, play={self._track.getPlayState()})")

    def _write_desktop(self, data: bytes):
        try:
            import sounddevice as sd
            import numpy as np
            samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32767.0
            sd.play(samples, samplerate=self._sample_rate, blocking=False)
        except ImportError:
            pass
        except Exception:
            pass

    def stop(self):
        self._running = False
        self.flush()
        with self._lock:
            if self._track:
                try:
                    self._track.stop()
                    self._track.release()
                except Exception:
                    pass
                self._track = None
