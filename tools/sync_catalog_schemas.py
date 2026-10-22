"""Regenerate catalog domains and confirmed-condition skill schemas."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from trialtrust.catalog import CATALOG
from trialtrust.mandate import CustomTask


if __name__ == '__main__':
    for name in ('mandate-review', 'evidence-retrieval'):
        path = ROOT / 'trialtrust' / 'skills' / name / 'manifest.json'
        manifest = json.loads(path.read_text(encoding='utf8'))
        fields = manifest['input_schema']['properties']
        fields['domain']['enum'] = [*CATALOG, 'custom']
        if 'fulfillment' in fields:
            fields['fulfillment'] = {'type':'string', 'minLength':1, 'maxLength':500}
        if 'quantity' in fields:
            fields['quantity'].pop('maximum', None)
        if name == 'mandate-review':
            fields['custom_task'] = CustomTask.model_json_schema()
            manifest['input_schema']['allOf'] = [{'if':{'properties':{'domain':{'const':'custom'}}},'then':{'required':['custom_task']}}]
        manifest['version'] = '1.3.0'
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
