"""Hamkaraneh Windows launcher.

Starts the LAN server, writes a log file, shows a small status window and
reports startup errors with a message box (a windowed exe has no console).
Log file: C:\\ProgramData\\Hamkaraneh\\server.log
"""
import os, sys, time, threading, socket, webbrowser, logging, traceback, secrets
from logging.handlers import RotatingFileHandler
from pathlib import Path
import urllib.request

FROZEN = getattr(sys, 'frozen', False)
HOME = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent
DATA_HOME = (Path(os.environ.get('PROGRAMDATA', str(HOME))) / 'Hamkaraneh') if FROZEN else HOME
PORT = int(os.environ.get('HAMKARANEH_PORT', '8000'))
NO_BROWSER = os.environ.get('HAMKARANEH_NO_BROWSER') == '1'
NO_GUI = os.environ.get('HAMKARANEH_NO_GUI') == '1'
APP_TITLE = 'همکارانه'


def _setup_logging():
    for base in (DATA_HOME, Path(os.environ.get('TEMP', '.')) / 'Hamkaraneh'):
        try:
            base.mkdir(parents=True, exist_ok=True)
            path = base / 'server.log'
            handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=2, encoding='utf-8')
            handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(name)s: %(message)s'))
            logging.basicConfig(level=logging.INFO, handlers=[handler])
            # A windowed exe has no stdout/stderr; give libraries a real stream.
            if sys.stdout is None or sys.stderr is None:
                stream = open(path, 'a', encoding='utf-8', buffering=1)
                if sys.stdout is None: sys.stdout = stream
                if sys.stderr is None: sys.stderr = stream
            return path
        except Exception:
            continue
    return None


LOG_PATH = _setup_logging()
log = logging.getLogger('hamkaraneh')


def alert(message):
    log.error(message)
    if NO_GUI:
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, message, APP_TITLE, 0x10)
    except Exception:
        pass


def lan_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('10.255.255.255', 1))
            return s.getsockname()[0]
    except Exception:
        return '127.0.0.1'


def port_in_use(port):
    with socket.socket() as s:
        s.settimeout(0.7)
        return s.connect_ex(('127.0.0.1', port)) == 0


def is_hamkaraneh(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/login', timeout=3) as r:
            return 'شبکه شرکت' in r.read().decode('utf-8', 'ignore')
    except Exception:
        return False


def open_browser():
    if not NO_BROWSER:
        webbrowser.open(f'http://127.0.0.1:{PORT}')


def prepare_environment():
    DATA_HOME.mkdir(parents=True, exist_ok=True)
    os.environ['COMPANY_SHARE_HOME'] = str(DATA_HOME)
    os.environ['COMPANY_SHARE_DB'] = str(DATA_HOME / 'company.db')
    os.environ.setdefault('SHARE_DATA', str(DATA_HOME / 'shared_files'))
    # Persist the session secret so logins survive a server restart.
    secret_file = DATA_HOME / '.session_secret'
    try:
        secret = secret_file.read_text(encoding='utf-8').strip() if secret_file.exists() else ''
        if len(secret) < 32:
            secret = secrets.token_urlsafe(48)
            secret_file.write_text(secret, encoding='utf-8')
    except Exception:
        secret = secrets.token_urlsafe(48)
    os.environ.setdefault('SESSION_SECRET', secret)
    sys.path.insert(0, str(HOME))


def run():
    log.info('Starting Hamkaraneh (frozen=%s, home=%s, data=%s)', FROZEN, HOME, DATA_HOME)

    if port_in_use(PORT):
        if is_hamkaraneh(PORT):
            log.info('Server already running; opening browser')
            open_browser()
        else:
            alert(f'پورت {PORT} توسط برنامهٔ دیگری استفاده می‌شود و همکارانه نمی‌تواند اجرا شود.\n'
                  f'آن برنامه را ببندید و دوباره تلاش کنید.\n\nPort {PORT} is already in use.')
        return

    try:
        prepare_environment()
        import uvicorn
        import main as app_module
    except Exception:
        err = traceback.format_exc()
        log.error('Startup import failed:\n%s', err)
        alert('اجرای همکارانه ناموفق بود.\nشرح خطا در این فایل ذخیره شده است:\n%s\n\n%s' % (LOG_PATH, err.strip().splitlines()[-1]))
        return

    config = uvicorn.Config(app_module.app, host='0.0.0.0', port=PORT,
                            log_level='info', log_config=None, access_log=False)
    server = uvicorn.Server(config)

    def serve():
        try:
            server.run()
        except BaseException:
            log.error('Server crashed:\n%s', traceback.format_exc())

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()

    for _ in range(100):  # wait up to ~20 s
        if server.started or not thread.is_alive():
            break
        time.sleep(0.2)
    if not server.started:
        alert(f'سرور همکارانه شروع نشد.\nجزئیات در فایل زیر است:\n{LOG_PATH}')
        return

    log.info('Server is listening on port %s', PORT)
    threading.Timer(0.5, open_browser).start()

    if not NO_GUI:
        try:
            show_window(server)
            return
        except Exception:
            log.warning('Status window unavailable, running without it:\n%s', traceback.format_exc())
    thread.join()


def show_window(server):
    import tkinter as tk
    root = tk.Tk()
    root.title('همکارانه — سرور')
    root.geometry('400x210')
    root.resizable(False, False)
    font = ('Tahoma', 10)
    tk.Label(root, text='سرور همکارانه در حال اجراست', font=('Tahoma', 12, 'bold'), fg='#067647').pack(pady=(16, 6))
    tk.Label(root, text='آدرس برای کاربران شبکه:', font=font).pack()
    url = f'http://{lan_ip()}:{PORT}'
    entry = tk.Entry(root, font=('Consolas', 11), justify='center', width=28)
    entry.insert(0, url)
    entry.configure(state='readonly')
    entry.pack(pady=4)
    tk.Label(root, text='این پنجره را نبندید؛ با ضربدر کوچک می‌شود و سرور روشن می‌ماند.', font=('Tahoma', 8), fg='#667085').pack(pady=2)
    row = tk.Frame(root); row.pack(pady=12)

    def stop():
        server.should_exit = True
        root.destroy()

    tk.Button(row, text='باز کردن صفحه', font=font, width=14, command=open_browser).pack(side='left', padx=6)
    tk.Button(row, text='توقف و خروج', font=font, width=14, command=stop).pack(side='left', padx=6)
    root.protocol('WM_DELETE_WINDOW', root.iconify)
    root.mainloop()
    server.should_exit = True
    time.sleep(0.5)


if __name__ == '__main__':
    try:
        run()
    except Exception:
        err = traceback.format_exc()
        log.error('Fatal:\n%s', err)
        alert('خطای غیرمنتظره:\n' + err.strip().splitlines()[-1])
