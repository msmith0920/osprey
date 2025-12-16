"""
{{ app_display_name }} - Control System Assistant

A production-grade template demonstrating control system integration patterns.
Based on the ALS Accelerator Assistant deployment (arXiv:2509.17255).

Features:
- Natural language channel finding (in-context or hierarchical pipelines)
- Historical data analysis (mock archiver)
- Live control system reads (mock EPICS)
- Complete benchmarking system
- Optional MCP server deployment

Architecture:
- Service Layer: Business logic (services/)
- Capability Layer: Osprey integration (capabilities/)
- Optional MCP: Standalone server deployment (services/channel_finder/)
"""

__version__ = "0.1.0"

# ---------------------------------------------------------------------------
# Compatibility: Osprey 0.10+ removed `get_logger` from BaseCapability.
# The assistant code still calls `self.get_logger()`, so we add a small shim
# that maps to the newer logger attribute if it exists.
# ---------------------------------------------------------------------------
import logging
from osprey.base.capability import BaseCapability

if not hasattr(BaseCapability, "get_logger"):
    def get_logger(self):
        """
        Preserve the legacy get_logger API used throughout the capabilities.
        Prefer any logger already provisioned by the framework; otherwise fall
        back to a standard Python logger keyed by capability name.
        """
        for attr in ("logger", "log", "_logger"):
            logger = getattr(self, attr, None)
            if logger:
                return logger
        return logging.getLogger(getattr(self, "name", self.__class__.__name__))

    BaseCapability.get_logger = get_logger  # type: ignore[attr-defined]
