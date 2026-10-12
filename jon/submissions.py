"""Fail-closed application submission for employer-authorized Greenhouse boards."""
import json
import os
import re
import httpx
from .connectors import read_json


def board_key(board):
    try:
        keys = json.loads(os.environ.get('JON_GREENHOUSE_KEYS', '{}'))
        return keys.get(board) if isinstance(keys, dict) else None
    except (ValueError, AttributeError):
        return None


async def preflight(job, profile, client):
    if job.get('provider') != 'greenhouse' or not board_key(job.get('board')):
        return 'This source requires a browser handoff. No employer-authorized submission credential is configured.'
    if not re.fullmatch(r'[0-9]+', job.get('external_id', '')):
        return 'Unsupported job identifier.'
    url = f"https://boards-api.greenhouse.io/v1/boards/{job['board']}/jobs/{job['external_id']}?questions=true"
    detail = await read_json(client, url)
    if not detail.get('questions'):
        return 'Application questions could not be verified. Use the employer form.'
    if detail.get('data_compliance') or detail.get('demographic_questions'):
        return 'This form contains consent or demographic questions. Complete them yourself on the employer form.'
    fields = {'first_name', 'last_name', 'email', 'phone', 'resume', 'resume_text'}
    for q in detail.get('questions', []) + detail.get('location_questions', []):
        if not q.get('required'):
            continue
        names = {f.get('name') for f in q.get('fields', [])}
        if not names or not names <= fields:
            return 'The form has additional required questions. Use the browser handoff.'
        if 'phone' in names and not profile.get('phone'):
            return 'A phone number is required. Update your profile and regenerate the draft.'
    if not profile.get('email') or len(profile.get('name', '').split()) < 2:
        return 'This adapter needs an email and first/last name. Use the employer form if your name does not fit those fields.'
    return None


async def send(job, snapshot, resume, client):
    p = snapshot['profile']
    first, last = p['name'].split(' ', 1)
    payload = {'first_name':first, 'last_name':last, 'email':p['email'], 'phone':p.get('phone', ''), 'resume_text':resume}
    url = f"https://boards-api.greenhouse.io/v1/boards/{job['board']}/jobs/{job['external_id']}"
    # Deliberately no automatic retry for a mutating request.
    response = await client.post(url, json=payload, auth=httpx.BasicAuth(board_key(job['board']), ''))
    if response.status_code != 200:
        return 'unknown', f'Provider returned HTTP {response.status_code}. Verify the outcome on the employer site; no automatic retry.'
    return 'submitted', 'Greenhouse acknowledged the application with HTTP 200. This is not a hiring outcome.'
