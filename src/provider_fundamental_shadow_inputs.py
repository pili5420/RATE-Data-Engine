"""Trust existing delivery records, then reuse the feature consumer/source replay."""
from pathlib import Path

from .eps_duration_facts.model import require
from .eps_duration_facts.raw import sha256
from .provider_eps_metadata import read_metadata
from .provider_financial_features import consume
from .provider_financial_feature_inputs import replay_binding, verify_snapshot


def load_delivery(pin):
    index_path = Path(pin["delivery_index"]).resolve()
    body = index_path.read_bytes()
    require(sha256(body) == pin["delivery_index_sha256"], "SHADOW_DELIVERY_INDEX_TAMPERED")
    index = read_metadata(body)
    inventory_path = index_path.parent / "delivery-artifact-hashes.json"
    inventory_raw = inventory_path.read_bytes()
    require(sha256(inventory_raw) == pin["delivery_inventory_sha256"], "SHADOW_DELIVERY_INVENTORY_TAMPERED")
    inventory = read_metadata(inventory_raw)
    verify_snapshot(inventory["files"])
    require(str(index_path) in inventory["files"] and inventory["files"][str(index_path)]["sha256"] == pin["delivery_index_sha256"], "SHADOW_INDEX_UNBOUND")
    producer = {"base_sha": index["base_sha"], "head_sha": index["head_sha"]}
    require(producer == pin["producer_code_binding"], "SHADOW_PRODUCER_BINDING_MISMATCH")
    manifest = Path(index["feature_manifest"]).resolve()
    require(manifest.parent == Path(pin["feature_directory"]).resolve() and str(manifest) in inventory["files"], "SHADOW_FEATURE_MANIFEST_UNBOUND")
    expected = inventory["files"][str(manifest)]["sha256"]
    require(expected == pin["feature_manifest_sha256"], "SHADOW_TRUSTED_MANIFEST_HASH_MISMATCH")
    result = consume(manifest.parent, expected, source_replayer=replay_binding, expected_code_binding=producer)
    package = read_metadata(Path(index["feature_package"]).read_bytes())
    require(Path(index["feature_package"]).resolve() == manifest.parent / "PROVIDER_FINANCIAL_FEATURES_V1.json" and
        package["content_sha256"] == result["content_sha256"], "SHADOW_FEATURE_PACKAGE_IDENTITY_MISMATCH")
    verify_snapshot(inventory["files"])
    return package


def source_pin(index_reference, index_sha256, inventory_sha256):
    path = Path(index_reference).resolve()
    require(sha256(path.read_bytes()) == index_sha256, "SHADOW_DELIVERY_INDEX_TAMPERED")
    index = read_metadata(path.read_bytes())
    inv_path = path.parent / "delivery-artifact-hashes.json"
    require(sha256(inv_path.read_bytes()) == inventory_sha256, "SHADOW_DELIVERY_INVENTORY_TAMPERED")
    inventory = read_metadata(inv_path.read_bytes())
    require(index["feature_manifest"] in inventory["files"], "SHADOW_FEATURE_MANIFEST_UNBOUND")
    return {"delivery_index": str(path), "delivery_index_sha256": index_sha256,
        "delivery_inventory_sha256": inventory_sha256, "feature_directory": str(Path(index["feature_manifest"]).parent),
        "feature_manifest_sha256": inventory["files"][index["feature_manifest"]]["sha256"],
        "producer_code_binding": {"base_sha": index["base_sha"], "head_sha": index["head_sha"]}}
