import copy,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import monitor as m
from analyzer import extract
from state_store import StateStore,dump,restore

CONFIG=json.loads((Path(__file__).parent/'config.json').read_text())
def doc(description=None,title='Estágio em TI',city='Belo Horizonte',region='MG'):
 description=description or '<h2>Responsabilidades e atribuições</h2><li>Apoiar monitoramento de servidores Linux, suporte técnico e inventário de ativos de TI.</li><h2>Requisitos e qualificações</h2><p>Cursando Sistemas de Informação a partir do 2º semestre.</p>'
 return {'url':'https://empresa.gupy.io/jobs/123','text':'Candidatar-se '+m.plain(description),'application_links':['/candidates/jobs/123/apply'],'job_postings':[{'title':title,'hiringOrganization':{'name':'Empresa'},'description':description,'employmentType':'INTERN' if 'Estágio' in title else 'FULL_TIME','jobLocation':{'address':{'addressLocality':city,'addressRegion':region,'addressCountry':'Brasil'}}}]}
class RulesTests(unittest.TestCase):
 def test_real_style_intern(self):self.assertEqual(extract(doc(),CONFIG)['status'],'eligible')
 def test_closed_without_jsonld(self):self.assertEqual(extract({'url':doc()['url'],'text':'Candidaturas encerradas','job_postings':[]},CONFIG)['status'],'rejected')
 def test_development_generic_title(self):
  d=doc('<h2>Responsabilidades</h2><p>Desenvolver software web e aplicações mobile.</p><h2>Requisitos</h2><p>Cursando Sistemas de Informação.</p>');self.assertEqual(extract(d,CONFIG)['status'],'rejected')
 def test_governance_corporate(self):
  d=doc('<h2>Responsabilidades</h2><p>Governança corporativa, conselho de administração e sustentabilidade.</p>');self.assertEqual(extract(d,CONFIG)['status'],'pending')
 def test_programming_desirable(self):
  d=doc();d['job_postings'][0]['description']+='<p>Python é um diferencial.</p>';self.assertEqual(extract(d,CONFIG)['status'],'eligible')
 def test_complete_optional(self):
  d=doc();d['job_postings'][0]['description']+='<p>Superior completo ou cursando.</p>';self.assertEqual(extract(d,CONFIG)['status'],'eligible')
 def test_complete_required(self):
  d=doc();d['job_postings'][0]['description']+='<p>Graduação concluída obrigatória.</p>';self.assertEqual(extract(d,CONFIG)['status'],'rejected')
 def test_semester(self):
  d=doc();d['job_postings'][0]['description']=d['job_postings'][0]['description'].replace('2º','5º');self.assertEqual(extract(d,CONFIG)['status'],'rejected')
 def test_outside_city(self):self.assertEqual(extract(doc(city='São Paulo',region='SP'),CONFIG)['status'],'rejected')
 def test_generic_support_remote_not_remote(self):
  d=doc();d['job_postings'][0]['description']+='<p>Suporte remoto aos usuários.</p>';self.assertFalse(extract(d,CONFIG)['remote'])
 def test_international_without_brazil(self):
  d=doc();p=d['job_postings'][0];p['jobLocation']={'address':{'addressCountry':'US'}};p['jobLocationType']='TELECOMMUTE';self.assertEqual(extract(d,CONFIG)['status'],'pending')
 def test_international_brazil_explicit(self):
  d=doc();p=d['job_postings'][0];p['jobLocation']={};p['jobLocationType']='TELECOMMUTE';p['applicantLocationRequirements']={'name':'Brazil'};self.assertEqual(extract(d,CONFIG)['status'],'eligible')
 def test_senior(self):self.assertEqual(extract(doc(title='Analista Sênior'),CONFIG)['status'],'rejected')
 def test_no_apply_link(self):
  d=doc();d['application_links']=[];self.assertEqual(extract(d,CONFIG)['status'],'pending')
 def test_no_course_intern(self):
  d=doc();d['job_postings'][0]['description']=d['job_postings'][0]['description'].split('<h2>Requisitos')[0];self.assertEqual(extract(d,CONFIG)['status'],'pending')
 def test_education_exclusive(self):
  d=doc();d['job_postings'][0]['description']=d['job_postings'][0]['description'].replace('Sistemas de Informação','Engenharia Elétrica');self.assertEqual(extract(d,CONFIG)['status'],'pending')

class MetadataTests(unittest.TestCase):
 def test_location_change_not_reused(self):
  original=extract(doc(),CONFIG)
  changed=extract(doc(city='Contagem'),CONFIG)
  self.assertNotEqual(original['location'],changed['location'])
 def test_deterministic_analysis(self):
  a=extract(doc(),CONFIG);b=extract(doc(),CONFIG)
  for j in [a,b]:j.pop('verified_at')
  self.assertEqual(a,b)

class PersistenceTests(unittest.TestCase):
 def setUp(self):self.temp=tempfile.TemporaryDirectory();self.c=m.connect(Path(self.temp.name))
 def tearDown(self):self.c.close();self.temp.cleanup()
 def test_unknown_records_not_merged(self):
  for url in ['https://example.com/job/a','https://example.com/job/b']:
   m.ingest(self.c,[dict(company='Não informado',title='Não informado',location=m.UNKNOWN,url=url,status='pending',reason='Sem dados')],CONFIG)
  self.assertEqual(self.c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],2)
 def test_round_trip_sent(self):
  self.c.execute('INSERT INTO sent VALUES(?,?,?,?)',('id','hash','delivery',m.now()));self.c.commit();data=dump(self.c);restore(self.c,data);self.assertEqual(self.c.execute('SELECT job_id FROM sent').fetchone()[0],'id')
 def test_corrupt_never_clears(self):
  self.c.execute('INSERT INTO sent VALUES(?,?,?,?)',('id','hash','delivery',m.now()));self.c.commit()
  with self.assertRaises(ValueError):restore(self.c,{'schema':0})
  self.assertEqual(self.c.execute('SELECT COUNT(*) FROM sent').fetchone()[0],1)
 def test_missing_branch_no_reset(self):
  store=StateStore('example/repo','test')
  with patch.object(store,'api',side_effect=FileNotFoundError),self.assertRaises(ValueError):store.load(self.c)
 def test_nonfastforward_propagates(self):
  store=StateStore('example/repo','test');store.ready=True;store.sha='old';calls=[]
  def api(path,method='GET',data=None):
   calls.append((path,method,data))
   if method=='PATCH':raise RuntimeError('conflict')
   return {'sha':'new'}
  with patch.object(store,'api',side_effect=api),self.assertRaises(RuntimeError):store.save(self.c)
  self.assertFalse(calls[-1][2]['force']);self.assertEqual(store.sha,'old')
 def test_checkpoint_failure_no_email(self):
  j=extract(doc(),CONFIG);self.c.execute('INSERT INTO candidates VALUES(?,?,?,?,?,NULL)',(j['url'],'test',m.now(),m.now(),json.dumps(doc())));self.c.commit();m.ingest(self.c,[j],CONFIG)
  def failure():raise RuntimeError('Persistence unavailable')
  with patch.object(m,'ROOT',Path(self.temp.name)),patch.dict(os.environ,{'EMAIL_ENABLED':'true','GITHUB_ACTIONS':'true'}),patch.object(m,'fetch',return_value=doc()),patch.object(m,'smtp_send') as smtp:
   with self.assertRaises(RuntimeError):m.dispatch(self.c,CONFIG,True,checkpoint=failure)
   smtp.assert_not_called()
 def test_env_not_loaded_on_actions(self):
  with patch.dict(os.environ,{'GITHUB_ACTIONS':'true'}),patch.object(Path,'read_text',side_effect=AssertionError):m.env_load()
 def test_no_token_in_api_error(self):
  import urllib.error
  store=StateStore('example/repo','DO-NOT-LOG')
  error=urllib.error.HTTPError('https://api.github.com',403,'secret',{},None)
  with patch('urllib.request.urlopen',side_effect=error):
   with self.assertRaises(RuntimeError) as exc:store.api('/test')
   self.assertNotIn('DO-NOT-LOG',str(exc.exception));self.assertNotIn('secret',str(exc.exception));error.close()
if __name__=='__main__':unittest.main()
