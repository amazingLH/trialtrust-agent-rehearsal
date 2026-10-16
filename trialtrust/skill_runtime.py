"""Trusted skill discovery, lazy instructions, capability gates and audit events.

Manifests select only handlers supplied by application code; no uploaded code,
module imports, URLs or shell commands can become an executable skill.
"""
from __future__ import annotations
import hashlib
import json
import time
from pathlib import Path

from jsonschema import validate

ROOT = Path(__file__).parent / 'skills'
TRUSTED = frozenset({'mandate-review','evidence-retrieval','plan-verification','pair-audit','request-analysis'})
CAPABILITIES = frozenset({'read_conditions','read_fixture','check_constraints','read_reports','analyze_text','model_call'})

def discover():
    return [load(name, instructions=False) for name in sorted(TRUSTED)]

def load(name, instructions=True):
    if name not in TRUSTED:
        raise ValueError('Unknown or untrusted skill')
    folder = ROOT / name
    manifest = json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    if manifest['id'] != name or not set(manifest['capabilities']) <= CAPABILITIES:
        raise ValueError('Invalid trusted skill manifest')
    body = (folder/'SKILL.md').read_text(encoding='utf-8')
    digest = hashlib.sha256(json.dumps(manifest,sort_keys=True,ensure_ascii=False).encode()+body.encode()).hexdigest()
    return {**manifest,'digest':digest,**({'instructions':body} if instructions else {})}

def instructions_for(names):
    return '\n\n'.join(load(name)['instructions'] for name in names)

def invoke(name, payload, handler, *, granted, required):
    skill = load(name)
    needed = set(required)
    if not set(skill['required_capabilities']) <= needed or not needed <= set(skill['capabilities']) or not needed <= set(granted):
        raise PermissionError('Skill capability not granted')
    validate(payload,skill['input_schema'])
    start = time.monotonic()
    result = handler(payload,skill['instructions'])
    validate(result,skill['output_schema'])
    event = {'skill_id':name,'name':skill['name'],'version':skill['version'],'manifest_digest':skill['digest'],
             'capabilities_used':sorted(needed),'status':'completed','duration_ms':round((time.monotonic()-start)*1000),
             'input_digest':hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
             'output_digest':hashlib.sha256(json.dumps(result,sort_keys=True,ensure_ascii=False).encode()).hexdigest()}
    return result,event
