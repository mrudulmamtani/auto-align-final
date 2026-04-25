"""
Policy Factory — multi-agent pipeline for generating auditable cybersecurity governance documents.

Usage:
    from policy_factory import PolicyFactory
    from policy_factory.models import EntityProfile, DocumentSpec

    factory = PolicyFactory()
    result  = factory.run(profile, spec)
"""
from .pipeline import PolicyFactory
from .models import EntityProfile, DocumentSpec

__all__ = ["PolicyFactory", "EntityProfile", "DocumentSpec"]
