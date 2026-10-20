"""Sequential native context observations; never a synthetic atomic snapshot."""
from datetime import datetime, timezone
import json

OPERATIONS = {'get_navigation_context', 'inspect_address_context'}


def compose(runtime, session, operation, parameters, active):
    observations = []
    allowed = {'document'} | ({'address'} if operation == 'inspect_address_context' else set())
    if operation not in OPERATIONS or set(parameters) - allowed:
        raise ValueError('Unknown native context operation or parameters')
    document = parameters.get('document')
    if document is not None and (not isinstance(document, str) or not document):
        raise ValueError('document must be a nonempty string or null for the bound program')
    if operation == 'inspect_address_context' and (not isinstance(parameters.get('address'), str) or not parameters['address']):
        raise ValueError('An explicit nonempty native address is required')

    def observe(method, arguments):
        active()
        started = datetime.now(timezone.utc).isoformat()
        response = runtime.request(method, arguments)
        # Preserve parsed protocol values, including nulls and producer errors.
        # The transport's private authentication token is never copied here.
        response = json.loads(json.dumps(response, ensure_ascii=False))
        if not isinstance(response, dict) or not isinstance(response.get('ok'), bool) or response['ok'] and 'result' not in response:
            raise ValueError('Native provider returned an invalid observation envelope')
        row = {'index': len(observations), 'operation': method, 'parameters': dict(arguments),
               'started_at': started, 'finished_at': datetime.now(timezone.utc).isoformat(), 'response': response}
        observations.append(row)
        return response, row['index']

    def facet(response, index):
        if response.get('ok') is True:
            return {'status': 'available', 'value': response.get('result'), 'source_observation': index}
        return {'status': 'unavailable', 'value': None, 'reason': response.get('error', 'No successful provider response'),
                'source_observation': index}

    def failed(response):
        return {'ok': False, 'error': response.get('error', 'Native context observation failed'),
                'observations': observations, 'composition': operation}

    raw_document, index = observe('current_document', {})
    document_facet = facet(raw_document, index)
    observed_document = raw_document.get('result') if raw_document.get('ok') is True else None
    if observed_document is not None and not isinstance(observed_document, str):
        raise ValueError('Native current_document response is not a document identity')
    bound_document = document if document is not None else observed_document
    selection = {'document': bound_document}
    facets = {'document': document_facet}
    if operation == 'get_navigation_context':
        raw_address, index = observe('current_address', selection)
        if raw_address.get('ok') is not True:
            return failed(raw_address)
        address = raw_address.get('result')
        if not isinstance(address, str) or not address:
            raise ValueError('Native current_address response is not a canonical address')
        facets['address'] = facet(raw_address, index)
    else:
        address = parameters['address']

    primary, index = observe('resolve_containing_procedure', {**selection, 'address': address})
    query_address = address
    if primary.get('ok') is True:
        resolved = primary.get('result')
        if not isinstance(resolved, dict) or not isinstance(resolved.get('found'), bool) or not isinstance(resolved.get('query_address'), str):
            raise ValueError('Native containing-procedure response lacks its explicit address/found observation')
        address = resolved['query_address']
        procedure = resolved.get('procedure')
        if resolved['found'] != (procedure is not None) or procedure is not None and not isinstance(procedure, dict):
            raise ValueError('Native containing-procedure result contradicts its found flag')
        facets['procedure'] = {'status': 'available', 'value': procedure, 'source_observation': index,
                               'absence_reason': resolved.get('reason') if procedure is None else None}
        if operation == 'inspect_address_context':
            facets['address'] = {'status': 'available', 'value': address, 'source_observation': index}
        query_address = address
    else:
        error = primary.get('error')
        unsupported = isinstance(error, dict) and error.get('code') in {
            'unsupported_operation', 'unsupported_capability', 'unsupported', 'not_supported', 'method_not_found'}
        if not unsupported:
            return failed(primary)
        procedure = None
        facets['procedure'] = facet(primary, index)
        if operation == 'inspect_address_context':
            address = None
            facets['address'] = {**facet(primary, index), 'requested_value': query_address}
    if operation == 'inspect_address_context':
        for name, method in [('name', 'address_name'), ('comment', 'comment'), ('inline_comment', 'inline_comment')]:
            response, source = observe(method, {**selection, 'address': query_address})
            facets[name] = facet(response, source)
        response, source = observe('list_bookmarks', {**selection, 'type': None, 'category': None})
        if response.get('ok') is True:
            rows = response.get('result')
            if not isinstance(rows, list) or any(not isinstance(row, dict) or not isinstance(row.get('address'), str) for row in rows):
                raise ValueError('Native bookmark inventory is not a complete address-bearing list')
            if address is None:
                facets['bookmarks'] = {'status': 'unavailable', 'value': None, 'source_observation': source,
                    'reason': 'Canonical address is unavailable; complete bookmark inventory remains in its source observation'}
            else:
                facets['bookmarks'] = {'status': 'available', 'value': [row for row in rows if row['address'] == address],
                                       'source_observation': source}
        else:
            facets['bookmarks'] = facet(response, source)

    result = {'format': 'vitruvius.native-context/1', 'context': operation, 'requested_document': document,
              'document': observed_document, 'requested_address': parameters.get('address'), 'address': address, 'procedure': procedure,
              'observation_consistency': 'sequential-provider-observations', 'facets': facets,
              'binding': {'origin': 'observed-native-session', 'session_id': session['id'],
                  'artifact_sha256': session['result']['artifact_sha256'],
                  'analysis_revision': session['result']['revision'],
                  'profile_sha256': session['result'].get('profile_sha256')},
              'observations': observations,
              'limitations': ['These are sequential provider observations, not an atomic cursor snapshot.',
                  'Analysis names, comments and bookmarks describe the selected analysis database, not runtime behavior.',
                  'Transfer retains historical parsed protocol observations; it never opens a native session.']}
    for name in ['name', 'comment', 'inline_comment', 'bookmarks']:
        if name in facets:
            result[name] = facets[name]['value']
    active()
    return {'ok': True, 'result': result, 'composition': operation}
