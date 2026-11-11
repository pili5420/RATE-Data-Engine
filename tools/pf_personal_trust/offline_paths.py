"""Engineering-output checks only, not atomic native output-root security."""
from pathlib import Path
import re

def approved_output(raw, runner_temp=None):
    if type(raw) is not str or not raw or any(x in ('.','..') for x in raw.replace('\\','/').split('/')):
        raise ValueError('CANONICAL_ABSOLUTE_OUTPUT_REQUIRED')
    out=Path(raw)
    if not out.is_absolute():
        raise ValueError('ABSOLUTE_OUTPUT_REQUIRED')
    # Reject reparse ancestors BEFORE resolving and before creating anything.
    for p in (out,*out.parents):
        if p.exists() and (p.is_symlink() or getattr(p.lstat(),'st_file_attributes',0)&0x400):
            raise ValueError('REPARSE_OUTPUT_FORBIDDEN')
    resolved=out.resolve()
    if out!=resolved:
        raise ValueError('PHYSICAL_PATH_ALIAS_FORBIDDEN')
    local_root=Path(r'D:\Codex')
    local=False
    if out.is_relative_to(local_root):
        parts=out.relative_to(local_root).parts
        local=bool(parts and re.fullmatch(r'RATE-PF-PERSONAL-001-(Evidence|Independent)-[0-9]{8}-[0-9]{6}',parts[0]))
    hosted=False
    if runner_temp is not None:
        root=Path(runner_temp)
        if not root.is_absolute() or any(x in ('.','..') for x in str(runner_temp).replace('\\','/').split('/')):
            raise ValueError('INVALID_HOSTED_ROOT')
        for p in (root,*root.parents):
            if p.exists() and (p.is_symlink() or getattr(p.lstat(),'st_file_attributes',0)&0x400):
                raise ValueError('REPARSE_HOSTED_ROOT')
        root=root.resolve()
        hosted=out.is_relative_to(root) and out!=root
    if out.exists() or not(local or hosted):
        raise ValueError('FRESH_SCOPED_OFFLINE_OUTPUT_REQUIRED')
    return out
