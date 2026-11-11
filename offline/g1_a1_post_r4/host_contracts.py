"""Static, nonexecuting host capability contracts."""
from __future__ import annotations
from dataclasses import dataclass
from offline.model_s_s2_r2.simulator import Decision


@dataclass(frozen=True)
class HostDeclaration:
    identity: str
    os_family: str
    credential_isolation: bool
    authority_binding: str
    custody_binding: str
    evidence_collection: bool
    recovery: str


def validate_static_host(declaration: HostDeclaration, *, expected_authority: str,
                         expected_custody: str) -> Decision:
    if not all(x.startswith("SYNTHETIC_") for x in
               (declaration.identity, expected_authority, expected_custody)):
        return Decision("BLOCKED", "HOST_IDENTITY_UNBOUND")
    if declaration.os_family not in {"SYNTHETIC_WINDOWS", "SYNTHETIC_LINUX"}:
        return Decision("BLOCKED", "HOST_OS_UNSUPPORTED")
    if declaration.credential_isolation is not True:
        return Decision("BLOCKED", "CREDENTIAL_ISOLATION_UNPROVEN")
    if declaration.authority_binding != expected_authority or declaration.custody_binding != expected_custody:
        return Decision("BLOCKED", "HOST_BINDING_MISMATCH")
    if declaration.evidence_collection is not True or declaration.recovery != "FAIL_CLOSED_MANUAL_REVIEW":
        return Decision("BLOCKED", "HOST_EVIDENCE_OR_RECOVERY_UNPROVEN")
    return Decision("PASS", "STATIC_SYNTHETIC_HOST_CONTRACT_ONLY", {"operational": False})


def operational_host_gate(*, verifier_appointed: bool, c11_adopted: bool,
                          custody_qualified: bool) -> Decision:
    # No host execution path exists in this package, including when all flags are true.
    return Decision("BLOCKED", "OPERATIONAL_HOST_ADAPTER_NOT_IMPLEMENTED")
