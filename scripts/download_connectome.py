"""Download exact upstream inputs with resume support and SHA-256 verification."""
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / 'vendor/doomfly'
registry = json.loads((UPSTREAM / 'doom/datasets.json').read_text())['datasets']['malecns_v1']['files']
lock = json.loads((UPSTREAM / 'data-provenance/malecns_v1/source.lock.json').read_text())
destination = UPSTREAM / 'connectome_data/malecns_v1'
destination.mkdir(parents=True, exist_ok=True)
for name, url in registry.items():
    target = destination / name
    if not target.exists():
        temporary = target.with_suffix('.download')
        subprocess.run(['curl', '--fail', '--location', '--retry', '3', '--connect-timeout', '30', '--continue-at', '-', '--output', str(temporary), url], check=True)
        candidate = temporary
    else:
        candidate = target
    digest = hashlib.sha256()
    with candidate.open('rb') as f:
        while chunk := f.read(8 * 1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != lock[name]['sha256'] or candidate.stat().st_size != lock[name]['bytes']:
        raise RuntimeError('Input integrity failed: ' + name)
    if candidate != target:
        candidate.replace(target)
    print(name, target.stat().st_size, 'verified', flush=True)
(destination / 'source.lock.json').write_text(json.dumps(lock, indent=2) + '\n')
commit = subprocess.check_output(['git', '-C', str(UPSTREAM), 'rev-parse', 'HEAD'], text=True).strip()
(ROOT / 'research/upstream-lock.json').write_text(json.dumps({'repository': 'https://github.com/nftechie/doomfly', 'commit': commit, 'inputs': lock}, indent=2) + '\n')
