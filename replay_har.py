"""Validate captured FIN data locally, without printing credentials or site IDs."""
import argparse
import importlib
import json
from pathlib import Path
import sys
import types

parser = argparse.ArgumentParser()
parser.add_argument('files', nargs='+', type=Path)
args = parser.parse_args()
pkg = types.ModuleType('har_replay')
pkg.__path__ = [str(Path(__file__).resolve().parent / 'custom_components/panasonic_cascade')]
sys.modules[pkg.__name__] = pkg
zinc = importlib.import_module(pkg.__name__ + '.zinc')
model = importlib.import_module(pkg.__name__ + '.model')
rows, grids, lines = {}, 0, 0
for path in args.files:
    entries = json.loads(path.read_text())['log']['entries']
    for entry in entries:
        request = entry['request']
        if '/api/' not in request['url'] or 'defs()' in request.get('postData', {}).get('text', ''):
            continue
        response = entry['response'].get('content', {}).get('text', '')
        if not response or entry['response']['status'] != 200:
            continue
        for grid in zinc.parse_grids(response):
            grids += 1
            lines += len(grid)
            for row in grid:
                ident = zinc.reference(row.get('id'))
                if ident:
                    rows[ident] = row
points = [r for r in rows.values() if r.get('point') is zinc.MARKER]
print(json.dumps({'grids':grids,'rows':lines,'points':len(points),'supported_controls':sum(model.control_kind(r) is not None for r in points)}, indent=2))
