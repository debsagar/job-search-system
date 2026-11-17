"""Synthetic lifecycle rehearsal; all files stay in a temporary directory."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import flow

def rejects(fn):
    try: fn()
    except ValueError: return
    raise AssertionError('Expected hold')

with TemporaryDirectory() as tmp:
    base=Path(tmp); flow.ROOT=base/'job-search'; flow.ROOT.mkdir()
    flow.write(flow.ROOT/'profile.json',{'name':'Fixture Candidate'})
    flow.write(base/'WORK_DOSSIER.json',{'projects':[{'id':'fixture','selection_status':'usable'}]})
    job={'company':'Fixture Labs','role':'Research Engineer','url':'https://example.com/job?utm_source=test',
         'jd_text':'Synthetic role, never contact this employer.', 'source_evidence':['synthetic fixture'],
         'eligibility':{k:{'pass':True,'evidence':'fixture'} for k in ['location','required_qualifications','open_role']},'fit':'Synthetic test only'}
    flow.write(flow.ROOT/'policy.json', {'excluded_employers':['Fixture Labs'], 'excluded_titles':[]})
    rejects(lambda: flow.check_fit(job))
    flow.write(flow.ROOT/'policy.json', {'excluded_employers':[], 'excluded_titles':['Research']})
    rejects(lambda: flow.check_fit(job))
    flow.write(flow.ROOT/'policy.json', {'excluded_employers':[], 'excluded_titles':[]})
    flow.check_fit(job)
    app=flow.ingest(job)['application_id']
    assert flow.ingest(dict(job,url='https://example.com/job'))['existing']
    pdf=base/'resume.pdf'
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] >>']
    body=b'%PDF-1.4\n'; offsets=[]
    for n,obj in enumerate(objects,1):
        offsets.append(len(body)); body+=f'{n} 0 obj\n'.encode()+obj+b'\nendobj\n'
    start=len(body); body+=b'xref\n0 4\n0000000000 65535 f \n'
    for offset in offsets: body+=f'{offset:010} 00000 n \n'.encode()
    body+=f'trailer\n<< /Size 4 /Root 1 0 R >>\nstartxref\n{start}\n%%EOF\n'.encode()
    pdf.write_bytes(body)
    prep={'project_ids':['fixture'],'resume_path':str(pdf),'resume_variant':'fixture-v1',
          'visual_review_evidence':'fixture review','claim_review_evidence':'fixture claims',
          'answers':[{'field':'name','value':'Fixture Candidate','required':True,'source':'profile.name'}]}
    flow.prepare(app,prep)
    obs={'job_url':'https://example.com/job','observed_at':flow.now(),'page_complete':True,'snapshot_ref':'fixture snapshot',
         'values':{'name':'Fixture Candidate'},'blockers':[],'missing_required':[],
         'attached_resume_sha256':flow.digest(pdf.read_bytes()),'attachment_evidence':'fixture attachment'}
    assert not flow.verify(app,dict(obs,values={'name':'Wrong'}))['ready']
    rejects(lambda:flow.intent(app))
    assert flow.verify(app,obs)['ready']
    flow.remember({'type':'answer','question':'Name?','value':'Fixture Candidate','source':'profile.name','reusable':True})
    assert flow.recall('Name?')['answer']
    flow.write(flow.ROOT/'profile.json',{'name':'Changed Fixture'})
    assert flow.recall('Name?')['answer'] is None
    rejects(lambda:flow.intent(app))
    flow.write(flow.ROOT/'profile.json',{'name':'Fixture Candidate'})
    flow.intent(app)
    rejects(lambda:flow.intent(app))
    flow.receipt(app,{'state':'unknown','evidence':['timeout fixture']})
    rejects(lambda:flow.prepare(app,prep))
    flow.receipt(app,{'state':'not_submitted','evidence':['fixture: employer confirms no application']})
    flow.verify(app,dict(obs,observed_at=flow.now()))
    flow.intent(app)
    flow.receipt(app,{'state':'submitted','evidence':['fixture receipt'],'confirmation':'Synthetic success','minutes':2})
    rejects(lambda:flow.intent(app))
    app2=flow.ingest(dict(job,url='https://example.com/other',company='Fixture labs'))['application_id']
    rejects(lambda:flow.prepare(app2,prep))
    flow.remember({'type':'site','url':'https://example.com/job','control':'phone','method':'type','worked':True,'evidence':'fixture'})
    assert 'phone' in flow.recall(url='https://example.com/job')['successful_methods']
    flow.remember({'type':'site','url':'https://example.com/job','control':'phone','method':'type','worked':False,'evidence':'new fixture'})
    assert not flow.recall(url='https://example.com/job')['successful_methods']
    summary=flow.manage.summarize(flow.events())
    assert summary['submitted']==1 and summary['pending_window']==1
print('PASS: ingest dedupe, PDF packet, wrong-value hold, stale-profile hold, memory invalidation, uncertain-click recovery, receipt, employer dedupe, failed-method retirement')
