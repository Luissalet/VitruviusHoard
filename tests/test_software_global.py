import json
import httpx
import pytest

@pytest.mark.asyncio
async def test_global_exact_proxy_and_sync_twin():
    from vitruvius_hoard.software.global_models import GlobalLink, global_job
    from hoard_link import LinkConfig
    requests=[]
    def handler(request):
        requests.append(request)
        if request.method=='GET':
            return httpx.Response(200,json={'endpoint_id':'global-id','model':'exact-model','connection_revision':'rev1','vision':False,'chat_path':'/api/global-model/v1/chat/completions'})
        body=json.loads(request.content)
        assert body['expected_endpoint_id']=='global-id' and body['expected_model']=='exact-model'
        assert body['expected_connection_revision']=='rev1'
        assert request.headers['authorization']=='Bearer synthetic-family-token'
        assert request.extensions['timeout']['read'] is None
        return httpx.Response(200,json={'choices':[{'message':{'content':'synthetic response'},'finish_reason':'stop'}]})
    client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    config=LinkConfig(faustus_urls=('http://synthetic.invalid',),faustus_token='synthetic-family-token')
    link=GlobalLink(config,client=client)
    with global_job():
        answer=await link.chat([{'role':'user','content':'synthetic'}])
        assert answer.text=='synthetic response'
        await link.chat([{'role':'user','content':'synthetic again'}])
    assert sum(r.method=='GET' for r in requests)==1
    assert all('/api/global-model' in str(r.url) for r in requests)
    assert isinstance(link.sync._twin(),GlobalLink)
    await link.aclose()
    await client.aclose()


@pytest.mark.asyncio
@pytest.mark.parametrize('status,finish',[(200,'length'),(200,None),(422,'stop'),(409,'stop')])
async def test_global_never_retries_or_accepts_incomplete_output(status,finish):
    from vitruvius_hoard.software.global_models import GlobalLink, global_job
    from hoard_link import LinkConfig
    sent=[]
    def handler(request):
        sent.append(request)
        if request.method=='GET':
            return httpx.Response(200,json={'endpoint_id':'pinned','model':'exact','connection_revision':'','vision':False,'chat_path':'/api/global-model/v1/chat/completions'})
        assert json.loads(request.content)['expected_connection_revision']==''
        return httpx.Response(status,json={'choices':[{'message':{'content':'partial'},'finish_reason':finish}]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        link=GlobalLink(LinkConfig(faustus_urls=('http://synthetic.invalid',)),client=client)
        with global_job(),pytest.raises((ValueError,httpx.HTTPStatusError)):
            await link.chat([{'role':'user','content':'synthetic'}],response_format={'type':'json_schema','json_schema':{'name':'fixed','schema':{'type':'object'},'strict':True}})
        assert len(sent)==2
        assert json.loads(sent[-1].content)['response_format']['json_schema']['strict']
        await link.aclose()
