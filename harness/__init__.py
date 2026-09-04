"""Offline teaching harness. Trusted host code owns adapters and policy."""

from .runtime import Harness, PolicyError, canonical_bytes, strict_gate

__all__ = ["Harness", "PolicyError", "canonical_bytes", "strict_gate"]
