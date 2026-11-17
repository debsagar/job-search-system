"""Application packets and recovery. T3 performs browser actions; this CLI never clicks Submit."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
from urllib.request import urlopen, Request
from uuid import uuid4
import manage

CODE = Path(__file__).resolve().parent
ROOT = Path(os.environ.get('JOB_SEARCH_HOME', str(CODE.parent / 'private' / 'job-search'))).expanduser().resolve()

def now():
    return datetime.now(timezone.utc).isoformat()

def digest(value):
    return hashlib.sha256(value).hexdigest()

def read(path):
    return json.loads(Path(path).read_text())

def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    os.replace(tmp, path)

def fingerprint():
    return digest((ROOT / 'profile.json').read_bytes())

def canonical(url):
    p = urlsplit(url)
    if p.scheme != 'https' or not p.hostname or p.username or p.password:
        raise ValueError('Expected public HTTPS job URL without credentials')
    query = [(k, v) for k, v in parse_qsl(p.query) if not k.lower().startswith('utm_') and k not in {'source','ref','gh_src'}]
    return urlunsplit(('https', p.netloc.lower(), p.path.rstrip('/'), urlencode(sorted(query)), ''))

def company_key(name):
    return re.sub(r'[^a-z0-9]', '', name.casefold())

@contextmanager
def locked():
    ROOT.mkdir(parents=True, exist_ok=True)
    with (ROOT / '.flow.lock').open('a') as h:
        fcntl.flock(h, fcntl.LOCK_EX)
        yield

def events():
    path = ROOT / 'events.jsonl'
    if not path.exists():
        return []
    with path.open() as h:
        return manage.read_events(h)

def packet(app_id):
    if not re.fullmatch(r'[a-z0-9-]+', app_id):
        raise ValueError('Invalid application id')
    return ROOT / 'applications' / app_id

def emit(app, kind, evidence, **extra):
    e = {k: app[k] for k in ('application_id','company','role','url','channel')}
    e.update(id=str(uuid4()), kind=kind, at=now(), evidence=evidence, **extra)
    # Same ledger lock used by manage.py, so independent add calls cannot interleave.
    with (ROOT / 'events.jsonl').open('a+') as h:
        fcntl.flock(h, fcntl.LOCK_EX)
        h.seek(0)
        prior = manage.read_events(h)
        manage.validate(e, prior)
        h.seek(0, 2)
        h.write(json.dumps(e, ensure_ascii=False) + '\n')
        h.flush()
        os.fsync(h.fileno())
    return e

def history(app):
    return [e for e in events() if e['application_id'] == app['application_id']]

def assert_available(app):
    relevant = [e for e in events() if company_key(e['company']) == company_key(app['company'])]
    if any(e['kind'] == 'submitted' for e in relevant):
        raise ValueError('Employer already has a confirmed application')
    intents = {e['id'] for e in relevant if e['kind'] == 'submission_intent'}
    resolved = {e.get('intent_id') for e in relevant if e['kind'] == 'not_submitted'}
    if intents - resolved or any(e['kind'] == 'submission_unknown' and not e.get('intent_id') for e in relevant):
        raise ValueError('Unresolved submission: reconcile the existing attempt before any retry')

def ingest(data):
    for k in ('company','role','url','jd_text','source_evidence','eligibility','fit'):
        if not data.get(k):
            raise ValueError(f'Missing {k}')
    if not isinstance(data['source_evidence'], list):
        raise ValueError('source_evidence must be a list')
    url = canonical(data['url'])
    ident = company_key(data['company'])[:32] + '-' + digest(url.encode())[:12]
    for e in events():
        if canonical(e['url']) == url:
            return {'application_id':e['application_id'], 'existing':True}
    app = dict(data, url=url, application_id=ident, channel=data.get('channel','direct'), discovered_at=now())
    write(packet(ident) / 'job.json', app)
    (packet(ident) / 'jd.txt').write_text(data['jd_text'])
    emit(app, 'discovered', data['source_evidence'])
    return {'application_id':ident, 'existing':False}

def check_fit(app):
    for gate in ('location','required_qualifications','open_role'):
        decision = app['eligibility'].get(gate, {})
        if decision.get('pass') is not True or not decision.get('evidence'):
            raise ValueError(f'Eligibility unresolved: {gate}')
    policy = read(ROOT / 'policy.json') if (ROOT / 'policy.json').exists() else {}
    exclusions = {company_key(name) for name in policy.get('excluded_employers', [])}
    if company_key(app['company']) in exclusions:
        raise ValueError('Excluded employer')
    if any(re.search(r'\b' + re.escape(title) + r'\b', app['role'], re.I) for title in policy.get('excluded_titles', [])):
        raise ValueError('Excluded seniority')
    if not app.get('fit'):
        raise ValueError('Written fit rationale missing')

def prepare(app_id, data):
    app = read(packet(app_id) / 'job.json')
    assert_available(app)
    check_fit(app)
    dossier = read(ROOT.parent / 'WORK_DOSSIER.json')
    cards = {p['id']:p for p in dossier['projects']}
    selected = data.get('project_ids', [])
    if not selected or any(i not in cards or cards[i].get('selection_status') != 'usable' for i in selected):
        raise ValueError('Select reviewed usable project IDs; resolve conditional cards in dossier first')
    source = Path(data['resume_path']).resolve()
    if source.suffix.lower() != '.pdf' or not source.read_bytes().startswith(b'%PDF'):
        raise ValueError('Expected a compiled PDF resume')
    info = subprocess.run(['pdfinfo', str(source)],check=True,capture_output=True,text=True).stdout
    if not re.search(r'^Pages:\s+1\s*$',info,re.M):
        raise ValueError('Resume must be one page')
    for key in ('visual_review_evidence','claim_review_evidence','resume_variant'):
        if not data.get(key):
            raise ValueError(f'Missing {key}')
    answers = data.get('answers', [])
    if not answers or len({a['field'] for a in answers}) != len(answers):
        raise ValueError('Answers need unique field identifiers')
    for a in answers:
        if not a.get('source') or 'value' not in a or a.get('required') not in (True, False):
            raise ValueError('Each answer needs field, value, required flag and source')
    destination = packet(app_id) / 'resume.pdf'
    if source != destination:
        shutil.copyfile(source, destination)
    data = dict(data, resume_path=str(destination), resume_sha256=digest(destination.read_bytes()),
                profile_sha256=fingerprint(), prepared_at=now())
    write(packet(app_id) / 'prepared.json', data)
    emit(app,'prepared',[str(packet(app_id)/'prepared.json')],project_ids=selected,resume_variant=data['resume_variant'])
    return {'prepared':app_id,'resume_sha256':data['resume_sha256']}

def current_materials(app_id, prepared):
    if prepared['profile_sha256'] != fingerprint():
        raise ValueError('Profile changed: prepare and verify again')
    if digest(Path(prepared['resume_path']).read_bytes()) != prepared['resume_sha256']:
        raise ValueError('Resume changed: prepare and verify again')

def verify(app_id, observation):
    app = read(packet(app_id)/'job.json')
    prepared = read(packet(app_id)/'prepared.json')
    assert_available(app)
    current_materials(app_id, prepared)
    errors = []
    if canonical(observation.get('job_url','')) != app['url']:
        errors.append('Wrong job identity')
    stamp = datetime.fromisoformat(observation['observed_at'])
    if stamp.tzinfo is None or not 0 <= (datetime.now(timezone.utc)-stamp).total_seconds() <= 600:
        errors.append('Read-back must be captured within 10 minutes')
    if observation.get('page_complete') is not True or not observation.get('snapshot_ref'):
        errors.append('Final-page snapshot missing')
    if observation.get('blockers'):
        errors.extend(observation['blockers'])
    for a in prepared['answers']:
        actual = observation.get('values', {}).get(a['field'])
        if actual != a['value']:
            errors.append('Value mismatch: '+a['field'])
    if observation.get('missing_required'):
        errors.append('Required fields remain empty')
    if observation.get('attached_resume_sha256') != prepared['resume_sha256'] or not observation.get('attachment_evidence'):
        errors.append('Resume attachment not verified')
    result = dict(observation, errors=errors, ready=not errors, verified_at=now(),
                  prepared_sha256=digest((packet(app_id)/'prepared.json').read_bytes()))
    write(packet(app_id)/'readback.json', result)
    emit(app,'verified' if not errors else 'blocked',[observation.get('snapshot_ref') or 'Missing snapshot'],errors=errors)
    return result

def intent(app_id):
    app = read(packet(app_id)/'job.json')
    assert_available(app)
    prepared = read(packet(app_id)/'prepared.json')
    current_materials(app_id, prepared)
    verified = read(packet(app_id)/'readback.json')
    age = (datetime.now(timezone.utc)-datetime.fromisoformat(verified['observed_at'])).total_seconds()
    if not verified['ready'] or not 0 <= age <= 600 or verified['prepared_sha256'] != digest((packet(app_id)/'prepared.json').read_bytes()):
        raise ValueError('Fresh passing read-back of current packet required')
    return emit(app,'submission_intent',[verified['snapshot_ref']],resume_sha256=prepared['resume_sha256'])

def receipt(app_id, data):
    app = read(packet(app_id)/'job.json')
    prior = history(app)
    active = [e for e in prior if e['kind']=='submission_intent' and not any(r.get('intent_id')==e['id'] and r['kind'] in {'submitted','not_submitted'} for r in prior)]
    if not active:
        raise ValueError('No unresolved submission intent')
    if data.get('state') not in {'submitted','not_submitted','unknown'} or not data.get('evidence'):
        raise ValueError('Receipt needs state and evidence')
    intent_id = active[-1]['id']
    kind = {'unknown':'submission_unknown'}.get(data['state'],data['state'])
    extra = {'intent_id':intent_id}
    if kind == 'submitted':
        prepared=read(packet(app_id)/'prepared.json')
        if not data.get('confirmation') or not isinstance(data.get('minutes'),(int,float)) or data['minutes']<0:
            raise ValueError('Confirmed receipt needs confirmation and nonnegative minutes')
        extra.update({k:prepared[k] for k in ('resume_variant','resume_sha256','project_ids')})
        extra.update(confirmation=data['confirmation'],minutes=data['minutes'],answers_file=str(packet(app_id)/'prepared.json'))
    result=emit(app,kind,data['evidence'],**extra)
    write(packet(app_id)/('receipt-'+result['id']+'.json'),data)
    return result

def remember(data):
    path=ROOT/'memory.json'
    memory=read(path) if path.exists() else {'answers':{},'sites':{}}
    if data['type']=='answer':
        if data.get('reusable') is not True or not data.get('source') or not data.get('question') or 'value' not in data:
            raise ValueError('Reusable answer needs question, value and source')
        memory['answers'][data['question'].strip().casefold()]=dict(data,profile_sha256=fingerprint(),at=now())
    elif data['type']=='site':
        host=urlsplit(canonical(data['url'])).hostname
        if not data.get('control') or not data.get('method') or not data.get('evidence') or not isinstance(data.get('worked'),bool):
            raise ValueError('Site lesson needs control, method, evidence and worked boolean')
        memory['sites'].setdefault(host,{})[data['control']]=dict(data,at=now())
    else:
        raise ValueError('Memory type must be answer or site')
    write(path,memory)
    return {'saved':data['type']}

def recall(question='',url=''):
    memory=read(ROOT/'memory.json') if (ROOT/'memory.json').exists() else {'answers':{},'sites':{}}
    answer=memory['answers'].get(question.strip().casefold())
    if answer and answer['profile_sha256']!=fingerprint():
        answer=None
    site=memory['sites'].get(urlsplit(url).hostname,{})
    return {'answer':answer,'successful_methods':{k:v for k,v in site.items() if v['worked']}}

def queue():
    result=[]
    for path in sorted((ROOT/'applications').glob('*/job.json')):
        app=read(path)
        h=history(app)
        result.append({k:app[k] for k in ('application_id','company','role','url')} | {'status':h[-1]['kind'] if h else 'unrecorded'})
    return result

def fetch_board(url):
    p=urlsplit(url)
    allowed = (p.hostname=='api.ashbyhq.com' and p.path.startswith('/posting-api/job-board/')) or (p.hostname=='boards-api.greenhouse.io' and p.path.startswith('/v1/boards/') and p.path.endswith('/jobs'))
    if p.scheme!='https' or not allowed or p.username or p.password:
        raise ValueError('Use public Ashby or Greenhouse job-list API URLs only')
    with urlopen(Request(url,headers={'User-Agent':'JobSearchSystem/1.0'}),timeout=30) as response:
        if urlsplit(response.url).hostname!=p.hostname:
            raise ValueError('Unexpected redirect')
        data=json.load(response)
    return {'source':url,'fetched_at':now(),'jobs':data.get('jobs',[])}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['ingest','prepare','verify','intent','receipt','remember','recall','queue','fetch'])
    parser.add_argument('arguments',nargs='*')
    args=parser.parse_args(); a=args.arguments
    try:
        with locked():
            if args.command=='ingest': result=ingest(read(a[0]))
            elif args.command=='prepare': result=prepare(a[0],read(a[1]))
            elif args.command=='verify': result=verify(a[0],read(a[1]))
            elif args.command=='intent': result=intent(a[0])
            elif args.command=='receipt': result=receipt(a[0],read(a[1]))
            elif args.command=='remember': result=remember(read(a[0]))
            elif args.command=='recall': result=recall(a[0] if a else '',a[1] if len(a)>1 else '')
            elif args.command=='queue': result=queue()
            else: result=fetch_board(a[0])
        print(json.dumps(result,indent=2,ensure_ascii=False))
        if args.command == 'receipt':
            # Receipt is already durable: a reporting failure must not invite resubmission.
            python = sys.executable
            try:
                subprocess.run([str(python), str(CODE / 'export_sheet.py')], capture_output=True, text=True, check=True)
            except (OSError, subprocess.CalledProcessError):
                print('Sheet refresh failed; receipt remains recorded. Run export_sheet.py separately.', file=sys.stderr)
    except (ValueError,KeyError,IndexError,FileNotFoundError) as exc:
        parser.exit(1,f'Hold: {exc}\n')

if __name__=='__main__':
    main()
