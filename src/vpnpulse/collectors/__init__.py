"""Collectors turn what a source can tell us into observations (see docs/collector-sdk.md)."""
from .base import Collected, Collector
from .fixture import FixtureCollector

__all__ = ["Collected", "Collector", "FixtureCollector"]
