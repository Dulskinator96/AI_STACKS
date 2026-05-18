"""Read-only observers. NEVER mutate substrate. Produce Issue objects only.

The four v1 observers are deliberately minimal:
    RuntimeHealthAgent — exception telemetry + cycle latency
    UIStateAgent       — UI signal emissions / render faults
    QueueWatchAgent    — worker-pool depth / stall
    DriftMonitor       — rolling repair frequency + confidence trend

DriftMonitor is the ONLY observer with authority over RepairCoordinator
(restrict / restore). It exercises that authority via the coordinator's
public surface, not by editing internal state.
"""
from maintenance.observers.base import ReadOnlyObserver
from maintenance.observers.runtime_health import RuntimeHealthAgent
from maintenance.observers.ui_state import UIStateAgent
from maintenance.observers.queue_watch import QueueWatchAgent
from maintenance.observers.drift_monitor import DriftMonitor
from maintenance.observers.stratum_health import StratumHealthAgent
from maintenance.observers.won_health import WONHealthAgent
from maintenance.observers.execution_integrity import ExecutionIntegrityAgent
from maintenance.observers.process_watch import ProcessWatchAgent
from maintenance.observers.resource_pressure import ResourcePressureAgent
from maintenance.observers.memory_integrity import MemoryIntegrityAgent
from maintenance.observers.telemetry_monitor import TelemetryMonitorAgent

__all__ = [
    "ReadOnlyObserver",
    "RuntimeHealthAgent", "UIStateAgent", "QueueWatchAgent", "DriftMonitor",
    "StratumHealthAgent", "WONHealthAgent",
    "ExecutionIntegrityAgent", "ProcessWatchAgent", "ResourcePressureAgent",
    "MemoryIntegrityAgent", "TelemetryMonitorAgent",
]
