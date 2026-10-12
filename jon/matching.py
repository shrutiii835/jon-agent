import re


def contains(text, phrase):
    return bool(re.search(r'(?<!\w)' + re.escape(phrase.lower()) + r'(?!\w)', text.lower()))


def match(job, profile):
    title = job['title'].lower()
    body = title + ' ' + job['description'].lower()
    reasons, blockers, unknowns = [], [], []
    role = not profile.roles or any(contains(title, r) for r in profile.roles)
    if role:
        reasons.append('Target role matches' if profile.roles else 'No role restriction')
    else:
        blockers.append('Outside target roles')
    if profile.companies and not any(c.casefold() == job['company'].casefold() for c in profile.companies):
        blockers.append('Outside target companies')
    if profile.remote_only and not job.get('remote'):
        blockers.append('Remote work not confirmed')
    if profile.locations and not any(contains(job.get('location', ''), l) for l in profile.locations):
        blockers.append('Location does not match; check remote eligibility')
    if profile.job_types:
        if not job.get('job_type'):
            unknowns.append('Employment type unknown')
        elif job['job_type'].lower() not in [t.lower() for t in profile.job_types]:
            blockers.append('Employment type does not match')
    if profile.salary_min:
        comparable = job.get('salary_period') == 'year' and job.get('currency') == profile.currency and job.get('salary_max') is not None
        if comparable:
            if job['salary_max'] < profile.salary_min:
                blockers.append('Salary below minimum')
            else:
                reasons.append('Salary range may meet minimum')
        else:
            unknowns.append('Salary unknown or not comparable; no currency conversion assumed')
            if not profile.allow_unknown_salary:
                blockers.append('Comparable salary required')
    matched = [s for s in profile.skills if contains(body, s)]
    missing = [s for s in profile.skills if not contains(body, s)]
    score = round((50 if role else 0) + (50 * len(matched) / len(profile.skills) if profile.skills else 0))
    return {'score': score, 'eligible': not blockers, 'reasons': reasons, 'blockers': blockers, 'unknowns': unknowns, 'matched_skills': matched, 'other_skills': missing}
