import asyncio
import csv
import hashlib
import io
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from urllib.parse import urlsplit
import httpx
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from .db import Store, now
from .models import Profile, Source, Evidence, JobInput, GithubImport, DraftRequest, Outcome, Revision
from .matching import match
from .connectors import discover, github_evidence
from .resumes import choose_evidence, assemble, digest, extract_resume, export_docx, export_pdf
from .submissions import board_key, preflight, send

ROOT = Path(__file__).resolve().parent.parent


class Approval(BaseModel):
    hash: str = Field(min_length=64, max_length=64)
    confirmed: bool


def create_app(data_dir=None):
    app = FastAPI(title='Jon • Job workspace', docs_url=None, redoc_url=None, openapi_url=None)
    store = Store(Path(data_dir or os.environ.get('JON_DATA_DIR', ROOT / 'data')) / 'jon.sqlite3')
    app.state.store = store
    token = secrets.token_urlsafe(32)
    sync_lock = asyncio.Lock()
    model_lock = asyncio.Lock()
    last_sync = [0.0]
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1', 'localhost', '[::1]', 'testserver'])

    @app.middleware('http')
    async def guard(request: Request, call_next):
        origin = request.headers.get('origin')
        if request.headers.get('sec-fetch-site') == 'cross-site' or (origin and origin != str(request.base_url).rstrip('/')):
            return JSONResponse({'detail':'Cross-origin access is disabled.'}, status_code=403)
        if request.url.path.startswith('/api/') and request.url.path != '/api/session':
            if not secrets.compare_digest(request.headers.get('x-jon-token', ''), token):
                return JSONResponse({'detail':'Session expired. Reload the app.'}, status_code=403)
        length = request.headers.get('content-length')
        try:
            if length and int(length) > 6_000_000:
                return JSONResponse({'detail':'Request exceeds 6 MB limit.'}, status_code=413)
        except ValueError:
            return JSONResponse({'detail':'Invalid content length.'}, status_code=400)
        response = await call_next(request)
        response.headers.update({'Cache-Control':'no-store', 'X-Content-Type-Options':'nosniff', 'Referrer-Policy':'no-referrer', 'X-Frame-Options':'DENY', 'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"})
        return response

    @app.exception_handler(httpx.HTTPError)
    async def provider_error(request, exc):
        return JSONResponse({'detail':'External service unavailable or rejected the request. Check configuration and try again; secrets are not included in this error.'}, status_code=502)

    @app.exception_handler(ValueError)
    async def value_error(request, exc):
        return JSONResponse({'detail':str(exc)[:300]}, status_code=400)

    @app.get('/api/session')
    def session():
        return {'token':token, 'model_configured':bool(os.environ.get('JON_MODEL_URL')), 'model':os.environ.get('JON_MODEL','Qwen/Qwen3.5-35B-A3B')}

    @app.get('/api/state')
    def state():
        profile = store.profile()
        with store.connect() as db:
            evidence = [dict(r) for r in db.execute('SELECT * FROM evidence ORDER BY id DESC')]
            sources = [dict(r) for r in db.execute('SELECT * FROM sources ORDER BY id')]
            applications = [dict(r) for r in db.execute('SELECT a.*,j.data job FROM applications a JOIN jobs j ON a.job_id=j.id ORDER BY a.updated_at DESC')]
            jobs = []
            for row in db.execute('SELECT * FROM jobs ORDER BY last_seen DESC'):
                job = json.loads(row['data'])
                job.update(match=match(job, profile), last_seen=row['last_seen'])
                jobs.append(job)
            events = [dict(r) for r in db.execute('SELECT * FROM events ORDER BY id DESC LIMIT 100')]
        for a in applications:
            a['snapshot'] = json.loads(a['snapshot'])
            a['job'] = json.loads(a['job'])
            a['direct_submission'] = a['job'].get('provider') == 'greenhouse' and bool(board_key(a['job'].get('board')))
        return {'profile':profile.model_dump(), 'evidence':evidence, 'sources':sources, 'jobs':sorted(jobs, key=lambda j:(j['match']['eligible'], j['match']['score']), reverse=True), 'applications':applications, 'events':events}

    @app.put('/api/profile')
    def save_profile(profile: Profile):
        with store.connect() as db:
            db.execute("INSERT INTO settings VALUES('profile',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (profile.model_dump_json(),))
        return {'ok':True}

    @app.post('/api/sources')
    def add_source(source: Source):
        with store.connect() as db:
            db.execute('INSERT INTO sources(provider,board,company) VALUES(?,?,?) ON CONFLICT(provider,board) DO UPDATE SET company=excluded.company', (source.provider, source.board, source.company))
        return {'ok':True}

    @app.delete('/api/sources/{id}')
    def delete_source(id: int):
        with store.connect() as db:
            db.execute('DELETE FROM sources WHERE id=?', (id,))
        return {'ok':True}

    @app.post('/api/discover')
    async def sync():
        if sync_lock.locked() or time.monotonic() - last_sync[0] < 30:
            raise HTTPException(429, 'Discovery is running or was just completed. Wait 30 seconds.')
        async with sync_lock:
            with store.connect() as db:
                sources = [dict(r) for r in db.execute('SELECT * FROM sources')]
            if not sources:
                raise HTTPException(400, 'Add at least one company job board first.')
            sem = asyncio.Semaphore(3)
            async with httpx.AsyncClient(timeout=25, follow_redirects=False) as client:
                async def run(source):
                    async with sem:
                        try:
                            jobs, skipped = await discover(source, client)
                            store.upsert_jobs(jobs)
                            return {'company':source['company'], 'count':len(jobs), 'skipped':skipped, 'error':None}
                        except (httpx.HTTPError, ValueError, KeyError, TypeError):
                            return {'company':source['company'], 'count':0, 'error':'Could not read board. Check its slug, provider and availability.'}
                results = await asyncio.gather(*(run(s) for s in sources))
            last_sync[0] = time.monotonic()
            with store.connect() as db:
                store.event(db, None, 'discovery', json.dumps(results))
            return {'results':results}

    @app.post('/api/jobs')
    def import_job(job: JobInput):
        data = job.model_dump()
        data.update(id='manual:' + hashlib.sha256(job.url.encode()).hexdigest()[:24], provider='manual', board='', external_id='')
        store.upsert_jobs([data])
        return {'id':data['id']}

    @app.post('/api/evidence')
    def add_evidence(evidence: Evidence):
        with store.connect() as db:
            cursor = db.execute('INSERT INTO evidence(category,title,text,source,verified,created_at) VALUES(?,?,?,?,?,?)', (evidence.category,evidence.title,evidence.text,evidence.source,evidence.verified,now()))
        return {'id':cursor.lastrowid}

    @app.put('/api/evidence/{id}')
    def update_evidence(id: int, evidence: Evidence):
        with store.connect() as db:
            if not db.execute('SELECT id FROM evidence WHERE id=?', (id,)).fetchone():
                raise HTTPException(404, 'Evidence not found.')
            db.execute('UPDATE evidence SET category=?,title=?,text=?,source=?,verified=? WHERE id=?', (evidence.category,evidence.title,evidence.text,evidence.source,evidence.verified,id))
        return {'ok':True}

    @app.delete('/api/evidence/{id}')
    def delete_evidence(id: int):
        with store.connect() as db:
            db.execute('DELETE FROM evidence WHERE id=?', (id,))
        return {'ok':True, 'note':'Existing application snapshots retain their original evidence.'}

    @app.post('/api/resume/extract')
    async def extract(file: UploadFile):
        data = await file.read(5_000_001)
        await file.close()
        if len(data) > 5_000_000:
            raise HTTPException(413, 'Resume must be smaller than 5 MB.')
        try:
            text = await asyncio.to_thread(extract_resume, file.filename or '', data)
        except Exception:
            raise HTTPException(400, 'Could not extract this file. Use a text-based PDF, DOCX, TXT or Markdown under 20 pages; you can also paste the text.')
        return {'text':text, 'filename':Path(file.filename or 'resume').name}

    @app.post('/api/github')
    async def github(request: GithubImport):
        items = await github_evidence(request.username, os.environ.get('JON_GITHUB_TOKEN', ''))
        added = 0
        with store.connect() as db:
            for e in items:
                if not db.execute('SELECT id FROM evidence WHERE source=?', (e['source'],)).fetchone():
                    db.execute('INSERT INTO evidence(category,title,text,source,verified,created_at) VALUES(?,?,?,?,?,?)', (e['category'],e['title'],e['text'],e['source'],False,now()))
                    added += 1
        return {'added':added, 'note':'Public non-fork repositories, up to 30 most recently updated repositories inspected. Review ownership and contributions before verifying.'}

    @app.post('/api/jobs/{id}/draft')
    async def draft(id: str, request: DraftRequest):
        job = store.job(id)
        if not job:
            raise HTTPException(404, 'Job not found.')
        profile = store.profile()
        if not profile.name or not profile.email:
            raise HTTPException(400, 'Add your name and email to your profile first.')
        with store.connect() as db:
            existing = db.execute('SELECT id FROM applications WHERE job_id=?', (id,)).fetchone()
            evidence = [dict(r) for r in db.execute('SELECT * FROM evidence WHERE verified=1')]
        if existing:
            return {'id':existing['id'], 'existing':True}
        if not evidence:
            raise HTTPException(400, 'Add and verify at least one piece of evidence first.')
        async with model_lock:
            try:
                selected, model = await choose_evidence(job, evidence, request.use_model)
            except (KeyError, TypeError):
                raise HTTPException(502, 'Model returned an invalid response. No draft was saved.')
        resume = assemble(profile, selected, job)
        snapshot = {'profile':profile.model_dump(), 'evidence':selected, 'job':job, 'user_edited':False}
        hash_value = digest(resume, snapshot)
        try:
            with store.connect() as db:
                cur = db.execute('INSERT INTO applications(job_id,status,resume,snapshot,hash,model,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)', (id,'needs_review',resume,json.dumps(snapshot),hash_value,model,now(),now()))
                store.event(db, cur.lastrowid, 'drafted', 'Evidence-backed resume generated; review required.')
                return {'id':cur.lastrowid}
        except sqlite3.IntegrityError:
            with store.connect() as db:
                existing = db.execute('SELECT id FROM applications WHERE job_id=?', (id,)).fetchone()
            return {'id':existing['id'], 'existing':True}

    @app.put('/api/applications/{id}/resume')
    def revise(id: int, revision: Revision):
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM applications WHERE id=?', (id,)).fetchone()
            if not row:
                raise HTTPException(404, 'Application not found.')
            if row['status'] not in ('needs_review', 'approved', 'needs_manual'):
                raise HTTPException(409, 'This application is locked because submission may already have happened.')
            snapshot = json.loads(row['snapshot'])
            snapshot['user_edited'] = True
            db.execute("UPDATE applications SET resume=?,snapshot=?,hash=?,status='needs_review',updated_at=? WHERE id=?", (revision.text,json.dumps(snapshot),digest(revision.text,snapshot),now(),id))
            store.event(db,id,'revised','User edited the resume. Previous approval invalidated; factual review required.')
        return {'ok':True}

    @app.post('/api/applications/{id}/approve')
    def approve(id: int, approval: Approval):
        if not approval.confirmed:
            raise HTTPException(400, 'Confirm the claims and contact details before approval.')
        with store.connect() as db:
            changed = db.execute("UPDATE applications SET status='approved',updated_at=? WHERE id=? AND hash=? AND status IN ('needs_review','needs_manual')", (now(),id,approval.hash)).rowcount
            if not changed:
                raise HTTPException(409, 'Draft changed or cannot be approved. Reload and review it.')
            store.event(db,id,'approved','User approved the exact resume and profile snapshot: ' + approval.hash)
        return {'ok':True}

    @app.post('/api/applications/{id}/submit')
    async def submit(id: int, approval: Approval):
        a = store.application(id)
        if not a or a['status'] != 'approved' or a['hash'] != approval.hash or not approval.confirmed:
            raise HTTPException(409, 'An approved, unchanged application is required.')
        snapshot = json.loads(a['snapshot'])
        job = snapshot['job']
        async with httpx.AsyncClient(timeout=25, follow_redirects=False) as client:
            reason = await preflight(job, snapshot['profile'], client)
            if reason:
                with store.connect() as db:
                    changed = db.execute("UPDATE applications SET status='needs_manual',updated_at=? WHERE id=? AND status='approved' AND hash=?", (now(),id,approval.hash)).rowcount
                    if not changed:
                        raise HTTPException(409, 'Application changed. Reload it.')
                    store.event(db,id,'needs_manual',reason)
                return {'status':'needs_manual', 'detail':reason}
            with store.connect() as db:
                changed = db.execute("UPDATE applications SET status='submitting',updated_at=? WHERE id=? AND status='approved' AND hash=?", (now(),id,approval.hash)).rowcount
                if not changed:
                    raise HTTPException(409, 'Another request already claimed or changed this application.')
                store.event(db,id,'submitting','Submission started; automatic retries disabled.')
            try:
                status, receipt = await send(job, snapshot, a['resume'], client)
            except Exception:
                status, receipt = 'unknown', 'Submission was interrupted. Check with the employer before any further action.'
            with store.connect() as db:
                db.execute('UPDATE applications SET status=?,receipt=?,updated_at=? WHERE id=?', (status,receipt,now(),id))
                store.event(db,id,status,receipt)
        return {'status':status, 'detail':receipt}

    @app.post('/api/applications/{id}/outcome')
    def outcome(id: int, outcome: Outcome):
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT status FROM applications WHERE id=?', (id,)).fetchone()
            if not row:
                raise HTTPException(404, 'Application not found.')
            permitted = {
                'submitted_manual': {'approved','needs_manual','unknown'},
                'interview': {'submitted','submitted_manual','interview'},
                'offer': {'submitted','submitted_manual','interview'},
                'rejected': {'submitted','submitted_manual','interview'},
                'withdrawn': {'approved','needs_manual','submitted','submitted_manual','interview','offer'},
            }
            if row['status'] not in permitted[outcome.status]:
                raise HTTPException(409, 'That outcome does not follow the current application state.')
            db.execute('UPDATE applications SET status=?,updated_at=? WHERE id=?', (outcome.status,now(),id))
            store.event(db,id,outcome.status,outcome.note)
        return {'ok':True}

    @app.get('/api/applications/{id}/resume/{format}')
    def download_resume(id: int, format: str):
        a = store.application(id)
        if not a:
            raise HTTPException(404, 'Application not found.')
        types = {'txt':'text/plain; charset=utf-8', 'pdf':'application/pdf', 'docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document'}
        if format not in types:
            raise HTTPException(400, 'Choose txt, pdf or docx.')
        data = a['resume'].encode() if format == 'txt' else export_pdf(a['resume']) if format == 'pdf' else export_docx(a['resume'])
        return Response(data, media_type=types[format], headers={'Content-Disposition':f'attachment; filename="resume-{id}.{format}"'})

    @app.get('/api/export')
    def export():
        output = io.StringIO(newline='')
        writer = csv.writer(output)
        writer.writerow(['Application ID','Company','Role','Status','URL','Created UTC','Updated UTC','Resume hash','Receipt'])
        with store.connect() as db:
            for a in db.execute('SELECT * FROM applications ORDER BY id'):
                job = json.loads(a['snapshot'])['job']
                values = [a['id'],job['company'],job['title'],a['status'],job['url'],a['created_at'],a['updated_at'],a['hash'],a['receipt'] or '']
                writer.writerow(["'" + str(v) if str(v).lstrip().startswith(('=','+','-','@','\t','\r')) else v for v in values])
        return Response(output.getvalue().encode('utf-8-sig'), media_type='text/csv', headers={'Content-Disposition':'attachment; filename="jon-applications.csv"'})

    app.mount('/static', StaticFiles(directory=ROOT / 'static'), name='static')

    @app.get('/')
    def index():
        return FileResponse(ROOT / 'static/index.html')

    return app
