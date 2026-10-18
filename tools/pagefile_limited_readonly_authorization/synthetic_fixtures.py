"""Fictional fixtures only, no target identity or formal Permit."""
import base64
import hashlib
import json
from tools.pagefile_non_gui_evidence import fixtures as prior
from tools.pagefile_limited_readonly_authorization import candidate as c

def envelope(packet=None):
 if packet is None:packet=prior.packet()
 return {'version':'PF_LRO_OFFLINE_RAW_CANDIDATE_V1','realm':'SYNTHETIC_ONLY','base_head':c.BASE_HEAD,
  'accepted_engine_sha256':c.ACCEPTED_ENGINE_SHA256,'accepted_schema_sha256':c.ACCEPTED_SCHEMA_SHA256,
  'scope_sha256':c.scope_hash(),'synthetic_source_packet_b64':base64.b64encode(prior.encode(packet)).decode()}
def wire(value):return c.canonical(value)+b'\n'
def submission(key='HOST'):
 b=b'FICTIONAL UNVERIFIED TEST EVIDENCE, NOT A SIGNATURE OR HOST ATTESTATION'
 return {'requirement':key,'artifact_utf8_b64':base64.b64encode(b).decode(),'artifact_sha256':hashlib.sha256(b).hexdigest(),'source_authority':'FICTIONAL_LABEL_ONLY','status':'UNVERIFIED_SUBMISSION'}
