"""Create private local state from fictional examples; never overwrite existing files."""
import shutil
from flow import CODE, ROOT

ROOT.mkdir(parents=True, exist_ok=True)
for source, destination in [
    ('profile.example.json', ROOT / 'profile.json'),
    ('policy.example.json', ROOT / 'policy.json'),
    ('dossier.example.json', ROOT.parent / 'WORK_DOSSIER.json'),
    ('jev-config.example.json', ROOT / 'jev-config.json'),
]:
    if not destination.exists():
        shutil.copyfile(CODE / 'examples' / source, destination)
for name in ('events.jsonl', 'changes.jsonl'):
    (ROOT / name).touch(exist_ok=True)
(ROOT / 'research').mkdir(exist_ok=True)
(ROOT / 'research' / 'sources.jsonl').touch(exist_ok=True)
print(f'Local state: {ROOT}. Replace fictional profile/dossier before real use.')
