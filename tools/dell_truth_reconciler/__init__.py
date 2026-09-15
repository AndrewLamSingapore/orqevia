"""Deterministic Dell-side truth reconciliation for JARVIS PRIME."""

from .core import Reconciler, TruthState, reconcile

__all__ = ["Reconciler", "TruthState", "reconcile"]
__version__ = "1.0.0"
