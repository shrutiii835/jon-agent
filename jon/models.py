import re
from urllib.parse import urlsplit
from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator


def public_url(value: str) -> str:
    import ipaddress
    p = urlsplit(value)
    if p.scheme != 'https' or not p.hostname or p.username or p.password:
        raise ValueError('Use a public HTTPS URL without credentials.')
    host = p.hostname.lower()
    if host == 'localhost' or '.' not in host or host.endswith(('.local', '.internal')):
        raise ValueError('Private URLs are not allowed.')
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return value
    if not ip.is_global:
        raise ValueError('Private addresses are not allowed.')
    return value


class Profile(BaseModel):
    name: str = Field(default='', max_length=120)
    email: str = Field(default='', max_length=200)
    phone: str = Field(default='', max_length=50)
    location: str = Field(default='', max_length=150)
    roles: list[str] = Field(default_factory=list, max_length=20)
    locations: list[str] = Field(default_factory=list, max_length=20)
    companies: list[str] = Field(default_factory=list, max_length=30)
    skills: list[str] = Field(default_factory=list, max_length=80)
    job_types: list[str] = Field(default_factory=list, max_length=10)
    remote_only: bool = False
    salary_min: int = Field(default=0, ge=0, le=100000000)
    currency: str = Field(default='INR', pattern=r'^[A-Z]{3}$')
    allow_unknown_salary: bool = True

    @field_validator('roles', 'locations', 'companies', 'skills', 'job_types')
    @classmethod
    def clean_lists(cls, values):
        if any(len(v) > 120 for v in values):
            raise ValueError('List entries must be at most 120 characters.')
        return list(dict.fromkeys(v.strip() for v in values if v.strip()))

    @field_validator('email')
    @classmethod
    def email_shape(cls, value):
        if value and not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', value):
            raise ValueError('Enter a valid email address.')
        return value


class Source(BaseModel):
    provider: Literal['greenhouse', 'lever', 'ashby']
    board: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9_-]{0,99}$')
    company: str = Field(min_length=1, max_length=150)


class Evidence(BaseModel):
    category: Literal['experience', 'project', 'education', 'achievement'] = 'project'
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=10, max_length=5000)
    source: str = Field(default='User supplied', max_length=1000)
    verified: bool = False


class JobInput(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    company: str = Field(min_length=1, max_length=150)
    location: str = Field(default='', max_length=300)
    description: str = Field(min_length=20, max_length=60000)
    url: str = Field(max_length=2000)
    job_type: str = Field(default='', max_length=100)
    remote: bool = False
    salary_min: float | None = Field(default=None, ge=0)
    salary_max: float | None = Field(default=None, ge=0)
    currency: str = Field(default='', max_length=3)
    salary_period: Literal['year', 'month', 'hour', 'unknown'] = 'unknown'

    @field_validator('url')
    @classmethod
    def validate_url(cls, value):
        return public_url(value)

    @model_validator(mode='after')
    def salary_order(self):
        if self.salary_min is not None and self.salary_max is not None and self.salary_min > self.salary_max:
            raise ValueError('Salary maximum must be at least the minimum.')
        return self


class GithubImport(BaseModel):
    username: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9-]{0,38}$')


class DraftRequest(BaseModel):
    use_model: bool = False


class Outcome(BaseModel):
    status: Literal['submitted_manual', 'interview', 'offer', 'rejected', 'withdrawn']
    note: str = Field(min_length=5, max_length=2000)


class Revision(BaseModel):
    text: str = Field(min_length=30, max_length=40000)
