import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import monitor as m
class MonitorTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.c=m.connect(self.root);self.cfg=json.loads((m.ROOT/'config.json').read_text());self.job=json.loads((Path(__file__).resolve().parent/'fixture_review.json').read_text())[0];self.job['verified_at']=m.now()
  self.c.execute('INSERT INTO candidates VALUES(?,?,?,?,?,NULL)',(self.job['url'],'test',m.now(),m.now(),json.dumps({'text':'Candidatar-se'})));self.c.commit()
 def tearDown(self):self.c.close();self.tmp.cleanup()
 def accept(self,j=None):m.ingest(self.c,[j or self.job],self.cfg)
 def invalid(self,**changes):
  j=copy.deepcopy(self.job);j.update(changes)
  with self.assertRaises(ValueError):m.validate(j,self.cfg)
 def test_accept_intern(self):self.accept();self.assertEqual(len(m.pending(self.c,self.cfg)),1)
 def test_duplicate_tracking_url(self):
  self.accept();j=copy.deepcopy(self.job);j['url']+='?utm_source=linkedin';self.accept(j);self.assertEqual(self.c.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],1)
 def test_sent_suppressed(self):
  self.accept();a,b,_,_=m.pending(self.c,self.cfg)[0];self.c.execute('INSERT INTO sent VALUES(?,?,?,?)',(a,b,'test',m.now()));self.assertEqual(m.pending(self.c,self.cfg),[])
 def test_update_flag(self):
  self.accept();a,b,_,_=m.pending(self.c,self.cfg)[0];self.c.execute('INSERT INTO sent VALUES(?,?,?,?)',(a,b,'test',m.now()));j=copy.deepcopy(self.job);j['salary']='R$ 1.200';self.accept(j);self.assertTrue(m.pending(self.c,self.cfg)[0][3])
 def test_collection_not_update(self):
  self.accept();fp=self.c.execute('SELECT fingerprint FROM jobs').fetchone()[0];j=copy.deepcopy(self.job);j['verified_at']=m.now();j['source']='Outra fonte oficial';self.accept(j);self.assertEqual(fp,self.c.execute('SELECT fingerprint FROM jobs').fetchone()[0])
 def test_closed(self):self.invalid(closed=True)
 def test_degree(self):self.invalid(degree_required=True)
 def test_senior(self):self.invalid(title='Analista de Infraestrutura Sênior')
 def test_semester_min(self):self.invalid(semester_min=5)
 def test_semester_max(self):self.invalid(semester_max=2)
 def test_location(self):self.invalid(location='São Paulo/SP')
 def test_remote_abroad(self):self.invalid(remote=True,brazil_explicit=False)
 def test_remote_brazil(self):
  j=copy.deepcopy(self.job);j.update(remote=True,brazil_explicit=True,location='Brasil');m.validate(j,self.cfg)
 def test_programming_complement(self):
  j=copy.deepcopy(self.job);j['desirable']='Python para scripts de infraestrutura';m.validate(j,self.cfg)
 def test_development_area(self):self.invalid(area='Desenvolvimento de Software')
 def test_entry(self):
  j=copy.deepcopy(self.job);j.update(kind='entry',title='Técnico de Suporte N1');m.validate(j,self.cfg)
 def test_expired(self):self.invalid(deadline_iso='2020-01-01')
 def test_stale(self):self.invalid(verified_at='2020-01-01T00:00:00+00:00')
 def test_experience(self):self.invalid(experience_years=3)
 def test_no_description(self):self.invalid(description_reviewed=False)
 def test_no_email_empty(self):
  with patch.object(m,'smtp_send') as send:self.assertFalse(m.dispatch(self.c,self.cfg,True)['sent']);send.assert_not_called()
 def test_dispatch_and_no_resend(self):
  self.accept()
  with patch.object(m,'ROOT',self.root),patch.dict(m.os.environ,{'EMAIL_ENABLED':'true'}),patch.object(m,'fetch',return_value={'text':'Candidatar-se','job_postings':[]}),patch.object(m,'smtp_send',return_value='<test@local>') as send:
   self.assertTrue(m.dispatch(self.c,self.cfg,True)['sent']);self.assertFalse(m.dispatch(self.c,self.cfg,True)['sent']);self.assertEqual(send.call_count,1)
 def test_uncertain_stops_retry(self):
  self.accept()
  with patch.object(m,'ROOT',self.root),patch.dict(m.os.environ,{'EMAIL_ENABLED':'true'}),patch.object(m,'fetch',return_value={'text':'Candidatar-se','job_postings':[]}),patch.object(m,'smtp_send',side_effect=TimeoutError):
   with self.assertRaises(TimeoutError):m.dispatch(self.c,self.cfg,True)
   with self.assertRaises(ValueError):m.dispatch(self.c,self.cfg,True)
  self.assertEqual(self.c.execute('SELECT COUNT(*) FROM sent').fetchone()[0],0)
if __name__=='__main__':unittest.main(verbosity=2)
