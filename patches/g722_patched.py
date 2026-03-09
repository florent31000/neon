import fractions
from typing import Optional, cast

try:
    from av import AudioFrame, AudioResampler, CodecContext
    from av.frame import Frame
    from av.packet import Packet
    try:
        from av import AudioCodecContext
    except ImportError:
        AudioCodecContext = None
    _AV_OK = True
except ImportError:
    _AV_OK = False

from ..jitterbuffer import JitterFrame
from ..mediastreams import convert_timebase
from .base import Decoder, Encoder

SAMPLE_RATE = 16000
SAMPLE_WIDTH = 2
SAMPLES_PER_FRAME = 320
TIME_BASE = fractions.Fraction(1, 16000)
CLOCK_BASE = fractions.Fraction(1, 8000)

_G722_AVAILABLE = _AV_OK


class G722Decoder(Decoder):
    def __init__(self):
        if not _G722_AVAILABLE:
            raise RuntimeError("G722 codec not available")
        self.codec = CodecContext.create("g722", "r")
        self.codec.format = "s16"
        self.codec.layout = "mono"
        self.codec.sample_rate = SAMPLE_RATE

    def decode(self, encoded_frame):
        packet = Packet(encoded_frame.data)
        packet.pts = encoded_frame.timestamp * 2
        packet.time_base = TIME_BASE
        return list(self.codec.decode(packet))


class G722Encoder(Encoder):
    def __init__(self):
        if not _G722_AVAILABLE:
            raise RuntimeError("G722 codec not available")
        self.codec = CodecContext.create("g722", "w")
        self.codec.format = "s16"
        self.codec.layout = "mono"
        self.codec.sample_rate = SAMPLE_RATE
        self.codec.time_base = TIME_BASE
        self.first_pts = None
        self.resampler = AudioResampler(
            format="s16", layout="mono", rate=SAMPLE_RATE,
            frame_size=SAMPLES_PER_FRAME,
        )

    def encode(self, frame, force_keyframe=False):
        packets = []
        for frame in self.resampler.resample(frame):
            packets += self.codec.encode(frame)
        if packets:
            if self.first_pts is None:
                self.first_pts = packets[0].pts
            timestamp = (packets[0].pts - self.first_pts) // 2
            return [bytes(p) for p in packets], timestamp
        else:
            return [], None

    def pack(self, packet):
        timestamp = convert_timebase(packet.pts, packet.time_base, CLOCK_BASE)
        return [bytes(packet)], timestamp
