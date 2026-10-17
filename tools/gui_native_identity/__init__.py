"""Offline Windows identity adapter candidate. No DLL binder, live CLI or Permit loader."""
from .adapter import OfflineIdentityCandidate
from .provider import ScriptedWindowsProvider
from .journal import SyntheticWorkspace

__all__ = ['OfflineIdentityCandidate', 'ScriptedWindowsProvider', 'SyntheticWorkspace']
