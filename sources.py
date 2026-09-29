"""Listagens oficiais complementam pesquisa RSS, sem login ou contorno de bloqueios."""
import html,json,re,urllib.parse
import monitor as m

def remember(c,url,source):
 u=m.canonical(url)
 c.execute('INSERT OR IGNORE INTO candidates VALUES(?,?,?,?,NULL,NULL)',(u,source,m.now(),m.now()))

def boards(c,config):
 found=set();failures=0
 for url in config['boards']:
  try:
   raw,final=m.get(url)
   if re.search(r'cf-chl-|verify you are human|just a moment\.\.\.',raw,re.I):raise ValueError('Fonte protegida')
   # Apenas links observados na listagem oficial; não enumerar IDs.
   for link in re.findall(r'href=[\"\x27]([^\"\x27]+)',raw):
    u=urllib.parse.urljoin(final,html.unescape(link))
    if re.search(r'/jobs/\d+|/job/[^/?]+',u) and urllib.parse.urlsplit(u).netloc==urllib.parse.urlsplit(final).netloc:
     found.add(m.canonical(u));remember(c,u,'Listagem oficial '+url)
   # Algumas páginas Gupy incluem jobId em estado público da listagem.
   if urllib.parse.urlsplit(final).netloc.endswith('.gupy.io'):
    for jid in re.findall(r'"jobId"\s*:\s*(\d+)',html.unescape(raw)):
     u=urllib.parse.urljoin(final,'/jobs/'+jid);found.add(u);remember(c,u,'Listagem oficial '+url)
  except Exception as e:failures+=1;m.logging.warning('Listagem indisponível: %s (%s)',url,type(e).__name__)
 c.commit();return {'board_urls':len(found),'board_failures':failures}

def collect(c,config,query_limit=16,page_limit=40):
 report=m.discover(c,config,query_limit);report.update(boards(c,config));report.update(fetched=0,fetch_errors=0,eligible=0,rejected=0,pending=0)
 from analyzer import extract
 # Round robin durável para não deixar anúncios antigos bloquearem a fila.
 rows=list(c.execute("SELECT url FROM candidates WHERE length(url)-length(replace(url,'/','')) >= 3 ORDER BY CASE WHEN document IS NULL THEN 0 ELSE 1 END,last_seen,url"))
 for row in rows[:page_limit]:
  url=row['url']
  try:
   doc=m.fetch(c,url);j=extract(doc,config)
   m.ingest(c,[j],config);report['fetched']+=1;report[j['status']]+=1
  except Exception as e:
   report['fetch_errors']+=1;m.logging.warning('Anúncio não processado (%s)',type(e).__name__)
   # Análise velha não pode ser enviada depois de erro na análise atual.
   c.execute("UPDATE jobs SET status='pending',reason='Revalidação falhou' WHERE id IN (SELECT job_id FROM aliases WHERE alias=?)",('url:'+m.canonical(url),));c.commit()
 return report
