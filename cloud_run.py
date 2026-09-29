#!/usr/bin/env python3
"""Entrada única para o runner efêmero: restore -> collect -> checkpoint -> email."""
import argparse,json,logging,os,sys
from pathlib import Path
import monitor as m
from state_store import StateStore
from sources import collect

def log_setup():
 (m.ROOT/'logs').mkdir(exist_ok=True)
 logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s',handlers=[logging.FileHandler(m.ROOT/'logs/cloud.log'),logging.StreamHandler()])

def test_email(c,store):
 # Idempotente: reexecução manual não manda outro teste já aceito.
 r=c.execute("SELECT status FROM deliveries WHERE id='smtp-initial-test'").fetchone()
 if r:
  if r[0]=='accepted':return {'test_email':'previously_accepted'}
  raise ValueError('Teste anterior incerto; conferir Enviados antes de repetir')
 c.execute("INSERT INTO deliveries VALUES('smtp-initial-test',?,'sending','[]',NULL,NULL)",(m.now(),));c.commit();store.save(c)
 try:mid=m.smtp_send('Teste — monitor de vagas no GitHub Actions','Teste solicitado do monitor na nuvem. Alertas regulares serão enviados somente para vagas novas ou atualizadas.')
 except Exception as e:
  c.execute("UPDATE deliveries SET status='uncertain',error=? WHERE id='smtp-initial-test'",(type(e).__name__,));c.commit();store.save(c);raise
 c.execute("UPDATE deliveries SET status='accepted',message_id=? WHERE id='smtp-initial-test'",(mid,));c.commit();store.save(c)
 return {'test_email':'smtp_accepted'}

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--mode',choices=['dry-run','test-email','live'],default='dry-run');ap.add_argument('--bootstrap',action='store_true');ap.add_argument('--local-test',action='store_true');ap.add_argument('--queries',type=int,default=16);ap.add_argument('--pages',type=int,default=40);a=ap.parse_args()
 if a.local_test and a.mode!='dry-run':raise SystemExit('local-test só permite dry-run')
 if a.mode!='dry-run':
  # Preflight antes de qualquer tentativa SMTP; valores nunca são impressos.
  if not os.getenv('SMTP_USER') or not os.getenv('SMTP_PASSWORD'):raise SystemExit('Crie SMTP_USER e SMTP_PASSWORD em Actions Secrets')
 os.environ['EMAIL_ENABLED']='true' if a.mode=='live' else 'false'
 log_setup();c=m.connect();store=None;rid=None;result={};failed=False
 try:
  if not a.local_test:
   store=StateStore();store.load(c,m.ROOT/'seed_history.json' if a.bootstrap else None)
  rid=c.execute('INSERT INTO runs(started,command,status) VALUES(?,?,?)',(m.now(),'cloud:'+a.mode,'running')).lastrowid;c.commit()
  config=json.loads((m.ROOT/'config.json').read_text());result=collect(c,config,a.queries,a.pages)
  if result['fetched']==0:raise ValueError('Nenhum anúncio pôde ser analisado; fontes indisponíveis ou fila vazia')
  if store:store.save(c)
  if a.mode=='test-email':result.update(test_email(c,store))
  else:result.update(m.dispatch(c,config,a.mode=='live',checkpoint=(lambda:store.save(c)) if store else None))
  c.execute('UPDATE runs SET status=?,finished=?,detail=? WHERE id=?',('ok',m.now(),json.dumps(result,ensure_ascii=False),rid));c.commit()
 except Exception as e:
  failed=True;logging.error('Execução interrompida: %s',type(e).__name__)
  result={'error_type':type(e).__name__,'action':'Consulte fontes, persistência ou Secrets; nenhum segredo registrado.'}
  if rid:c.execute('UPDATE runs SET status=?,finished=?,detail=? WHERE id=?',('error',m.now(),json.dumps(result),rid));c.commit()
 finally:
  if store and store.ready:
   try:store.save(c)
   except Exception as e:failed=True;logging.error('Persistência final falhou: %s; branch anterior preservada',type(e).__name__)
  # Sumário numérico: não contém destinatário, mensagem SMTP ou conteúdo remoto.
  safe={k:v for k,v in result.items() if k not in ['urls','query_texts','message_id']}
  print(json.dumps(safe,ensure_ascii=False,indent=2))
  if os.getenv('GITHUB_STEP_SUMMARY'):
   with open(os.environ['GITHUB_STEP_SUMMARY'],'a') as f:f.write('## Monitor de vagas\n\n```json\n'+json.dumps(safe,ensure_ascii=False,indent=2)+'\n```\n')
  c.close()
 return int(failed)
if __name__=='__main__':sys.exit(main())
