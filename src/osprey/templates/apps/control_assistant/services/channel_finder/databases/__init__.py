"""
Database implementations for Channel Finder.

Provides various database backend implementations:
- flat: Simple flat list format (base implementation for in-context databases)
- template: Compact template-based format with expansion (extends flat)
- hierarchical: Hierarchical tree structure for large databases
"""

from .flat import ChannelDatabase as FlatChannelDatabase
from .hierarchical import HierarchicalChannelDatabase
from .template import ChannelDatabase as TemplateChannelDatabase

# Backward compatibility alias
LegacyChannelDatabase = FlatChannelDatabase

__all__ = [
    "FlatChannelDatabase",
    "LegacyChannelDatabase",  # Backward compatibility
    "TemplateChannelDatabase",
    "HierarchicalChannelDatabase",
]
