"""Snapshot JSON auditável da base SQLite em branch GitHub separada, sem cache."""
import base64,json,os,urllib.request,urllib.error
from pathlib import Path
import monitor as m
TABLES=('candidates','jobs','aliases','deliveries','sent','meta','runs')

def dump(c):
 tables={t:[dict(r) for r in c.execute('SELECT * FROM '+t+' ORDER BY 1')] for t in TABLES}
 # Textos já coletados são reobtidos; não versionar HTML volumoso a cada hora.
 for row in tables['candidates']:row['document']=None
 return {'schema':1,'tables':tables}
def restore(c,payload):
 if payload.get('schema')!=1 or set(payload.get('tables',{}))!=set(TABLES):raise ValueError('Snapshot ausente/corrompido; abortando sem resetar histórico')
 with c:
  for table in TABLES:
   cols=[r[1] for r in c.execute('PRAGMA table_info('+table+')')]
   rows=payload['tables'][table]
   for r in rows:
    if set(r)!=set(cols):raise ValueError('Schema incompatível no histórico')
   c.execute('DELETE FROM '+table)
   for r in rows:c.execute('INSERT INTO '+table+' VALUES('+','.join('?' for _ in cols)+')',[r[k] for k in cols])
 if c.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Histórico inválido')

class StateStore:
 def __init__(self,repo=None,token=None):
  self.repo=repo or os.environ['GITHUB_REPOSITORY'];self.token=token or os.environ['GH_STATE_TOKEN'];self.sha=None;self.tree=None;self.ready=False
 def api(self,path,method='GET',data=None):
  req=urllib.request.Request('https://api.github.com/repos/'+self.repo+path,method=method,headers={'Authorization':'Bearer '+self.token,'Accept':'application/vnd.github+json','User-Agent':'vagas-ti-monitor','Content-Type':'application/json'},data=json.dumps(data).encode() if data is not None else None)
  try:
   with urllib.request.urlopen(req,timeout=30) as r:return json.load(r)
  except urllib.error.HTTPError as e:
   # Nunca logar headers, corpo da resposta ou token.
   if e.code==404:raise FileNotFoundError('Recurso GitHub não encontrado') from None
   raise RuntimeError('GitHub HTTP '+str(e.code)) from None
 def load(self,c,seed=None):
  try:ref=self.api('/git/ref/heads/monitor-state')
  except FileNotFoundError:
   if seed is None:raise ValueError('Branch monitor-state ausente. Execute bootstrap manual; não resetar automaticamente.')
   restore(c,json.loads(Path(seed).read_text()));self.ready=True;self.save(c);return
  self.sha=ref['object']['sha'];commit=self.api('/git/commits/'+self.sha);self.tree=commit['tree']['sha']
  tree=self.api('/git/trees/'+self.tree)
  entry=next((x for x in tree['tree'] if x['path']=='state.json'),None)
  if not entry:raise ValueError('state.json ausente na branch existente; restaure o histórico')
  blob=self.api('/git/blobs/'+entry['sha']);restore(c,json.loads(base64.b64decode(blob['content'])));self.ready=True
 def save(self,c):
  if not self.ready:raise ValueError('Estado não carregado')
  c.commit();content=json.dumps(dump(c),ensure_ascii=False,sort_keys=True,indent=2)
  if len(content.encode())>20_000_000:raise ValueError('Histórico excede 20MB; manutenção necessária, sem apagar sent')
  blob=self.api('/git/blobs','POST',{'encoding':'utf-8','content':content})
  tree=self.api('/git/trees','POST',{'tree':[{'path':'state.json','mode':'100644','type':'blob','sha':blob['sha']}]})
  commit=self.api('/git/commits','POST',{'message':'Persist monitor state '+m.now(),'tree':tree['sha'],'parents':[self.sha] if self.sha else []})
  if self.sha:self.api('/git/refs/heads/monitor-state','PATCH',{'sha':commit['sha'],'force':False})
  else:self.api('/git/refs','POST',{'ref':'refs/heads/monitor-state','sha':commit['sha']})
  self.sha=commit['sha'];self.tree=tree['sha']
