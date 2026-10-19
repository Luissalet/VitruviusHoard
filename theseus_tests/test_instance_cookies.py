from fastapi.testclient import TestClient

from theseus.api import create_app


def test_same_host_instances_keep_independent_port_cookies(tmp_path):
    first,second = create_app(tmp_path/'first'),create_app(tmp_path/'second',port=64177)
    with TestClient(first,base_url='http://localhost:5217') as a, TestClient(second,base_url='http://localhost:64177') as b:
        assert a.get('/api/projects').status_code==401
        response = a.get('/')
        assert 'theseus_token_5217=' in response.headers['set-cookie']
        assert 'HttpOnly' in response.headers['set-cookie'] and 'SameSite=strict' in response.headers['set-cookie']
        b.cookies.update(a.cookies)
        assert b.get('/api/projects').status_code==401
        b.get('/')
        a.cookies.update(b.cookies)
        assert a.get('/api/projects').status_code==200
        assert b.get('/api/projects').status_code==200
        a.get('/')
        b.cookies.update(a.cookies)
        assert b.get('/api/projects').status_code==200


def test_legacy_cookie_and_bearer_clients_keep_their_existing_contract(tmp_path):
    data = tmp_path/'data'
    app = create_app(data)
    token = (data/'mcp-token').read_text().strip()
    with TestClient(app,base_url='http://localhost:5217') as client:
        client.cookies.set('theseus_token',token)
        assert client.get('/api/projects').status_code==200
        client.cookies.clear()
        assert client.get('/api/projects',headers={'Authorization':'Bearer '+token}).status_code==200
        assert client.get('/api/projects',headers={'Authorization':'Bearer wrong-instance'}).status_code==401
