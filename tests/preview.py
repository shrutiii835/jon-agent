"""Isolated UI fixture server. Never submits to any external employer."""
from pathlib import Path
import uvicorn
from jon.app import create_app

app = create_app(Path(__file__).resolve().parent.parent / 'test-results' / 'ui')

if __name__ == '__main__':
    uvicorn.run(app, host='127.0.0.1', port=8766, access_log=False)
