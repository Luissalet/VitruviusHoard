"""Reconcile immutable static files and Inspector script texts without live reads."""
import hashlib
import json
from pathlib import Path


def saved_pair(request, source_bytes, reference_operation, candidate_operation):
    reference = json.loads(source_bytes)
    candidate_bytes = Path(request['candidate_path']).read_bytes()
    if hashlib.sha256(candidate_bytes).hexdigest() != request['expected_candidate_sha256']:
        raise ValueError('Retained candidate document changed; its receipt hash no longer matches')
    candidate = json.loads(candidate_bytes)
    reference_operations=[reference_operation] if isinstance(reference_operation,str) else reference_operation
    candidate_operations=[candidate_operation] if isinstance(candidate_operation,str) else candidate_operation
    if reference['operation'] not in reference_operations or candidate['operation'] not in candidate_operations:
        raise ValueError('Select saved '+' or '.join(reference_operations)+' and '+' or '.join(candidate_operations)+' observations')
    return reference,candidate,candidate_bytes


def reconcile(request, source_bytes):
    operation=('browser.observe','browser.scenario','browser.coverage') if request['operation']=='browser.reconcile_sources' else 'javascript.observe'
    reference,candidate,candidate_bytes=saved_pair(request,source_bytes,'javascript.application',operation)
    files = []
    for node in reference['result']['graph']['nodes']:
        identity = node['identity']
        if identity['strategy'] != 'content-digest':
            continue
        for observation in node['observations']:
            properties = observation['properties']
            if 'file_kind' in properties and properties.get('path') is not None:
                row = {'node_id': node['node_id'], 'path': properties['path'], 'sha256': identity['sha256']}
                if row not in files:
                    files.append(row)
    mappings = request['parameters'].get('mappings', [])
    rows = []
    participating = set()
    for script in candidate['result']['scripts']:
        source = script.get('source',{'state':'not-recorded'})
        captured = source.get('state') == 'captured'
        digest = None
        if captured:
            digest = hashlib.sha256(source['text'].encode('utf8')).hexdigest()
            if digest != source['sha256']:
                raise ValueError('Captured script text differs from its recorded source hash')
        exact = [row for row in files if digest and row['sha256'] == digest]
        declarations = [row for row in mappings if row['runtime_url'] == script.get('url')]
        declared = [row for row in files if any(row['path'] == mapping['source_path'] for mapping in declarations)]
        contradictions = [row for row in declared if digest and row['sha256'] != digest]
        candidates = exact or declared
        participating.update((row['node_id'], row['path']) for row in candidates)
        rows.append({'script_id': script['scriptId'], 'url': script.get('url'),
            'source_state': source['state'], 'source_sha256': digest,
            'state': ('ambiguous-content' if len(exact) > 1 else 'content-match') if exact else
                     'contradicted-declaration' if contradictions else
                     'declared-unverified' if declared else 'unresolved',
            'basis': 'captured-utf8-sha256' if exact else 'caller-declaration' if declarations else 'none',
            'candidates': candidates, 'declarations': declarations, 'contradictions': contradictions,
            'missing_declared_paths': [m['source_path'] for m in declarations if not any(f['path'] == m['source_path'] for f in files)]})
    return {'reference_analysis_sha256': hashlib.sha256(source_bytes).hexdigest(),
        'capture_sha256': hashlib.sha256(candidate_bytes).hexdigest(),
        'capture_operation':candidate['operation'],'capture_mode': candidate['result'].get('capture_mode','unknown'), 'files': files, 'scripts': rows,
        'unobserved_files': [row for row in files if (row['node_id'], row['path']) not in participating],
        'limitations': ['Only retained JSON inputs were compared; no target or original path was read.',
            'Hashes compare captured UTF-8 script text with original file bytes; wrappers or encoding changes may prevent a match.',
            'Caller mappings are declarations, not identity evidence. URLs alone are not matched automatically.',
            'Multiple paths with identical contents remain ambiguous. Unobserved files may execute outside the captured window.',
            'Script presence does not prove calls, imports, IPC, callbacks or behavioral equivalence.']}
