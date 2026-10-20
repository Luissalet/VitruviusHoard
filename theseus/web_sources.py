"""Export only bytes already retained in a browser observation document."""
import base64
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import unquote, unquote_to_bytes, urlsplit


def _identity(data):
    return {'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


def _url_path(url):
    """Preserve unambiguous URL layout; never turn arbitrary URL paths into writes."""
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in {'http', 'https'} or not parsed.netloc or parsed.query or parsed.fragment or parsed.username is not None:
            return None
        if re.search(r'%(?:2f|5c)', parsed.path, re.I):
            return None
        path = unquote(parsed.path, encoding='utf8', errors='strict')
        parts = path.removeprefix('/').split('/')
        host = parsed.netloc.replace(':', '_')
        for part in [host, *parts]:
            if (not part or part in {'.', '..'} or part[-1] in '. '
                    or re.search(r'[\x00-\x1f<>:"/\\|?*]', part)
                    or re.fullmatch(r'(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', part, re.I)):
                return None
        return '/'.join(['urls', parsed.scheme, host, *parts])
    except (ValueError, UnicodeError):
        return None


def _response_bytes(observations, request_id):
    if not isinstance(request_id, str) or not request_id:
        raise ValueError('Retained response has no request occurrence ID')
    commands = [row['message'] for row in observations if row.get('direction') == 'sent'
                and isinstance(row.get('message'), dict)
                and row['message'].get('method') == 'Network.getResponseBody'
                and row['message'].get('params', {}).get('requestId') == request_id]
    if len(commands) != 1:
        raise ValueError('Expected one retained response-body command for this request occurrence')
    command = commands[0]
    if type(command.get('id')) is not int:
        raise ValueError('Retained response-body command has no numeric protocol ID')
    # A duplicate command ID cannot be associated with a unique response.
    if sum(row.get('direction') == 'sent' and row.get('message', {}).get('id') == command['id']
           for row in observations) != 1:
        raise ValueError('Retained protocol command ID is ambiguous')
    replies = [row['message'] for row in observations if row.get('direction') == 'received'
               and row.get('message', {}).get('id') == command['id']]
    if len(replies) != 1 or 'error' in replies[0]:
        raise ValueError('Retained response-body reply is missing, ambiguous or failed')
    reply = replies[0].get('result', {})
    text = reply.get('body')
    if not isinstance(text, str) or not isinstance(reply.get('base64Encoded'), bool):
        raise ValueError('Retained response-body reply has no explicit representation')
    return (base64.b64decode(text, validate=True), 'cdp-base64-bytes') if reply['base64Encoded'] else (text.encode('utf8'), 'cdp-text-utf8')


def export_sources(source_bytes, output_directory):
    document = json.loads(source_bytes)
    if document.get('operation') not in {'browser.observe', 'browser.scenario', 'browser.coverage'}:
        raise ValueError('Select a retained browser observation, scenario or coverage capture')
    capture = document['result']
    entries, contents = [], {}

    def retain(row, load, expected, representation=None):
        if row['state'] == 'captured':
            try:
                data, actual_representation = load()
                if _identity(data) != expected:
                    raise ValueError('Retained content does not match its recorded SHA-256 and byte length')
                if representation is not None and representation != actual_representation:
                    raise ValueError('Retained response representation differs from its recorded identity')
                row.update(**_identity(data), representation=actual_representation,
                           content_base64=base64.b64encode(data).decode('ascii'))
            except (ValueError, KeyError, TypeError, UnicodeError) as exc:
                row.update(state='unavailable', reason=str(exc))
        entries.append(row)

    for index, script in enumerate(capture.get('scripts', [])):
        source = script.get('source', {})
        row = {'id': f'script-{index:06d}', 'kind': 'page-script', 'url': script.get('url', ''),
               'script_id': script.get('scriptId'), 'source_map_url': script.get('sourceMapURL'),
               'capture_index': index, 'state': source.get('state', 'unavailable')}
        retain(row, lambda: (source['text'].encode('utf8'), 'debugger-text-utf8'),
               {'sha256': source.get('sha256'), 'bytes': source.get('utf8_bytes')})
        map_url = script.get('sourceMapURL', '')
        if isinstance(map_url, str) and map_url.startswith('data:'):
            inline = {'id': f'inline-map-{index:06d}', 'kind': 'inline-source-map', 'url': map_url,
                      'script_entry_id': row['id'], 'capture_index': index, 'state': 'captured'}
            try:
                header, encoded = map_url.split(',', 1)
                data = unquote_to_bytes(encoded)
                if header.endswith(';base64'):
                    data = base64.b64decode(data, validate=True)
                expected = _identity(data)
                retain(inline, lambda: (data, 'declared-data-url-bytes'), expected)
            except ValueError as exc:
                inline.update(state='unavailable', reason=str(exc)); entries.append(inline)

    for index, response in enumerate(capture.get('network', [])):
        body = response.get('body', {})
        row = {'id': f'response-{index:06d}', 'kind': 'network-response',
               'url': response.get('response', {}).get('url') or response.get('name', ''),
               'request_id': response.get('request_id'), 'capture_index': index,
               'state': body.get('state', 'unavailable')}
        retain(row, lambda: _response_bytes(capture.get('observations', []), response.get('request_id')),
               {'sha256': body.get('sha256'), 'bytes': body.get('bytes')}, body.get('representation'))

    paths = {row['id']: _url_path(row['url']) for row in entries if row['state'] == 'captured'}
    # Windows case-insensitive collisions and file/directory conflicts isolate
    # every occurrence, rather than silently selecting whichever was seen first.
    candidates = [path.casefold() for path in paths.values() if path is not None]
    for row in entries:
        if row['state'] != 'captured':
            continue
        proposed = paths[row['id']]
        folded = proposed.casefold() if proposed else None
        collision = folded and (candidates.count(folded) > 1 or any(
            other != folded and (other.startswith(folded+'/') or folded.startswith(other+'/')) for other in candidates))
        suffix = '.js' if row['kind'] == 'page-script' else '.map' if row['kind'] == 'inline-source-map' else '.bin'
        row['relative_path'] = proposed if proposed and not collision else 'occurrences/'+row['id']+suffix
        row['layout'] = 'url-path' if proposed and not collision else 'isolated-occurrence'
        contents[row['relative_path']] = base64.b64decode(row['content_base64'], validate=True)

    result = {'format': 'vitruvius.web-sources/1', 'capture_sha256': hashlib.sha256(source_bytes).hexdigest(),
              'capture_operation': document['operation'], 'entries': entries,
              'limitations': [
                  'Only retained observations are exported; no page, URL or original artifact path is read.',
                  'Debugger and text response bodies are UTF-8 encodings of CDP strings, not original wire bytes.',
                  'URLs and script/request IDs describe occurrences inside this capture; duplicates are preserved.',
                  'Safe unambiguous HTTP(S) paths retain their layout per origin; query variants, inline content and collisions use isolated occurrence paths.',
                  'Missing or excluded observations remain unknown; an export is not a complete deployment inventory.',
                  'Inline maps are declarations; a script/map pairing does not authenticate a deployment.',
              ]}
    contents['manifest.json'] = json.dumps(result, ensure_ascii=False, indent=2).encode('utf8')
    directory = Path(output_directory)
    directory.mkdir(parents=True, exist_ok=False)
    artifacts = []
    for name, data in contents.items():
        destination = directory/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        artifacts.append({'relative_path': name, **_identity(data), 'source_location': 'retained-capture:'+result['capture_sha256']+':'+name})
    result['artifacts'] = artifacts
    return result
