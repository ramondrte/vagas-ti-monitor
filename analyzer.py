"""Classificação conservadora, determinística, sem IA/API paga ou sessão interativa."""
import datetime as dt
import re
import urllib.parse
import monitor as m

AREA_RULES = {
 'Governança de TI': r'governanca de ti|it governance|cobit|controles (?:internos )?de ti|riscos de ti|compliance de ti|auditoria de ti|politicas de ti|processos de ti|gestao de (?:ativos|fornecedores|contratos) de ti|cmdb',
 'Infraestrutura / Cloud': r'infraestrutura (?:de ti|de redes)|servidores|administracao.{0,20}redes|active directory|microsoft 365|\baws\b|\bazure\b|cloud|computacao em nuvem|windows server|\blinux\b',
 'NOC / Monitoramento': r'\bnoc\b|zabbix|grafana|observabilidade|monitoramento.{0,35}(?:servidores|servicos|redes|sistemas)|network operations',
 'ITSM / Gestão de Serviços de TI': r'\bitsm\b|\bitil\b|iso 20000|gestao de (?:incidentes|problemas|mudancas|servicos de ti)|change management|incident management|service management|\bsla\b',
 'Suporte / ITSM': r'suporte (?:tecnico|de ti)|service desk|help desk|atendimento tecnico|chamados|troubleshooting|it support',
 'Operações de TI': r'operacoes de ti|it operations|technology operations|operacao.{0,25}(?:servidores|redes|infraestrutura)',
 'Segurança / GRC': r'seguranca da informacao|information security|security operations|\bsoc\b|\bgrc\b|iso 27001|cybersecurity|controles de acesso',
}
SENIOR=r'\b(pleno|senior|especialista|coordenador|lider|gerente|manager|lead|principal)\b'
DEV=r'desenvolv(?:er|imento|edor).{0,25}(?:software|web|aplicac|front|back|full.?stack|mobile)|data scien|cientista de dados|automatiz.{0,20}testes'

def lines(html):
 return [m.plain(x) for x in re.split(r'</?(?:p|li|h[1-6]|div|br)[^>]*>',html,flags=re.I) if m.plain(x)]
def sections(raw):
 out={'intro':[],'activities':[],'requirements':[],'desirable':[],'extra':[]};current='intro'
 for text in lines(raw):
  n=m.norm(text)
  if len(n)<110 and re.match(r'responsabilidades|principais atividades|atividades|responsibilities|what you.ll do',n):current='activities';continue
  if len(n)<110 and re.match(r'requisitos|qualificacoes|requirements|qualifications|what you.ll need',n):current='requirements';continue
  if len(n)<90 and re.match(r'diferenciais|desejaveis|nice to have|preferred',n):current='desirable';continue
  if len(n)<90 and re.match(r'informacoes adicionais|beneficios|additional information|benefits',n):current='extra';continue
  out[current].append(text)
 return out

def extract(doc, config):
 postings=doc.get('job_postings',[])
 j={'company':'Não informado','title':'Não informado','location':m.UNKNOWN,'url':doc['url'],'status':'pending','reason':'Sem JobPosting público estruturado; não enviar automaticamente.'}
 if not postings:
  if re.search(r'candidaturas encerradas|inscricoes encerradas|vaga (encerrada|finalizada)',m.norm(doc.get('text',''))):j.update(status='rejected',reason='Candidaturas encerradas na página oficial.')
  return j
 p=postings[0]; raw=p.get('description','');sec=sections(raw); description=m.plain(raw);n=m.norm(description)
 title=p.get('title',''); j.update({k:m.UNKNOWN for k in m.FIELDS});j.update(company=p.get('hiringOrganization',{}).get('name') or 'Não informado',title=title or 'Não informado',url=doc['url'],verified_at=m.now(),description_hash=m.digest(description),description_reviewed=True,source=urllib.parse.urlsplit(doc['url']).netloc)
 def stop(reason,status='rejected'):j.update(status=status,reason=reason);return j
 page=m.norm(doc['text']);nt=m.norm(title)
 if re.search(r'candidaturas encerradas|inscricoes encerradas|vaga (encerrada|finalizada)|job (?:is )?(?:closed|no longer available)',page):return stop('Candidaturas encerradas na página oficial.')
 deadline=p.get('validThrough','')[:10]
 if deadline:
  try:
   if dt.date.fromisoformat(deadline)<dt.date.today():return stop('Prazo encerrado.')
   j.update(deadline=deadline,deadline_iso=deadline)
  except ValueError:return stop('Prazo não interpretável.','pending')
 j['published']=p.get('datePosted',m.UNKNOWN)
 if re.search(SENIOR,nt):return stop('Senioridade incompatível.')
 internship=bool(re.search(r'estagi|\bintern\b|internship',nt+' '+str(p.get('employmentType','')).lower()))
 entry=bool(re.search(r'junior|\bjr\b|assistente|tecnico|operador|\bn[12]\b',nt))
 if not internship and not entry:
  entry=bool(re.search(r'sem experiencia|nao (?:e )?necessari[ao].{0,20}experiencia',n) and re.search(r'auxiliar|apoiar|sob supervisao',n))
 if not (internship or entry):return stop('Nível de entrada não comprovado.','pending')
 j['kind']='internship' if internship else 'entry'
 activities=sec['activities'] or sec['intro'];requirements=sec['requirements']
 if not activities:return stop('Responsabilidades não identificadas.','pending')
 req=m.norm(' '.join(requirements));j['requirements']='; '.join(requirements) or m.UNKNOWN
 # Regras em trechos obrigatórios; diferenciais não se tornam requisito.
 for line in requirements:
  x=m.norm(line)
  if re.search(r'desejavel|diferencial|preferencial|ou cursando|ou em andamento|cursando ou',x):continue
  if re.search(r'(?:superior|graduacao|bacharelado).{0,20}(?:complet[ao]|concluid[ao])|bachelor.s degree required',x):return stop('Graduação concluída obrigatória.')
  if re.search(r'(?:[2-9]|dois|tres|quatro|cinco)\s*(?:\+|a \d+)?\s*(?:anos|years).{0,35}experien|experien.{0,40}(?:[2-9]|dois|tres)\s*(?:\+)?\s*(?:anos|years)',x):return stop('Experiência obrigatória acima do perfil.')
 act=m.norm(' '.join(activities));matches={area:len(re.findall(pattern,act)) for area,pattern in AREA_RULES.items()}
 dev=len(re.findall(DEV,act));best=max(matches.values(),default=0)
 if re.search(DEV,nt) or (dev and dev>=best):return stop('Desenvolvimento/dados predominante nas atividades.')
 if not best:return stop('Não há atividades de TI compatíveis comprovadas.','pending')
 # Seleciona a área predominante nas atividades; ordem só desempata.
 area=max(config['area_order'],key=lambda a:matches[a]);j['area']=area
 if area=='Segurança / GRC' and not re.search(r'governanca|risco|compliance|infraestrutura|operac|controles|\bsoc\b|\bgrc\b|iso 27001',act):return stop('Segurança sem relação comprovada com governança/operação.','pending')
 locations=p.get('jobLocation',[]);locations=locations if isinstance(locations,list) else [locations]
 addresses=[x.get('address',{}) for x in locations if isinstance(x,dict)]
 locs=[', '.join(str(a.get(k,'')) for k in ['addressLocality','addressRegion','addressCountry'] if a.get(k)) for a in addresses]
 remote=p.get('jobLocationType')=='TELECOMMUTE' or bool(re.search(r'100% remoto|totalmente remoto|fully remote|trabalho remoto|modalidade:? remoto',n))
 hybrid=bool(re.search(r'hibrid|hybrid',n))
 if hybrid:remote=False
 j.update(remote=remote,location=' / '.join(locs) or m.UNKNOWN,modality='Remoto' if remote else ('Híbrido' if hybrid else ('Presencial' if 'presencial' in n else m.UNKNOWN)))
 allowed=p.get('applicantLocationRequirements',[]);allowed=allowed if isinstance(allowed,list) else [allowed]
 countries=' '.join(str(x.get('name','')) for x in allowed if isinstance(x,dict))
 brazil=bool(re.search(r'brasil|brazil|\bbr\b',m.norm(countries)))
 if remote:
  # Local de trabalho no Brasil estruturado + modalidade remota também é evidência nacional.
  brazil=brazil or any(m.norm(a.get('addressCountry','')) in ['br','brasil','brazil'] for a in addresses)
  brazil=brazil or bool(re.search(r'remoto.{0,25}(?:brasil|brazil)|(?:brasil|brazil).{0,25}remoto',n))
  if not brazil:return stop('Remoto sem autorização explícita para trabalhar do Brasil.','pending')
  j.update(brazil_explicit=True,location='Brasil (remoto)')
 elif not any(any(m.norm(city)==m.norm(a.get('addressLocality','')) for city in config['cities']) and m.norm(a.get('addressRegion','')) in ['mg','minas gerais'] for a in addresses):return stop('Localidade fora do perfil.' if locs else 'Localidade não confirmada.', 'rejected' if locs and any(a.get('addressLocality') for a in addresses) else 'pending')
 course_lines=[x for x in requirements if re.search(r'curs|superior|graduacao|formation|degree|education',m.norm(x))]
 course='; '.join(course_lines); nc=m.norm(course)
 if course and not re.search(r'sistemas de informacao|tecnologia da informacao|computacao.{0,100}(?:correlat|afins)|(?:correlat|afins).{0,100}computacao',nc):return stop('Curso incompatível ou sem equivalência clara.','pending')
 j['course']=course or m.UNKNOWN
 if internship and not re.search(r'cursando|em andamento|estudante|enrolled',nc):return stop('Matrícula em curso compatível não confirmada.','pending')
 sem_lines=[x for x in requirements if re.search(r'semestre|periodo|formatura|graduation',m.norm(x))]
 j['semester']='; '.join(x for x in sem_lines if re.search(r'semestre|periodo',m.norm(x))) or m.UNKNOWN
 j['graduation']='; '.join(x for x in sem_lines if re.search(r'formatura|graduation|conclusao',m.norm(x))) or m.UNKNOWN
 for x in map(m.norm,sem_lines):
  lo=re.search(r'(?:a partir do|minimo|desde o)\s*(\d+)\s*[º°o]?\s*(?:semestre|periodo)',x)
  hi=re.search(r'(?:ate o|maximo)\s*(\d+)\s*[º°o]?\s*(?:semestre|periodo)',x)
  bounds=re.search(r'(\d+)\s*[º°o]?\s*(?:ao|a|ate|-)\s*(\d+)\s*[º°o]?\s*(?:semestre|periodo)',x)
  if lo:j['semester_min']=int(lo[1])
  if hi:j['semester_max']=int(hi[1])
  if bounds:j.update(semester_min=int(bounds[1]),semester_max=int(bounds[2]))
  if re.search(r'\d',x) and re.search(r'semestre|periodo',x) and not (lo or hi or bounds):return stop('Restrição de semestre ambígua.','pending')
 if j.get('semester_min',0)>config['semester'] or j.get('semester_max',99)<config['semester']:return stop('Semestre incompatível.')
 for line in lines(raw):
  nl=m.norm(line)
  if re.search(r'bolsa|salario|remuneracao',nl):j['salary']=line
  if re.search(r'horario|horas|\d{1,2}h.{0,15}\d{1,2}h',nl):j['hours']=line
 benefits=[x for x in lines(raw) if re.search(r'vale.transporte|vale.refeicao|vale.alimentacao|seguro de vida|plano de saude|assistencia medica|beneficios',m.norm(x))]
 j['benefits']='; '.join(benefits) or m.UNKNOWN
 j['desirable']='; '.join(sec['desirable']+[x for x in requirements if re.search(r'desejavel|diferencial|preferencial',m.norm(x))]) or m.UNKNOWN
 j['activities']='; '.join(activities)
 if internship and re.search(r'\b(?:[7-9]|1[0-2])\s*(?:horas diarias|h/dia)|\b(?:40|44)\s*horas',m.norm(j['hours'])):return stop('Jornada incompatível com estágio.')
 host=urllib.parse.urlsplit(doc['url']).netloc
 trusted=any(host==x or host.endswith('.'+x) for x in config['official_domains'])
 if not trusted:return stop('Fonte não validada como anúncio oficial.','pending')
 links=[urllib.parse.urljoin(doc['url'],x) for x in doc.get('application_links',[]) if not x.startswith('#')]
 links=[x for x in links if urllib.parse.urlsplit(x).scheme=='https']
 opening=next((x for x in ['Candidatar-se','Ir para candidatura','Apply for this job','Apply now'] if m.norm(x) in page),None)
 if not links or not opening:return stop('Candidatura aberta não comprovada por link e texto.','pending')
 j.update(application_url=links[0],official=True,status='eligible',reason='Atividades e requisitos compatíveis pelas regras locais; lacunas sinalizadas.',closed=False,degree_required=False)
 idmatch=re.search(r'/jobs/(\d+)',doc['url']);ident=p.get('identifier',{})
 if idmatch:j['job_id']=idmatch[1]
 elif isinstance(ident,dict) and ident.get('value'):j['job_id']=str(ident['value'])
 j['evidence']={'open':opening,'location':j['location'],'level':title,'area':activities[0],'course':j['course'],'semester':j['semester'],'requirements':j['requirements']}
 j['compatibility']=f"As atividades descritas se relacionam a {area}, com foco em {', '.join(a for a,v in matches.items() if v)}. A localidade e o nível são compatíveis com o perfil. Requisitos ausentes ou ambíguos estão identificados como precisa confirmar; não equivalem a requisitos dispensados."
 return j
