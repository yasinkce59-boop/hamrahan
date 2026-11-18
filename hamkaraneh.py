# -*- coding: utf-8 -*-
"""Hamkaraneh (همکارانه) - dead-simple chat + file sharing between computers on one network.

No server, no accounts, no IP addresses: every computer that runs the app finds
the others automatically (UDP broadcast) and talks to them directly (TCP).
Only the Python standard library is used.
"""
import os, sys, re, json, time, uuid, queue, socket, hashlib, logging, tempfile, threading, traceback, subprocess
from pathlib import Path
from logging.handlers import RotatingFileHandler

APP_TITLE = 'همکارانه'
DISCOVERY_PORT = 48555      # UDP: "I am here" announcements
LOCK_PORT = 48557           # local only: allows a single window per computer
BEACON_SECONDS = 2.0
PEER_TIMEOUT = 9.0
CHUNK = 256 * 1024
MAX_HEADER = 65536
MAX_TEXT = 5000

log = logging.getLogger('hamkaraneh')


# ----------------------------------------------------------------- helpers
def safe_name(name):
    """Make a received file name harmless (no folders, no forbidden characters)."""
    name = os.path.basename(str(name).replace('\\', '/'))
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name).strip(' .')
    stem = name.split('.')[0].upper()
    if stem in {'CON', 'PRN', 'AUX', 'NUL'} or re.fullmatch(r'(COM|LPT)[1-9]', stem or ''):
        name = '_' + name
    return name[:150] or 'file'


def unique_path(folder, name):
    p = Path(folder) / name
    if not p.exists():
        return p
    stem, suffix, i = p.stem, p.suffix, 1
    while True:
        q = p.with_name(f'{stem} ({i}){suffix}')
        if not q.exists():
            return q
        i += 1


def local_ips():
    ips = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ips.add(info[4][0])
    except Exception:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('10.255.255.255', 1))
            ips.add(s.getsockname()[0])
    except Exception:
        pass
    return sorted(i for i in ips if not i.startswith(('127.', '169.254.', '0.')))


def human_size(n):
    for unit in ('B', 'KB', 'MB', 'GB'):
        if n < 1024 or unit == 'GB':
            return f'{n:.0f} {unit}' if unit == 'B' else f'{n:.1f} {unit}'
        n /= 1024


# -------------------------------------------------------------------- core
class Node:
    """Finds other computers and exchanges messages/files with them."""

    def __init__(self, name, inbox, events, discovery_port=DISCOVERY_PORT, extra_targets=()):
        self.id = uuid.uuid4().hex
        self.name = name
        self.inbox = Path(inbox)
        self.events = events
        self.discovery_port = discovery_port
        self.extra_targets = list(extra_targets)   # for tests: extra (ip, port) beacon targets
        self.peers = {}
        self.lock = threading.Lock()
        self.stopping = threading.Event()
        self.port = 0
        self.udp = None
        self.server = None
        self._snapshot = None

    # ---- lifecycle
    def start(self):
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind(('', 0))
        self.server.listen(32)
        self.port = self.server.getsockname()[1]
        threading.Thread(target=self._accept_loop, daemon=True).start()
        try:
            self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.udp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.udp.bind(('', self.discovery_port))
            self.udp.settimeout(1.0)
            threading.Thread(target=self._listen_loop, daemon=True).start()
        except OSError as e:
            log.error('cannot listen for other computers: %s', e)
            self.events.put(('warn', 'نمی‌توانم صدای کامپیوترهای دیگر را بشنوم. شاید برنامهٔ دیگری مانع شده است.'))
        threading.Thread(target=self._beacon_loop, daemon=True).start()

    def stop(self):
        self.stopping.set()
        for s in (self.server, self.udp):
            try:
                if s: s.close()
            except Exception:
                pass

    # ---- discovery
    def peer_list(self):
        with self.lock:
            return sorted((dict(id=k, **v) for k, v in self.peers.items()), key=lambda p: p['name'].lower())

    def _notify_peers(self):
        snap = tuple((p['id'], p['name']) for p in self.peer_list())
        if snap != self._snapshot:
            self._snapshot = snap
            self.events.put(('peers', self.peer_list()))

    def _expire(self):
        now = time.time()
        with self.lock:
            for k in [k for k, v in self.peers.items() if now - v['seen'] > PEER_TIMEOUT]:
                del self.peers[k]
        self._notify_peers()

    def _listen_loop(self):
        while not self.stopping.is_set():
            try:
                data, addr = self.udp.recvfrom(2048)
            except socket.timeout:
                self._expire(); continue
            except OSError:
                break
            try:
                m = json.loads(data.decode('utf-8'))
                if m.get('app') != 'hamkaraneh' or m.get('id') == self.id:
                    continue
                with self.lock:
                    self.peers[m['id']] = {'name': str(m.get('name', '?'))[:40], 'ip': addr[0],
                                           'port': int(m['port']), 'seen': time.time()}
                self._notify_peers()
            except Exception:
                continue

    def _beacon_loop(self):
        while not self.stopping.is_set():
            data = json.dumps({'app': 'hamkaraneh', 'v': 1, 'id': self.id, 'name': self.name,
                               'port': self.port}, ensure_ascii=False).encode('utf-8')
            for ip in local_ips():
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                        s.bind((ip, 0))
                        for target in ('255.255.255.255', ip.rsplit('.', 1)[0] + '.255'):
                            try: s.sendto(data, (target, self.discovery_port))
                            except OSError: pass
                except OSError:
                    pass
            for target in self.extra_targets:
                try:
                    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                        s.sendto(data, target)
                except OSError:
                    pass
            self._expire()
            self.stopping.wait(BEACON_SECONDS)

    # ---- receiving
    def _accept_loop(self):
        while not self.stopping.is_set():
            try:
                conn, addr = self.server.accept()
            except OSError:
                break
            threading.Thread(target=self._handle, args=(conn, addr), daemon=True).start()

    def _handle(self, conn, addr):
        tmp = None
        try:
            conn.settimeout(30)
            f = conn.makefile('rb')
            h = json.loads(f.readline(MAX_HEADER).decode('utf-8'))
            sender = str(h.get('from', addr[0]))[:40]
            if h.get('type') == 'msg':
                self.events.put(('msg', sender, str(h.get('text', ''))[:MAX_TEXT], time.time()))
            elif h.get('type') == 'file':
                size = int(h['size'])
                if size < 0:
                    raise ValueError('bad size')
                self.inbox.mkdir(parents=True, exist_ok=True)
                dest = unique_path(self.inbox, safe_name(h.get('name', 'file')))
                tmp = dest.with_name(dest.name + '.part')
                left = size
                with open(tmp, 'wb') as out:
                    while left > 0:
                        chunk = f.read(min(CHUNK, left))
                        if not chunk:
                            raise ConnectionError('connection closed early')
                        out.write(chunk); left -= len(chunk)
                os.replace(tmp, dest); tmp = None
                self.events.put(('file', sender, str(dest), size))
            else:
                return
            conn.sendall(b'OK\n')
        except Exception as e:
            log.warning('receive failed from %s: %s', addr, e)
            self.events.put(('warn', 'دریافت از یک کامپیوتر ناموفق بود.'))
        finally:
            try:
                if tmp and Path(tmp).exists(): Path(tmp).unlink()
            except Exception:
                pass
            conn.close()

    # ---- sending
    def _targets(self, to=None):
        peers = self.peer_list()
        return [p for p in peers if to is None or p['id'] == to]

    def _open(self, peer):
        s = socket.create_connection((peer['ip'], peer['port']), timeout=8)
        s.settimeout(60)
        return s

    @staticmethod
    def _header(sock, header):
        sock.sendall((json.dumps(header, ensure_ascii=False) + '\n').encode('utf-8'))

    @staticmethod
    def _ack(sock):
        return sock.recv(16).startswith(b'OK')

    def send_text(self, text, to=None):
        results = []
        for p in self._targets(to):
            ok = False
            try:
                with self._open(p) as s:
                    self._header(s, {'type': 'msg', 'from': self.name, 'text': text})
                    ok = self._ack(s)
            except Exception as e:
                log.warning('send text to %s failed: %s', p['name'], e)
            results.append((p['name'], ok))
        return results

    def send_file(self, path, to=None, progress=None):
        path = Path(path)
        size = path.stat().st_size
        results = []
        for p in self._targets(to):
            ok = False
            try:
                with self._open(p) as s, open(path, 'rb') as fh:
                    self._header(s, {'type': 'file', 'from': self.name, 'name': path.name, 'size': size})
                    sent, last = 0, -1
                    while True:
                        chunk = fh.read(CHUNK)
                        if not chunk: break
                        s.sendall(chunk); sent += len(chunk)
                        pct = int(sent * 100 / size) if size else 100
                        if progress and pct != last:
                            progress(p['name'], pct); last = pct
                    ok = self._ack(s)
            except Exception as e:
                log.warning('send file to %s failed: %s', p['name'], e)
            results.append((p['name'], ok))
        return results


# --------------------------------------------------------------------- gui
def open_in_explorer(path):
    path = Path(path)
    try:
        if os.name == 'nt':
            if path.is_file():
                subprocess.Popen(['explorer', '/select,', str(path)])
            else:
                os.startfile(str(path))
    except Exception as e:
        log.warning('cannot open %s: %s', path, e)


class App:
    def __init__(self, node, events, config_dir):
        import tkinter as tk
        from tkinter import ttk, filedialog, simpledialog
        self.tk, self.ttk, self.filedialog, self.simpledialog = tk, ttk, filedialog, simpledialog
        self.node, self.events, self.config_dir = node, events, Path(config_dir)
        self.started = time.time()
        self.peers = []
        self.peer_ids = [None]
        self.unread = False
        self.link_count = 0

        root = self.root = tk.Tk()
        root.title(APP_TITLE)
        root.geometry('680x620')
        root.minsize(540, 480)
        root.configure(bg='#f2f4f8')
        font = ('Tahoma', 11)

        top = tk.Frame(root, bg='#ffffff', highlightbackground='#d0d5dd', highlightthickness=1)
        top.pack(fill='x', padx=10, pady=(10, 6))
        self.status = tk.Label(top, text='', font=('Tahoma', 14, 'bold'), bg='#ffffff', pady=6)
        self.status.pack(fill='x')
        self.hint = tk.Label(top, text='', font=('Tahoma', 10), bg='#ffffff', fg='#475467',
                             wraplength=620, justify='center', pady=4)
        self.hint.pack(fill='x')

        mid = tk.Frame(root, bg='#f2f4f8')
        mid.pack(fill='both', expand=True, padx=10)
        self.chat = tk.Text(mid, wrap='word', font=font, state='disabled', bg='#ffffff', relief='flat',
                            highlightbackground='#d0d5dd', highlightthickness=1, padx=10, pady=8)
        sb = tk.Scrollbar(mid, command=self.chat.yview)
        self.chat.configure(yscrollcommand=sb.set)
        sb.pack(side='left', fill='y')
        self.chat.pack(side='right', fill='both', expand=True)
        self.chat.tag_configure('who_me', foreground='#175cd3', font=('Tahoma', 9, 'bold'), justify='right', spacing1=8)
        self.chat.tag_configure('who_other', foreground='#067647', font=('Tahoma', 9, 'bold'), justify='right', spacing1=8)
        self.chat.tag_configure('text', justify='right')
        self.chat.tag_configure('sys', foreground='#667085', font=('Tahoma', 9), justify='center', spacing1=6)
        self.chat.tag_configure('link', foreground='#175cd3', underline=True, font=('Tahoma', 10, 'bold'), justify='right')

        self.info = tk.Label(root, text='', font=('Tahoma', 9), bg='#f2f4f8', fg='#475467')
        self.info.pack(fill='x', padx=10)

        row1 = tk.Frame(root, bg='#f2f4f8'); row1.pack(fill='x', padx=10, pady=(4, 2))
        tk.Button(row1, text='ارسال', font=('Tahoma', 11, 'bold'), bg='#175cd3', fg='white', width=10,
                  relief='flat', command=self.send_text).pack(side='left', padx=(0, 6))
        self.entry = tk.Entry(row1, font=font, justify='right', relief='solid', bd=1)
        self.entry.pack(side='left', fill='x', expand=True, ipady=6)
        self.entry.bind('<Return>', lambda e: self.send_text())
        self.entry.focus_set()

        row2 = tk.Frame(root, bg='#f2f4f8'); row2.pack(fill='x', padx=10, pady=(4, 10))
        tk.Button(row2, text='ارسال فایل', font=font, width=12, command=self.send_files).pack(side='right', padx=3)
        tk.Button(row2, text='فایل‌های دریافتی', font=font, width=14,
                  command=lambda: open_in_explorer(self.node.inbox)).pack(side='right', padx=3)
        tk.Button(row2, text='تغییر نام من', font=('Tahoma', 9), command=self.rename).pack(side='left', padx=3)
        self.to_box = ttk.Combobox(row2, state='readonly', width=18, justify='right', font=('Tahoma', 10))
        self.to_box.pack(side='right', padx=(14, 3))
        tk.Label(row2, text='به:', font=('Tahoma', 10), bg='#f2f4f8').pack(side='right')
        self.refresh_peers([])

        root.bind('<FocusIn>', self.on_focus)
        root.report_callback_exception = self.on_error
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.add_system(f'نام شما در شبکه: {self.node.name}')
        self.poll()

    # ---- ui helpers
    def append(self, who_tag, who, body, link=None):
        c = self.chat
        c.configure(state='normal')
        if who:
            c.insert('end', f'{who}  {time.strftime("%H:%M")}\n', who_tag)
        if link:
            self.link_count += 1
            tag = f'link{self.link_count}'
            c.insert('end', body + '\n', ('link', tag))
            c.tag_bind(tag, '<Button-1>', lambda e, p=link: open_in_explorer(p))
            c.tag_bind(tag, '<Enter>', lambda e: c.configure(cursor='hand2'))
            c.tag_bind(tag, '<Leave>', lambda e: c.configure(cursor=''))
        else:
            c.insert('end', body + '\n', 'text' if who else who_tag)
        c.configure(state='disabled')
        c.see('end')

    def add_system(self, text):
        self.append('sys', None, text)

    def on_focus(self, _=None):
        if self.unread:
            self.unread = False
            self.root.title(APP_TITLE)

    def alert_new(self):
        try: self.root.bell()
        except Exception: pass
        if self.root.focus_displayof() is None:
            self.unread = True
            self.root.title('● پیام جدید - ' + APP_TITLE)

    def on_error(self, exc, val, tb):
        log.error('UI error:\n%s', ''.join(traceback.format_exception(exc, val, tb)))

    def refresh_peers(self, peers):
        self.peers = peers
        current = self.peer_ids[self.to_box.current()] if self.to_box.current() >= 0 and self.to_box.current() < len(self.peer_ids) else None
        self.peer_ids = [None] + [p['id'] for p in peers]
        self.to_box['values'] = ['همه'] + [p['name'] for p in peers]
        self.to_box.current(self.peer_ids.index(current) if current in self.peer_ids else 0)
        self.update_status()

    def update_status(self):
        if self.peers:
            names = '، '.join(p['name'] for p in self.peers)
            self.status.configure(text='وصل شد: ' + names, fg='#067647')
            self.hint.configure(text='حالا می‌توانید پیام بنویسید یا فایل بفرستید.')
        else:
            self.status.configure(text='در حال پیدا کردن کامپیوتر دیگر…', fg='#b54708')
            text = 'برنامهٔ همکارانه را روی کامپیوتر دوم هم باز کنید. هر دو باید به یک وای‌فای یا یک شبکه وصل باشند.'
            if time.time() - self.started > 20:
                text += '\nاگر هنوز پیدا نشد: اگر ویندوز پرسید «Allow access»، روی «Allow» بزنید و بعد هر دو برنامه را ببندید و دوباره باز کنید.'
            self.hint.configure(text=text)

    def target(self):
        i = self.to_box.current()
        return self.peer_ids[i] if 0 <= i < len(self.peer_ids) else None

    # ---- actions
    def send_text(self):
        text = self.entry.get().strip()
        if not text:
            return
        if not self.peers:
            self.add_system('هنوز کامپیوتری پیدا نشده؛ پیام ارسال نشد.')
            return
        self.entry.delete(0, 'end')
        to = self.target()

        def work():
            res = self.node.send_text(text, to)
            self.events.put(('sent_text', text, res))
        threading.Thread(target=work, daemon=True).start()

    def send_files(self):
        if not self.peers:
            self.add_system('هنوز کامپیوتری پیدا نشده؛ فایل ارسال نشد.')
            return
        paths = self.filedialog.askopenfilenames(title='فایل‌هایی که می‌خواهید بفرستید را انتخاب کنید')
        to = self.target()
        for path in paths:
            def work(path=path):
                name = Path(path).name
                res = self.node.send_file(path, to, progress=lambda who, pct: self.events.put(('progress', name, who, pct)))
                self.events.put(('sent_file', name, res))
            threading.Thread(target=work, daemon=True).start()

    def rename(self):
        new = self.simpledialog.askstring('تغییر نام', 'نام شما در شبکه چه باشد؟', initialvalue=self.node.name, parent=self.root)
        if new and new.strip():
            self.node.name = new.strip()[:40]
            try:
                self.config_dir.mkdir(parents=True, exist_ok=True)
                (self.config_dir / 'name.txt').write_text(self.node.name, encoding='utf-8')
            except Exception:
                pass
            self.add_system(f'نام شما اکنون «{self.node.name}» است.')

    def close(self):
        self.node.stop()
        self.root.destroy()

    # ---- event loop
    def poll(self):
        try:
            while True:
                ev = self.events.get_nowait()
                kind = ev[0]
                if kind == 'peers':
                    old = {p['id'] for p in self.peers}
                    self.refresh_peers(ev[1])
                    for p in ev[1]:
                        if p['id'] not in old:
                            self.add_system(f'«{p["name"]}» وصل شد.')
                    for gone in old - {p['id'] for p in ev[1]}:
                        self.add_system('یک کامپیوتر قطع شد.')
                elif kind == 'msg':
                    self.append('who_other', ev[1], ev[2]); self.alert_new()
                elif kind == 'file':
                    self.append('who_other', ev[1], f'فایل «{Path(ev[2]).name}» ({human_size(ev[3])}) دریافت شد - برای دیدن کلیک کنید', link=ev[2])
                    self.alert_new()
                elif kind == 'sent_text':
                    ok = [n for n, good in ev[2] if good]
                    bad = [n for n, good in ev[2] if not good]
                    if ok:
                        self.append('who_me', 'من', ev[1])
                    if bad:
                        self.add_system('ارسال به این کامپیوتر ناموفق بود: ' + '، '.join(bad))
                elif kind == 'sent_file':
                    self.info.configure(text='')
                    ok = [n for n, good in ev[2] if good]
                    bad = [n for n, good in ev[2] if not good]
                    if ok:
                        self.add_system(f'فایل «{ev[1]}» برای {"، ".join(ok)} ارسال شد.')
                    if bad:
                        self.add_system(f'فایل «{ev[1]}» به {"، ".join(bad)} نرسید.')
                elif kind == 'progress':
                    self.info.configure(text=f'در حال ارسال «{ev[1]}» به {ev[2]}: {ev[3]}٪' if ev[3] < 100 else '')
                elif kind == 'warn':
                    self.add_system(ev[1])
        except queue.Empty:
            pass
        if not self.peers:
            self.update_status()
        self.root.after(150, self.poll)

    def run(self):
        self.root.mainloop()


# -------------------------------------------------------------------- main
def message_box(text, icon=0x10):
    if os.environ.get('HAMKARANEH_NO_GUI') == '1':
        return
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, text, APP_TITLE, icon)
    except Exception:
        pass


def setup_logging():
    base = Path(os.environ.get('LOCALAPPDATA') or Path.home()) / 'Hamkaraneh'
    try:
        base.mkdir(parents=True, exist_ok=True)
        path = base / 'app.log'
        handler = RotatingFileHandler(path, maxBytes=500_000, backupCount=1, encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'))
        logging.basicConfig(level=logging.INFO, handlers=[handler])
        if sys.stdout is None: sys.stdout = open(path, 'a', encoding='utf-8')
        if sys.stderr is None: sys.stderr = open(path, 'a', encoding='utf-8')
        return base, path
    except Exception:
        return base, None


def wait_event(q, kind, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        try:
            ev = q.get(timeout=max(0.1, end - time.time()))
        except queue.Empty:
            break
        if ev[0] == kind:
            return ev
    raise AssertionError(f'no "{kind}" event received')


def selftest(outfile):
    """Runs two nodes in this process and checks discovery, chat and file transfer."""
    lines, ok = [], True
    try:
        import tkinter  # noqa: F401  (make sure the packaged app contains it)
        tmp = Path(tempfile.mkdtemp())
        qa, qb = queue.Queue(), queue.Queue()
        a = Node('A', tmp / 'a', qa, discovery_port=48601, extra_targets=[('127.0.0.1', 48602)])
        b = Node('B', tmp / 'b', qb, discovery_port=48602, extra_targets=[('127.0.0.1', 48601)])
        a.start(); b.start()
        t0 = time.time()
        while time.time() - t0 < 15 and not (a.peer_list() and b.peer_list()):
            time.sleep(0.2)
        assert a.peer_list() and b.peer_list(), 'computers did not find each other'
        lines.append('discovery ok')
        assert a.send_text('سلام', None) == [('B', True)], 'send_text failed'
        ev = wait_event(qb, 'msg')
        assert ev[2] == 'سلام', 'wrong message text'
        lines.append('chat ok')
        src = tmp / 'big.bin'
        src.write_bytes(os.urandom(3_000_000))
        assert a.send_file(src, None) == [('B', True)], 'send_file failed'
        got = wait_event(qb, 'file')
        assert hashlib.sha256(Path(got[2]).read_bytes()).hexdigest() == hashlib.sha256(src.read_bytes()).hexdigest(), 'file differs'
        lines.append('file ok')
        assert safe_name('..\\..\\evil.txt') == 'evil.txt' and safe_name('a/b/c.exe') == 'c.exe' and safe_name('CON') == '_CON'
        lines.append('safe names ok')
        a.stop(); b.stop()
    except Exception:
        ok = False
        lines.append(traceback.format_exc())
    Path(outfile).write_text(('PASS\n' if ok else 'FAIL\n') + '\n'.join(lines), encoding='utf-8')
    return 0 if ok else 1


def main():
    if len(sys.argv) >= 3 and sys.argv[1] == '--selftest':
        sys.exit(selftest(sys.argv[2]))

    base, _ = setup_logging()
    log.info('starting')

    # one window per computer
    lock = socket.socket()
    try:
        lock.bind(('127.0.0.1', LOCK_PORT))
    except OSError:
        message_box('همکارانه از قبل باز است. آن را در نوار پایین ویندوز پیدا کنید.', 0x40)
        return

    try:  # lets the installer close the app when updating
        import ctypes
        _mutex = ctypes.windll.kernel32.CreateMutexW(None, False, 'HamkaranehAppMutex')  # noqa: F841
    except Exception:
        pass

    name_file = base / 'name.txt'
    try:
        name = name_file.read_text(encoding='utf-8').strip()
    except Exception:
        name = ''
    name = name or socket.gethostname()

    docs = Path.home() / 'Documents'
    inbox = (docs if docs.exists() else Path.home()) / 'Hamkaraneh-Received'

    events = queue.Queue()
    try:
        node = Node(name, inbox, events)
        node.start()
        App(node, events, base).run()
    except Exception:
        err = traceback.format_exc()
        log.error('fatal:\n%s', err)
        message_box('همکارانه اجرا نشد.\n\n' + err.strip().splitlines()[-1] + f'\n\nگزارش: {base / "app.log"}')


if __name__ == '__main__':
    main()
