#!/usr/bin/env python3
"""Coleta pública, armazenamento auditável e envio. Análise independente em analyzer.py."""
import argparse, datetime as dt, email.message, email.utils, fcntl, hashlib, html, json, logging, os, re, smtplib, sqlite3, ssl, time, unicodedata, urllib.parse, urllib.request, xml.etree.ElementTree as ET
from pathlib import Path
from logging.handlers import RotatingFileHandler
ROOT=Path(os.environ.get('MONITOR_ROOT',Path(__file__).resolve().parent)).resolve()
UNKNOWN='Não informado / precisa confirmar'
FIELDS={'company':'Empresa','title':'Cargo','location':'Localização','modality':'Modalidade','area':'Área principal','salary':'Bolsa/salário','benefits':'Benefícios','hours':'Carga horária','course':'Curso exigido','semester':'Semestre/período exigido','graduation':'Previsão de formatura exigida','activities':'Principais atividades','requirements':'Principais requisitos','desirable':'Conhecimentos desejáveis','deadline':'Prazo de inscrição','published':'Data da publicação','url':'Link oficial da vaga','source':'Fonte','found_at':'Data em que a automação encontrou a vaga','compatibility':'Compatibilidade com meu perfil'}
def now(): return dt.datetime.now(dt.timezone.utc).isoformat()
def norm(s): return ''.join(c for c in unicodedata.normalize('NFKD',str(s).lower()) if not unicodedata.combining(c))
def canonical(u):
 p=urllib.parse.urlsplit(u); q=urllib.parse.parse_qsl(p.query)
 q=[(k,v) for k,v in q if not k.lower().startswith('utm_') and k not in ['jobBoardSource','source','sourceCode']]
 return urllib.parse.urlunsplit((p.scheme,p.netloc.lower(),p.path.rstrip('/'),urllib.parse.urlencode(sorted(q)),''))
def digest(x): return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def plain(s): return re.sub(r'\s+',' ',html.unescape(re.sub('<[^>]+>',' ',s))).strip()
def get(url):
 if urllib.parse.urlsplit(url).scheme!='https': raise ValueError('Somente HTTPS público')
 for attempt in range(3):
  try:
   with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'PersonalJobMonitor/1.0 (public job research)'}),timeout=25) as r:
    raw=r.read(3_000_001)
    if len(raw)>3_000_000: raise ValueError('Página excede limite')
    return raw.decode('utf-8',errors='replace'),r.geturl()
  except urllib.error.HTTPError as e:
   if e.code not in [500,502,503,504] or attempt==2: raise
  except (TimeoutError,urllib.error.URLError):
   if attempt==2: raise
  time.sleep(2**attempt)
def connect(root=ROOT):
 (root/'data').mkdir(exist_ok=True)
 c=sqlite3.connect(root/'data/jobs.sqlite3'); c.row_factory=sqlite3.Row
 c.executescript('''CREATE TABLE IF NOT EXISTS candidates(url TEXT PRIMARY KEY,source TEXT,first_seen TEXT,last_seen TEXT,document TEXT,error TEXT);
 CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,fingerprint TEXT,record TEXT,status TEXT,reason TEXT,first_seen TEXT,last_seen TEXT);
 CREATE TABLE IF NOT EXISTS aliases(alias TEXT PRIMARY KEY,job_id TEXT);
 CREATE TABLE IF NOT EXISTS deliveries(id TEXT PRIMARY KEY,created TEXT,status TEXT,job_versions TEXT,message_id TEXT,error TEXT);
 CREATE TABLE IF NOT EXISTS sent(job_id TEXT,fingerprint TEXT,delivery_id TEXT,sent_at TEXT,PRIMARY KEY(job_id,fingerprint));
 CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT);
 CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY,started TEXT,finished TEXT,command TEXT,status TEXT,detail TEXT);''')
 return c
def fetch(c,url,source='Página oficial'):
 url=canonical(url); stamp=now()
 try:
  raw,final=get(url)
  if re.search(r'verify you are human|just a moment\.\.\.|cf-chl-|access denied',raw,re.I): raise ValueError('Proteção detectada; não contornar')
  jobs=[]
  def walk(x):
   if isinstance(x,list):
    for v in x: walk(v)
   elif isinstance(x,dict):
    if x.get('@type')=='JobPosting': jobs.append(x)
    if '@graph' in x: walk(x['@graph'])
  for s in re.findall(r'<script[^>]*type=[\"\x27]application/ld\+json[\"\x27][^>]*>(.*?)</script>',raw,re.S|re.I):
   try: walk(json.loads(html.unescape(s)))
   except ValueError: pass
  text=plain(re.sub(r'<(script|style)[^>]*>.*?</\1>',' ',raw,flags=re.S|re.I))
  doc={'url':canonical(final),'fetched_at':stamp,'job_postings':jobs,'text':text,'application_links':re.findall(r'href=[\"\x27]([^\"\x27]+)[\"\x27][^>]*>\s*(?:<[^>]+>\s*)*(?:Candidatar|Apply|Ir para candidatura)',raw,re.I)}
  c.execute('INSERT INTO candidates VALUES(?,?,?,?,?,NULL) ON CONFLICT(url) DO UPDATE SET last_seen=excluded.last_seen,document=excluded.document,error=NULL',(url,source,stamp,stamp,json.dumps(doc,ensure_ascii=False)));c.commit();return doc
 except Exception as e:
  c.execute('INSERT INTO candidates VALUES(?,?,?,?,NULL,?) ON CONFLICT(url) DO UPDATE SET last_seen=excluded.last_seen,error=excluded.error',(url,source,stamp,stamp,type(e).__name__));c.commit();logging.warning('Falha na fonte %s: %s',url,type(e).__name__);raise

def discover(c,config,limit):
 row=c.execute("SELECT value FROM meta WHERE key='query_cursor'").fetchone();start=int(row[0]) if row else 0
 n=min(limit or len(config['queries']),len(config['queries']))
 queries=[config['queries'][(start+i)%len(config['queries'])] for i in range(n)]; found=set(); errors=0
 for q in queries:
  try:
   raw,_=get('https://www.bing.com/search?format=rss&q='+urllib.parse.quote(q))
   for item in ET.fromstring(raw).findall('.//item'):
    u=item.findtext('link',''); host=urllib.parse.urlsplit(u).netloc
    if not any(host==d or host.endswith('.'+d) for d in config['domains']): continue
    u=canonical(u);found.add(u)
    c.execute('INSERT OR IGNORE INTO candidates VALUES(?,?,?,?,NULL,NULL)',(u,'Bing RSS: '+q,now(),now()))
   c.commit()
  except Exception as e: errors+=1;logging.warning('Busca falhou: %s',type(e).__name__)
  time.sleep(.5)
 c.execute("INSERT INTO meta VALUES('query_cursor',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str((start+n)%len(config['queries'])),));c.commit()
 return {'queries':len(queries),'query_texts':queries,'errors':errors,'urls':sorted(found),'note':'RSS complementar; listagens oficiais e análise local executadas por sources.py.'}

def validate(j,config):
 required=['company','title','location','url','status','reason']
 if any(not j.get(k) for k in required): raise ValueError('Registro incompleto')
 if j['status'] not in ['eligible','rejected','pending']: raise ValueError('Status inválido')
 if j['status']!='eligible': return
 for k in FIELDS: j.setdefault(k,UNKNOWN)
 ev=j.get('evidence',{})
 for k in ['open','location','level','area','course','semester','requirements']:
  if not ev.get(k): raise ValueError('Falta evidência: '+k)
 if not j.get('official') or not j.get('application_url'): raise ValueError('Link oficial/candidatura obrigatório')
 verified=dt.datetime.fromisoformat(j['verified_at'])
 if verified.tzinfo is None or not 0 <= (dt.datetime.now(dt.timezone.utc)-verified).total_seconds()<86400: raise ValueError('Verificação deve ter menos de 24h')
 if j.get('closed') or j.get('degree_required') or j.get('experience_years',0)>1: raise ValueError('Requisito incompatível')
 if re.search(r'\b(pleno|senior|especialista|coordenador|lider|gerente|manager|lead)\b',norm(j['title'])): raise ValueError('Senioridade incompatível')
 if j.get('semester_min',0)>config['semester'] or j.get('semester_max',99)<config['semester']: raise ValueError('Semestre incompatível')
 if j.get('remote'):
  if not j.get('brazil_explicit'): raise ValueError('Remoto sem elegibilidade explícita para Brasil')
 elif not any(norm(x) in norm(j['location']) for x in config['cities']): raise ValueError('Localidade incompatível')
 if j['area'] not in config['area_order']: raise ValueError('Área não permitida')
 if j.get('deadline_iso') and dt.date.fromisoformat(j['deadline_iso'])<dt.date.today(): raise ValueError('Prazo encerrado')
 if j.get('kind') not in ['internship','entry']: raise ValueError('Nível não avaliado')
 if not j.get('description_reviewed'): raise ValueError('Descrição não analisada')

def ingest(c,records,config):
 for j in records:
  validate(j,config);j['url']=canonical(j['url'])
  if j['status']=='eligible':
   doc=c.execute('SELECT document,error FROM candidates WHERE url=?',(j['url'],)).fetchone()
   if not doc or doc['error'] or not doc['document']:raise ValueError('Coleta oficial necessária antes da análise')
   text=norm(json.loads(doc['document'])['text'])
   if re.search(r'candidaturas encerradas|inscricoes encerradas|vaga (encerrada|finalizada)',text):raise ValueError('Página informa encerramento')
   if norm(j['evidence']['open']) not in text:raise ValueError('Evidência de abertura ausente da página')
  aliases=['url:'+j['url']]
  if all(not norm(j[k]).startswith('nao informado') for k in ['company','title','location']):
   aliases.append('tuple:'+digest([norm(j['company']),norm(j['title']),norm(j['location'])]))
  aliases+=['url:'+canonical(u) for u in j.get('alternate_urls',[])]
  if j.get('job_id'): aliases+=['id:'+norm(j['company'])+':'+str(j['job_id'])]
  ids={r[0] for a in aliases for r in c.execute('SELECT job_id FROM aliases WHERE alias=?',(a,))}
  if len(ids)>1: raise ValueError('Identidades conflitantes; revisar antes de enviar')
  jid=next(iter(ids),digest(aliases[-1])); old=c.execute('SELECT first_seen FROM jobs WHERE id=?',(jid,)).fetchone()
  first=old[0] if old else now();j['found_at']=first
  # Datas de coleta e fontes não são mudanças significativas.
  fp=digest({k:norm(j.get(k,UNKNOWN)) for k in ['title','location','modality','area','salary','benefits','hours','course','semester','graduation','activities','requirements','desirable','deadline']})
  c.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET fingerprint=excluded.fingerprint,record=excluded.record,status=excluded.status,reason=excluded.reason,last_seen=excluded.last_seen',(jid,fp,json.dumps(j,ensure_ascii=False),j['status'],j['reason'],first,now()))
  for a in aliases: c.execute('INSERT OR IGNORE INTO aliases VALUES(?,?)',(a,jid))
 c.commit()
def pending(c,config):
 result=[]
 for r in c.execute("SELECT * FROM jobs WHERE status='eligible'"):
  if c.execute('SELECT 1 FROM sent WHERE job_id=? AND fingerprint=?',(r['id'],r['fingerprint'])).fetchone():continue
  j=json.loads(r['record'])
  try:validate(j,config)
  except ValueError:continue
  updated=c.execute('SELECT 1 FROM sent WHERE job_id=?',(r['id'],)).fetchone() is not None
  result.append((r['id'],r['fingerprint'],j,updated))
 return sorted(result,key=lambda x:(x[2]['kind']!='internship',config['area_order'].index(x[2]['area'])))
def render(rows):
 chunks=[]
 for _,_,j,updated in rows:
  chunks.append(('Vaga atualizada\n' if updated else '')+'\n'.join(f'{label}: {j.get(k,UNKNOWN)}' for k,label in FIELDS.items())+'\nLink para candidatura: '+j.get('application_url',j['url']))
 return '\n\n'+'\n\n'+'\n\n'.join(chunks)
def env_load():
 if os.getenv('GITHUB_ACTIONS')=='true': return
 p=ROOT/'.env'
 if p.exists():
  for line in p.read_text().splitlines():
   if line.strip() and not line.lstrip().startswith('#'):
    k,v=line.split('=',1);os.environ.setdefault(k.strip(),v.strip().strip('\"\x27'))
def smtp_send(subject,body):
 env_load()
 os.environ.setdefault('SMTP_HOST','smtp.gmail.com')
 os.environ.setdefault('MAIL_FROM',os.environ.get('SMTP_USER',''))
 os.environ.setdefault('MAIL_TO',os.environ.get('SMTP_USER',''))
 for k in ['SMTP_HOST','SMTP_USER','SMTP_PASSWORD','MAIL_FROM','MAIL_TO']:
  if not os.getenv(k) or os.getenv(k).startswith('PREENCHA'):raise ValueError('Configure '+k+' em GitHub Actions Secrets ou no ambiente')
 msg=email.message.EmailMessage();msg['From']=os.environ['MAIL_FROM'];msg['To']=os.environ['MAIL_TO'];msg['Subject']=subject;msg['Message-ID']=email.utils.make_msgid();msg['Date']=email.utils.formatdate(localtime=True);msg.set_content(body)
 port=int(os.getenv('SMTP_PORT','465'));ctx=ssl.create_default_context()
 if port==465: server=smtplib.SMTP_SSL(os.environ['SMTP_HOST'],port,timeout=30,context=ctx)
 else:
  server=smtplib.SMTP(os.environ['SMTP_HOST'],port,timeout=30);server.ehlo();server.starttls(context=ctx);server.ehlo()
 with server:
  server.login(os.environ['SMTP_USER'],os.environ['SMTP_PASSWORD'])
  refused=server.send_message(msg)
  if refused:raise RuntimeError('Destinatário recusado')
 return msg['Message-ID']
def dispatch(c,config,send=False,checkpoint=None):
 checkpoint=checkpoint or (lambda: None)
 rows=pending(c,config)
 if not rows:return {'new_jobs':0,'sent':False}
 body=render(rows); (ROOT/'data/preview.txt').write_text(body)
 if not send:return {'new_jobs':len(rows),'sent':False,'preview':'data/preview.txt'}
 if c.execute("SELECT 1 FROM deliveries WHERE status IN ('sending','uncertain')").fetchone():raise ValueError('Envio anterior incerto; verificar caixa enviada antes de repetir')
 env_load()
 if os.getenv('EMAIL_ENABLED')!='true':raise ValueError('EMAIL_ENABLED não está true')
 # Revalidação online final impede mandar uma vaga removida após análise.
 for _,_,j,_ in rows:
  d=fetch(c,j['url']); t=norm(d['text'])
  if re.search(r'vaga (encerrada|finalizada)|candidaturas encerradas|inscricoes encerradas|job (is )?(closed|no longer available)',t):raise ValueError('Vaga encerrada na revalidação')
  if d['job_postings']:
   current=d['job_postings'][0]
   if current.get('validThrough','9999')[:10]<dt.date.today().isoformat():raise ValueError('Prazo oficial expirou')
   if j.get('description_hash') and digest(plain(current.get('description','')))!=j['description_hash']:raise ValueError('Descrição mudou; analisar novamente')
  evidence=norm(j['evidence']['open'])
  if evidence not in t:raise ValueError('Evidência de candidatura mudou; analisar novamente')
 did=digest([now(),[(a,b) for a,b,_,_ in rows]])
 c.execute('INSERT INTO deliveries VALUES(?,?,?,?,?,NULL)',(did,now(),'sending',json.dumps([(a,b) for a,b,_,_ in rows]),None));c.commit()
 checkpoint()  # Durável ANTES do SMTP: uma queda nunca causa repetição cega.
 try:mid=smtp_send(f'🚨 Novas vagas de estágio em TI — {len(rows)} vagas encontradas',body)
 except Exception as e:
  c.execute('UPDATE deliveries SET status=?,error=? WHERE id=?',('uncertain',type(e).__name__,did));c.commit();checkpoint();raise
 c.execute('UPDATE deliveries SET status=?,message_id=? WHERE id=?',('accepted',mid,did))
 for a,b,_,_ in rows:c.execute('INSERT INTO sent VALUES(?,?,?,?)',(a,b,did,now()))
 c.commit();checkpoint();return {'new_jobs':len(rows),'sent':True,'smtp_accepted':True,'message_id':mid}
def main():
 (ROOT/'logs').mkdir(exist_ok=True);h=RotatingFileHandler(ROOT/'logs/runs.log',maxBytes=1_000_000,backupCount=5);logging.basicConfig(level=logging.INFO,handlers=[h],format='%(asctime)s %(levelname)s %(message)s')
 ap=argparse.ArgumentParser();ap.add_argument('command',choices=['discover','fetch','ingest','preview','send','test-email','status']);ap.add_argument('--file');ap.add_argument('--url');ap.add_argument('--limit',type=int,default=12);a=ap.parse_args()
 with open(ROOT/'data.lock','w') as lock:
  fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);c=connect();config=json.loads((ROOT/'config.json').read_text());rid=c.execute('INSERT INTO runs(started,command,status) VALUES(?,?,?)',(now(),a.command,'running')).lastrowid;c.commit()
  try:
   if a.command=='discover':out=discover(c,config,a.limit)
   elif a.command=='fetch':out=fetch(c,a.url)
   elif a.command=='ingest':records=json.loads(Path(a.file).read_text());ingest(c,records,config);out={'processed':len(records)}
   elif a.command in ['preview','send']:out=dispatch(c,config,a.command=='send')
   elif a.command=='test-email':out={'smtp_accepted':True,'message_id':smtp_send('Teste — monitor de vagas de TI','Este é o teste único solicitado. Alertas futuros serão enviados somente quando houver vagas novas ou atualizações significativas.')}
   else:out={t:c.execute('SELECT COUNT(*) FROM '+t).fetchone()[0] for t in ['candidates','jobs','sent','deliveries','runs']}
   c.execute('UPDATE runs SET finished=?,status=?,detail=? WHERE id=?',(now(),'ok',json.dumps(out,ensure_ascii=False)[:2000],rid));c.commit();logging.info('%s concluído',a.command);print(json.dumps(out,ensure_ascii=False,indent=2))
  except Exception as e:
   c.execute('UPDATE runs SET finished=?,status=?,detail=? WHERE id=?',(now(),'error',type(e).__name__,rid));c.commit();logging.error('%s: %s',a.command,type(e).__name__);raise SystemExit(str(e) if isinstance(e,ValueError) else type(e).__name__+'; consulte logs')
if __name__=='__main__':main()
