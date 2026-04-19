"""Convenient public exports for the NetSim source modules.

Import from this module to access core simulation types from one place.
"""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
	from .channel import Channel as Channel
	from .network import Network as Network
	from .network_sim import Event as Event
	from .network_sim import NetworkSim as NetworkSim
	from .node import Node as Node
	from .packet import Packet as Packet

_EXPORTS = {
	"Channel": ("channel", "Channel"),
	"Network": ("network", "Network"),
	"NetworkSim": ("network_sim", "NetworkSim"),
	"Event": ("network_sim", "Event"),
	"Node": ("node", "Node"),
	"Packet": ("packet", "Packet"),
}

__all__ = (
	"Channel",
	"Network",
	"NetworkSim",
	"Event",
	"Node",
	"Packet",
)


def __getattr__(name: str) -> Any:
	if name not in _EXPORTS:
		raise AttributeError(f"module 'index' has no attribute '{name}'")

	module_name, symbol_name = _EXPORTS[name]
	module = import_module(f".{module_name}", package=__package__)
	symbol = getattr(module, symbol_name)
	globals()[name] = symbol
	return symbol


def __dir__() -> list[str]:
	return sorted(set(globals().keys()) | set(__all__))
