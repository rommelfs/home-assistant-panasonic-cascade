"""Set real repository metadata before publishing. Does not contact GitHub."""
import argparse
import json
from pathlib import Path
import re

parser = argparse.ArgumentParser()
parser.add_argument('repository', help='GitHub owner/repository')
parser.add_argument('--maintainer', required=True, help='GitHub username, without @')
args = parser.parse_args()
if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', args.repository):
    parser.error('Expected owner/repository')
if not re.fullmatch(r'[A-Za-z0-9-]+', args.maintainer):
    parser.error('Invalid GitHub username')
p = Path(__file__).resolve().parent / 'custom_components/panasonic_cascade/manifest.json'
data = json.loads(p.read_text())
data.update(documentation=f'https://github.com/{args.repository}#readme',
            issue_tracker=f'https://github.com/{args.repository}/issues',
            codeowners=[f'@{args.maintainer}'])
p.write_text(json.dumps(data, indent=2) + '\n')
print('Local manifest updated. Nothing has been published.')
