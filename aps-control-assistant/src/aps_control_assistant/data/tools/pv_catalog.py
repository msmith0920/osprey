"""
Utility for loading PV aliases from the PVs.mon SDDS file.
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import struct
from dataclasses import dataclass
from threading import RLock
from typing import Dict, Iterable, List, Optional, Tuple


QUERY_STOPWORDS = {
    "list",
    "lists",
    "pv",
    "pvs",
    "name",
    "names",
    "of",
    "the",
    "for",
    "and",
    "or",
    "what",
    "show",
    "find",
    "get",
    "tell",
    "me",
    "please",
    "value",
    "values",
    "history",
    "plot",
    "monitor",
    "data",
    "info",
    "information",
    "about",
    "is",
    "are",
    "to",
    "in",
    "on",
    "at",
    "by",
    "be",
    "do",
    "go",
    "we",
    "us",
    "it",
    "its",
    "sr",
}

TIME_KEYWORDS = {
    "last",
    "past",
    "recent",
    "previous",
    "month",
    "months",
    "week",
    "weeks",
    "day",
    "days",
    "hour",
    "hours",
    "minute",
    "minutes",
    "today",
    "yesterday",
    "tomorrow",
    "tonight",
    "ago",
}

@dataclass(frozen=True)
class PVEntry:
    """Represents a Process Variable and its aliases."""

    pv_name: str
    label: str
    aliases: List[str]


class PVCatalog:
    """
    Parses the PVs.mon SDDS file and exposes alias lookups.
    """

    def __init__(self, filepath: Optional[str] = None):
        self.filepath = filepath or self.default_path()
        self.entries: List[PVEntry] = []
        self.alias_map: Dict[str, PVEntry] = {}
        self._load()

    @staticmethod
    def default_path() -> str:
        utils_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(utils_dir)
        return os.path.join(project_root, "PVs.mon")

    def _load(self) -> None:
        if not os.path.exists(self.filepath):
            return

        ascii_mode = False
        try:
            with open(self.filepath, "rb") as sniff:
                header = sniff.read(4096)
                ascii_mode = b"mode=ascii" in header.lower()
        except OSError:
            return

        if ascii_mode:
            self._load_ascii()
            return

        parameter_types: List[str] = []
        column_defs: List[Tuple[str, str]] = []
        try:
            with open(self.filepath, "rb") as f:
                # Skip header lines, tracking parameter definitions
                while True:
                    line = f.readline()
                    if not line:
                        return

                    stripped = line.strip()
                    if not stripped:
                        continue

                    lower_line = stripped.lower()
                    if lower_line.startswith(b"&parameter"):
                        decoded = stripped.decode("utf-8", errors="ignore")
                        param_type = self._extract_parameter_type(decoded)
                        if param_type:
                            parameter_types.append(param_type)

                    elif lower_line.startswith(b"&column"):
                        decoded = stripped.decode("utf-8", errors="ignore")
                        column_def = self._extract_column_definition(decoded)
                        if column_def:
                            column_defs.append(column_def)

                    if lower_line.startswith(b"&data"):
                        break

                # After header, binary section begins
                row_count = self._read_int(f)
                if parameter_types:
                    self._skip_parameter_data(f, parameter_types)

                if not column_defs:
                    logging.warning("No column definitions found in PV catalog %s.", self.filepath)
                    return

                for index in range(row_count):
                    pv_name = None
                    description = None
                    try:
                        for col_name, col_type in column_defs:
                            value = self._read_column_value(f, col_type)
                            if value is None:
                                continue
                            if col_name == "controlname":
                                pv_name = value
                            elif col_name == "description":
                                description = value
                    except EOFError as exc:
                        logging.warning(
                            "PV catalog %s ended unexpectedly after %d/%d rows: %s",
                            self.filepath,
                            index,
                            row_count,
                            exc,
                        )
                        break

                    if not pv_name:
                        continue
                    entry = self._build_entry(pv_name, description or "")
                    self.entries.append(entry)
                    for alias in entry.aliases:
                        self.alias_map.setdefault(alias, entry)
        except (OSError, EOFError) as exc:
            logging.warning("Failed to load PV catalog %s: %s", self.filepath, exc)

    def _load_ascii(self) -> None:
        try:
            with open(self.filepath, "r", encoding="utf-8", errors="ignore") as fh:
                data_section = False
                column_names: List[str] = []
                control_idx: Optional[int] = None
                description_idx: Optional[int] = None
                for raw_line in fh:
                    line = raw_line.strip()
                    if not line:
                        continue
                    lower_line = line.lower()
                    if not data_section:
                        if lower_line.startswith("&column"):
                            column_def = self._extract_column_definition(line)
                            if column_def:
                                column_names.append(column_def[0])
                        if lower_line.startswith("&data"):
                            data_section = True
                            control_idx = self._column_index(column_names, "controlname")
                            description_idx = self._column_index(column_names, "description")
                        continue

                    if line.startswith(("!", "#", "/")):
                        continue
                    try:
                        parts = shlex.split(line)
                    except ValueError:
                        continue
                    if control_idx is None or description_idx is None:
                        continue
                    max_index = max(control_idx, description_idx)
                    if max_index >= len(parts):
                        continue
                    pv_name = parts[control_idx]
                    description = parts[description_idx] if description_idx < len(parts) else ""
                    entry = self._build_entry(pv_name, description)
                    self.entries.append(entry)
                    for alias in entry.aliases:
                        self.alias_map.setdefault(alias, entry)
        except OSError:
            return

    def _read_int(self, fh) -> int:
        data = fh.read(4)
        if len(data) != 4:
            raise EOFError("Unexpected end of PV catalog.")
        return struct.unpack(">I", data)[0]

    def _read_string(self, fh) -> str:
        length = self._read_int(fh)
        if length == 0:
            return ""
        data = fh.read(length)
        if len(data) != length:
            raise EOFError("Unexpected end of PV catalog string.")
        return data.decode("utf-8", errors="ignore")

    @staticmethod
    def _extract_parameter_type(definition: str) -> Optional[str]:
        match = re.search(r"type\s*=\s*([a-zA-Z]+)", definition)
        if match:
            return match.group(1).lower()
        return None

    @staticmethod
    def _extract_column_definition(definition: str) -> Optional[Tuple[str, str]]:
        name_match = re.search(r"name\s*=\s*([^,]+)", definition, re.IGNORECASE)
        type_match = re.search(r"type\s*=\s*([^,]+)", definition, re.IGNORECASE)
        if not name_match or not type_match:
            return None
        name = name_match.group(1).strip().lower()
        col_type = type_match.group(1).strip().lower()
        return name, col_type

    @staticmethod
    def _column_index(column_names: List[str], target: str) -> Optional[int]:
        target = target.lower()
        for idx, name in enumerate(column_names):
            if name == target:
                return idx
        return None

    def _skip_parameter_data(self, fh, parameter_types: List[str]) -> None:
        for param_type in parameter_types:
            if param_type == "string":
                length = self._read_int(fh)
                if length > 0:
                    self._consume_bytes(fh, length)
            elif param_type == "character":
                self._consume_bytes(fh, 1)
            elif param_type in {"short", "ushort"}:
                self._consume_bytes(fh, 2)
            elif param_type in {"long", "ulong", "int"}:
                self._consume_bytes(fh, 4)
            elif param_type in {"float"}:
                self._consume_bytes(fh, 4)
            elif param_type in {"double"}:
                self._consume_bytes(fh, 8)
            else:
                logging.warning("Unknown parameter type '%s' in PV catalog.", param_type)

    @staticmethod
    def _consume_bytes(fh, count: int) -> None:
        if count <= 0:
            return
        data = fh.read(count)
        if len(data) != count:
            raise EOFError("Unexpected end of PV catalog parameter data.")

    def _read_column_value(self, fh, column_type: str) -> Optional[str]:
        column_type = column_type.lower()
        if column_type == "string":
            return self._read_string(fh)
        if column_type == "character":
            data = fh.read(1)
            if len(data) != 1:
                raise EOFError("Unexpected end of PV catalog column data.")
            return data.decode("utf-8", errors="ignore")
        if column_type in {"short", "ushort"}:
            self._consume_bytes(fh, 2)
            return None
        if column_type in {"long", "ulong", "int"}:
            self._consume_bytes(fh, 4)
            return None
        if column_type == "float":
            self._consume_bytes(fh, 4)
            return None
        if column_type == "double":
            self._consume_bytes(fh, 8)
            return None
        logging.warning("Unknown column type '%s' in PV catalog.", column_type)
        return None

    def _build_entry(self, pv_name: str, description: str) -> PVEntry:
        alias_parts = re.split(r"[;,]", description)
        aliases = [pv_name.lower()]
        friendly_aliases: List[str] = []

        for part in alias_parts:
            raw = part.strip().lower()
            if not raw:
                continue

            cleaned = re.sub(r"^[^a-z0-9]+", "", raw).strip()
            if not cleaned:
                continue

            normalized = re.sub(r"^[0-9]+\s*", "", cleaned).strip()
            if not normalized:
                normalized = cleaned

            aliases.append(normalized)
            friendly_aliases.append(normalized)

            if normalized != cleaned:
                aliases.append(cleaned)
            if cleaned != raw:
                aliases.append(raw)

        label = friendly_aliases[0] if friendly_aliases else pv_name

        lower_pv = pv_name.lower()
        if lower_pv == "s-dcct:currentm":
            aliases.extend([
                "beam current",
                "storage ring current",
                "sr current",
                "sr beam current",
                "aps storage ring current",
                "beam curren",
            ])
        elif lower_pv == "bts:besocm:a:data:beam:qm":
            aliases.extend([
                "bts charge",
                "injector charge",
            ])

        # Add extra context-aware aliases for common PVs
        lower_pv = pv_name.lower()
        if lower_pv == "s-dcct:currentm":
            aliases.extend([
                "beam current",
                "storage ring current",
                "sr current",
                "sr beam current",
            ])
        elif lower_pv == "bts:besocm:a:data:beam:qm":
            aliases.extend([
                "bts charge",
                "injector charge",
            ])

        # Provide variants without punctuation
        additional: Iterable[str] = []
        for alias in list(aliases):
            stripped = alias.replace("-", " ").strip()
            if stripped and stripped not in aliases:
                aliases.append(stripped)
            colon_split = alias.replace(":", " ").strip()
            if colon_split and colon_split not in aliases:
                aliases.append(colon_split)
        aliases = list(dict.fromkeys(aliases))  # deduplicate preserving order

        return PVEntry(pv_name=pv_name, label=label, aliases=aliases)

    @staticmethod
    def _extend_query_tokens(tokens: List[str]) -> List[str]:
        if not tokens:
            return []
        extended: List[str] = []
        index = 0
        length = len(tokens)
        while index < length:
            current = tokens[index]
            next_token = tokens[index + 1] if index + 1 < length else ""
            if (
                current
                and next_token
                and current[-1].isdigit()
                and next_token[0].isalpha()
                and any(ch.isdigit() for ch in next_token)
            ):
                extended.append(current + next_token)
                index += 2
            else:
                extended.append(current)
                index += 1
        return extended

    @classmethod
    def _build_alias_tokens(cls, alias_lower: str) -> Set[str]:
        tokens = set(re.findall(r"[a-z0-9:_-]+", alias_lower))
        for part in alias_lower.split(":"):
            part = part.strip()
            if part:
                tokens.add(part)
        enriched = set(tokens)
        for token in list(tokens):
            normalized = cls._normalize_token(token)
            if not normalized:
                continue
            enriched.add(normalized)
            enriched.update(cls._split_transition_fragments(normalized))
        return enriched

    @staticmethod
    def _split_transition_fragments(token: str) -> Set[str]:
        fragments: Set[str] = set()
        for pattern in (r"(?<=\d)(?=[a-z])", r"(?<=[a-z])(?=\d)"):
            for fragment in re.split(pattern, token):
                if fragment:
                    fragments.add(fragment)
        return fragments

    @staticmethod
    def _normalize_token(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", value)

    @classmethod
    def _collect_matching_tokens(cls, tokens: List[str], alias_tokens: Set[str]) -> Set[str]:
        matched: Set[str] = set()
        for token in tokens:
            candidates = {token}
            normalized = cls._normalize_token(token)
            if normalized:
                candidates.add(normalized)
            if any(candidate in alias_tokens for candidate in candidates if candidate):
                matched.add(token)
        return matched

    @staticmethod
    def _filter_entries_by_context(entries: List[PVEntry], query_lower: str) -> List[PVEntry]:
        negative_keywords = ("setpoint", "set point", "command", "cmd", "trim")
        if any(keyword in query_lower for keyword in negative_keywords):
            return entries

        filtered = [
            entry
            for entry in entries
            if not any(
                keyword in entry.label.lower() or keyword in entry.pv_name.lower()
                for keyword in negative_keywords
            )
        ]
        return filtered

    def match_query(self, text: str) -> Optional[PVEntry]:
        """
        Match a query string against known aliases. Returns the best match.
        """
        lowered = text.lower()
        best_entry = None
        best_alias_length = 0
        for alias, entry in self.alias_map.items():
            if alias and alias in lowered:
                if len(alias) > best_alias_length:
                    best_alias_length = len(alias)
                    best_entry = entry
        return best_entry

    def match_all(self, text: str) -> List[PVEntry]:
        """
        Return all catalog entries whose aliases appear in the provided text.
        """
        lowered = text.lower()
        tokens = [
            token
            for token in re.findall(r"[a-z0-9:_-]+", lowered)
            if token and len(token) >= 2 and token not in QUERY_STOPWORDS
        ]
        filtered_tokens = [token for token in tokens if token not in TIME_KEYWORDS]
        effective_tokens = self._extend_query_tokens(filtered_tokens)
        required_token_set = set(effective_tokens)

        direct_matches: Dict[str, PVEntry] = {}
        token_matches: Dict[str, PVEntry] = {}
        token_hits: Dict[str, Set[str]] = {}
        for alias, entry in self.alias_map.items():
            alias_lower = alias.lower()
            if alias_lower and alias_lower in lowered:
                direct_matches.setdefault(entry.pv_name, entry)
                continue

            if not effective_tokens:
                continue

            alias_tokens = self._build_alias_tokens(alias_lower)
            matched_tokens = self._collect_matching_tokens(effective_tokens, alias_tokens)
            if not matched_tokens:
                continue

            hits = token_hits.setdefault(entry.pv_name, set())
            hits.update(matched_tokens)
            if hits.issuperset(required_token_set):
                token_matches.setdefault(entry.pv_name, entry)

        if direct_matches:
            return list(direct_matches.values())

        if token_matches:
            filtered = self._filter_entries_by_context(list(token_matches.values()), lowered)
            if filtered:
                return filtered
            return list(token_matches.values())

        return []

    def get_default_entry(self) -> Optional[PVEntry]:
        """
        Returns the first entry in the catalog as a reasonable default.
        """
        return self.entries[0] if self.entries else None

    def get_entry_by_pv(self, pv_name: str) -> Optional[PVEntry]:
        pv_lower = pv_name.lower()
        for entry in self.entries:
            if entry.pv_name.lower() == pv_lower:
                return entry
        return None


_CATALOG_CACHE: Dict[str, Tuple[Optional[float], PVCatalog]] = {}
_CATALOG_LOCK = RLock()


def get_pv_catalog(filepath: Optional[str] = None, force_reload: bool = False) -> PVCatalog:
    """
    Returns a cached PVCatalog instance, refreshing when the underlying file changes.
    """
    path = filepath or PVCatalog.default_path()
    path = os.path.abspath(path)
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        mtime = None

    with _CATALOG_LOCK:
        cached = _CATALOG_CACHE.get(path)
        if force_reload or cached is None or cached[0] != mtime:
            catalog = PVCatalog(filepath=path)
            _CATALOG_CACHE[path] = (mtime, catalog)
            return catalog
        return cached[1]


def clear_pv_catalog_cache(filepath: Optional[str] = None) -> None:
    """
    Clears the cached catalog (optionally for a specific file).
    """
    with _CATALOG_LOCK:
        if filepath is not None:
            path = filepath
            if not os.path.isabs(path):
                path = os.path.abspath(path)
            _CATALOG_CACHE.pop(path, None)
        else:
            _CATALOG_CACHE.clear()
