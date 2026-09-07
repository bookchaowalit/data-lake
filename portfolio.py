"""Consume explicit domain CLIs; no direct scraper imports or external messages."""
import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from discovery.profile import enrich, load_profile

ROOT=Path(__file__).resolve().parents[3]


def select_items(payload, now, *, open_only=False, query='', max_age_hours=72, starting_within_days=None, upcoming_within_days=None):
    if starting_within_days is not None and starting_within_days < 0:
        raise ValueError('starting window must be nonnegative')
    if upcoming_within_days is not None and upcoming_within_days < 0:
        raise ValueError('upcoming window must be nonnegative')
    selected=[]
    for item in payload['items']:
        checked=datetime.fromisoformat(item['provenance']['checked_at'].replace('Z','+00:00'))
        fresh=timedelta(0) <= now-checked <= timedelta(hours=max_age_hours)
        deadline=item['deadline']
        deadline_at=deadline.get('at') if deadline['kind']=='fixed' else None
        deadline_time=datetime.fromisoformat(deadline_at.replace('Z','+00:00')) if deadline_at else None
        expired=bool(deadline_time and deadline_time <= now)
        days_until_deadline=((deadline_time-now).total_seconds()/86400) if deadline_time else None
        availability=item.get('availability') or {}
        starts_at=availability.get('starts_at')
        start_time=datetime.fromisoformat(starts_at.replace('Z','+00:00')) if starts_at else None
        not_started=bool(start_time and start_time > now)
        days_until_start=((start_time-now).total_seconds()/86400) if start_time else None
        if query.casefold() not in (item['title']+' '+item['category']).casefold():continue
        if starting_within_days is not None and (days_until_start is None or days_until_start < 0 or days_until_start > starting_within_days):continue
        if upcoming_within_days is not None:
            starts_soon=days_until_start is not None and 0 <= days_until_start <= upcoming_within_days
            deadline_soon=days_until_deadline is not None and 0 <= days_until_deadline <= upcoming_within_days
            if not (starts_soon or deadline_soon):continue
        continuous_unknown_deadline = deadline['kind']=='unknown' and availability.get('kind')=='continuous'
        if open_only and (not fresh or expired or not_started or item['status']!='open' or (deadline['kind']=='unknown' and not continuous_unknown_deadline) or item['record_kind']=='directory'):continue
        label='scheduled' if not_started else ('expired' if expired else item['status'])
        row={'schema_version':payload['schema_version'], 'product':payload['source'], 'freshness':'fresh' if fresh else 'stale', 'availability':label, 'item':item}
        if starts_at:
            row['availability_starts_at']=starts_at
            row['days_until_start']=round(days_until_start, 2)
        if deadline_at:
            row['deadline_at']=deadline_at
            row['days_until_deadline']=round(days_until_deadline, 2)
        if upcoming_within_days is not None:
            row['queue_reasons']=[reason for reason, matched in (
                ('availability_start', days_until_start is not None and 0 <= days_until_start <= upcoming_within_days),
                ('deadline', days_until_deadline is not None and 0 <= days_until_deadline <= upcoming_within_days),
            ) if matched]
        selected.append(row)
    return selected


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['acquire','list','queue','status'])
    parser.add_argument('--domain')
    parser.add_argument('--query',default='')
    parser.add_argument('--open-only',action='store_true')
    parser.add_argument('--profile', help='Explicit private discovery.profile.v1 JSON; never persisted')
    parser.add_argument('--deadline-within-days', type=int, help='Keep fixed deadlines within this future window')
    parser.add_argument('--starting-within-days', type=int, help='Keep scheduled availability starts within this future window')
    parser.add_argument('--upcoming-within-days', type=int, help='Keep records with a future availability start or fixed deadline within this window')
    args=parser.parse_args(argv)
    if args.starting_within_days is not None and args.starting_within_days < 0:
        parser.error('--starting-within-days must be nonnegative')
    if args.upcoming_within_days is not None and args.upcoming_within_days < 0:
        parser.error('--upcoming-within-days must be nonnegative')
    if args.command == 'queue' and args.starting_within_days is not None and args.upcoming_within_days is not None:
        parser.error('queue accepts one of --upcoming-within-days or --starting-within-days')
    if args.command == 'queue' and args.upcoming_within_days is None:
        args.upcoming_within_days = args.starting_within_days if args.starting_within_days is not None else 30
        args.starting_within_days = None
    manifest=json.loads((ROOT/'systems/architecture/discovery-portfolio-v1.json').read_text())
    products=[p for p in manifest['products'] if p.get('live_sources_enabled') and (not args.domain or p['domain']==args.domain)]
    if not products:parser.error('no enabled source pilot for this domain')
    result={'contract':'discovery.portfolio.v1','command':args.command,'sources':[],'items':[]}
    now=datetime.now(timezone.utc)
    if args.profile:
        profile_path = Path(args.profile)
        if not profile_path.is_absolute() and not profile_path.exists():
            profile_path = ROOT / profile_path
        profile = load_profile(profile_path)
    else:
        profile = None
    for product in products:
        repo=(ROOT/product['local_path']).resolve()
        if not repo.is_relative_to(ROOT/'projects/product/engineering/book-dev'):
            raise ValueError('product outside portfolio boundary')
        command='records' if args.command in {'list','queue'} else args.command
        module=product['id'].replace('-','_')+'.capture'
        source_ids=product.get('enabled_source_ids') or [None]
        for source_id in source_ids:
            invocation=[sys.executable,'-m',module,command,'--lake',str(repo/'data/lake'),'--state-dir',str(repo/'data/control')]
            if source_id is not None:
                invocation.extend(['--source-id',source_id])
            try:
                run=subprocess.run(invocation,cwd=repo,env={**os.environ,'PYTHONPATH':str(repo/'src'),'SOLO_EMPIRE_ROOT':str(ROOT)},capture_output=True,text=True,timeout=90)
            except (OSError, subprocess.TimeoutExpired):
                result['sources'].append({'product':product['id'],'source_id':source_id,'status':'unavailable'})
                continue
            if run.returncode:
                result['sources'].append({'product':product['id'],'source_id':source_id,'status':'unavailable'})
                continue
            try:
                payload=json.loads(run.stdout)
            except json.JSONDecodeError:
                result['sources'].append({'product':product['id'],'source_id':source_id,'status':'invalid-output'})
                continue
            if args.command in {'list','queue'}:
                if payload.get('schema_version') != product['live_schema_version'] or payload.get('source') != product['id'] or payload.get('data_status') != 'live':
                    result['sources'].append({'product':product['id'],'source_id':source_id,'status':'invalid-contract'})
                    continue
                result['sources'].append({'product':product['id'],'source_id':source_id,'status':'ok','checked_at':payload['retrieved_at']})
                result['items'].extend(select_items(payload,now,open_only=args.open_only,query=args.query,starting_within_days=args.starting_within_days,upcoming_within_days=args.upcoming_within_days))
            else:
                result['sources'].append({'product':product['id'],'source_id':source_id,'status':'unavailable',**payload})
    if args.command == 'queue':
        result['items'].sort(key=lambda row:min(value for value in (row.get('availability_starts_at'),row.get('deadline_at')) if value) if row.get('availability_starts_at') or row.get('deadline_at') else '9999')
        result['queue']={'window_days':args.upcoming_within_days,'matches':'future availability starts or fixed deadlines'}
    else:
        result['items'].sort(key=lambda row:(row['item']['deadline']['at'] or '9999',row['item']['title']))
    if profile is not None:
        result['items'] = enrich(result['items'], profile, now=now, deadline_within_days=args.deadline_within_days)
        result['matching'] = {'profile_version': profile['profile_version'], 'stored': False, 'interpretation': 'triage only; verify official terms'}
    elif args.deadline_within_days is not None:
        raise ValueError('--deadline-within-days requires --profile')
    result['partial']=any(s.get('status') in {'unavailable','invalid-output','invalid-contract','failed','quarantined'} for s in result['sources'])
    print(json.dumps(result,indent=2,ensure_ascii=False))
    return 1 if result['partial'] else 0


if __name__=='__main__':raise SystemExit(main())
