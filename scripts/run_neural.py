"""Load local .env assignments without shell execution, then use MaleCNS."""
import os
from pathlib import Path
import shlex
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
env_file = ROOT / '.env'
if env_file.exists():
    for number, line in enumerate(env_file.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:].strip()
        if '=' not in line:
            raise SystemExit('Invalid .env assignment at line ' + str(number))
        key, value = line.split('=', 1)
        key = key.strip()
        parts = shlex.split(value, comments=True)
        if not key.isidentifier() or len(parts) > 1:
            raise SystemExit('Invalid .env assignment at line ' + str(number))
        if key.startswith(('LLM_', 'OPENAI_', 'DEEPSEEK_', 'NEURAL_', 'FLYCODER_')) or key in {'MAX_STEPS', 'MAX_ATTEMPTS', 'TEST_TIMEOUT'}:
            os.environ[key] = parts[0] if parts else ''
arguments = sys.argv[1:]
if not arguments or arguments[0] not in {'demo', 'run'}:
    arguments.insert(0, 'demo')
sys.argv = ['flycoder', *arguments, '--connectome', 'malecns']
from flycoder.__main__ import main
raise SystemExit(main())
