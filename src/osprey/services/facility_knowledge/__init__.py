"""
Facility Knowledge Service

Provides access to the OKF (OSPREY Knowledge Framework) document model and related
utilities for parsing, validating, and serializing facility knowledge documents.

Note: the seeder subpackage is intentionally excluded from this namespace — import it
directly from ``osprey.services.facility_knowledge.seed`` to avoid circular loading.
"""

from .okf import OKFDocument, OKFDocumentError

__all__ = [
    "OKFDocument",
    "OKFDocumentError",
]
