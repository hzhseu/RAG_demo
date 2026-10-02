"""Collect local dependency versions and publisher notices for redistribution review."""
import importlib.metadata
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parent.parent
target = ROOT / 'docs/dependency-notices'
target.mkdir(parents=True, exist_ok=True)
records = []
for distribution in importlib.metadata.distributions():
    name = distribution.metadata['Name']
    folder = target / 'python' / f'{name}-{distribution.version}'
    notices = []
    for item in distribution.files or []:
        if any(word in item.name.lower() for word in ('license', 'copying', 'notice')) or item.name == 'METADATA':
            source = Path(distribution.locate_file(item))
            if source.is_file() and '.dist-info' in str(item):
                path = folder / Path(*item.parts[1:])
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, path)
                notices.append(path.relative_to(target).as_posix())
    records.append({'scope': 'backend and development environment', 'name': name, 'version': distribution.version, 'declared_license': distribution.metadata.get('License-Expression') or distribution.metadata.get('License'), 'notices': notices})

pnpm = ROOT / 'frontend/node_modules/.pnpm'
seen = set()
for path in list(pnpm.glob('*/node_modules/*/package.json')) + list(pnpm.glob('*/node_modules/@*/*/package.json')):
    package = json.loads(path.read_text(encoding='utf-8'))
    name, version = package['name'], package['version']
    if (name, version) in seen:
        continue
    seen.add((name, version))
    folder = target / 'javascript' / (name.replace('/', '_') + '-' + version)
    notices = []
    for source in path.parent.iterdir():
        if source.is_file() and any(word in source.name.lower() for word in ('license', 'copying', 'notice')):
            folder.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, folder / source.name)
            notices.append((folder / source.name).relative_to(target).as_posix())
    records.append({'scope': 'frontend and build tools', 'name': name, 'version': version, 'declared_license': package.get('license'), 'notices': notices})

(target / 'inventory.json').write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding='utf-8')
shutil.copy2(ROOT / 'requirements.lock.txt', target / 'requirements.lock.txt')
shutil.copy2(ROOT / 'frontend/pnpm-lock.yaml', target / 'pnpm-lock.yaml')
print(f'Collected version/license metadata for {len(records)} dependencies')
