"""Original process comparisons: byte identity, explicit scope and partial order."""
import base64
import copy
import hashlib
import json

import pytest

from theseus.process_compare import compare_results


def blob(value):
    return {'base64':base64.b64encode(value).decode(),'bytes':len(value),'sha256':hashlib.sha256(value).hexdigest()}


def observation(stdout=b'answer\x00\xff',stderr=b'',exit_code=0):
    contract={'argv':['original.exe'],'mode':'pipes','steps':[]}
    return {'format':'vitruvius.process-capture/1','status':'complete','stream_complete':True,
        'contract':contract,'contract_sha256':hashlib.sha256(json.dumps(contract,sort_keys=True,ensure_ascii=False).encode()).hexdigest(),
        'process':{'exit_code':exit_code,'input_file_changes':[]},'stdout':blob(stdout),'stderr':blob(stderr),
        'terminal':{'representation':'not-selected','raw_bytes':blob(b'')},'files':[],
        'steps':[],'events':[],'order':{'global_collection_order_is_causality':False,'edges':[]}}


def test_exact_bytes_exit_and_explicit_dimensions():
    original=observation();candidate=observation();candidate['process']['argv']=['replacement.exe']
    assert compare_results(original,candidate,{'dimensions':['stdout','stderr','exit']})['state']=='same-selected-observations'
    result=compare_results(original,observation(b'answer\x00\xfe'),{'dimensions':['stdout','exit']})
    assert result['state']=='different-selected-observations' and result['dimensions'][0]['state']=='different'
    assert compare_results(original,observation(exit_code=7),{'dimensions':['exit']})['state']=='different-selected-observations'


def test_partial_or_missing_channels_never_prove_equality_and_hashes_are_checked():
    original=observation();partial=observation();partial['status']='partial'
    assert compare_results(original,partial,{'dimensions':['stdout']})['state']=='unknown'
    bad=observation();bad['stdout']['base64']=base64.b64encode(b'altered').decode()
    with pytest.raises(ValueError,match='hash|identity'):compare_results(original,bad,{'dimensions':['stdout']})
    with pytest.raises(ValueError):compare_results(original,original,{'dimensions':[]})


def test_normalization_is_literal_scoped_counted_and_retains_source_identity():
    a,b=observation(b'port=1234\x00'),observation(b'port=9876\x00')
    result=compare_results(a,b,{'dimensions':['stdout'],'normalizations':[
        {'dimension':'stdout','side':'reference','from':'1234','to':'PORT'},
        {'dimension':'stdout','side':'candidate','from':'9876','to':'PORT'}]})
    assert result['state']=='same-selected-observations'
    assert [row['occurrences'] for row in result['normalizations']]==[1,1]
    assert a['stdout']['sha256']!=b['stdout']['sha256']
    assert compare_results(a,b,{'dimensions':['stderr']})['normalizations']==[]


def test_files_compare_both_snapshots_and_preserve_unavailable_and_duplicate_labels():
    a,b=observation(),observation()
    a['files']=[{'label':'result','before':{'state':'file',**blob(b'old')},'after':{'state':'file',**blob(b'new')}}]
    b['files']=copy.deepcopy(a['files']);b['files'][0]['before']={'state':'absent'}
    assert compare_results(a,b,{'dimensions':['files']})['dimensions'][0]['state']=='different'
    b['files'][0]['before']=copy.deepcopy(a['files'][0]['before']);b['files'][0]['after']={'state':'unavailable','error':'busy'}
    assert compare_results(a,b,{'dimensions':['files']})['state']=='unknown'
    b['files']=a['files']*2
    assert compare_results(a,b,{'dimensions':['files']})['state']=='unknown'


def test_trace_requires_observed_happens_before_not_collection_time():
    a,b=observation(),observation()
    events=[{'id':'request:1','channel':'request','kind':'received','at_seconds':1},
        {'id':'response:1','channel':'response','kind':'sent','at_seconds':2}]
    for value in [a,b]:value['events']=copy.deepcopy(events)
    query={'dimensions':['trace'],'trace':{'nodes':[{'id':'request','match':{'kind':'received'}},
        {'id':'response','match':{'kind':'sent'}}],'before':[{'before':'request','after':'response'}]}}
    assert compare_results(a,b,query)['state']=='unknown'
    for value in [a,b]:value['order']['edges']=[{'before':'request:1','after':'response:1','basis':'observed-request-response'}]
    assert compare_results(a,b,query)['state']=='same-selected-observations'
    b['order']['edges']=[{'before':'response:1','after':'request:1','basis':'same-observed-channel'}]
    assert compare_results(a,b,query)['state']=='different-selected-observations'
    b['order']['edges']=[{'before':'missing','after':'response:1'}]
    assert compare_results(a,b,query)['state']=='unknown'


def test_input_contract_difference_remains_unknown_and_terminal_is_explicit():
    a,b=observation(),observation();b['contract']['steps']=[{'kind':'input','text':'changed'}]
    b['contract_sha256']=hashlib.sha256(json.dumps(b['contract'],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    assert compare_results(a,b,{'dimensions':['stdout']})['state']=='unknown'
    assert compare_results(a,a,{'dimensions':['terminal']})['state']=='unknown'
