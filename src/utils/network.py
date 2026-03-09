"""
Network manager for Neon.

On Android, when connected to the robot's WiFi AP (which has no internet),
we need to explicitly route traffic:
  - OpenAI WebSocket → cellular (4G/5G)
  - Robot HTTP/WebRTC → WiFi (192.168.12.1)

The key insight: once a TCP socket is established through a particular network
interface, it stays on that interface even if we change the process-wide binding.
So we:
  1. Bind to cellular → connect WebSocket → unbind
  2. Bind to WiFi → connect robot HTTP → unbind
  3. Both connections continue working through their respective interfaces
"""

from kivy.utils import platform
from src.utils.logger import log

_cm = None
_cellular_network = None
_wifi_network = None


def _ensure_cm():
    """Initialize the ConnectivityManager if needed."""
    global _cm
    if platform != "android" or _cm is not None:
        return
    from jnius import autoclass
    PythonActivity = autoclass("org.kivy.android.PythonActivity")
    Context = autoclass("android.content.Context")
    activity = PythonActivity.mActivity
    _cm = activity.getSystemService(Context.CONNECTIVITY_SERVICE)


def _find_networks():
    """Discover cellular and WiFi network objects."""
    global _cellular_network, _wifi_network
    if platform != "android":
        return

    _ensure_cm()
    if _cm is None:
        return

    from jnius import autoclass
    NetworkCapabilities = autoclass("android.net.NetworkCapabilities")

    networks = _cm.getAllNetworks()
    for network in networks:
        caps = _cm.getNetworkCapabilities(network)
        if caps is None:
            continue

        if caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR):
            if caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET):
                _cellular_network = network

        if caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI):
            _wifi_network = network


def bind_to_cellular():
    """Bind process to cellular for internet access (OpenAI API)."""
    if platform != "android":
        return
    _ensure_cm()
    _find_networks()

    if _cellular_network is None:
        log("No cellular network available", "WARNING")
        return

    try:
        _cm.bindProcessToNetwork(_cellular_network)
        log("Process bound to cellular", "SUCCESS")
    except Exception as e:
        log(f"Cellular bind failed: {e}", "WARNING")


def bind_to_wifi():
    """Bind process to WiFi for local robot access."""
    if platform != "android":
        return
    _ensure_cm()
    _find_networks()

    if _wifi_network is None:
        log("No WiFi network available", "WARNING")
        return

    try:
        _cm.bindProcessToNetwork(_wifi_network)
        log("Process bound to WiFi", "SUCCESS")
    except Exception as e:
        log(f"WiFi bind failed: {e}", "WARNING")


def unbind():
    """Remove process-wide network binding (use system default routing)."""
    if platform != "android":
        return
    _ensure_cm()
    if _cm is None:
        return
    try:
        _cm.bindProcessToNetwork(None)
    except Exception as e:
        log(f"Unbind failed: {e}", "WARNING")


# Legacy aliases
def setup_dual_network():
    bind_to_cellular()

def _bind_to_cellular():
    bind_to_cellular()

def unbind_for_local():
    unbind()
