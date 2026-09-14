"""Build a separate no-contraction kernel for numeric diagnosis, never replace default."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
source = ROOT / 'vendor/doomfly/doom/kernel.cpp'
out = ROOT / 'research' / ('libneural-no-contract.dylib' if sys.platform == 'darwin' else 'libneural-no-contract.so')
out.parent.mkdir(parents=True, exist_ok=True)
flags = ['-O3', '-std=c++17', '-shared', '-fPIC', '-ffp-contract=off']
subprocess.run(['clang++', *flags, str(source), '-o', str(out)], check=True)
record = {'kernel_source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
          'binary_sha256': hashlib.sha256(out.read_bytes()).hexdigest(),
          'compile_flags': flags, 'diagnostic_only': True,
          'compiler': subprocess.check_output(['clang++', '--version'], text=True).strip()}
out.with_suffix(out.suffix + '.json').write_text(json.dumps(record, indent=2) + '\n')
print(out)
