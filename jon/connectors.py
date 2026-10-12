"""Read-only connectors. Remote content is data, never instructions."""
import asyncio
import hashlib
import html
from html.parser import HTMLParser
import httpx
from .models import JobInput

MAX_RESPONSE = 8_000_000


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
    def handle_data(self, data):
        self.parts.append(data)


def plain(value):
    parser = TextParser()
    parser.feed(html.unescape(value or ''))
    return html.unescape(' '.join(parser.parts)).strip()[:60000]


async def read_json(client, url, headers=None):
    # Only code-constructed URLs on fixed API hosts reach here. Redirects disabled.
    for attempt in range(3):
        async with client.stream('GET', url, headers=headers) as response:
            if response.status_code in (429, 502, 503, 504) and attempt < 2:
                await asyncio.sleep(min(2 ** attempt, 4))
                continue
            response.raise_for_status()
            chunks, size = [], 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > MAX_RESPONSE:
                    raise ValueError('Provider response exceeds safety limit.')
                chunks.append(chunk)
            import json
            return json.loads(b''.join(chunks))


def normalize(source, raw):
    p = source['provider']
    common = {'company': source['company'], 'salary_period': 'unknown'}
    if p == 'greenhouse':
        values = dict(title=raw['title'], location=raw.get('location', {}).get('name', ''), description=plain(raw.get('content', '')), url=raw['absolute_url'])
    elif p == 'lever':
        cats = raw.get('categories', {})
        desc = raw.get('descriptionPlain') or plain(raw.get('description', ''))
        for section in raw.get('lists', []):
            desc += '\n' + section.get('text', '') + '\n' + plain(section.get('content', ''))
        values = dict(title=raw['text'], location=cats.get('location', ''), description=desc, url=raw.get('applyUrl') or raw['hostedUrl'], job_type=cats.get('commitment', ''), remote=raw.get('workplaceType') == 'remote')
        salary = raw.get('salaryRange') or {}
        if salary:
            common.update(salary_min=salary.get('min'), salary_max=salary.get('max'), currency=salary.get('currency', ''), salary_period='year' if salary.get('interval') in ('per-year-salary', 'year') else 'unknown')
    else:
        values = dict(title=raw['title'], location=raw.get('location', ''), description=raw.get('descriptionPlain') or plain(raw.get('descriptionHtml', '')), url=raw.get('applyUrl') or raw['jobUrl'], job_type={'FullTime':'Full-time','PartTime':'Part-time','Intern':'Internship','Contract':'Contract','Temporary':'Temporary'}.get(raw.get('employmentType'), raw.get('employmentType', '')), remote=raw.get('isRemote', False))
        salaries = [c for c in (raw.get('compensation') or {}).get('summaryComponents', []) if c.get('compensationType') == 'Salary' and c.get('interval') == '1 YEAR']
        if len(salaries) == 1:
            salary = salaries[0]
            common.update(salary_min=salary.get('minValue'), salary_max=salary.get('maxValue'), currency=salary.get('currencyCode') or '', salary_period='year')
    if p == 'greenhouse':
        # A location label is weak evidence; only a dedicated remote label counts.
        values['remote'] = values['location'].strip().lower() == 'remote'
    if len(values['description']) < 20:
        values['description'] += '\nFull details are available at the original listing.'
    data = JobInput(**(common | values)).model_dump()
    raw_id = str(raw.get('id') or hashlib.sha256(data['url'].encode()).hexdigest()[:24])
    data.update(id=f"{p}:{source['board']}:{raw_id}", provider=p, board=source['board'], external_id=raw_id)
    return data


async def discover(source, client):
    p, b = source['provider'], source['board']
    urls = {
        'greenhouse': f'https://boards-api.greenhouse.io/v1/boards/{b}/jobs?content=true',
        'lever': f'https://api.lever.co/v0/postings/{b}?mode=json',
        'ashby': f'https://api.ashbyhq.com/posting-api/job-board/{b}?includeCompensation=true',
    }
    payload = await read_json(client, urls[p])
    items = payload if p == 'lever' else payload['jobs']
    jobs, skipped = [], 0
    for item in items[:3000]:
        if p == 'ashby' and item.get('isListed') is False:
            continue
        try:
            jobs.append(normalize(source, item))
        except (ValueError, KeyError, TypeError):
            skipped += 1
    return jobs, skipped


async def github_evidence(username, token=''):
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'Jon-job-workspace'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
        repos = await read_json(client, f'https://api.github.com/users/{username}/repos?sort=updated&per_page=30', headers)
        results = []
        for repo in repos:
            if repo.get('fork') or repo.get('archived'):
                continue
            # Repository metadata is not proof of personal authorship. Review required.
            text = f"Repository: {repo['name']}. Description: {repo.get('description') or 'No description provided'}. Primary language: {repo.get('language') or 'Unspecified'}."
            results.append(dict(category='project', title=repo['name'], text=text, source=repo['html_url'], verified=False))
        return results
