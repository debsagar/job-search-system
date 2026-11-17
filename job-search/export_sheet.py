"""Export the application ledger to a private workbook; never submit anything."""
import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from flow import ROOT
ROOT.mkdir(parents=True, exist_ok=True)
read = lambda p: json.loads(p.read_text())
events = [json.loads(line) for line in (ROOT / 'events.jsonl').read_text().splitlines() if line.strip()] if (ROOT / 'events.jsonl').exists() else []
metadata = read(ROOT / 'sheet-notes.json') if (ROOT / 'sheet-notes.json').exists() else {}
wb = Workbook()
overview = wb.active
overview.title = 'Applications'
overview.append(['Company', 'Role', 'Status', 'Role location', 'Company base', 'Employer pay range', 'Pay evidence', 'Your stated expectation', 'Submitted at (UTC)', 'Job URL', 'Exact submitted resume', 'Saved JD', 'Confirmation', 'Resume variant', 'PDF SHA256', 'Fit / notes'])
jds = wb.create_sheet('Job descriptions')
jds.append(['Company', 'Role', 'Job URL', 'Captured at', 'Full saved job description'])
answers = wb.create_sheet('Form answers')
answers.append(['Company', 'Role', 'Field', 'Exact answer', 'Required', 'Source'])
submitted = 0
for path in sorted((ROOT / 'applications').glob('*/job.json')):
    app = read(path)
    packet = path.parent
    history = [e for e in events if e.get('application_id') == app['application_id']]
    successes = [e for e in history if e['kind'] == 'submitted']
    receipt = successes[-1] if successes else {}
    status = 'Submitted — confirmed' if receipt else history[-1]['kind'] if history else 'Unrecorded'
    submitted += bool(receipt)
    prep = read(packet / 'prepared.json') if (packet / 'prepared.json').exists() else {}
    meta = metadata.get(app['company'], {})
    expectation = next((a['value'] for a in prep.get('answers', []) if a['field'] == 'compensation'), 'Not asked / not submitted')
    resume = packet / 'resume.pdf'
    if receipt:
        assert resume.exists() and hashlib.sha256(resume.read_bytes()).hexdigest() == receipt['resume_sha256'], f'Submitted PDF mismatch: {app["company"]}'
    rel = lambda p: str(p.relative_to(ROOT))
    overview.append([app['company'], app['role'], status, meta.get('location', app['eligibility']['location']['evidence']), meta.get('base', 'Not yet verified — do not infer from role location'), meta.get('pay', 'Not disclosed in saved employer JD'), meta.get('pay_source', 'Saved employer JD'), expectation, receipt.get('at', ''), app['url'], rel(resume) if resume.exists() else '', rel(packet / 'jd.txt'), rel(packet / 'confirmation.json') if (packet / 'confirmation.json').exists() else '', prep.get('resume_variant', ''), prep.get('resume_sha256', ''), app['fit']])
    for col in (10, 11, 12, 13):
        cell = overview.cell(overview.max_row, col)
        if cell.value:
            cell.hyperlink = cell.value
            cell.style = 'Hyperlink'
    jds.append([app['company'], app['role'], app['url'], app.get('discovered_at', ''), app['jd_text']])
    for answer in prep.get('answers', []):
        answers.append([app['company'], app['role'], answer['field'], answer['value'], answer.get('required', False), answer.get('source', '')])

leads = wb.create_sheet('Leads and holds')
leads.append(['Company', 'Role', 'Status — NOT submitted', 'Role location', 'Company base', 'Employer pay range', 'Job URL', 'Saved JD / evidence', 'Prepared resume', 'Next action / reason'])
for lead in (read(ROOT / 'sheet-leads.json') if (ROOT / 'sheet-leads.json').exists() else []):
    leads.append([lead.get(k, '') for k in ['company', 'role', 'status', 'location', 'base', 'pay', 'url', 'evidence', 'resume', 'notes']])
    for col in (7, 8, 9):
        cell = leads.cell(leads.max_row, col)
        if cell.value:
            cell.hyperlink = cell.value
            cell.style = 'Hyperlink'

guide = wb.create_sheet('Read me')
guide.append(['Item', 'Details'])
for row in [
    ('Updated UTC', datetime.now(timezone.utc).isoformat()),
    ('Confirmed companies', str(submitted)),
    ('Scope', 'Use your local policy and source-backed eligibility checks.'),
    ('Pay', 'Employer ranges and candidate expectations are separate. Unknown means not verified.'),
    ('Company base', 'Separate from job location. Not yet verified means headquarters/incorporation has not been confirmed.'),
    ('Submitted resumes', 'Applications tab links immutable packet PDFs, not later revised working resumes. SHA256 checked at export.'),
    ('Evidence', 'Job descriptions tab retains complete captured text for every packet. Leads tab is a curated shortlist, not every search result.'),
    ('Links', 'Local links are relative to this workbook in job-search/. Keep the accompanying applications directory alongside it. Web URLs can be opened anywhere.'),
    ('Source of truth', 'events.jsonl and applications/* packets. Workbook is a generated view; edit source notes/records rather than workbook cells.'),
    ('Refresh', 'From project root: .venv/bin/python job-search/export_sheet.py'),
    ('Privacy', 'Private local workbook, including personal form answers. Not uploaded to Google Sheets or any public site.'),
]:
    guide.append(row)

for ws in wb:
    ws.freeze_panes = 'A2'
    ws.auto_filter.ref = ws.dimensions
    ws.row_dimensions[1].height = 32
    for cell in ws[1]:
        cell.fill = PatternFill('solid', fgColor='183B56')
        cell.font = Font(color='FFFFFF', bold=True)
        cell.alignment = Alignment(wrap_text=True, vertical='center')
    for row in ws.iter_rows(min_row=2):
        ws.row_dimensions[row[0].row].height = 64 if ws != jds else 110
        for cell in row:
            if isinstance(cell.value, str):
                cell.data_type = 's'  # External text must never become an Excel formula.
            cell.alignment = Alignment(wrap_text=True, vertical='top')
            if cell.row % 2 == 0:
                cell.fill = PatternFill('solid', fgColor='EFF5F9')
    for col in range(1, ws.max_column + 1):
        ws.column_dimensions[get_column_letter(col)].width = 30
overview.column_dimensions['B'].width = 43
overview.column_dimensions['P'].width = 65
jds.column_dimensions['E'].width = 110
answers.column_dimensions['D'].width = 80
leads.column_dimensions['J'].width = 75
guide.column_dimensions['B'].width = 110
output = ROOT / 'Applications.xlsx'
wb.save(output)
with (ROOT / 'Applications.csv').open('w', newline='', encoding='utf-8-sig') as handle:
    writer = csv.writer(handle)
    for row in overview.values:
        writer.writerow(["'" + v if isinstance(v, str) and v.startswith(('=', '+', '-', '@')) else v for v in row])
check = load_workbook(output)
assert check['Applications'].max_row - 1 == len(list((ROOT / 'applications').glob('*/job.json')))
assert sum(row[2].value == 'Submitted — confirmed' for row in check['Applications'].iter_rows(min_row=2)) == submitted
print(f'{output}: {submitted} confirmed applications, {leads.max_row - 1} leads/holds; PDF hashes and workbook read-back passed.')
