import asyncio
import csv
import io
import json
import zipfile
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock
import httpx
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from jon.app import create_app
from jon.db import Store
from jon.models import Profile, JobInput, Source
from jon.matching import match
from jon.connectors import normalize, discover, plain
from jon.resumes import choose_evidence, extract_resume
from jon.submissions import preflight

PROFILE = {'name':'Test Candidate','email':'candidate@example.com','skills':['Python','SQL'],'roles':['Software Engineer'],'salary_min':1000000,'currency':'INR'}
JOB = {'title':'Software Engineer','company':'Example Co','description':'Build Python and SQL services for internal analytics. Full-time position in Bengaluru.','location':'Bengaluru','url':'https://example.com/jobs/123','job_type':'Full-time','salary_min':1200000,'salary_max':2000000,'currency':'INR','salary_period':'year'}
EVIDENCE = {'category':'project','title':'Analytics service','text':'Built a Python service with SQL queries for an academic analytics project.','source':'My project notes','verified':True}


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        c.headers['X-Jon-Token'] = c.get('/api/session').json()['token']
        yield c


def seed(client, job=None):
    assert client.put('/api/profile',json=PROFILE).status_code == 200
    assert client.post('/api/evidence',json=EVIDENCE).status_code == 200
    jid = client.post('/api/jobs',json=job or JOB).json()['id']
    r = client.post(f'/api/jobs/{jid}/draft',json={})
    assert r.status_code == 200, r.text
    aid = r.json()['id']
    a = client.get('/api/state').json()['applications'][0]
    return aid, a


def approve(client, aid, a):
    return client.post(f'/api/applications/{aid}/approve',json={'hash':a['hash'],'confirmed':True})


def test_full_manual_workflow_and_exports(client):
    aid,a=seed(client)
    assert EVIDENCE['text'] in a['resume']
    assert approve(client,aid,a).status_code==200
    r=client.post(f'/api/applications/{aid}/submit',json={'hash':a['hash'],'confirmed':True})
    assert r.json()['status']=='needs_manual'
    assert client.post(f'/api/applications/{aid}/outcome',json={'status':'submitted_manual','note':'Employer confirmation page received.'}).status_code==200
    assert client.post(f'/api/applications/{aid}/outcome',json={'status':'interview','note':'Interview scheduled by recruiter.'}).status_code==200
    pdf=client.get(f'/api/applications/{aid}/resume/pdf')
    reader=PdfReader(io.BytesIO(pdf.content))
    assert 'Test Candidate' in reader.pages[0].extract_text()
    docx=client.get(f'/api/applications/{aid}/resume/docx')
    assert EVIDENCE['text'] in extract_resume('resume.docx',docx.content)
    rows=list(csv.reader(io.StringIO(client.get('/api/export').text.lstrip('\ufeff'))))
    assert rows[1][3]=='interview'
    assert rows[1][7]==a['hash']


def test_requires_verified_evidence_and_profile(client):
    jid=client.post('/api/jobs',json=JOB).json()['id']
    assert client.post(f'/api/jobs/{jid}/draft',json={}).status_code==400
    client.put('/api/profile',json=PROFILE)
    client.post('/api/evidence',json=EVIDENCE|{'verified':False})
    assert client.post(f'/api/jobs/{jid}/draft',json={}).status_code==400


def test_edit_invalidates_approval_and_stale_hash(client):
    aid,a=seed(client)
    approve(client,aid,a)
    assert client.put(f'/api/applications/{aid}/resume',json={'text':a['resume']+'\nReviewed project description.'}).status_code==200
    assert approve(client,aid,a).status_code==409
    assert client.post(f'/api/applications/{aid}/submit',json={'hash':a['hash'],'confirmed':True}).status_code==409
    updated=client.get('/api/state').json()['applications'][0]
    assert updated['status']=='needs_review' and updated['hash']!=a['hash']
    assert updated['snapshot']['user_edited']


def test_profile_changes_do_not_mutate_snapshot(client):
    aid,a=seed(client)
    client.put('/api/profile',json=PROFILE|{'email':'changed@example.com'})
    snapshot=client.get('/api/state').json()['applications'][0]['snapshot']
    assert snapshot['profile']['email']==PROFILE['email']


def test_no_duplicate_drafts_under_concurrency(client):
    aid,a=seed(client)
    def call(_):
        return client.post(f"/api/jobs/{a['job_id']}/draft",json={}).json()['id']
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids=list(pool.map(call,range(4)))
    assert ids==[aid]*4
    assert len(client.get('/api/state').json()['applications'])==1


def test_unauthorized_and_cross_origin(client):
    assert client.get('/api/state',headers={'X-Jon-Token':''}).status_code==403
    assert client.get('/api/session',headers={'Origin':'https://evil.example'}).status_code==403
    assert client.get('/api/session',headers={'Sec-Fetch-Site':'cross-site'}).status_code==403
    assert client.get('/api/session',headers={'Host':'evil.example'}).status_code==400
    assert client.post('/api/jobs',json=JOB,headers={'Origin':'https://evil.example'}).status_code==403
    response=client.get('/')
    assert "frame-ancestors 'none'" in response.headers['content-security-policy']


@pytest.mark.parametrize('url',['javascript:alert(1)','http://example.com','https://127.0.0.1/a','https://localhost/a','https://169.254.169.254/','https://user:pass@example.com/a'])
def test_unsafe_import_url_rejected(client,url):
    assert client.post('/api/jobs',json=JOB|{'url':url}).status_code==422


def test_source_path_injection_rejected(client):
    assert client.post('/api/sources',json={'provider':'greenhouse','board':'../../secret','company':'Test'}).status_code==422


def test_csv_formula_escaped(client):
    seed(client,JOB|{'company':'=HYPERLINK("https://example.com")'})
    row=list(csv.reader(io.StringIO(client.get('/api/export').text.lstrip('\ufeff'))))[1]
    assert row[1].startswith("'=")


def test_invalid_transitions_rejected(client):
    aid,a=seed(client)
    assert client.post(f'/api/applications/{aid}/outcome',json={'status':'interview','note':'Unconfirmed outcome'}).status_code==409
    assert client.post(f'/api/applications/{aid}/outcome',json={'status':'submitted_manual','note':'Unreviewed draft'}).status_code==409
    assert client.post(f'/api/applications/{aid}/approve',json={'hash':a['hash'],'confirmed':False}).status_code==400


def test_salary_currency_unknown_and_remote_filters():
    p=Profile(**PROFILE)
    assert match(JOB,p)['eligible']
    assert not match(JOB|{'salary_max':500000},p)['eligible']
    assert match(JOB|{'currency':'USD'},p)['unknowns']
    assert not match(JOB|{'currency':'USD'},p.model_copy(update={'allow_unknown_salary':False}))['eligible']
    assert not match(JOB,p.model_copy(update={'remote_only':True}))['eligible']
    assert not match(JOB|{'remote':True,'location':'United States'},p.model_copy(update={'locations':['India']}))['eligible']


def test_skill_word_boundaries():
    p=Profile(skills=['Java','SQL'])
    result=match(JOB|{'description':'JavaScript and MySQL application','title':'Engineer'},p)
    assert result['matched_skills']==[]


def test_resume_import_and_zip_limit(client):
    response=client.post('/api/resume/extract',files={'file':('notes.txt',b'Built a Python service for analytics.','text/plain')})
    assert response.json()['text']=='Built a Python service for analytics.'
    assert client.post('/api/resume/extract',files={'file':('evil.exe',b'MZdata')}).status_code==400
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('large.xml','a'*21000000)
    with pytest.raises(ValueError,match='expansion'):
        extract_resume('bomb.docx',buffer.getvalue())


def test_restart_marks_inflight_unknown(tmp_path):
    with TestClient(create_app(tmp_path)) as c:
        c.headers['X-Jon-Token']=c.get('/api/session').json()['token']
        aid,a=seed(c)
        with c.app.state.store.connect() as db:
            db.execute("UPDATE applications SET status='submitting' WHERE id=?",(aid,))
    restarted=Store(tmp_path/'jon.sqlite3')
    assert restarted.application(aid)['status']=='unknown'


def test_network_timeout_never_retries_or_marks_sent(client,monkeypatch):
    aid,a=seed(client)
    approve(client,aid,a)
    monkeypatch.setattr('jon.app.preflight',AsyncMock(return_value=None))
    sender=AsyncMock(side_effect=httpx.ReadTimeout('timeout'))
    monkeypatch.setattr('jon.app.send',sender)
    payload={'hash':a['hash'],'confirmed':True}
    assert client.post(f'/api/applications/{aid}/submit',json=payload).json()['status']=='unknown'
    assert client.post(f'/api/applications/{aid}/submit',json=payload).status_code==409
    assert sender.await_count==1
    assert client.put(f'/api/applications/{aid}/resume',json={'text':a['resume']}).status_code==409


def test_atomic_claim_prevents_duplicate_external_send(client,monkeypatch):
    aid,a=seed(client);approve(client,aid,a)
    monkeypatch.setattr('jon.app.preflight',AsyncMock(return_value=None))
    async def delayed(*args):
        await asyncio.sleep(.05)
        return 'submitted','Mock employer receipt'
    sender=AsyncMock(side_effect=delayed)
    monkeypatch.setattr('jon.app.send',sender)
    def submit(_):
        return client.post(f'/api/applications/{aid}/submit',json={'hash':a['hash'],'confirmed':True}).status_code
    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses=list(pool.map(submit,range(4)))
    assert statuses.count(200)==1
    assert sender.await_count==1


def test_submission_form_required_question_and_consent_fail_closed(monkeypatch):
    monkeypatch.setenv('JON_GREENHOUSE_KEYS','{"example":"secret"}')
    job={'provider':'greenhouse','board':'example','external_id':'123'}
    async def run(payload):
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=payload))) as c:
            return await preflight(job,PROFILE,c)
    basic={'questions':[{'required':True,'fields':[{'name':'email'}]}]}
    assert asyncio.run(run(basic)) is None
    assert 'additional' in asyncio.run(run({'questions':[{'required':True,'fields':[{'name':'question_work_auth'}]}]}))
    assert 'consent' in asyncio.run(run(basic|{'data_compliance':[{'requires_consent':True}]}))
    assert asyncio.run(run({}))


def test_model_rejects_fabricated_ids(monkeypatch):
    monkeypatch.setenv('JON_MODEL_URL','http://127.0.0.1:8000/v1')
    response=httpx.Response(200,json={'choices':[{'message':{'content':'{"evidence_ids":[999]}'}}]},request=httpx.Request('POST','http://localhost'))
    monkeypatch.setattr(httpx.AsyncClient,'post',AsyncMock(return_value=response))
    with pytest.raises(ValueError,match='unsupported'):
        asyncio.run(choose_evidence(JOB,[EVIDENCE|{'id':1}],True))


def test_model_never_authors_resume_claims(monkeypatch):
    monkeypatch.setenv('JON_MODEL_URL','https://model.example/v1')
    response=httpx.Response(200,json={'choices':[{'message':{'content':'{"evidence_ids":[1],"made_up_text":"10 years at Google"}'}}]},request=httpx.Request('POST','https://model.example'))
    sender=AsyncMock(return_value=response)
    monkeypatch.setattr(httpx.AsyncClient,'post',sender)
    selected,model=asyncio.run(choose_evidence(JOB,[EVIDENCE|{'id':1}],True))
    assert selected[0]['text']==EVIDENCE['text']
    assert PROFILE['email'] not in json.dumps(sender.call_args.kwargs['json'])


def test_model_endpoint_insecure_rejected(monkeypatch):
    monkeypatch.setenv('JON_MODEL_URL','http://remote.example/v1')
    with pytest.raises(ValueError,match='HTTPS'):
        asyncio.run(choose_evidence(JOB,[EVIDENCE|{'id':1}],True))


@pytest.mark.parametrize('provider,raw',[
    ('greenhouse',{'id':123,'title':'Software Engineer','content':'<p>Build Python systems and test them.</p>','absolute_url':'https://example.com/job','location':{'name':'Remote'}}),
    ('lever',{'id':'abc','text':'Software Engineer','descriptionPlain':'Build Python systems and test them.','hostedUrl':'https://example.com/job','categories':{'location':'India','commitment':'Full-time'},'workplaceType':'remote'}),
    ('ashby',{'id':'abc','title':'Software Engineer','descriptionPlain':'Build Python systems and test them.','jobUrl':'https://example.com/job','employmentType':'FullTime','isRemote':True})])
def test_provider_normalization(provider,raw):
    result=normalize({'provider':provider,'company':'Test','board':'test'},raw)
    assert result['remote'] is True
    assert result['id'].startswith(provider+':test:')
    assert '<p>' not in result['description']


def test_discovery_mocked_contract():
    async def run():
        raw={'jobs':[{'id':1,'title':'Engineer','content':'Build reliable systems and applications.','absolute_url':'https://example.com/jobs/1'}]}
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=raw))) as c:
            return await discover({'provider':'greenhouse','board':'test','company':'Test'},c)
    jobs,skipped=asyncio.run(run())
    assert len(jobs)==1 and skipped==0


def test_escaped_html_removed():
    assert plain('&lt;p&gt;Build reliable systems&lt;/p&gt;') == 'Build reliable systems'


def test_ashby_compensation_and_unlisted_jobs():
    async def run():
        visible = {'title':'Engineer','descriptionPlain':'Build reliable analytics services.','jobUrl':'https://example.com/job','isListed':True,'compensation':{'summaryComponents':[{'compensationType':'Salary','interval':'1 YEAR','currencyCode':'INR','minValue':1000000,'maxValue':2000000}]}}
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'jobs':[visible,visible|{'isListed':False}]}))) as c:
            return await discover({'provider':'ashby','board':'test','company':'Test'},c)
    jobs,skipped=asyncio.run(run())
    assert len(jobs)==1 and jobs[0]['salary_max']==2000000 and jobs[0]['currency']=='INR'
