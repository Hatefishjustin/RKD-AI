"""Architect-only isolated probes. No business code changes or external calls."""
import copy
import hashlib
import json
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / 'mvp'), str(ROOT / 'scripts')]
import w2_closeout_repro as harness
from rkd_mvp.ai_spatial_outputs import measure, build_cost

results = {}
triangle = [[0, 0], [6000, 0], [0, 6000]]
model = harness.l_shape_model([harness.keepout('cut', 0, 1, 6, 1)])
model['spatial']['zones'][0]['polygon_mm'] = triangle
model['spatial']['zones'][0]['area_sqm'] = 18
scope = {'declared_by': 'architect_manual_test', 'declaration': 'analytic fixture only',
         'unit': 'mm', 'areas': [{'object_id': 'face1', 'polygon_mm': triangle,
                                 'material_ref': {'material_id': 'test-floor'}, 'unit': 'm2'}]}
q = measure(model, finish_scope=scope)
geom = harness.find_q(q, 'Q-FLOOR-GEOMETRIC-NET')
finish = harness.find_q(q, 'Q-FLOOR-FINISH')
results['sloped_deduction'] = {
    'analytic_basis': 'triangle 18m2 minus integral(6-y, y=1..2)=4.5m2; net=13.5m2',
    'expected_m2': 13.5, 'geometry': geom,
    'finish': finish, 'cost': build_cost(q, settings={'floor_unit_price_cny': 1000})}
unit_scope = copy.deepcopy(scope)
unit_scope['unit'] = 'm'
unit_scope['areas'][0]['unit'] = 'ft2'
try:
    uq = measure(model, finish_scope=unit_scope)
    results['unit_mismatch'] = {'rejected': False, 'result': harness.find_q(uq, 'Q-FLOOR-FINISH')}
except (ValueError, TypeError) as error:
    results['unit_mismatch'] = {'rejected': True, 'error': str(error)}

results['packages'] = []
for label in ('layout-A', 'layout-B'):
    folder = ROOT / 'deliverables-for-review/roadmap/W2-收口整改/outputs' / label
    manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
    with zipfile.ZipFile(folder / 'package.zip') as archive:
        bad = [entry['filename'] for entry in manifest['files']
               if entry['filename'] not in archive.namelist()
               or hashlib.sha256(archive.read(entry['filename'])).hexdigest() != entry['sha256']
               or len(archive.read(entry['filename'])) != entry['size_bytes']]
        results['packages'].append({'layout': label, 'mismatches': bad,
                                    'render_in_zip': 'render.png' in archive.namelist()})

with tempfile.TemporaryDirectory(prefix='rkd-architect-w2-') as runtime:
    stack = harness.Stack(Path(runtime))
    try:
        revision = stack.import_layout('A')
        stack.spatial_ai.start_workers = False
        good_code, good_response, _ = stack.submit(revision, 'architect-prior-success-0001', render=False)
        good_id = good_response['item']['job_id']
        assert good_code in (200, 202) and good_response['item']['status'] == 'succeeded', (good_code, good_response)
        stack.spatial_ai.start_workers = True
        original_launch = stack.spatial_ai._launch
        observed = {}
        def launch_after_read(org, project, job_id):
            # Deterministic scheduling seam: another HTTP read after commit,
            # before worker ownership is recorded. No sleep and no DB mutation.
            code, state, _ = harness.http('GET', stack.base + '/spatial-outputs?job_id=' + job_id)
            observed.update({'get_status': code, 'job_during_gap': state.get('job')})
            original_launch(org, project, job_id)
        stack.spatial_ai._launch = launch_after_read
        code, response, _ = stack.submit(revision, 'architect-launch-gap-0001', render=False)
        job_id = response['item']['job_id']
        state = stack.state('?job_id=' + job_id)
        results['normal_launch_gap'] = {'submit_status': code, **observed,
                                       'final_job': state['job']}
        results['explicit_failed_job_query'] = {
            'requested_job_id': job_id, 'job_status': state['job']['status'],
            'returned_revision_job_id': (state.get('revision') or {}).get('job_id'),
            'previous_successful_job_id': good_id,
            'unrelated_artifacts_returned': bool(state.get('artifacts'))}
    finally:
        stack.close()

out = Path(__file__).with_name('boundary-results.json')
out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'geometry_m2': geom['value'], 'independent_m2': geom['independent_recompute_m2'],
                  'finish_m2': finish['value'], 'unit_mismatch_rejected': results['unit_mismatch']['rejected'],
                  'launch_gap_status': results['normal_launch_gap']['final_job']['status'],
                  'launch_gap_error': results['normal_launch_gap']['final_job']['error_code'],
                  'packages': results['packages'], 'evidence': str(out)}, ensure_ascii=False))
