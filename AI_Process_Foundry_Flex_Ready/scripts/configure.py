"""Prepare config on the destination laptop. Never print secrets or overwrite .env."""
import argparse
import json
from pathlib import Path
import shutil
from dotenv import dotenv_values

parser = argparse.ArgumentParser()
parser.add_argument('--sync-functions', action='store_true', help='Copiar .env al local.settings.json privado')
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
for source, target in (('.env.example', '.env'), ('local.settings.example.json', 'local.settings.json')):
    destination = root / target
    if destination.exists():
        print(f'{target}: se conserva el archivo existente')
    else:
        shutil.copyfile(root / source, destination)
        print(f'{target}: creado; completar valores locales')
if args.sync_functions:
    target = root / 'local.settings.json'
    data = json.loads(target.read_text())
    values = {k: v for k, v in dotenv_values(root / '.env').items() if v}
    data['Values'].update(values)
    if values.get('AZURE_STORAGE_CONNECTION_STRING'):
        data['Values']['AzureWebJobsStorage'] = values['AZURE_STORAGE_CONNECTION_STRING']
    target.write_text(json.dumps(data, indent=2), encoding='utf-8')
    print('local.settings.json sincronizado sin mostrar secretos; no publicar este archivo')
