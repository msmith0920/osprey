"""Direct unit tests for the machine-description parser entry point.

The individual validation rules are exercised end-to-end through
``SimulationEngine`` construction in ``test_engine.py``; this file locks the
contract of the extracted ``parse_machine`` entry point and the ``ParsedMachine``
container it returns.
"""

from pathlib import Path

import pytest

from osprey.simulation.machine import (
    DEFAULT_SCENARIO,
    ParsedMachine,
    Scenario,
    SimChannel,
    parse_machine,
)

_PATH = Path("machine.json")


def _machine(**overrides):
    base = {
        "name": "TestMachine",
        "description": "fixture",
        "channels": {
            "PV:A": {"value": 10.0, "units": "mA"},
            "PV:B": {"expr": "ch('PV:A') * 2"},
        },
        "scenarios": {
            "fault": {"description": "a fault", "overrides": {"PV:A": 1.0}},
        },
    }
    base.update(overrides)
    return base


class TestParseMachineHappyPath:
    def test_returns_parsed_machine(self):
        model = parse_machine(_machine(), _PATH)
        assert isinstance(model, ParsedMachine)
        assert model.name == "TestMachine"
        assert model.description == "fixture"
        assert set(model.channels) == {"PV:A", "PV:B"}
        assert isinstance(model.channels["PV:A"], SimChannel)

    def test_expression_refs_are_extracted(self):
        model = parse_machine(_machine(), _PATH)
        assert model.channels["PV:B"].refs == ("PV:A",)

    def test_default_nominal_scenario_injected(self):
        model = parse_machine(_machine(), _PATH)
        assert DEFAULT_SCENARIO in model.scenarios
        assert isinstance(model.scenarios["fault"], Scenario)

    def test_explicit_nominal_not_overwritten(self):
        machine = _machine(scenarios={"nominal": {"description": "custom nominal"}})
        model = parse_machine(machine, _PATH)
        assert model.scenarios["nominal"].description == "custom nominal"

    def test_metadata_defaults_when_absent(self):
        machine = {"channels": {"PV:A": {"value": 1.0}}}
        model = parse_machine(machine, _PATH)
        assert model.name == ""
        assert model.description == ""
        assert set(model.scenarios) == {DEFAULT_SCENARIO}


class TestParseMachineValidation:
    def test_missing_channels_mapping(self):
        with pytest.raises(ValueError, match="must define a 'channels' mapping"):
            parse_machine({"name": "x"}, _PATH)

    def test_non_dict_machine(self):
        with pytest.raises(ValueError, match="must define a 'channels' mapping"):
            parse_machine([], _PATH)

    def test_unknown_reference_propagates(self):
        machine = {"channels": {"PV:B": {"expr": "ch('PV:MISSING')"}}}
        with pytest.raises(ValueError, match="references unknown channel 'PV:MISSING'"):
            parse_machine(machine, _PATH)

    def test_reference_cycle_propagates(self):
        machine = {
            "channels": {
                "PV:A": {"expr": "ch('PV:B')"},
                "PV:B": {"expr": "ch('PV:A')"},
            }
        }
        with pytest.raises(ValueError, match="reference cycle detected"):
            parse_machine(machine, _PATH)

    def test_invalid_event_propagates(self):
        machine = _machine(
            scenarios={
                "fault": {
                    "archiver": [{"channel": "PV:A", "events": [{"shape": "bogus", "at": 0.5}]}]
                }
            }
        )
        with pytest.raises(ValueError, match="event shape must be one of"):
            parse_machine(machine, _PATH)
