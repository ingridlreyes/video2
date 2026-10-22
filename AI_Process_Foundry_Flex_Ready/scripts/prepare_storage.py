"""Initialize only the three contemplated containers in the configured existing account."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engine.storage import BlobStore
from azure.core.exceptions import ResourceExistsError

if __name__ == '__main__':
    store = BlobStore()
    for name in ('raw', 'analysis', 'delivery'):
        try:
            store.client.create_container(name)
            print(name + ': creado privado')
        except ResourceExistsError:
            print(name + ': ya existe')
