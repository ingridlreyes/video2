"""Portable source bundle; explicit allowlist excludes secrets, venv and generated data."""
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
output = root / 'AI_Process_Foundry_Flex_Ready.zip'
files = {p for pattern in ('*.py', '*.md', '*.txt') for p in root.glob(pattern)}
files.update(root / name for name in ('.env.example', '.gitignore', '.funcignore', 'host.json',
                                     'local.settings.example.json', 'example_steps.json'))
for folder in ('engine', 'scripts', 'tests', 'docs', 'examples', 'diagrams', 'assets'):
    files.update(p for p in (root / folder).rglob('*') if p.is_file()
                 and '__pycache__' not in p.parts and p.suffix != '.pyc')
with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(files):
        archive.write(path, path.relative_to(root))
with zipfile.ZipFile(output) as archive:
    assert archive.testzip() is None
    assert not any(Path(n).name in ('.env', 'local.settings.json') or '.venv' in Path(n).parts
                   for n in archive.namelist())
    print(f'{output.name}: {len(archive.namelist())} archivos; {output.stat().st_size:,} bytes; sin credenciales')
