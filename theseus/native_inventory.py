"""Compose exact names and a conditional image base from complete observations."""
from datetime import datetime, timezone
import json
import re
from urllib.parse import unquote

OPERATIONS = {'resolve_name_references', 'binary_overview'}


def _address_key(value, default_space):
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r'(?:(.+):)?0[xX]([0-9a-fA-F]+)', value)
    if not match:
        return None
    try:
        space = unquote(match[1], errors='strict') if match[1] else default_space
    except UnicodeError:
        return None
    if not isinstance(space, str) or not space:
        return None
    return space, int(match[2], 16)


def compose(runtime, session, operation, parameters, active):
    allowed = {'document', 'name'} if operation == 'resolve_name_references' else set()
    if operation not in OPERATIONS or not isinstance(parameters, dict) or set(parameters) - allowed:
        raise ValueError('Unknown native inventory operation or parameters')
    if operation == 'resolve_name_references':
        if not isinstance(parameters.get('name'), str) or not parameters['name']:
            raise ValueError('An exact nonempty symbol name is required')
        if parameters.get('document') is not None and (
                not isinstance(parameters['document'], str) or not parameters['document']):
            raise ValueError('document must be a nonempty string or null for the bound program')
    observations = []
    default_space = session['result'].get('info', {}).get('target', {}).get('default_address_space')

    def observe(method, arguments):
        active()
        started = datetime.now(timezone.utc).isoformat()
        response = runtime.request(method, arguments)
        response = json.loads(json.dumps(response, ensure_ascii=False))
        observations.append({'index': len(observations), 'operation': method,
            'parameters': dict(arguments), 'started_at': started,
            'finished_at': datetime.now(timezone.utc).isoformat(), 'response': response})
        if not isinstance(response, dict) or not isinstance(response.get('ok'), bool) or (
                response['ok'] and 'result' not in response):
            return {'ok': False, 'error': {'code': 'invalid_observation',
                'message': 'The native provider returned an invalid observation envelope'}}
        return response

    def failed(response):
        return {'ok': False, 'error': response.get('error', 'Native inventory observation failed'),
                'composition': operation, 'observations': observations}

    def invalid(message):
        return failed({'error': {'code': 'invalid_observation', 'message': message}})

    if operation == 'resolve_name_references':
        current = observe('current_document', {})
        if not current['ok']:
            return failed(current)
        if not isinstance(current['result'], str) or not current['result']:
            return invalid('The current document is not a nonempty native identity')
        document = parameters.get('document') or current['result']
        names = observe('list_names', {'document': document, 'address': None})
        if not names['ok']:
            return failed(names)
        rows = names['result']
        if not isinstance(rows, list) or any(not isinstance(row, dict) or
                not isinstance(row.get('value'), str) or not isinstance(row.get('address'), str) or
                not row['address'] for row in rows):
            return invalid('The name inventory is not a complete list of names and canonical addresses')
        if any(_address_key(row['address'], default_space) is None for row in rows):
            return invalid('The name inventory contains an invalid or unbound native address')
        matches = [row for row in rows if row['value'] == parameters['name']]
        unique = {}
        for row in matches:
            unique.setdefault(_address_key(row['address'], default_space), row['address'])
        addresses = list(unique.values())
        result = {'document': document, 'name': parameters['name'], 'matches': matches,
                  'addresses': addresses, 'references': []}
        if not addresses:
            result.update(status='unresolved', reason='name_not_found')
        elif len(addresses) != 1:
            result.update(status='unresolved', reason='ambiguous_name')
        else:
            refs = observe('xrefs', {'document': document, 'address': addresses[0]})
            if not refs['ok']:
                return failed(refs)
            if not isinstance(refs['result'], list) or any(
                    _address_key(row, default_space) is None for row in refs['result']):
                return invalid('The native reference observation is not a complete address list')
            result.update(status='resolved', reason=None, address=addresses[0], references=refs['result'])
    else:
        response = observe('read_binary_inventory_summary', {})
        if not response['ok']:
            return failed(response)
        raw = response['result']
        if not isinstance(raw, dict) or not isinstance(raw.get('segments'), list) or any(
                not isinstance(row, dict) for row in raw['segments']):
            return invalid('The binary summary does not contain a complete segment list')
        result = dict(raw)
        bases = [_address_key(row.get('image_base'), default_space) for row in raw['segments']]
        result.update(segment_count=len(raw['segments']), image_base=None,
                      image_base_address_space=None, image_base_status='unknown')
        if not bases:
            result['image_base_reason'] = 'no_segments'
        elif any(base is None for base in bases):
            result['image_base_reason'] = 'incomplete_base_observation'
        elif len(set(bases)) != 1:
            result['image_base_reason'] = 'conflicting_base_observations'
        else:
            space, value = bases[0]
            result.update(image_base='0x' + format(value, 'x'), image_base_address_space=space,
                          image_base_status='observed', image_base_reason=None)

    result.update(format='vitruvius.native-inventory/1', composition=operation,
        observation_consistency='sequential-provider-observations', observations=observations,
        binding={'origin': 'observed-native-session', 'session_id': session['id'],
            'artifact_sha256': session['result']['artifact_sha256'],
            'analysis_revision': session['result']['revision'],
            'profile_sha256': session['result'].get('profile_sha256')},
        limitations=['These are static observations of the selected native analysis database.',
            'Names and references do not prove runtime behavior or complete symbol recovery.'])
    active()
    return {'ok': True, 'result': result, 'composition': operation}
