"""Optional read-only smoke test. Does not store data or submit applications."""
import asyncio
import json
import httpx
from jon.connectors import discover


async def main():
    async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
        jobs, skipped = await discover({'provider':'greenhouse','board':'stripe','company':'Stripe'}, client)
        print(json.dumps({'provider':'greenhouse','jobs_received':len(jobs),'skipped':skipped,'sample_titles':[j['title'] for j in jobs[:3]]}))
        if not jobs:
            raise SystemExit('Live discovery returned no jobs.')


if __name__ == '__main__':
    asyncio.run(main())
