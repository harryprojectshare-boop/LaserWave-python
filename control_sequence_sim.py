#!/usr/bin/env python3
"""Simulation-only timing controller for a microwave/laser experiment.

This module intentionally does NOT access GPIO or any physical hardware.
It provides a safe software-only scaffold for validating event ordering,
telemetry logging, and CSV outputs that can be consumed by external tools
such as CAD or engineering workflows.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, field
from pathlib import Path
import time
from typing import List


@dataclass(slots=True)
class SequenceConfig:
    """Configurable timing parameters for the simulated sequence."""

    coil_lead_ms: float = 500.0
    laser_to_microwave_delay_us: float = 1.0
    microwave_on_ms: float = 20.0
    laser_pulse_ns: int = 10
    emergency_stop: bool = False
    cooling_fan_ok: bool = True


@dataclass(slots=True)
class TelemetryEvent:
    """Single timestamped event in the simulated run."""

    event: str
    relative_ns: int
    details: str = ""


@dataclass(slots=True)
class SequenceSimulator:
    """Runs a software-only event schedule and records telemetry."""

    config: SequenceConfig
    telemetry: List[TelemetryEvent] = field(default_factory=list)

    def _record(self, event: str, t0_ns: int, details: str = "") -> None:
        self.telemetry.append(
            TelemetryEvent(
                event=event,
                relative_ns=time.perf_counter_ns() - t0_ns,
                details=details,
            )
        )

    def _wait_until(self, target_ns: int) -> None:
        while time.perf_counter_ns() < target_ns:
            pass

    def validate_interlocks(self) -> None:
        if self.config.emergency_stop:
            raise RuntimeError("Emergency stop is engaged; refusing to run sequence.")
        if not self.config.cooling_fan_ok:
            raise RuntimeError("Cooling fan interlock is not satisfied; refusing to run sequence.")

    def start_sequence(self) -> List[TelemetryEvent]:
        """Execute a fully simulated timing sequence."""
        self.validate_interlocks()
        self.telemetry.clear()

        t0_ns = time.perf_counter_ns()
        self._record("sequence_start", t0_ns, "simulation mode")

        coil_off_ns = t0_ns + int(self.config.coil_lead_ms * 1_000_000)
        laser_fire_ns = coil_off_ns
        laser_low_ns = laser_fire_ns + self.config.laser_pulse_ns
        microwave_on_ns = laser_low_ns + int(self.config.laser_to_microwave_delay_us * 1_000)
        microwave_off_ns = microwave_on_ns + int(self.config.microwave_on_ms * 1_000_000)

        self._record("coil_power_on", t0_ns, "simulated magnetic coil enable")
        self._wait_until(laser_fire_ns)

        self._record("laser_high", t0_ns, f"pulse_ns={self.config.laser_pulse_ns}")
        self._wait_until(laser_low_ns)
        self._record("laser_low", t0_ns)

        self._wait_until(microwave_on_ns)
        self._record("microwaves_on", t0_ns, "4 channels, simulated concurrent trigger")

        self._wait_until(microwave_off_ns)
        self._record("microwaves_off", t0_ns)
        self._record("coil_power_off", t0_ns)
        self._record("sequence_complete", t0_ns)
        return list(self.telemetry)

    def write_csv(self, output_path: Path) -> Path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", newline="", encoding="utf-8") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(["event", "relative_ns", "relative_us", "details"])
            for item in self.telemetry:
                writer.writerow(
                    [
                        item.event,
                        item.relative_ns,
                        item.relative_ns / 1_000.0,
                        item.details,
                    ]
                )
        return output_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Simulation-only sequence logger for validating timing offsets and "
            "exporting telemetry to CSV for review in downstream tools."
        )
    )
    parser.add_argument(
        "--laser-to-microwave-delay-us",
        type=float,
        default=1.0,
        help="Delay between the end of the laser pulse and simulated microwave enable.",
    )
    parser.add_argument(
        "--coil-lead-ms",
        type=float,
        default=500.0,
        help="How long before the laser the simulated magnetic coil turns on.",
    )
    parser.add_argument(
        "--microwave-on-ms",
        type=float,
        default=20.0,
        help="Simulated microwave on-time.",
    )
    parser.add_argument(
        "--laser-pulse-ns",
        type=int,
        default=10,
        help="Laser pulse width in nanoseconds for the simulation log.",
    )
    parser.add_argument(
        "--fan-ok",
        action="store_true",
        help="Mark the cooling fan interlock as satisfied.",
    )
    parser.add_argument(
        "--emergency-stop",
        action="store_true",
        help="Simulate an asserted emergency-stop input.",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=Path("telemetry/sequence_log.csv"),
        help="Output CSV path.",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    simulator = SequenceSimulator(
        SequenceConfig(
            coil_lead_ms=args.coil_lead_ms,
            laser_to_microwave_delay_us=args.laser_to_microwave_delay_us,
            microwave_on_ms=args.microwave_on_ms,
            laser_pulse_ns=args.laser_pulse_ns,
            emergency_stop=args.emergency_stop,
            cooling_fan_ok=args.fan_ok,
        )
    )

    try:
        simulator.start_sequence()
    except RuntimeError as exc:
        print(f"Sequence blocked: {exc}")
        return 2

    csv_path = simulator.write_csv(args.csv)
    print(f"Simulation complete. Telemetry written to {csv_path}")
    for event in simulator.telemetry:
        print(f"{event.event:18} {event.relative_ns:>12} ns  {event.details}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
