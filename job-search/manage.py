"""Local campaign records. No network calls or application submission."""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path

ROOT = Path(os.environ.get('JOB_SEARCH_HOME', str(Path(__file__).resolve().parent.parent / 'private' / 'job-search'))).expanduser().resolve()
KINDS = {'verified', 'submission_intent', 'not_submitted', 'discovered', 'prepared', 'blocked', 'skipped', 'submitted', 'submission_unknown',
         'outreach_drafted', 'outreach_approved', 'outreach_sent', 'reply', 'screen',
         'interview', 'offer', 'rejected', 'withdrawn', 'note'}


def validate(event, previous):
    for key in ('id', 'kind', 'application_id', 'company', 'role', 'url', 'channel', 'at', 'evidence'):
        if not event.get(key):
            raise ValueError(f'Missing {key}')
    if event['kind'] not in KINDS:
        raise ValueError('Unknown kind')
    if not isinstance(event['evidence'], list) or not all(isinstance(v, str) and v.strip() for v in event['evidence']):
        raise ValueError('Evidence must contain paths, receipt text, or source URLs')
    if not event['url'].startswith(('https://', 'http://')):
        raise ValueError('Expected HTTP(S) role URL')
    stamp = datetime.fromisoformat(event['at'])
    if stamp.tzinfo is None:
        raise ValueError('Timestamp needs timezone')
    if any(p['id'] == event['id'] for p in previous):
        raise ValueError('Duplicate event id')
    related = [p for p in previous if p['application_id'] == event['application_id']]
    if related and any(event[k] != related[0][k] for k in ('company', 'role', 'url', 'channel')):
        raise ValueError('Application identity/channel changed; use a note to explain corrections')
    if related and stamp < max(datetime.fromisoformat(p['at']) for p in related):
        raise ValueError('Record events in chronological order')
    if event['kind'] == 'submitted':
        for key in ('confirmation', 'resume_variant', 'resume_sha256', 'project_ids', 'answers_file', 'minutes'):
            if key not in event or event[key] in (None, '', []):
                raise ValueError(f'Submission needs {key}')
        digest = event['resume_sha256']
        if not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
            raise ValueError('Expected SHA256 hex digest')
        if not isinstance(event['minutes'], (int, float)) or event['minutes'] < 0:
            raise ValueError('Minutes must be nonnegative')
        company = event['company'].strip().casefold()
        if any(p['kind'] == 'submitted' and p['company'].strip().casefold() == company for p in previous):
            raise ValueError('Company already submitted in this campaign')
    if event['kind'] in {'outreach_approved', 'outreach_sent'}:
        for key in ('recipient', 'message_sha256'):
            if not event.get(key):
                raise ValueError(f'Outreach needs {key}')
    if event['kind'] == 'outreach_sent':
        if not any(p['kind'] == 'outreach_approved' and p.get('recipient') == event['recipient']
                   and p.get('message_sha256') == event['message_sha256'] for p in related):
            raise ValueError('Exact message/recipient approval missing')
    if event['kind'] == 'reply' and not isinstance(event.get('human'), bool):
        raise ValueError('Reply must distinguish human from acknowledgement')


def read_events(handle):
    events = []
    for number, line in enumerate(handle, 1):
        if line.strip():
            event = json.loads(line)
            try:
                validate(event, events)
            except (ValueError, TypeError) as exc:
                raise ValueError(f'Line {number}: {exc}') from exc
            events.append(event)
    return events


def summarize(events, now=None):
    now = now or datetime.now(timezone.utc)
    groups = defaultdict(list)
    for event in events:
        groups[event['application_id']].append(event)
    result = {'applications_seen': len(groups), 'submitted': 0, 'mature_14d': 0,
              'pending_window': 0, 'human_replies_mature': 0, 'screens': 0,
              'interviews': 0, 'offers': 0, 'submission_unknown': 0,
              'submission_minutes': 0, 'by_channel': {}}
    for history in groups.values():
        submissions = [e for e in history if e['kind'] == 'submitted']
        resolved = {e.get('intent_id') for e in history if e['kind'] == 'not_submitted'}
        result['submission_unknown'] += int(not submissions and any(e['kind'] in {'submission_unknown', 'submission_intent'} and (e.get('intent_id') or e['id']) not in resolved for e in history))
        if not submissions:
            continue
        event = submissions[0]
        mature = (now - datetime.fromisoformat(event['at'])).days >= 14
        replied = any(e['kind'] == 'reply' and e.get('human') is True for e in history)
        result['submitted'] += 1
        result['mature_14d'] += int(mature)
        result['pending_window'] += int(not mature)
        result['human_replies_mature'] += int(mature and replied)
        result['submission_minutes'] += event['minutes']
        for kind, key in [('screen', 'screens'), ('interview', 'interviews'), ('offer', 'offers')]:
            result[key] += int(any(e['kind'] == kind for e in history))
        channel = result['by_channel'].setdefault(event['channel'], {'submitted': 0, 'mature_14d': 0, 'human_replies_mature': 0})
        channel['submitted'] += 1
        channel['mature_14d'] += int(mature)
        channel['human_replies_mature'] += int(mature and replied)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['add', 'check', 'report'])
    parser.add_argument('input', nargs='?', type=Path)
    args = parser.parse_args()
    ROOT.mkdir(parents=True, exist_ok=True)
    path = ROOT / 'events.jsonl'
    with path.open('a+', encoding='utf-8') as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        events = read_events(handle)
        if args.command == 'add':
            if args.input is None:
                parser.error('add requires an event JSON file')
            event = json.loads(args.input.read_text())
            event.setdefault('at', datetime.now(timezone.utc).isoformat())
            validate(event, events)
            handle.seek(0, 2)
            handle.write(json.dumps(event, ensure_ascii=False) + '\n')
            print(f"Recorded {event['id']}")
        elif args.command == 'check':
            print(f'{len(events)} valid events')
        else:
            print(json.dumps(summarize(events), indent=2))


if __name__ == '__main__':
    main()
