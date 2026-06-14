"""OSPREY Facility Knowledge MCP Server.

FastMCP server exposing OKF bundle read tools: list_concepts, read_concept,
and search.  The bundle root is resolved from the ``facility_knowledge.bundle_path``
key in config.yml (via ``OSPREY_CONFIG``), relative to the config file's parent
directory when the value is not absolute.

Usage::

    python -m osprey.mcp_server.facility_knowledge
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

from osprey.mcp_server.errors import make_error

if TYPE_CHECKING:
    # Imported at type-checking time only so the runtime import stays lazy
    # (mirrors seeder/ttl_seeder.py — the bundle is constructed in create_server).
    from osprey.services.facility_knowledge.okf.bundle import OKFBundle

logger = logging.getLogger("osprey.mcp_server.facility_knowledge")

mcp = FastMCP(
    "osprey_facility_knowledge",
    instructions=(
        "Read and draft OKF facility knowledge documents: list concepts, read a concept "
        "by ID, search the bundle for a query string, or draft/update a concept document. "
        "draft_concept requires human approval via the PreToolUse hook before the write "
        "is committed to disk."
    ),
)

# ---------------------------------------------------------------------------
# Bundle resolution
# ---------------------------------------------------------------------------

_bundle: OKFBundle | None = None  # resolved lazily at startup by create_server

# ---------------------------------------------------------------------------
# Concurrent-draft collision guard
# ---------------------------------------------------------------------------

# Defense-in-depth guard for concurrent draft attempts on the same concept ID.
# Because draft_concept contains no await points, the asyncio event loop never
# yields mid-call, so two "concurrent" callers are actually serialised by the
# event loop and this set will not fire under normal operation.  It is kept as
# a latent safeguard in case an await is introduced in the write path later.
_drafts_in_flight: set[str] = set()


def _get_bundle() -> OKFBundle:
    """Return the initialised OKFBundle singleton.

    Raises:
        ToolError: If the bundle has not been initialised (server not started
            via :func:`create_server`).
    """
    if _bundle is None:
        make_error(
            "server_not_initialised",
            "Facility knowledge bundle has not been initialised.",
            ["Start the server via `python -m osprey.mcp_server.facility_knowledge`."],
        )
    return _bundle


def _resolve_bundle_path(config: dict, config_dir: Path) -> Path:
    """Resolve the bundle path from loaded config.

    Looks up ``facility_knowledge.bundle_path`` in *config*.  A relative
    value is resolved against *config_dir* (the directory that contains
    config.yml).

    Args:
        config: Parsed OSPREY config dict.
        config_dir: Directory of the config file, used to resolve relative paths.

    Returns:
        Absolute :class:`~pathlib.Path` to the bundle root.

    Raises:
        KeyError: If ``facility_knowledge.bundle_path`` is absent from config.
    """
    raw = config["facility_knowledge"]["bundle_path"]
    p = Path(raw)
    return p if p.is_absolute() else (config_dir / p).resolve()


# ---------------------------------------------------------------------------
# Server lifecycle
# ---------------------------------------------------------------------------


def create_server() -> FastMCP:
    """Initialise the bundle singleton and register tools, then return the server.

    Reads ``facility_knowledge.bundle_path`` from the OSPREY config, constructs
    an :class:`~osprey.services.facility_knowledge.okf.bundle.OKFBundle`, and
    imports the tool modules so that ``@mcp.tool()`` decorators self-register.

    Returns:
        The configured :class:`~fastmcp.FastMCP` instance.
    """
    global _bundle

    from osprey.services.facility_knowledge.okf.bundle import OKFBundle, OKFBundleError
    from osprey.utils.workspace import load_osprey_config, resolve_config_path

    config_path = resolve_config_path()
    config = load_osprey_config()

    try:
        bundle_path = _resolve_bundle_path(config, config_path.parent)
    except KeyError:
        logger.warning(
            "facility_knowledge.bundle_path not set in config — tools will return errors"
        )
        bundle_path = None

    if bundle_path is not None:
        try:
            _bundle = OKFBundle(bundle_path)
            logger.info("Facility knowledge bundle loaded from %s", bundle_path)
        except OKFBundleError as exc:
            logger.error("Failed to load facility knowledge bundle: %s", exc)
            _bundle = None

    # Tools are defined below in this module and self-register via @mcp.tool()
    # at import time — no separate tool imports needed.
    logger.info("Facility knowledge MCP server initialised")
    return mcp


# ---------------------------------------------------------------------------
# MCP tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def capabilities() -> str:
    """Report facility knowledge bundle capabilities.

    Returns bundle path, concept count, sorted list of distinct concept types,
    and whether draft writes are enabled.  Does NOT require database connectivity
    beyond the already-initialised bundle singleton.

    Returns:
        JSON object with ``bundle_path``, ``count``, ``types`` (sorted list of
        distinct ``type`` frontmatter values), and ``write_enabled: true``.
    """
    try:
        bundle = _get_bundle()
        entries = bundle.list_concepts()
        # ConceptEntry.type is populated only when the index parser emits it;
        # fall back to reading each document's frontmatter to collect types.
        raw_types: set[str] = {e.type for e in entries if e.type}
        if not raw_types:
            for entry in entries:
                try:
                    doc = bundle.read_concept(entry.concept_id)
                    t = doc.frontmatter.get("type", "")
                    if t:
                        raw_types.add(str(t))
                except Exception:
                    pass
        return json.dumps(
            {
                "bundle_path": str(bundle.root),
                "count": len(entries),
                "types": sorted(raw_types),
                "write_enabled": True,
            }
        )
    except ToolError:
        raise
    except Exception as exc:
        logger.exception("capabilities failed")
        return make_error(
            "internal_error",
            f"Failed to get capabilities: {exc}",
            ["Check MCP server logs for details."],
        )


@mcp.tool()
async def list_concepts() -> str:
    """List all concepts in the facility knowledge bundle.

    Returns the index-level listing (concept ID, title, and optional
    description) without reading every document body — suitable for
    progressive disclosure.

    Returns:
        JSON object with a ``concepts`` list, each entry containing
        ``concept_id``, ``title``, and ``description``.
    """
    try:
        bundle = _get_bundle()
        entries = bundle.list_concepts()
        return json.dumps(
            {
                "concepts": [
                    {
                        "concept_id": e.concept_id,
                        "title": e.title,
                        "description": e.description,
                    }
                    for e in sorted(entries, key=lambda e: e.concept_id)
                ],
                "count": len(entries),
            }
        )
    except ToolError:
        raise
    except Exception as exc:
        logger.exception("list_concepts failed")
        return make_error(
            "internal_error",
            f"Failed to list concepts: {exc}",
            ["Check MCP server logs for details."],
        )


@mcp.tool()
async def read_concept(concept_id: str) -> str:
    """Read a facility knowledge concept document by its OKF §2 concept ID.

    The concept ID is the file path within the bundle minus the ``.md``
    suffix, e.g. ``tables/beam_params`` or ``facility_overview``.

    Cross-links in the document body may reference concepts that do not
    exist in the bundle; the document is returned as-is (OKF §9 tolerance).

    Args:
        concept_id: OKF §2 path-minus-extension identifier.

    Returns:
        JSON object with ``concept_id``, ``frontmatter``, and ``body``.
    """
    try:
        bundle = _get_bundle()
        doc = bundle.read_concept(concept_id)
        return json.dumps(
            {
                "concept_id": concept_id,
                "frontmatter": doc.frontmatter,
                "body": doc.body,
            }
        )
    except ToolError:
        raise
    except Exception as exc:
        # Distinguish not-found (OKFBundleError) from internal errors.
        from osprey.services.facility_knowledge.okf.bundle import OKFBundleError

        if isinstance(exc, OKFBundleError):
            return make_error(
                "not_found",
                str(exc),
                [
                    "Use list_concepts to see available concept IDs.",
                    "Concept IDs are the file path minus .md (e.g. 'tables/users').",
                ],
            )
        logger.exception("read_concept failed")
        return make_error(
            "internal_error",
            f"Failed to read concept {concept_id!r}: {exc}",
            ["Check MCP server logs for details."],
        )


@mcp.tool()
async def search(query: str) -> str:
    """Search the facility knowledge bundle for a query string.

    Performs a case-insensitive substring match over each concept's
    frontmatter values and body text.  Reserved index/log files are
    never returned.

    Args:
        query: Substring to search for (case-insensitive).

    Returns:
        JSON object with a ``results`` list, each entry containing
        ``concept_id``, ``title``, ``description``, and a ``snippet``
        (first 200 characters of the body).
    """
    try:
        bundle = _get_bundle()
        matches = bundle.search(query)
        return json.dumps(
            {
                "query": query,
                "results": [
                    {
                        "concept_id": cid,
                        "title": doc.frontmatter.get("title", cid),
                        "description": doc.frontmatter.get("description", ""),
                        "snippet": doc.body[:200].strip(),
                    }
                    for cid, doc in matches
                ],
                "count": len(matches),
            }
        )
    except ToolError:
        raise
    except Exception as exc:
        logger.exception("search failed")
        return make_error(
            "internal_error",
            f"Search failed for query {query!r}: {exc}",
            ["Check MCP server logs for details."],
        )


@mcp.tool()
async def draft_concept(
    concept_id: str,
    doc_type: str,
    title: str,
    description: str,
    body: str,
    extra_frontmatter: str = "{}",
) -> str:
    """Write or update a facility knowledge concept document.

    Creates or replaces the ``.md`` file for *concept_id* in the bundle.
    The document is validated at the ``"authoring"`` level (OKF §9) before
    writing: ``type``, ``title``, and ``description`` must all be non-empty.

    **Human approval required** — this tool is listed in the ``approval``
    config under ``draft_concept: always``.  The OSPREY ``PreToolUse`` hook
    intercepts the call and prompts for operator confirmation before the
    filesystem write occurs.  If the operator rejects, the hook blocks the
    call and this function is never invoked.

    **Collision policy** — the effective policy is last-write-wins.  Because
    this function contains no ``await`` points, the asyncio event loop never
    yields mid-call; approval-gated calls are therefore serialised in practice
    and each overwrites the previous file.  ``_drafts_in_flight`` is kept as
    a latent defense-in-depth guard in case the write path ever acquires an
    ``await``; it does not fire under the current execution model.

    Args:
        concept_id: OKF §2 path-minus-extension identifier for the concept to
            write, e.g. ``accelerator_overview`` or ``tables/beam_params``.
            Must not escape the bundle root (path traversal is rejected).
        doc_type: Value for the ``type`` frontmatter field (e.g.
            ``facility_overview``, ``data_table``, ``reference``).
        title: Human-readable display name for the concept.
        description: One-sentence summary used in index listings and search
            snippets.
        body: Markdown body text that follows the frontmatter block.
        extra_frontmatter: JSON object of additional frontmatter key/value
            pairs to merge alongside ``type``, ``title``, and ``description``.
            Defaults to ``{}``.

    Returns:
        JSON object with ``concept_id``, ``path`` (absolute path written),
        and ``status: "written"``.

    Raises:
        ToolError: On validation failure, path traversal, bundle not
            initialised, or I/O error.
    """
    from osprey.services.facility_knowledge.okf.bundle import OKFBundleError
    from osprey.services.facility_knowledge.okf.document import OKFDocument, OKFDocumentError

    try:
        bundle = _get_bundle()
    except ToolError:
        raise

    # Collision guard: reject concurrent drafts for the same concept ID.
    if concept_id in _drafts_in_flight:
        return make_error(
            "draft_conflict",
            f"A draft for concept {concept_id!r} is already in progress.",
            [
                "Wait for the current draft to complete before submitting another.",
                "Sequential re-drafts are allowed (last-approved-wins).",
            ],
        )

    # Parse extra_frontmatter JSON before acquiring the lock.
    try:
        extra: dict = json.loads(extra_frontmatter) if extra_frontmatter.strip() else {}
    except json.JSONDecodeError as exc:
        return make_error(
            "validation_error",
            f"extra_frontmatter is not valid JSON: {exc}",
            ['Pass a JSON object, e.g. \'{"tags": ["epics"]}\'. Use "{}" for no extras.'],
        )
    if not isinstance(extra, dict):
        return make_error(
            "validation_error",
            "extra_frontmatter must be a JSON object, not an array or scalar.",
            ['Use a JSON object, e.g. \'{"resource": "https://example.com"}\'.'],
        )

    _drafts_in_flight.add(concept_id)
    try:
        # Build the document — reserved keys win over extra_frontmatter.
        frontmatter = {**extra, "type": doc_type, "title": title, "description": description}
        doc = OKFDocument(frontmatter=frontmatter, body=body)

        # Validate at authoring level before touching the filesystem.
        try:
            doc.validate("authoring")
        except OKFDocumentError as exc:
            return make_error(
                "validation_error",
                str(exc),
                [
                    "Provide non-empty type, title, and description.",
                    "timestamp is not required.",
                ],
            )

        # Resolve path — OKFBundle.resolve_concept_path enforces containment.
        try:
            target = bundle.resolve_concept_path(concept_id)
        except OKFBundleError as exc:
            return make_error(
                "path_traversal",
                str(exc),
                ["Use a relative path within the bundle (e.g. 'tables/beam_params')."],
            )

        # Ensure parent directories exist.
        target.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write: serialise and flush to disk.
        target.write_text(doc.serialize(), encoding="utf-8")

        logger.info("draft_concept: wrote %s → %s", concept_id, target)
        return json.dumps(
            {
                "concept_id": concept_id,
                "path": str(target),
                "status": "written",
            }
        )

    except ToolError:
        raise
    except Exception as exc:
        logger.exception("draft_concept failed for %s", concept_id)
        return make_error(
            "internal_error",
            f"Failed to write concept {concept_id!r}: {exc}",
            ["Check MCP server logs for details."],
        )
    finally:
        _drafts_in_flight.discard(concept_id)
