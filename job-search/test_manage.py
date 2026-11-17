"""Offline checks: never populate the real campaign with test applications."""
from datetime import datetime, timezone
from io import StringIO
import json
from manage import validate, read_events, summarize

base = dict(id='test-1',kind='submitted',application_id='test-company-role',company='Test Company',
            role='Engineer',url='https://example.com/role',channel='direct',at='2026-01-01T00:00:00+00:00',
            evidence=['test fixture only'],confirmation='fixture',resume_variant='v1',resume_sha256='a'*64,
            project_ids=['example-project'],answers_file='fixture.json',minutes=5)
validate(base, [])
assert len(read_events(StringIO(json.dumps(base)+'\n'))) == 1

def fails(event, prior):
    try:
        validate(event, prior)
    except ValueError:
        return
    raise AssertionError('Expected refusal')

fails(dict(base, id='test-2'), [base])
fails({k:v for k,v in base.items() if k != 'confirmation'}, [])
fails(dict(base, at='2026-01-01'), [])
sent = dict(base, id='sent', kind='outreach_sent', recipient='test@example.com', message_sha256='b'*64)
fails(sent, [])
approved = dict(sent, id='approved', kind='outreach_approved')
validate(sent, [approved])
fails(dict(sent, recipient='different@example.com'), [approved])
auto = dict(base,id='auto',kind='reply',human=False,at='2026-01-02T00:00:00+00:00')
human = dict(auto,id='human',human=True)
old = datetime(2026,2,1,tzinfo=timezone.utc)
assert summarize([base,auto],old)['human_replies_mature'] == 0
assert summarize([base,human],old)['human_replies_mature'] == 1
assert summarize([base,human],datetime(2026,1,3,tzinfo=timezone.utc))['pending_window'] == 1
assert summarize([],old)['submitted'] == 0
print('PASS: duplicate, receipt, timezone, exact approval, acknowledgement, and maturity checks')
