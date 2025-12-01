"""
Mock control system connector for development and testing.

Works with any PV names - generates realistic synthetic data.
Ideal for R&D and development without control room access.

Related to Issue #18 - Control System Abstraction (Layer 2 - Mock Implementation)
"""

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Any

import numpy as np

from osprey.connectors.control_system.base import (
    ChannelMetadata,
    ChannelValue,
    ChannelWriteResult,
    ControlSystemConnector,
    WriteVerification,
)
from osprey.utils.logger import get_logger

logger = get_logger("mock_connector")


class MockConnector(ControlSystemConnector):
    """
    Mock control system connector for development and testing.

    This connector simulates a control system without requiring real hardware.
    It generates realistic synthetic data for any PV name, making it ideal
    for R&D and development when you don't have access to the control room.

    Features:
    - Accepts any PV name
    - Generates realistic initial values based on PV naming conventions
    - Adds configurable noise to simulate real measurements
    - Maintains state between reads and writes
    - Simulates readback PVs (e.g., :SP -> :RB)

    Example:
        >>> config = {
        >>>     'response_delay_ms': 10,
        >>>     'noise_level': 0.01,
        >>>     'enable_writes': True
        >>> }
        >>> connector = MockConnector()
        >>> await connector.connect(config)
        >>> value = await connector.read_pv('BEAM:CURRENT')
        >>> print(f"Beam current: {value.value} {value.metadata.units}")
    """

    def __init__(self):
        self._connected = False
        self._state: dict[str, float] = {}
        self._subscriptions: dict[str, tuple] = {}

    async def connect(self, config: dict[str, Any]) -> None:
        """
        Initialize mock connector.

        Args:
            config: Configuration with keys:
                - response_delay_ms: Simulated response delay (default: 10)
                - noise_level: Relative noise level 0-1 (default: 0.01)
                - enable_writes: (DEPRECATED) Use execution_control.epics.writes_enabled instead
        """
        self._response_delay = config.get('response_delay_ms', 10) / 1000.0
        self._noise_level = config.get('noise_level', 0.01)

        # Use global writes_enabled flag (with deprecation support)
        from osprey.utils.config import get_config_value

        # Check for deprecated parameter
        local_enable = config.get('enable_writes')
        if local_enable is not None:
            logger.warning(
                "config.control_system.connector.mock.enable_writes is deprecated. "
                "Use control_system.writes_enabled instead. "
                "Local setting will be ignored in future versions."
            )
            # Honor it for now for backward compatibility
            self._enable_writes = local_enable
        else:
            # Use global flag - try new location first
            writes_enabled = get_config_value('control_system.writes_enabled', None)

            # Fall back to old location for backward compatibility
            if writes_enabled is None:
                writes_enabled = get_config_value('execution_control.epics.writes_enabled', None)
                if writes_enabled is not None:
                    logger.warning("⚠️  DEPRECATED: 'execution_control.epics.writes_enabled' is deprecated.")
                    logger.warning("   Please move this setting to 'control_system.writes_enabled' in your config.yml")
                else:
                    writes_enabled = False  # Default to safe

            self._enable_writes = writes_enabled

        self._connected = True
        logger.debug(f"Mock connector initialized (writes_enabled={self._enable_writes})")

    async def disconnect(self) -> None:
        """Cleanup mock connector."""
        self._state.clear()
        self._subscriptions.clear()
        self._connected = False
        logger.debug("Mock connector disconnected")

    async def read_channel(
        self,
        channel_address: str,
        timeout: float | None = None
    ) -> ChannelValue:
        """
        Read channel - generates realistic value if not cached.

        Args:
            channel_address: Any channel name (mock accepts all names)
            timeout: Ignored for mock connector

        Returns:
            ChannelValue with synthetic data
        """
        # Simulate network delay
        await asyncio.sleep(self._response_delay)

        # Get or generate initial value
        if channel_address not in self._state:
            self._state[channel_address] = self._generate_initial_value(channel_address)

        # Add noise
        base_value = self._state[channel_address]
        noise = np.random.normal(0, abs(base_value) * self._noise_level)
        value = base_value + noise

        return ChannelValue(
            value=value,
            timestamp=datetime.now(),
            metadata=ChannelMetadata(
                units=self._infer_units(channel_address),
                timestamp=datetime.now(),
                description=f"Mock channel: {channel_address}"
            )
        )

    async def write_channel(
        self,
        channel_address: str,
        value: Any,
        timeout: float | None = None,
        verification_level: str = "callback",
        tolerance: float | None = None
    ) -> ChannelWriteResult:
        """
        Write channel - updates internal state with simulated verification.

        Args:
            channel_address: Any channel name
            value: Value to write
            timeout: Ignored for mock connector
            verification_level: "none", "callback", or "readback"
            tolerance: Absolute tolerance for readback verification

        Returns:
            ChannelWriteResult with write status and verification details
        """
        if not self._enable_writes:
            logger.warning(f"Write to {channel_address} rejected (writes disabled)")
            return ChannelWriteResult(
                channel_address=channel_address,
                value_written=value,
                success=False,
                verification=WriteVerification(
                    level=verification_level,
                    verified=False,
                    notes="Writes disabled in mock connector"
                ),
                error_message="Mock connector has writes disabled"
            )

        # Simulate network delay
        await asyncio.sleep(self._response_delay)

        # Update state
        self._state[channel_address] = float(value)

        # Update corresponding readback channel (simulate small offset)
        readback_ch = channel_address.replace(':SP', ':RB').replace(':SET', ':GET')
        if readback_ch != channel_address:
            # Simulate small offset between setpoint and readback
            offset = np.random.normal(0, abs(float(value)) * 0.001)
            self._state[readback_ch] = float(value) + offset

        if verification_level == "none":
            logger.debug(f"Mock write (no verification): {channel_address} = {value}")
            return ChannelWriteResult(
                channel_address=channel_address,
                value_written=value,
                success=True,
                verification=WriteVerification(
                    level="none",
                    verified=False,
                    notes="No verification requested (mock)"
                )
            )

        elif verification_level == "callback":
            # Simulate callback confirmation (mock always succeeds)
            logger.debug(f"Mock write (callback simulated): {channel_address} = {value}")
            return ChannelWriteResult(
                channel_address=channel_address,
                value_written=value,
                success=True,
                verification=WriteVerification(
                    level="callback",
                    verified=True,
                    notes="Simulated callback confirmation (mock)"
                )
            )

        elif verification_level == "readback":
            # Full verification - read back and compare
            try:
                # Add small delay to simulate readback
                await asyncio.sleep(self._response_delay)

                readback = await self.read_channel(channel_address)

                # Check tolerance
                diff = abs(float(readback.value) - float(value))
                verified = diff <= (tolerance or 0.001)

                logger.debug(
                    f"Mock write (readback verified={verified}): {channel_address} = {value}, "
                    f"readback = {readback.value}, diff = {diff:.6f}, tolerance = {tolerance}"
                )

                return ChannelWriteResult(
                    channel_address=channel_address,
                    value_written=value,
                    success=True,
                    verification=WriteVerification(
                        level="readback",
                        verified=verified,
                        readback_value=float(readback.value),
                        tolerance_used=tolerance,
                        notes=(
                            f"Simulated readback: {readback.value}, tolerance: ±{tolerance}, diff: {diff:.6f} (mock)"
                            if verified else
                            f"Simulated readback mismatch: {readback.value} (expected {value}, diff: {diff:.6f} > tolerance {tolerance}) (mock)"
                        )
                    )
                )

            except Exception as e:
                logger.warning(f"Mock readback failed for {channel_address}: {e}")
                return ChannelWriteResult(
                    channel_address=channel_address,
                    value_written=value,
                    success=True,
                    verification=WriteVerification(
                        level="readback",
                        verified=False,
                        notes=f"Simulated readback failed: {str(e)} (mock)"
                    ),
                    error_message=f"Mock readback verification failed: {str(e)}"
                )

        else:
            raise ValueError(f"Invalid verification_level: {verification_level}. Must be 'none', 'callback', or 'readback'")

    async def read_multiple_channels(
        self,
        channel_addresses: list[str],
        timeout: float | None = None
    ) -> dict[str, ChannelValue]:
        """Read multiple channels concurrently."""
        tasks = [self.read_channel(ch) for ch in channel_addresses]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        return {
            ch: result
            for ch, result in zip(channel_addresses, results, strict=True)
            if not isinstance(result, Exception)
        }

    async def subscribe(
        self,
        channel_address: str,
        callback: Callable[[ChannelValue], None]
    ) -> str:
        """
        Subscribe to channel changes.

        Note: Mock connector only triggers callbacks on write_channel calls.
        """
        sub_id = f"mock_{channel_address}_{id(callback)}"
        self._subscriptions[sub_id] = (channel_address, callback)
        logger.debug(f"Mock subscription created: {sub_id}")
        return sub_id

    async def unsubscribe(self, subscription_id: str) -> None:
        """Unsubscribe from channel changes."""
        if subscription_id in self._subscriptions:
            del self._subscriptions[subscription_id]
            logger.debug(f"Mock subscription removed: {subscription_id}")

    async def get_metadata(self, channel_address: str) -> ChannelMetadata:
        """Get channel metadata (synthetic for mock)."""
        return ChannelMetadata(
            units=self._infer_units(channel_address),
            description=f"Mock channel: {channel_address}",
            timestamp=datetime.now()
        )

    async def validate_channel(self, channel_address: str) -> bool:
        """All channel names are valid in mock mode."""
        return True

    def _generate_initial_value(self, channel_name: str) -> float:
        """
        Generate realistic initial value based on channel type.

        Uses naming conventions to infer reasonable values.
        """
        ch_lower = channel_name.lower()

        if 'current' in ch_lower:
            return 500.0 if 'beam' in ch_lower else 150.0
        elif 'voltage' in ch_lower:
            return 5000.0
        elif 'power' in ch_lower:
            return 50.0
        elif 'pressure' in ch_lower:
            return 1e-9
        elif 'temp' in ch_lower:
            return 25.0
        elif 'lifetime' in ch_lower:
            return 10.0
        elif 'position' in ch_lower or 'pos' in ch_lower:
            return 0.0
        elif 'energy' in ch_lower:
            return 1900.0  # MeV for typical storage ring
        else:
            return 100.0

    def _infer_units(self, channel_name: str) -> str:
        """Infer units from channel name."""
        ch_lower = channel_name.lower()

        if 'current' in ch_lower:
            return 'mA' if 'beam' in ch_lower else 'A'
        elif 'voltage' in ch_lower:
            return 'V'
        elif 'power' in ch_lower:
            return 'kW'
        elif 'pressure' in ch_lower:
            return 'Torr'
        elif 'temp' in ch_lower:
            return '°C'
        elif 'lifetime' in ch_lower:
            return 'hours'
        elif 'position' in ch_lower or 'pos' in ch_lower:
            return 'mm'
        elif 'energy' in ch_lower:
            return 'MeV'
        else:
            return ''

