"""
providers/ — AI provider adapter package for Athena Assistant.

Public surface:
  from providers.base import Message, ProviderAdapter, ProviderResponse
  from providers.router import ProviderRouter

Individual adapters are imported lazily by the router to avoid crashing
on import when CLI tools are absent or optional packages are not installed.
"""
