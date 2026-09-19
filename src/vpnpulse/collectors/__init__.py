"""Collectors turn what a source can tell us into observations (see docs/collector-sdk.md)."""
from .base import Collected, Collector
from .fixture import FixtureCollector
from .registry import build_collectors, load_collectors_map, unreferenced
from .ssh import SshCollector, SshTarget, call_helper

__all__ = ["Collected", "Collector", "FixtureCollector", "SshCollector", "SshTarget", "build_collectors", "call_helper", "load_collectors_map", "unreferenced"]
