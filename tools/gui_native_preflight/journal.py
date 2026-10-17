"""Reuse accepted PR73 process-crash journal unchanged; no production ledger."""
from pathlib import Path
from .contracts import BASE_TOOL_SHA
from .protocol import require
def accepted_workspace(root):
 from gui_native_identity.protocol import code_identity
 from gui_native_identity.journal import SyntheticWorkspace
 require(code_identity()==BASE_TOOL_SHA,'ACCEPTED_PR73_JOURNAL_SOURCE_CHANGED')
 return SyntheticWorkspace(Path(root))
