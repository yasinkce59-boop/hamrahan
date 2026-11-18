"""Windows server launcher: starts the LAN service and opens its local control page."""
import os, sys, time, threading, socket, webbrowser
from pathlib import Path
import uvicorn

home = Path(sys.executable).resolve().parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parent
# Keep all writable company data in the shared machine data folder, not Program Files.
data_home = Path(os.environ.get('PROGRAMDATA', home)) / 'Hamkaraneh' if getattr(sys, 'frozen', False) else home
os.environ['COMPANY_SHARE_HOME'] = str(data_home)
os.environ['COMPANY_SHARE_DB'] = str(data_home / 'company.db')
os.environ.setdefault('SHARE_DATA', str(data_home / 'shared_files'))
data_home.mkdir(parents=True, exist_ok=True)
os.environ.setdefault('SESSION_SECRET', __import__('secrets').token_urlsafe(48))
sys.path.insert(0, str(home))
import main

def open_page():
    time.sleep(1.5)
    webbrowser.open('http://127.0.0.1:8000')

if __name__ == '__main__':
    threading.Thread(target=open_page, daemon=True).start()
    # Windowed PyInstaller builds have stdout=None; disable Uvicorn's default
    # formatter, which calls sys.stdout.isatty() during startup.
    uvicorn.run(main.app, host='0.0.0.0', port=8000, log_level='warning', log_config=None, access_log=False)
