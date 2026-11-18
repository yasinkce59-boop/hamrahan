import os, sqlite3, hashlib, secrets, shutil, html
from pathlib import Path
from datetime import datetime
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

BASE=Path(os.environ.get('COMPANY_SHARE_HOME', Path(__file__).parent))
DATA=Path(os.getenv('SHARE_DATA', BASE/'shared_files')); DATA.mkdir(parents=True,exist_ok=True)
DB=Path(os.environ.get('COMPANY_SHARE_DB', BASE/'company.db'))
app=FastAPI(title='شبکه شرکت')
app.add_middleware(SessionMiddleware, secret_key=os.getenv('SESSION_SECRET', secrets.token_hex(32)), https_only=False, same_site='lax')

def db():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c
def setup():
 c=db(); c.executescript('''CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, salt TEXT, digest TEXT, role TEXT DEFAULT 'user');
 CREATE TABLE IF NOT EXISTS files(id INTEGER PRIMARY KEY, name TEXT, disk TEXT, size INTEGER, uploader TEXT, updated TEXT);
 CREATE TABLE IF NOT EXISTS messages(id INTEGER PRIMARY KEY, sender TEXT, body TEXT, sent TEXT);
 CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, username TEXT, action TEXT, item TEXT, at TEXT, detail TEXT);''')
 if not c.execute('SELECT 1 FROM users').fetchone():
  salt=secrets.token_hex(16); digest=hashlib.pbkdf2_hmac('sha256',b'ChangeMe123!',salt.encode(),180000).hex()
  c.execute('INSERT INTO users(username,salt,digest,role) VALUES(?,?,?,?)',('admin',salt,digest,'admin'))
 c.commit(); c.close()
setup()
def now(): return datetime.now().astimezone().isoformat(timespec='seconds')
def audit(user,action,item='',detail=''):
 c=db(); c.execute('INSERT INTO audit(username,action,item,at,detail) VALUES(?,?,?,?,?)',(user,action,item,now(),detail));c.commit();c.close()
def current(req): return req.session.get('user')
def need(req):
 u=current(req)
 if not u: raise HTTPException(401,'ابتدا وارد شوید')
 return u
def page(req):
 if not current(req): return RedirectResponse('/login',303)
 return HTMLResponse(HTML.replace('%%USER%%',html.escape(current(req))).replace('%%ROLE%%',html.escape(req.session.get('role','user'))))

@app.get('/',response_class=HTMLResponse)
def home(req:Request): return page(req)
@app.get('/login',response_class=HTMLResponse)
def loginpage(): return HTMLResponse(LOGIN.replace('%%ERROR%%',''))
@app.post('/login')
def login(req:Request, username:str=Form(...), password:str=Form(...)):
 c=db(); row=c.execute('SELECT * FROM users WHERE username=?',(username,)).fetchone();c.close()
 if not row or hashlib.pbkdf2_hmac('sha256',password.encode(),row['salt'].encode(),180000).hex()!=row['digest']:
  return HTMLResponse(LOGIN.replace('%%ERROR%%','نام کاربری یا رمز عبور اشتباه است'),401)
 req.session['user']=username;req.session['role']=row['role'];audit(username,'ورود');return RedirectResponse('/',303)
@app.get('/logout')
def logout(req:Request):
 if current(req): audit(current(req),'خروج')
 req.session.clear();return RedirectResponse('/login',303)
@app.post('/api/users')
def create_user(req:Request, username:str=Form(...), password:str=Form(...), role:str=Form('user')):
 admin=need(req)
 if req.session.get('role')!='admin': raise HTTPException(403)
 if not username.strip() or len(password)<10: raise HTTPException(400,'نام کاربری لازم است و رمز باید حداقل ۱۰ نویسه باشد')
 salt=secrets.token_hex(16); digest=hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),180000).hex()
 c=db()
 try: c.execute('INSERT INTO users(username,salt,digest,role) VALUES(?,?,?,?)',(username.strip(),salt,digest,'admin' if role=='admin' else 'user'));c.commit()
 except sqlite3.IntegrityError: raise HTTPException(409,'این نام کاربری وجود دارد')
 finally:c.close()
 audit(admin,'ساخت کاربر',username);return RedirectResponse('/',303)
@app.post('/api/password')
def change_password(req:Request, old_password:str=Form(...), new_password:str=Form(...)):
 u=need(req)
 if len(new_password)<10: raise HTTPException(400,'رمز جدید باید حداقل ۱۰ نویسه باشد')
 c=db(); row=c.execute('SELECT * FROM users WHERE username=?',(u,)).fetchone()
 if not row or hashlib.pbkdf2_hmac('sha256',old_password.encode(),row['salt'].encode(),180000).hex()!=row['digest']:
  c.close(); raise HTTPException(400,'رمز فعلی صحیح نیست')
 salt=secrets.token_hex(16); digest=hashlib.pbkdf2_hmac('sha256',new_password.encode(),salt.encode(),180000).hex()
 c.execute('UPDATE users SET salt=?,digest=? WHERE username=?',(salt,digest,u));c.commit();c.close();audit(u,'تغییر رمز');return RedirectResponse('/',303)
@app.get('/api/files')
def files(req:Request):
 need(req); c=db(); rows=[dict(x) for x in c.execute('SELECT id,name,size,uploader,updated FROM files ORDER BY name COLLATE NOCASE')];c.close();return rows
@app.post('/api/files')
def upload(req:Request, file:UploadFile=File(...)):
 u=need(req); name=Path(file.filename or 'file').name
 if not name or name in ('.','..'): raise HTTPException(400,'نام فایل نامعتبر است')
 # Replace existing file with same name; retain stable record and audit it.
 c=db(); old=c.execute('SELECT * FROM files WHERE name=?',(name,)).fetchone()
 disk=old['disk'] if old else secrets.token_hex(16)+'_'+name
 dest=DATA/disk; tmp=DATA/(disk+'.tmp')
 with tmp.open('wb') as out: shutil.copyfileobj(file.file,out)
 size=tmp.stat().st_size;tmp.replace(dest)
 if old: c.execute('UPDATE files SET size=?,uploader=?,updated=? WHERE id=?',(size,u,now(),old['id']))
 else: c.execute('INSERT INTO files(name,disk,size,uploader,updated) VALUES(?,?,?,?,?)',(name,disk,size,u,now()))
 c.commit();c.close();audit(u,'بارگذاری/ویرایش',name,f'{size} bytes');return RedirectResponse('/',303)
@app.get('/api/files/{fid}')
def download(req:Request,fid:int):
 u=need(req);c=db();r=c.execute('SELECT * FROM files WHERE id=?',(fid,)).fetchone();c.close()
 if not r or not (DATA/r['disk']).exists(): raise HTTPException(404,'فایل پیدا نشد')
 audit(u,'بازکردن/دریافت',r['name']);return FileResponse(DATA/r['disk'],filename=r['name'])
@app.delete('/api/files/{fid}')
def delete(req:Request,fid:int):
 u=need(req);c=db();r=c.execute('SELECT * FROM files WHERE id=?',(fid,)).fetchone()
 if not r: c.close(); raise HTTPException(404)
 (DATA/r['disk']).unlink(missing_ok=True);c.execute('DELETE FROM files WHERE id=?',(fid,));c.commit();c.close();audit(u,'حذف',r['name']);return {'ok':True}
@app.get('/api/messages')
def messages(req:Request,after:int=0):
 need(req);c=db();rows=[dict(x) for x in c.execute('SELECT * FROM messages WHERE id>? ORDER BY id LIMIT 300',(after,))];c.close();return rows
@app.post('/api/messages')
def send(req:Request, body:str=Form(...)):
 u=need(req);body=body.strip()
 if not body or len(body)>4000: raise HTTPException(400)
 c=db();c.execute('INSERT INTO messages(sender,body,sent) VALUES(?,?,?)',(u,body,now()));c.commit();c.close();audit(u,'ارسال پیام');return {'ok':True}
@app.get('/api/audit')
def audits(req:Request):
 need(req)
 if req.session.get('role')!='admin': raise HTTPException(403)
 c=db(); rows=[dict(x) for x in c.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 1000')];c.close();return rows

LOGIN='''<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>ورود | شبکه شرکت</title><style>body{font:16px Tahoma;background:#eef2f7;display:grid;place-items:center;height:100vh;margin:0}.box{background:white;padding:32px;border-radius:18px;width:min(360px,85vw);box-shadow:0 12px 45px #152b4518}input,button{font:inherit;padding:12px;border-radius:9px;border:1px solid #ccd4df;width:100%;box-sizing:border-box;margin:8px 0}button{background:#175cd3;color:white;border:0;cursor:pointer}small{color:#667085}.err{color:#b42318}</style><div class="box"><h2>شبکه شرکت</h2><p>برای ورود، اطلاعات حساب خود را وارد کنید.</p><form method="post"><input name="username" placeholder="نام کاربری" required><input name="password" type="password" placeholder="رمز عبور" required><button>ورود</button></form><div class="err">%%ERROR%%</div><small>حساب اولیه: admin / ChangeMe123! — پس از نصب حتماً تغییر دهید.</small></div></html>'''
HTML='''<!doctype html><html lang="fa" dir="rtl"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>شبکه شرکت</title><style>
:root{--ink:#142033;--muted:#667085;--blue:#175cd3;--line:#e4e9f0}*{box-sizing:border-box}body{margin:0;background:#f5f7fb;color:var(--ink);font:15px Tahoma,Arial}.top{background:#101e32;color:#fff;padding:18px 4vw;display:flex;justify-content:space-between;align-items:center}.top a{color:#c6d8ff}.wrap{max-width:1180px;margin:28px auto;padding:0 18px}.grid{display:grid;grid-template-columns:1.4fr 1fr;gap:18px}.card{background:#fff;border:1px solid var(--line);border-radius:16px;padding:20px;box-shadow:0 4px 16px #132b4510;margin-bottom:18px}h1{font-size:21px;margin:0}h2{font-size:17px;margin:0 0 14px}.sub{color:#bdc9da;font-size:13px;margin-top:6px}.row{display:flex;gap:8px}input,button{font:inherit;padding:10px;border:1px solid #cfd7e3;border-radius:9px}input{min-width:0;flex:1}button{background:var(--blue);border:0;color:white;cursor:pointer}button.danger{background:#c43228;padding:7px 10px}button.gray{background:#eef2f7;color:#344054}table{width:100%;border-collapse:collapse}th,td{text-align:right;padding:11px 7px;border-bottom:1px solid var(--line);font-size:13px}th{color:var(--muted)}.file{color:#175cd3;text-decoration:none}.meta{color:var(--muted);font-size:12px}.chat{height:350px;overflow:auto;background:#f8fafc;border-radius:10px;padding:12px;margin-bottom:10px}.msg{padding:8px 10px;margin:7px 0;background:white;border:1px solid var(--line);border-radius:10px}.msg b{color:var(--blue)}.msg small{color:var(--muted);margin-right:8px}.admin{display:none}.admin.on{display:block}.foot{text-align:center;color:var(--muted);font-size:12px;padding:18px}.hide{display:none}@media(max-width:760px){.grid{grid-template-columns:1fr}.top{padding:15px}.card{padding:15px}}
</style><header class="top"><div><h1>شبکه همکاری شرکت</h1><div class="sub">پیام‌رسان داخلی · فایل‌های مشترک · ثبت فعالیت</div></div><div>%%USER%% · <a href="#password">تغییر رمز</a> · <a href="/logout">خروج</a></div></header><main class="wrap"><div class="grid"><section><div class="card"><h2>📁 فضای فایل مشترک</h2><form action="/api/files" method="post" enctype="multipart/form-data" class="row"><input type="file" name="file" required><button>بارگذاری / جایگزینی</button></form><p class="meta">فایل هم‌نام جایگزین نسخه قبلی می‌شود؛ برای همکاری هم‌زمان، نسخه پشتیبان جداگانه بارگذاری کنید.</p><div style="overflow:auto"><table><thead><tr><th>نام فایل</th><th>اندازه</th><th>ثبت‌کننده</th><th>عملیات</th></tr></thead><tbody id="files"></tbody></table></div></div><div class="card admin" id="auditbox"><h2>🧾 سابقه فعالیت (مدیر)</h2><div style="max-height:340px;overflow:auto"><table><thead><tr><th>زمان</th><th>کاربر</th><th>عملیات</th><th>مورد</th></tr></thead><tbody id="audit"></tbody></table></div></div></section><section><div class="card"><h2>💬 گفت‌وگوی شبکه</h2><div class="chat" id="chat"></div><form id="send" class="row"><input id="text" placeholder="پیام خود را بنویسید…" maxlength="4000" autocomplete="off"><button>ارسال</button></form></div><div class="card admin" id="userbox"><h2>＋ ساخت حساب کاربری</h2><form action="/api/users" method="post"><input name="username" placeholder="نام کاربری" required><input name="password" type="password" placeholder="رمز (حداقل ۱۰ نویسه)" minlength="10" required><select name="role"><option value="user">کاربر عادی</option><option value="admin">مدیر</option></select><button>ساخت حساب</button></form></div></section></div><div class="card" id="password"><h2>🔐 تغییر رمز عبور</h2><form action="/api/password" method="post" class="row"><input type="password" name="old_password" placeholder="رمز فعلی" required><input type="password" name="new_password" placeholder="رمز جدید (حداقل ۱۰ نویسه)" minlength="10" required><button>تغییر رمز</button></form></div><div class="foot">توسعه‌دهنده: یاسین تقوی · ایمیل: Yasintaghavi@gmail.com</div></main><script>
const isAdmin='%%ROLE%%'==='admin';if(isAdmin){document.querySelectorAll('.admin').forEach(x=>x.classList.add('on'))}const esc=s=>String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
async function loadFiles(){let r=await fetch('/api/files');if(r.status===401)return location='/login';let a=await r.json();document.querySelector('#files').innerHTML=a.map(f=>`<tr><td><a class="file" target="_blank" href="/api/files/${f.id}" onclick="auditOpen(${f.id})">${esc(f.name)}</a><div class="meta">${esc(f.updated)}</div></td><td>${(f.size/1024).toFixed(1)} KB</td><td>${esc(f.uploader)}</td><td><button class="danger" onclick="delFile(${f.id})">حذف</button></td></tr>`).join('')||'<tr><td colspan="4">هنوز فایلی بارگذاری نشده است.</td></tr>'}
async function auditOpen(id){}async function delFile(id){if(confirm('فایل حذف شود؟')){await fetch('/api/files/'+id,{method:'DELETE'});loadFiles()}}
let last=0;async function loadChat(){let a=await(await fetch('/api/messages?after='+last)).json();for(const m of a){last=m.id;let d=document.createElement('div');d.className='msg';d.innerHTML=`<b>${esc(m.sender)}</b><small>${esc(m.sent)}</small><div>${esc(m.body)}</div>`;chat.appendChild(d)}chat.scrollTop=chat.scrollHeight}
document.querySelector('#send').onsubmit=async e=>{e.preventDefault();let inp=document.querySelector('#text');if(!inp.value.trim())return;let fd=new FormData();fd.append('body',inp.value);await fetch('/api/messages',{method:'POST',body:fd});inp.value='';loadChat()};
async function loadAudit(){if(!isAdmin)return;let a=await(await fetch('/api/audit')).json();document.querySelector('#audit').innerHTML=a.map(x=>`<tr><td>${esc(x.at)}</td><td>${esc(x.username)}</td><td>${esc(x.action)}</td><td>${esc(x.item)}</td></tr>`).join('')}
loadFiles();loadChat();loadAudit();setInterval(loadChat,2500);setInterval(loadFiles,10000);setInterval(loadAudit,12000);
</script></html>'''
