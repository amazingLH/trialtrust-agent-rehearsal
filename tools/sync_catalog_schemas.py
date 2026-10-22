"""Regenerate closed skill schemas after adding supported catalog entries."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from trialtrust.catalog import CATALOG, FULFILLMENTS


if __name__ == '__main__':
    for name in ('mandate-review', 'evidence-retrieval'):
        path = ROOT / 'trialtrust' / 'skills' / name / 'manifest.json'
        manifest = json.loads(path.read_text(encoding='utf8'))
        fields = manifest['input_schema']['properties']
        fields['domain']['enum'] = list(CATALOG)
        if 'fulfillment' in fields:
            fields['fulfillment']['enum'] = list(FULFILLMENTS)
        manifest['version'] = '1.1.0'
        path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf8')
