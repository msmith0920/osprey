import pandas as pd
from handlers.base_handler import BaseHandler
from handlers.pv_monitor_handler import PVMonitorHandler
from epics_utils import get_pv_value
from utils.get_log_data import find_log_files, load_log_dataframe
from datetime import datetime, timedelta
from utils.time_parsing_agent import TimeParsingAgent, TimeParsingError
from utils.llm_time_parser import LLMTimeParser
from utils.llm_pv_intent import LLMIntentParser
from utils.pv_catalog import get_pv_catalog, PVEntry
from utils.sdds_plotter import SDDSReadError
from utils.timezone import get_aps_timezone
from utils.archiver_client import (
    fetch_archiver_history,
    ArchiverUnavailableError,
)
from utils.orbit_display import (
    CURRENT_ORBIT_COMMAND,
    command_as_string,
    is_current_orbit_request,
    launch_current_orbit_display,
)
from typing import Optional, Tuple, List, Dict, Any
import re


class PVDataHandler(BaseHandler):
    DEFAULT_HISTORY_HOURS = 6
    BEAM_CURRENT_ALIASES = (
        "beam current",
        "storage ring current",
        "sr current",
        "sr beam current",
    )
    HISTORY_SOURCE_DATA_LOGGER = "data_logger"
    HISTORY_SOURCE_ARCHIVER = "archiver"
    DEFAULT_HISTORY_SOURCE = HISTORY_SOURCE_DATA_LOGGER
    HISTORY_SOURCE_LABELS = {
        HISTORY_SOURCE_DATA_LOGGER: "data logger",
        HISTORY_SOURCE_ARCHIVER: "APS archiver",
    }
    LOCAL_TIMEZONE = get_aps_timezone()

    def __init__(self, system_name, system_prompt, base_url, chat_endpoint, model, user, debug=False):
        super().__init__(system_name, system_prompt, base_url, chat_endpoint, model, user)
        self.debug = debug
        self.tools = {
            "get_pv_value": self.get_pv_value_tool,
            "get_pv_history": self.get_pv_history_tool,
            "display_current_orbit": self.display_current_orbit_tool,
        }
        self.time_parser = TimeParsingAgent()
        self.llm_time_parser = LLMTimeParser(chat_endpoint, model, user)
        self.intent_parser = LLMIntentParser(chat_endpoint, model, user)
        self.monitor_handler = PVMonitorHandler(
            system_name="PV Monitor",
            system_prompt=system_prompt,
            base_url=base_url,
            chat_endpoint=chat_endpoint,
            model=model,
            user=user,
            debug=debug,
        )
        self.pv_catalog = get_pv_catalog()

    def process_query(self, user_input: str, progress_callback=None, tool_activity_callback=None):
        # Reload catalog if PVs.mon changed
        self.pv_catalog = get_pv_catalog()
        user_input_lower = user_input.lower()
        history_source = self._detect_history_source(user_input_lower)
        tool_activity_log: List[Dict[str, Any]] = []
        sources_log: List[Dict[str, Any]] = []

        def log_tool_call(tool_name: str, parameters: Dict[str, Any]) -> None:
            entry = {"tool_name": tool_name, "parameters": parameters}
            tool_activity_log.append(entry)
            if tool_activity_callback:
                tool_activity_callback(entry)

        def log_tool_result(
            tool_name: str,
            parameters: Dict[str, Any],
            result_summary: Dict[str, Any],
            record_source: bool = True,
        ) -> None:
            entry = {
                "tool_name": tool_name,
                "parameters": parameters,
                "result": result_summary,
            }
            tool_activity_log.append(entry)
            if tool_activity_callback:
                tool_activity_callback(entry)
            if record_source:
                sources_log.append({
                    "tool_name": tool_name,
                    "parameters": parameters,
                    "result": result_summary,
                })

        def finalize(payload: Dict[str, Any]) -> Dict[str, Any]:
            existing_sources = list(payload.get("sources", []))
            existing_sources.extend(sources_log)
            payload["sources"] = existing_sources

            existing_activity = list(payload.get("tool_activity", []))
            existing_activity.extend(tool_activity_log)
            payload["tool_activity"] = existing_activity

            return payload

        def summarize_value_response(info: Dict[str, Any]) -> Dict[str, Any]:
            summary = {
                "message": info.get("message"),
                "accessible": info.get("accessible"),
                "pv_name": info.get("pv_name"),
            }
            if "value" in info:
                value = info.get("value")
                if hasattr(value, "item"):
                    try:
                        value = value.item()
                    except Exception:
                        value = str(value)
                summary["value"] = value
            if info.get("error_message"):
                summary["error_message"] = info["error_message"]
            if info.get("label"):
                summary["label"] = info.get("label")
            return summary

        intent_info = self._analyze_intent(
            user_input,
            log_tool_call,
            log_tool_result,
        )
        intent_label = ""
        if intent_info:
            intent_label = str(intent_info.get("intent", "")).lower()

        if intent_label == "orbit" or is_current_orbit_request(user_input_lower):
            command_label = command_as_string(CURRENT_ORBIT_COMMAND)
            log_tool_call("display_current_orbit", {"command": command_label})
            result = self.display_current_orbit_tool()
            summary = {
                "success": result.get("success"),
                "command": result.get("command", command_label),
            }
            if result.get("pid") is not None:
                summary["pid"] = result["pid"]
            if result.get("error"):
                summary["error"] = result["error"]
            log_tool_result("display_current_orbit", {"command": command_label}, summary)
            message = result.get("message", "Unable to launch the current orbit display.")
            details: List[str] = []
            command_string = result.get("command", command_label)
            if command_string:
                details.append(f"Command: {command_string}")
            if result.get("pid") is not None:
                details.append(f"PID: {result['pid']}")
            if details:
                message = "\n".join([message, *details])
            payload = {
                'success': result.get("success", False),
                'response': message,
                'system': self.system_name,
                'tools_used': ['display_current_orbit'],
                'error_message': result.get("error") if not result.get("success") else None,
                'command': command_string,
                'stdout': message,
            }
            if result.get("pid") is not None:
                payload['pid'] = result["pid"]
            return finalize(payload)

        list_requested = False
        should_history = False

        if intent_info:
            if intent_label == "list":
                list_requested = True
            elif intent_label == "history":
                should_history = True
            if intent_info.get("requires_time_range") or intent_info.get("mentions_time_range"):
                should_history = True
        else:
            if self._is_pv_name_listing_request(user_input_lower):
                list_requested = True
            if self._has_explicit_range(user_input_lower) or self._is_history_request(user_input_lower):
                should_history = True

        is_pv_name_query = list_requested

        pv_entries = self._resolve_pv_entries(user_input)
        if not pv_entries:
            prefix_matches = self._resolve_prefix_entries(user_input)
            if prefix_matches:
                pv_entries = prefix_matches
        if intent_label == "monitor":
            prefix_matches = self._resolve_prefix_entries(user_input)
            if prefix_matches:
                existing = {entry.pv_name for entry in pv_entries or []}
                combined: List[PVEntry] = list(pv_entries or [])
                for entry in prefix_matches:
                    if entry.pv_name not in existing:
                        combined.append(entry)
                        existing.add(entry.pv_name)
                pv_entries = combined
        if not pv_entries:
            return finalize({
                'success': False,
                'response': "Unable to determine which PV you want. Please mention the PV name or one of its descriptions from PVs.mon.",
                'system': self.system_name,
                'tools_used': [],
                'error_message': "PV not recognized"
            })

        if intent_label == "monitor":
            monitor_result = self._delegate_to_monitor(user_input, pv_entries, tool_activity_callback)
            return finalize(monitor_result)

        # If user is asking for PV names, return the list without getting values/history
        if is_pv_name_query:
            summary = {
                "count": len(pv_entries),
                "pv_names": [entry.pv_name for entry in pv_entries[: min(10, len(pv_entries))]],
            }
            if pv_entries:
                summary["labels"] = [entry.label for entry in pv_entries[: min(10, len(pv_entries))]]
            log_tool_result(
                "pv_catalog_lookup",
                {"query": user_input},
                summary,
            )
            return finalize(self._list_pv_names(pv_entries))

        reference_time = datetime.now()
        want_history = should_history

        parsed_time = None
        if want_history:
            parsed_time = self._parse_time_range(
                user_input,
                reference_time,
                tool_activity_callback=tool_activity_callback,
                use_llm=True,
                log_tool_call=log_tool_call,
                log_tool_result=log_tool_result,
            )
            if not parsed_time:
                parsed_time = self._build_default_history_range(reference_time)

        if parsed_time:
            start_time = parsed_time['start_datetime']
            end_time = parsed_time['end_datetime']
            duration_label = parsed_time.get('duration_label') or self._format_duration(parsed_time.get('quantity', 0), parsed_time.get('unit', 'seconds'))
            time_reference = self._build_time_reference(parsed_time, duration_label)
            sources_log.append({
                "tool_name": "time_range_resolution",
                "parameters": {
                    "query": user_input,
                },
                "result": {
                    "start": parsed_time.get('start'),
                    "end": parsed_time.get('end'),
                    "source": parsed_time.get('source'),
                    "duration_label": duration_label,
                },
            })
            sources_log.append({
                "tool_name": "history_source_selection",
                "parameters": {
                    "query": user_input,
                },
                "result": {
                    "history_source": history_source,
                },
            })

            if len(pv_entries) == 1:
                entry = pv_entries[0]

                result = self._call_history_tool(
                    entry.pv_name,
                    start_time,
                    end_time,
                    "",
                    entry.label,
                    history_source=history_source,
                    log_tool_call=log_tool_call,
                    log_tool_result=log_tool_result,
                )
                if not result['success']:
                    return finalize(result)

                source_label = self._describe_history_source(history_source)
                result['response'] = (
                    f"{entry.label} history from {parsed_time['start']} to {parsed_time['end']} "
                    f"based on {time_reference} using the {source_label}. {result['response']}"
                )
                result['duration_label'] = duration_label
                result['display_label'] = entry.label
                result['history_source'] = history_source
                return finalize(result)

            histories = []
            responses = []
            missing_messages: List[str] = []
            for entry in pv_entries:
                result = self._call_history_tool(
                    entry.pv_name,
                    start_time,
                    end_time,
                    "",
                    entry.label,
                    generate_plot=False,
                    history_source=history_source,
                    log_tool_call=log_tool_call,
                    log_tool_result=log_tool_result,
                )
                if not result['success']:
                    error_text = result.get('error_message') or result.get('response') or ""
                    normalized = error_text.lower()
                    if "no data found" in normalized:
                        message = error_text or f"No data found for {entry.label} ({entry.pv_name})."
                        missing_messages.append(message)
                        continue
                    return finalize(result)

                dataframe = result.get('dataframe')
                if dataframe is None or dataframe.empty:
                    message = f"No data found for {entry.label} ({entry.pv_name})."
                    missing_messages.append(message)
                    continue

                histories.append((dataframe, entry.label, entry.pv_name))
                responses.append(result['response'])

            if not histories:
                combined_message = (
                    "No data available for the requested PVs."
                    if not missing_messages
                    else " ".join(missing_messages)
                )
                return finalize({
                    'success': False,
                    'response': combined_message,
                    'system': self.system_name,
                    'tools_used': ['get_pv_history'],
                    'error_message': combined_message,
                    'missing_messages': missing_messages,
                    'history_source': history_source,
                })

            try:
                plot_data = self._build_plot_payload(histories, "PV History")
            except SDDSReadError as exc:
                return finalize({
                    'success': False,
                    'response': f"Unable to render combined plot: {exc}",
                    'system': self.system_name,
                    'tools_used': ['get_pv_history'],
                    'error_message': str(exc)
                })

            labels = ", ".join(entry.label for entry in pv_entries)
            source_label = self._describe_history_source(history_source)
            return finalize({
                'success': True,
                'response': (
                    f"{labels} history from {parsed_time['start']} to {parsed_time['end']} "
                    f"based on {time_reference} using the {source_label}.\n"
                    + "\n".join(responses)
                    + ("\n" + "\n".join(missing_messages) if missing_messages else "")
                ),
                'system': self.system_name,
                'tools_used': ['get_pv_history'],
                'error_message': None,
                'plot_data': plot_data,
                'display_label': labels,
                'duration_label': duration_label,
                'missing_messages': missing_messages,
                'history_source': history_source,
            })

        if want_history:
            return finalize({
                'success': False,
                'response': "I couldn't determine the requested time range. Please provide a clear date range or duration (e.g., 'from 2024-07-01 to 2024-07-05').",
                'system': self.system_name,
                'tools_used': [],
                'error_message': "Missing or invalid parameters for historical data query."
            })

        if len(pv_entries) == 1:
            entry = pv_entries[0]
            params = {
                "pv_name": entry.pv_name,
                "label": entry.label,
            }
            log_tool_call("get_pv_value", params)
            value_info = self.get_pv_value_tool(entry.pv_name, entry.label)
            log_tool_result("get_pv_value", params, summarize_value_response(value_info))
            return finalize({
                'success': True,
                'response': value_info['message'],
                'system': self.system_name,
                'tools_used': ['get_pv_value'],
                'error_message': None,
                'display_label': entry.label,
            })

        values = []
        for entry in pv_entries:
            params = {
                "pv_name": entry.pv_name,
                "label": entry.label,
            }
            log_tool_call("get_pv_value", params)
            value_info = self.get_pv_value_tool(entry.pv_name, entry.label)
            log_tool_result("get_pv_value", params, summarize_value_response(value_info))
            values.append(value_info['message'])

        return finalize({
            'success': True,
            'response': "\n".join(values),
            'system': self.system_name,
            'tools_used': ['get_pv_value'],
            'error_message': None,
            'display_label': ", ".join(entry.label for entry in pv_entries),
        })

    def get_pv_value_tool(self, pv_name: str, display_label: Optional[str] = None) -> Dict[str, Any]:
        label = display_label or pv_name
        response: Dict[str, Any] = {
            'pv_name': pv_name,
            'label': label,
            'accessible': False,
            'value': None,
            'error_message': None,
        }
        try:
            result = get_pv_value(pv_name)
            accessible = result.get('accessible', False)
            response['accessible'] = accessible
            response['value'] = result.get('value')
            response['error_message'] = result.get('error_message')

            if accessible:
                response['message'] = f"The current value of {label} ({pv_name}) is: {result.get('value')}"
            else:
                response['message'] = (
                    f"Could not retrieve value for {label} ({pv_name}): {result.get('error_message')}"
                )
        except Exception as e:
            response['error_message'] = str(e)
            response['message'] = f"An error occurred while getting PV value for {pv_name}: {str(e)}"

        return response

    def get_pv_history_tool(
        self,
        pv_name: str,
        start_time_str: str,
        end_time_str: str,
        output_file: str,
        display_label: Optional[str] = None,
        history_source: Optional[str] = None,
    ):
        source = self._normalize_history_source(history_source)
        if source == self.HISTORY_SOURCE_ARCHIVER:
            return self._get_archiver_history(
                pv_name,
                start_time_str,
                end_time_str,
                display_label=display_label,
            )
        return self._get_data_logger_history(
            pv_name,
            start_time_str,
            end_time_str,
            output_file,
            display_label=display_label,
        )

    def _get_data_logger_history(
        self,
        pv_name: str,
        start_time_str: str,
        end_time_str: str,
        output_file: str,
        display_label: Optional[str] = None,
    ) -> Dict[str, Any]:
        label = display_label or pv_name
        response = self._history_response_template(
            pv_name,
            label,
            self.HISTORY_SOURCE_DATA_LOGGER,
            output_file=output_file or None,
        )

        try:
            start_time, end_time = self._parse_history_window(start_time_str, end_time_str)
        except ValueError as exc:
            response['message'] = str(exc)
            response['error_message'] = response['message']
            return response

        try:
            listing = find_log_files(pv_name, start_time, end_time)
        except Exception as exc:
            response['message'] = f"An error occurred while locating history for {pv_name}: {exc}"
            response['error_message'] = response['message']
            return response

        if not listing or not listing.files:
            response['message'] = f"No data found for {label} ({pv_name})."
            response['error_message'] = response['message']
            return response

        try:
            dataframe = load_log_dataframe(listing)
        except Exception as exc:
            response['message'] = f"Unable to load history for {label} ({pv_name}): {exc}"
            response['error_message'] = response['message']
            return response

        if dataframe.empty:
            response['message'] = f"No data found for {label} ({pv_name})."
            response['error_message'] = response['message']
            return response

        dataframe = dataframe.copy()
        time_series = dataframe["Time"]
        if pd.api.types.is_datetime64_any_dtype(time_series):
            dataframe["Time"] = pd.to_datetime(time_series, utc=False, errors="coerce").dt.tz_localize(None)
        else:
            dataframe["Time"] = self._convert_epoch_to_local(time_series)

        response['accessible'] = True
        response['dataframe'] = dataframe
        source_label = self._describe_history_source(self.HISTORY_SOURCE_DATA_LOGGER)
        response['message'] = f"Historical data retrieved for {label} ({pv_name}) via {source_label}."
        return response

    def _get_archiver_history(
        self,
        pv_name: str,
        start_time_str: str,
        end_time_str: str,
        display_label: Optional[str] = None,
    ) -> Dict[str, Any]:
        label = display_label or pv_name
        response = self._history_response_template(
            pv_name,
            label,
            self.HISTORY_SOURCE_ARCHIVER,
        )

        try:
            start_time, end_time = self._parse_history_window(start_time_str, end_time_str)
        except ValueError as exc:
            response['message'] = str(exc)
            response['error_message'] = response['message']
            return response

        try:
            dataframe = fetch_archiver_history(
                pv_name,
                start_time,
                end_time,
                tzinfo=self.LOCAL_TIMEZONE,
            )
        except ArchiverUnavailableError as exc:
            response['message'] = f"Archiver unavailable for {label} ({pv_name}): {exc}"
            response['error_message'] = response['message']
            return response
        except Exception as exc:
            response['message'] = f"Unable to load archiver data for {label} ({pv_name}): {exc}"
            response['error_message'] = response['message']
            return response

        if dataframe.empty:
            response['message'] = f"No archiver data found for {label} ({pv_name})."
            response['error_message'] = response['message']
            return response

        response['accessible'] = True
        response['dataframe'] = dataframe
        source_label = self._describe_history_source(self.HISTORY_SOURCE_ARCHIVER)
        response['message'] = f"Historical data retrieved for {label} ({pv_name}) via {source_label}."
        return response

    @staticmethod
    def _parse_history_window(start_time_str: str, end_time_str: str) -> Tuple[datetime, datetime]:
        try:
            start_time = datetime.strptime(start_time_str, '%Y-%m-%d %H:%M:%S')
            end_time = datetime.strptime(end_time_str, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            raise ValueError("Invalid time format. Please use 'YYYY-MM-DD HH:MM:SS'.")
        if end_time < start_time:
            start_time, end_time = end_time, start_time
        return start_time, end_time

    def _history_response_template(
        self,
        pv_name: str,
        label: str,
        history_source: str,
        *,
        output_file: Optional[str] = None,
    ) -> Dict[str, Any]:
        return {
            'message': '',
            'accessible': False,
            'output_file': output_file,
            'pv_name': pv_name,
            'error_message': None,
            'dataframe': None,
            'label': label,
            'history_source': history_source,
        }

    @classmethod
    def _describe_history_source(cls, history_source: str) -> str:
        return cls.HISTORY_SOURCE_LABELS.get(history_source, history_source.replace("_", " "))

    @classmethod
    def _normalize_history_source(cls, history_source: Optional[str]) -> str:
        if not history_source:
            return cls.DEFAULT_HISTORY_SOURCE
        lowered = history_source.lower()
        if lowered in {cls.HISTORY_SOURCE_ARCHIVER, cls.HISTORY_SOURCE_DATA_LOGGER}:
            return lowered
        return cls.DEFAULT_HISTORY_SOURCE

    @classmethod
    def _detect_history_source(cls, user_input_lower: str) -> str:
        if "pva." in user_input_lower or re.search(r"\barchiver\b", user_input_lower):
            return cls.HISTORY_SOURCE_ARCHIVER
        if re.search(r"\bdata[-\s]?logger\b", user_input_lower):
            return cls.HISTORY_SOURCE_DATA_LOGGER
        return cls.DEFAULT_HISTORY_SOURCE

    def get_tools_description(self):
        return "Available tools: get_pv_value, get_pv_history, display_current_orbit"

    @staticmethod
    def display_current_orbit_tool() -> Dict[str, Any]:
        """Launch ADT to display the current orbit."""
        return launch_current_orbit_display()

    def _delegate_to_monitor(
        self,
        user_input: str,
        pv_entries: List[PVEntry],
        tool_activity_callback,
    ) -> Dict[str, Any]:
        try:
            self.monitor_handler.pv_catalog = get_pv_catalog()
        except Exception:
            pass

        if hasattr(self.monitor_handler, "build_request_from_entries") and pv_entries:
            try:
                monitor_result = self.monitor_handler.build_request_from_entries(pv_entries)
            except Exception:
                monitor_result = self.monitor_handler.process_query(
                    user_input,
                    progress_callback=None,
                    tool_activity_callback=tool_activity_callback,
                )
        else:
            monitor_result = self.monitor_handler.process_query(
                user_input,
                progress_callback=None,
                tool_activity_callback=tool_activity_callback,
            )
        monitor_result.setdefault("system", self.system_name)
        if "monitor_request" not in monitor_result:
            monitor_result["monitor_request"] = {
                "action": "add",
                "pvs": [
                    {"pv_name": entry.pv_name, "label": entry.label}
                    for entry in pv_entries
                ],
            }
        return monitor_result

    def _analyze_intent(
        self,
        user_input: str,
        log_tool_call,
        log_tool_result,
    ) -> Optional[Dict[str, Any]]:
        cleaned = (user_input or "").strip()
        if not cleaned:
            return None

        parameters = {"query": cleaned}
        heuristic = self._heuristic_intent(cleaned.lower())
        if heuristic is not None:
            heuristic_result = dict(heuristic)
            log_tool_call("interpret_intent", parameters)
            log_tool_result("interpret_intent", parameters, heuristic_result)
            return heuristic_result

        log_tool_call("interpret_intent", parameters)
        try:
            result = self.intent_parser.analyze(cleaned)
        except Exception as exc:
            log_tool_result(
                "interpret_intent",
                parameters,
                {"intent": "unknown", "error": str(exc)},
                record_source=False,
            )
            return None

        summary = result or {"intent": "unknown"}
        log_tool_result("interpret_intent", parameters, summary)
        return result or summary

    def _heuristic_intent(self, lowered: str) -> Optional[Dict[str, Any]]:
        if not lowered:
            return None

        if is_current_orbit_request(lowered):
            return {
                "intent": "orbit",
                "mentions_time_range": False,
                "requires_time_range": False,
                "confidence": 1.0,
                "notes": "heuristic: orbit keywords",
            }

        if self._is_pv_name_listing_request(lowered):
            return {
                "intent": "list",
                "mentions_time_range": False,
                "requires_time_range": False,
                "confidence": 0.9,
                "notes": "heuristic: list keywords",
            }

        if self._has_explicit_range(lowered) or self._is_history_request(lowered):
            return {
                "intent": "history",
                "mentions_time_range": True,
                "requires_time_range": True,
                "confidence": 0.85,
                "notes": "heuristic: history keywords",
            }

        monitor_keywords = [
            "monitor",
            "watch",
            "track",
            "scope",
            "live",
            "real-time",
            "realtime",
            "plot",
            "graph",
        ]
        if any(keyword in lowered for keyword in monitor_keywords):
            if not self._contains_time_hint(lowered):
                multi_clues = (" and ", " & ", ",", ";", " plus ", " along with ", " vs ", " versus ")
                if not any(clue in lowered for clue in multi_clues):
                    return {
                        "intent": "monitor",
                        "mentions_time_range": False,
                        "requires_time_range": False,
                        "confidence": 0.75,
                        "notes": "heuristic: monitor keywords",
                    }

        value_keywords = ["current value", "current reading", "value", "now", "read"]
        if any(keyword in lowered for keyword in value_keywords):
            return {
                "intent": "value",
                "mentions_time_range": False,
                "requires_time_range": False,
                "confidence": 0.6,
                "notes": "heuristic: value keywords",
            }

        return None

    @staticmethod
    def _format_duration(quantity: float, unit: str) -> str:
        if quantity is None or unit is None:
            return "the selected time range"
        if float(quantity).is_integer():
            quantity_str = str(int(quantity))
        else:
            quantity_str = f"{quantity:.2f}".rstrip('0').rstrip('.')

        singular_unit = unit[:-1] if unit.endswith('s') else unit
        unit_str = singular_unit if quantity == 1 else unit

        return f"{quantity_str} {unit_str}"

    @staticmethod
    def _build_time_reference(parsed_time: dict, duration_label: str) -> str:
        matched_text = (parsed_time.get('matched_text') or '').strip()
        if matched_text:
            lowered = matched_text.lower()
            if lowered.startswith("last "):
                return f"the last {matched_text[5:]}"
            if lowered.startswith("past "):
                return f"the past {matched_text[5:]}"
            if lowered.startswith(("the last ", "the past ", "within ", "in ", "over ", "during ")):
                return matched_text
            return matched_text

        if duration_label:
            return duration_label

        quantity = parsed_time.get('quantity')
        unit = parsed_time.get('unit')
        if quantity is not None and unit:
            try:
                return PVDataHandler._format_duration(quantity, unit)
            except Exception:
                pass

        return "the selected time range"

    def _generate_plot(
        self,
        dataframe: Optional[pd.DataFrame],
        pv_name: Optional[str],
        start_time: datetime,
        end_time: datetime,
        display_label: Optional[str],
    ) -> dict:
        if dataframe is None or dataframe.empty:
            raise SDDSReadError("History data did not contain any samples.")

        if not pv_name:
            raise SDDSReadError("PV name missing for plot generation.")

        return self._build_plot_payload(
            [(dataframe, display_label or pv_name, pv_name)],
            f"{display_label or pv_name} History",
        )

    @staticmethod
    def _build_plot_payload(
        datasets: List[Tuple[object, str, Optional[str]]],
        title: str,
    ) -> dict:
        """
        Convert one or more dataframes into a serializable plot payload for Qt rendering.
        """
        series_payload = []
        earliest_start = None

        for axis_index, item in enumerate(datasets):
            if len(item) >= 3:
                dataframe, label, pv_name = item[0], item[1], item[2]
            else:
                dataframe, label = item[0], item[1]
                pv_name = None
            cleaned = dataframe.dropna(subset=["Time", "Value"])
            if cleaned.empty:
                continue

            times = [
                ts.to_pydatetime().replace(tzinfo=None).isoformat()
                for ts in cleaned["Time"]
            ]
            values = cleaned["Value"].astype(float).tolist()
            if not times or not values:
                continue

            display_label = label
            if pv_name:
                base_label = (label or "").lower()
                if pv_name.lower() not in base_label:
                    display_label = f"{label} ({pv_name})" if label else pv_name

            series_payload.append({
                "label": display_label,
                "times": times,
                "values": values,
                "y_axis": axis_index,
            })

            candidate_start = cleaned["Time"].iloc[0].to_pydatetime().replace(tzinfo=None)
            if earliest_start is None or candidate_start < earliest_start:
                earliest_start = candidate_start

        if not series_payload:
            raise SDDSReadError("History file did not contain any samples.")

        tz_name = datetime.now().astimezone().tzname() or "local"
        start_text = None
        if earliest_start is not None:
            start_text = (
                f"Time starting {earliest_start.strftime('%a %b %d %H:%M:%S')} "
                f"{tz_name} {earliest_start.year}"
            )

        return {
            "title": title,
            "series": series_payload,
            "start_text": start_text,
        }

    @staticmethod
    def _is_history_request(user_input_lower: str) -> bool:
        history_keywords = [
            "history",
            "historical",
            "trend",
            "record",
            "yesterday",
            "last night",
            "day before yesterday",
            "day before last",
            "day after tomorrow",
        ]
        if any(keyword in user_input_lower for keyword in history_keywords):
            return True

        return PVDataHandler._contains_time_hint(user_input_lower)

    @staticmethod
    def _contains_time_hint(user_input_lower: str) -> bool:
        if PVDataHandler._has_explicit_range(user_input_lower):
            return True

        if re.search(r"\b(last|past|previous)\s+(?:\d+(?:\.\d+)?\s*)?(seconds?|sec|s|minutes?|mins?|m|hours?|hrs?|h|days?|d|weeks?|w|months?|mo|years?|yr|y)\b", user_input_lower):
            return True

        if re.search(r"\b(last|previous|past)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)(?:'s)?\b", user_input_lower):
            return True

        if re.search(r"\b(since|from)\s+\d{4}", user_input_lower):
            return True

        if re.search(r"\b(since|from)\s+(?:last|past|previous)\b", user_input_lower):
            return True

        if re.search(r"\b(?:for|in|during)\s+the\s+last\s+\d+(?:\.\d+)?\s*(seconds?|sec|s|minutes?|mins?|m|hours?|hrs?|h|days?|d|weeks?|w|months?|mo|years?|yr|y)\b", user_input_lower):
            return True

        if re.search(r"\b\d+(?:\.\d+)?\s*(seconds?|sec|s|minutes?|mins?|m|hours?|hrs?|h|days?|d|weeks?|w|months?|mo|years?|yr|y)\s+ago\b", user_input_lower):
            return True

        if re.search(r"\b\d+(?:\.\d+)?\s*(h|hr|hrs|m|min|mins|s)\b", user_input_lower):
            return True

        time_markers = ["yesterday", "earlier", "recent", "ago", "weekend", "week", "month", "year"]
        if any(marker in user_input_lower for marker in time_markers):
            return True

        return False


    def _parse_time_range(
        self,
        user_input: str,
        reference_time: datetime,
        tool_activity_callback=None,
        use_llm: bool = True,
        log_tool_call=None,
        log_tool_result=None,
    ) -> Optional[dict]:
        parsed_time = None
        parameters = {
            'text': user_input,
            'reference_time': reference_time.isoformat(),
        }
        if log_tool_call:
            log_tool_call('TimeParsingAgent', parameters)
        try:
            parsed_time = self.time_parser.parse(user_input, reference_time=reference_time)
        except TimeParsingError:
            parsed_time = None

        if parsed_time:
            parsed_time['source'] = 'rule'
            summary = {
                'start': parsed_time.get('start'),
                'end': parsed_time.get('end'),
                'duration_label': parsed_time.get('duration_label'),
                'source': 'rule',
            }
            if log_tool_result:
                log_tool_result('TimeParsingAgent', parameters, summary, record_source=False)
            elif tool_activity_callback:
                tool_activity_callback({'tool_name': 'TimeParsingAgent', 'result': summary})
            return parsed_time

        if use_llm and self.llm_time_parser:
            llm_result = None
            llm_parameters = dict(parameters)
            try:
                if log_tool_call:
                    log_tool_call('ArgoTimeParser', llm_parameters)
                llm_result = self.llm_time_parser.parse(user_input, reference_time)
            except Exception:
                llm_result = None

            if llm_result:
                summary = {
                    'expression': llm_result.get('duration_label'),
                    'start': llm_result.get('start'),
                    'end': llm_result.get('end'),
                    'source': 'llm',
                }
                if log_tool_result:
                    log_tool_result('ArgoTimeParser', llm_parameters, summary, record_source=False)
                elif tool_activity_callback:
                    tool_activity_callback({'tool_name': 'ArgoTimeParser', 'result': summary})
                return llm_result

        return None

    def _call_history_tool(
        self,
        pv_name: str,
        start_time: datetime,
        end_time: datetime,
        output_file: str,
        display_label: str,
        generate_plot: bool = True,
        history_source: str = DEFAULT_HISTORY_SOURCE,
        log_tool_call=None,
        log_tool_result=None,
    ) -> dict:
        tool_start_time_str = start_time.strftime('%Y-%m-%d %H:%M:%S')
        tool_end_time_str = end_time.strftime('%Y-%m-%d %H:%M:%S')
        parameters = {
            'pv_name': pv_name,
            'start_time': tool_start_time_str,
            'end_time': tool_end_time_str,
            'history_source': history_source,
        }
        if output_file:
            parameters['output_file'] = output_file

        if log_tool_call:
            log_tool_call('get_pv_history', parameters)

        tool_response = self.get_pv_history_tool(
            pv_name,
            tool_start_time_str,
            tool_end_time_str,
            output_file,
            display_label=display_label,
            history_source=history_source,
        )

        summary = {
            'message': tool_response.get('message'),
            'accessible': tool_response.get('accessible'),
            'pv_name': pv_name,
            'label': display_label,
            'start_time': tool_start_time_str,
            'end_time': tool_end_time_str,
            'history_source': history_source,
        }
        dataframe = tool_response.get('dataframe')
        if dataframe is not None:
            try:
                summary['rows'] = int(len(dataframe))
            except Exception:
                summary['rows'] = None
        error_message = tool_response.get('error_message')
        if error_message:
            summary['error_message'] = error_message

        if log_tool_result:
            log_tool_result('get_pv_history', parameters, summary)

        result = {
            'success': tool_response.get('accessible', False),
            'response': tool_response.get('message', ''),
            'system': self.system_name,
            'tools_used': ['get_pv_history'],
            'error_message': tool_response.get('error_message'),
            'display_label': display_label,
            'dataframe': tool_response.get('dataframe'),
            'start_time': tool_start_time_str,
            'end_time': tool_end_time_str,
            'history_source': history_source,
        }

        if not result['success']:
            if not result['error_message']:
                result['error_message'] = tool_response.get('message')
            return result

        dataframe = tool_response.get('dataframe')

        if generate_plot:
            try:
                plot_data = self._generate_plot(
                    dataframe=dataframe,
                    pv_name=pv_name,
                    start_time=start_time,
                    end_time=end_time,
                    display_label=display_label,
                )
                result['plot_data'] = plot_data
            except SDDSReadError as exc:
                result['response'] += f" Unable to render plot: {exc}"
            except Exception as exc:
                result['response'] += f" Plot generation failed: {exc}"

        return result

    def _resolve_pv_entries(self, user_input: str) -> Optional[List[PVEntry]]:
        matches = self.pv_catalog.match_all(user_input)
        if matches:
            preferred = self._prefer_beam_current(matches, user_input)
            if preferred:
                return preferred
            return matches

        # Fallback: look for tokens (e.g., equipment mnemonics) that partially
        # match any catalog alias. This helps with queries like "S01AQ1"
        # where the catalog entries are labelled "s01aq1 ps current readback".
        tokens = [
            token
            for token in re.findall(r"[a-z0-9:._-]+", user_input.lower())
            if any(ch.isdigit() for ch in token) and len(token) >= 3
        ]

        if tokens:
            partial_matches: List[PVEntry] = []
            seen = set()
            for entry in self.pv_catalog.entries:
                alias_hit = False
                for alias in entry.aliases:
                    alias_lower = alias.lower()
                    if any(token in alias_lower for token in tokens):
                        alias_hit = True
                        break
                if alias_hit and entry.pv_name not in seen:
                    partial_matches.append(entry)
                    seen.add(entry.pv_name)
            if partial_matches:
                return partial_matches

        return None

    def _resolve_prefix_entries(self, user_input: str) -> List[PVEntry]:
        tokens = re.findall(r"[A-Za-z0-9:_/-]+", user_input)
        prefixes = [token.lower() for token in tokens if ':' in token]
        if not prefixes:
            return []

        seen = set()
        matches: List[PVEntry] = []
        for entry in self.pv_catalog.entries:
            lower_name = entry.pv_name.lower()
            if any(lower_name.startswith(prefix) for prefix in prefixes):
                if entry.pv_name not in seen:
                    matches.append(entry)
                    seen.add(entry.pv_name)
        return matches

    def _prefer_beam_current(
        self,
        entries: List[PVEntry],
        user_input: str,
    ) -> Optional[List[PVEntry]]:
        lowered = user_input.lower()
        if len(entries) <= 2:
            return None
        multi_clues = (" and ", " & ", ",", ";", " vs ", " versus ", " along with ", " plus ")
        if any(clue in lowered for clue in multi_clues):
            return None
        if not any(alias in lowered for alias in self.BEAM_CURRENT_ALIASES):
            return None

        for entry in entries:
            if entry.pv_name.lower() == "s-dcct:currentm":
                return [entry]
        return None

    @classmethod
    def _convert_epoch_to_local(cls, series: pd.Series) -> pd.Series:
        timestamps = pd.to_datetime(series, unit="s", utc=True)
        if cls.LOCAL_TIMEZONE is not None:
            timestamps = timestamps.dt.tz_convert(cls.LOCAL_TIMEZONE)
        return timestamps.dt.tz_localize(None)

    def _build_default_history_range(self, reference_time: datetime) -> dict:
        end_time = reference_time.replace(microsecond=0)
        start_time = end_time - timedelta(hours=self.DEFAULT_HISTORY_HOURS)
        return {
            'start_datetime': start_time,
            'end_datetime': end_time,
            'start': start_time.strftime('%Y%m%d-%H%M%S'),
            'end': end_time.strftime('%Y%m%d-%H%M%S'),
            'quantity': float(self.DEFAULT_HISTORY_HOURS),
            'unit': 'hours',
            'matched_text': f'last {self.DEFAULT_HISTORY_HOURS} hours',
            'duration': end_time - start_time,
            'duration_label': f'last {self.DEFAULT_HISTORY_HOURS} hours',
            'source': 'default',
        }

    @staticmethod
    def _has_explicit_range(user_input_lower: str) -> bool:
        return bool(re.search(r"\bfrom\b.*\bto\b", user_input_lower))

    @staticmethod
    def _is_pv_name_listing_request(user_input_lower: str) -> bool:
        """
        Detect if the user is asking for PV names (not values or history).
        """
        # Patterns that indicate the user wants PV names listed
        pv_name_patterns = [
            r"\bwhat\s+(?:is|are)\s+(?:the\s+)?pv\s+names?",
            r"\blist\s+(?:the\s+)?pv\s+names?",
            r"\bshow\s+(?:me\s+)?(?:the\s+)?pv\s+names?",
            r"\bfind\s+(?:the\s+)?pv\s+names?",
            r"\bget\s+(?:the\s+)?pv\s+names?",
            r"\btell\s+me\s+(?:the\s+)?pv\s+name",
            r"\bwhich\s+pv",
            r"\bpv\s+(?:is|for)",
        ]
        
        # Check if any pattern matches
        for pattern in pv_name_patterns:
            if re.search(pattern, user_input_lower):
                if not any(word in user_input_lower for word in ['value', 'current value', 'reading', 'history', 'trend', 'plot', 'graph']):
                    return True

        if "name" in user_input_lower:
            verb_clues = ["list", "show", "display", "what are", "tell me", "give me", "which", "provide"]
            if any(clue in user_input_lower for clue in verb_clues):
                if not any(word in user_input_lower for word in ['value', 'current value', 'reading', 'history', 'trend', 'plot', 'graph']):
                    return True

        return False

    def _list_pv_names(self, pv_entries: List[PVEntry]) -> dict:
        """
        Return a formatted list of PV names and their descriptions.
        """
        if len(pv_entries) == 1:
            entry = pv_entries[0]
            response = f"The PV name is: {entry.pv_name}\nDescription: {entry.label}"
        else:
            response = f"Found {len(pv_entries)} PV(s):\n\n"
            for i, entry in enumerate(pv_entries, 1):
                response += f"{i}. {entry.pv_name}\n   Description: {entry.label}\n"
        
        return {
            'success': True,
            'response': response,
            'system': self.system_name,
            'tools_used': [],
            'error_message': None,
            'display_label': ', '.join(entry.label for entry in pv_entries),
        }
