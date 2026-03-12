"""
Robot controller for Neon.
Manages WebRTC connection to Unitree Go2 and sends movement/gesture commands.

Uses the vendored unitree_webrtc_connect library (from Rex project).
"""

import asyncio
import json
import random
import logging as _logging
from typing import Any, Dict, Optional

from src.utils.logger import log


class _NeonLogHandler(_logging.Handler):
    _SKIP = ("setLocalDescription", "setRemoteDescription", "connection_made",
             "iceGatheringState", "Creating offer", "protocol(",
             "m=audio", "m=video", "m=application", "a=candidate",
             "a=ssrc", "a=ice-", "a=fingerprint", "a=setup", "a=mid",
             "a=sendrecv", "a=sendonly", "a=rtcp", "a=rtpmap", "a=fmtp",
             "a=group", "a=msid", "a=sctp", "v=0", "o=-", "s=-", "t=0",
             "c=IN", "Recieved con_", "Check CandidatePair",
             "Discovered peer", "rt/wirelesscontroller",
             "RtcpSrPacket", "RtcpSdesPacket", "RtcpRrPacket",
             "RTCSctpTransport", "RtcpByePacket",
             "Heartbeat", "heartbeat", "rtt_probe",
             "error_received", "DataChunk", "SackChunk",
             "RTCRtpSender", "BINDING", "a=recvonly")
    def emit(self, record):
        msg = record.getMessage()
        if any(s in msg for s in self._SKIP):
            return
        log(f"[WebRTC] {msg}", "INFO")


_log_handler_installed = False


ACTION_MAP = {
    "stand_up": "StandUp",
    "sit": "Sit",
    "lie_down": "StandDown",
    "wave_hello": "Hello",
    "stretch": "Stretch",
    "heart": "FingerHeart",
    "wiggle": "WiggleHips",
}


class RobotController:
    def __init__(self, config: Dict[str, Any]):
        self._config = config
        self._conn = None
        self._connected = False
        self._moving = False

        move_cfg = config.get("movement", {})
        self._max_speed = move_cfg.get("max_speed", 0.5)
        self._rotation_speed = move_cfg.get("rotation_speed", 0.8)
        self._obstacle_avoidance = move_cfg.get("obstacle_avoidance", True)

    @property
    def is_connected(self) -> bool:
        return self._connected

    async def connect(self) -> bool:
        conn_cfg = self._config.get("connection", {})
        method = conn_cfg.get("method", "ap").lower()
        robot_ip = conn_cfg.get("robot_ip", "192.168.12.1")
        serial = conn_cfg.get("serial_number", "")
        username = conn_cfg.get("remote_username", "")
        password = conn_cfg.get("remote_password", "")

        log(f"Connecting to Go2 (method={method}, ip={robot_ip})...")

        try:
            global _log_handler_installed
            if not _log_handler_installed:
                _ulog = _logging.getLogger()
                _ulog.handlers.clear()
                _ulog.addHandler(_NeonLogHandler())
                _ulog.setLevel(_logging.INFO)
                for noisy in ("aioice", "aiortc", "aiortc.rtcrtpreceiver",
                              "aiortc.rtcrtpsender", "aiortc.rtcsctptransport",
                              "aiortc.rtcdtlstransport", "aiortc.rtcicetransport"):
                    _logging.getLogger(noisy).setLevel(_logging.WARNING)
                _log_handler_installed = True

            from src.vendor.unitree_webrtc_connect.webrtc_driver import UnitreeWebRTCConnection
            from src.vendor.unitree_webrtc_connect.constants import WebRTCConnectionMethod
            from src.utils import network as _netmod

            if method == "sta":
                if serial and not robot_ip:
                    self._conn = UnitreeWebRTCConnection(
                        WebRTCConnectionMethod.LocalSTA, serialNumber=serial
                    )
                else:
                    self._conn = UnitreeWebRTCConnection(
                        WebRTCConnectionMethod.LocalSTA, ip=robot_ip
                    )
            elif method == "remote":
                self._conn = UnitreeWebRTCConnection(
                    WebRTCConnectionMethod.Remote,
                    serialNumber=serial,
                    username=username,
                    password=password,
                )
            else:
                self._conn = UnitreeWebRTCConnection(
                    WebRTCConnectionMethod.LocalAP
                )

            _netmod._find_networks()
            if _netmod._wifi_network is not None:
                _netmod.bind_to_wifi()
            else:
                log("No WiFi network available, skipping connection attempt", "WARNING")
                raise RuntimeError("No WiFi network available")
            try:
                await self._conn.connect()
            except Exception:
                try:
                    _netmod.unbind()
                except Exception:
                    pass
                raise

            try:
                _netmod.unbind()
            except Exception:
                pass

            self._connected = True
            log("Robot body connected!", "SUCCESS")

            await self._init_robot()
            return True

        except Exception as e:
            log(f"Robot connection failed: {e}", "ERROR")
            self._connected = False
            return False

    async def disconnect(self):
        if self._conn:
            try:
                await self._conn.disconnect()
            except Exception:
                pass
        self._connected = False
        log("Robot disconnected")

    async def _init_robot(self):
        try:
            await self._ensure_normal_mode()
        except Exception as e:
            log(f"Mode switch warning: {e}", "WARNING")

        if self._obstacle_avoidance:
            try:
                await self._set_obstacle_avoidance(True)
            except Exception as e:
                log(f"Obstacle avoidance warning: {e}", "WARNING")

    async def _send_sport_cmd(self, command_name: str, params=None) -> bool:
        if not self._conn or not self._connected:
            return False
        try:
            from src.vendor.unitree_webrtc_connect.constants import RTC_TOPIC, SPORT_CMD
            api_id = SPORT_CMD.get(command_name)
            if api_id is None:
                log(f"Unknown sport command: {command_name}", "WARNING")
                return False

            payload = {"api_id": api_id}
            if params:
                payload["parameter"] = params
            await self._conn.datachannel.pub_sub.publish_request_new(
                RTC_TOPIC["SPORT_MOD"], payload
            )
            return True
        except Exception as e:
            log(f"Sport command failed: {e}", "ERROR")
            return False

    async def _send_wireless(self, lx=0.0, ly=0.0, rx=0.0, ry=0.0, keys=0) -> bool:
        if not self._conn or not self._connected:
            return False
        try:
            from src.vendor.unitree_webrtc_connect.constants import RTC_TOPIC
            payload = {
                "lx": float(lx), "ly": float(ly),
                "rx": float(rx), "ry": float(ry),
                "keys": int(keys),
            }
            self._conn.datachannel.pub_sub.publish_without_callback(
                RTC_TOPIC["WIRELESS_CONTROLLER"], payload
            )
            return True
        except Exception as e:
            log(f"Wireless controller failed: {e}", "ERROR")
            return False

    async def move(self, direction="forward", speed=0.5, duration=0) -> str:
        """Move the robot using wireless controller (joystick) for obstacle avoidance support.
        duration=0 means continuous until stop_robot is called."""
        if not self._connected:
            return "Body not connected, cannot move."

        speed = max(0.1, min(1.0, speed)) * self._max_speed

        lx, ly, rx, ry = 0.0, 0.0, 0.0, 0.0
        if direction == "forward":
            ly = speed
        elif direction == "backward":
            ly = -speed
        elif direction == "left":
            lx = -speed
        elif direction == "right":
            lx = speed
        else:
            return f"Unknown direction: {direction}"

        log(f"Moving {direction} speed={speed:.2f}" +
            (f" for {duration:.1f}s" if duration > 0 else " (continuous)"), "ROBOT")

        self._moving = True

        if duration > 0:
            elapsed = 0.0
            while elapsed < duration and self._moving:
                await self._send_wireless(lx=lx, ly=ly, rx=rx, ry=ry)
                await asyncio.sleep(0.1)
                elapsed += 0.1
            self._moving = False
            await self._send_wireless()
            return f"Moved {direction} for {duration:.1f}s"
        else:
            asyncio.ensure_future(self._continuous_move_wireless(lx, ly, rx, ry))
            return f"Moving {direction} continuously — call stop_robot to stop"

    async def _continuous_move_wireless(self, lx, ly, rx, ry):
        """Send wireless controller commands in a loop until self._moving is False."""
        while self._moving and self._connected:
            await self._send_wireless(lx=lx, ly=ly, rx=rx, ry=ry)
            await asyncio.sleep(0.1)

    async def turn(self, direction="left", angle=90) -> str:
        """Turn the robot using wireless controller (joystick) for obstacle avoidance support."""
        if not self._connected:
            return "Body not connected, cannot turn."

        import math
        angle_rad = abs(angle) * math.pi / 180.0
        rx = -self._rotation_speed if direction == "left" else self._rotation_speed

        duration = angle_rad / self._rotation_speed

        log(f"Turning {direction} {angle}° (duration={duration:.1f}s, rx={rx:.2f})", "ROBOT")

        elapsed = 0.0
        while elapsed < duration:
            await self._send_wireless(rx=rx)
            await asyncio.sleep(0.1)
            elapsed += 0.1

        await self._send_wireless()

        return f"Turned {direction} {angle}°"

    async def do_action(self, action: str) -> str:
        if not self._connected:
            return "Body not connected, cannot perform action."

        if action == "dance":
            sport_name = random.choice(["Dance1", "Dance2"])
        else:
            sport_name = ACTION_MAP.get(action)

        if not sport_name:
            return f"Unknown action: {action}"

        log(f"Action: {action} (sport cmd: {sport_name})", "ROBOT")

        if sport_name not in ("StandUp", "StandDown"):
            await self._stand_up_first()

        ok = await self._send_sport_cmd(sport_name)
        if not ok:
            log(f"Action {action} may have failed to send", "WARNING")
            return f"Failed to send {action}"
        return f"Performing {action}"

    async def _stand_up_first(self):
        """Send RecoveryStand to ensure robot is standing, then brief pause."""
        try:
            await self._send_sport_cmd("RecoveryStand")
            await asyncio.sleep(0.5)
        except Exception:
            pass

    async def stop(self) -> str:
        log("STOP command!", "ROBOT")
        self._moving = False
        await self._send_wireless()
        await self._send_sport_cmd("StopMove")
        return "Stopped"

    async def emergency_stop(self) -> str:
        log("EMERGENCY STOP!", "ROBOT")
        self._moving = False
        await self._send_sport_cmd("StopMove")
        await self._send_sport_cmd("StandDown")
        return "Emergency stop — lying down"

    async def _ensure_normal_mode(self):
        if not self._conn:
            return
        try:
            from src.vendor.unitree_webrtc_connect.constants import RTC_TOPIC
            response = await self._conn.datachannel.pub_sub.publish_request_new(
                RTC_TOPIC["MOTION_SWITCHER"], {"api_id": 1001}
            )
            current_mode = None
            if response and response.get("data"):
                data = response["data"].get("data")
                if data:
                    decoded = json.loads(data) if isinstance(data, str) else data
                    current_mode = decoded.get("name")
            if current_mode != "normal":
                await self._conn.datachannel.pub_sub.publish_request_new(
                    RTC_TOPIC["MOTION_SWITCHER"],
                    {"api_id": 1002, "parameter": {"name": "normal"}},
                )
                await asyncio.sleep(2)
                log("Switched to normal mode", "ROBOT")
        except Exception as e:
            log(f"Failed to switch motion mode: {e}", "WARNING")

    async def _set_obstacle_avoidance(self, enabled: bool):
        if not self._conn:
            return
        try:
            from src.vendor.unitree_webrtc_connect.constants import RTC_TOPIC
            set_payload = {"api_id": 1002, "parameter": enabled}
            response = await self._conn.datachannel.pub_sub.publish_request_new(
                RTC_TOPIC["OBSTACLES_AVOID"], set_payload
            )
            status_code = -1
            if response and response.get("data"):
                status_code = response["data"].get("header", {}).get("status", {}).get("code", -1)

            if status_code == 0:
                log(f"Obstacle avoidance {'enabled' if enabled else 'disabled'}", "ROBOT")
                return

            for alt_payload in [
                {"api_id": 1002, "parameter": {"switch": enabled}},
                {"api_id": 1002, "parameter": {"data": enabled}},
            ]:
                try:
                    resp = await self._conn.datachannel.pub_sub.publish_request_new(
                        RTC_TOPIC["OBSTACLES_AVOID"], alt_payload
                    )
                    if resp and resp.get("data"):
                        code = resp["data"].get("header", {}).get("status", {}).get("code", -1)
                        if code == 0:
                            log(f"Obstacle avoidance {'enabled' if enabled else 'disabled'} (alt)", "ROBOT")
                            return
                except Exception:
                    continue

            log("Obstacle avoidance: no confirmation received, may still be active", "WARNING")
        except Exception as e:
            log(f"Obstacle avoidance setup failed: {e}", "WARNING")
