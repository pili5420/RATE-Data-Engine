"""Only the pinned accepted pure model is imported; accepted files are never edited."""
import hashlib,importlib.util
from pathlib import Path
from .contracts import BASELINE_TOOL_SHA
from .protocol import need
def accepted():
 p=Path(__file__).resolve().parent.parent/'gui_gate2/identity_binding.py'
 need(hashlib.sha256(p.read_bytes()).hexdigest()==BASELINE_TOOL_SHA,'ACCEPTED_PR72_TOOL_CHANGED')
 s=importlib.util.spec_from_file_location('accepted_pr72_offline_model',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
