/** Project selected historical managed documents without reopening their artifacts. */
import {createHash} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {z} from 'zod';
import {createEvidence,type Evidence} from './src/domain/evidence.js';
import {projectManagedApplicationGraph,type ProjectManagedApplicationGraphInput} from './src/domain/managed/managedApplicationGraph.js';
import type {JsonValue} from './src/domain/jsonValue.js';
import {retainedInputSchema} from './retained-evidence.js';

type Input=z.infer<typeof retainedInputSchema>;
const digest=z.string().regex(/^[a-f0-9]{64}$/u);
const envelopeSchema=z.object({operation:z.string(),artifact_sha256:digest,result:z.unknown()}).passthrough();
const resultIdentitySchema=z.object({artifact:z.object({sha256:digest,path:z.string()}),
  coverage:z.object({state:z.enum(['complete','partial','unavailable'])})}).passthrough();
const scopeSchema=z.object({type_names:z.array(z.string()).nullable(),method_offset:z.number().int().nonnegative(),
  method_limit:z.number().int().nonnegative().nullable(),user_strings:z.boolean()}).strict();
const facets={
  'managed.artifact':{key:'managed_artifact',operation:'inspect_managed_artifact'},
  'managed.members':{key:'managed_members',operation:'inspect_managed_members'},
  'managed.native_boundaries':{key:'managed_native_boundaries',operation:'inspect_managed_native_boundaries'},
} as const;
const hash=(raw:Buffer)=>createHash('sha256').update(raw).digest('hex');
const provider={id:'theseus-retained-managed',name:'Theseus retained managed projection',version:'1'};

export async function retainedManagedGraph(inputs:Input[],artifactSha256:string) {
  const selected=inputs.filter(input=>input.selected);
  if(!selected.length||selected.length>3)throw new Error('Select one to three managed observations');
  const projection:ProjectManagedApplicationGraphInput={};
  const carriers:Evidence[]=[];
  const sources=new Map<string,{analysis_sha256:string;operation:string;artifact_sha256:string;
    document_base64:string;carrier_evidence_id:string|null;
    occurrences:{job_id:string;selected:boolean;artifact_id:string|null;provider:unknown}[]}>();
  const missing:{job_id:string;reason:string}[]=[];
  const scope:Record<string,unknown>=Object.fromEntries(Object.values(facets).map(facet=>[facet.key,
    {selected:false,source_coverage:null,observation_scope:null,scope_status:'not-selected'}]));
  // Read and authenticate every supplied document, including secondary selections and closure.
  for(const input of inputs) {
    if(input.error) {
      if(input.selected)throw new Error('Selected retained document is unavailable');
      missing.push({job_id:input.job_id,reason:input.error});continue;
    }
    if(!input.path||!input.analysis_sha256)throw new Error('Retained document has no authenticated path/hash');
    const bytes=await readFile(input.path);
    if(hash(bytes)!==input.analysis_sha256)throw new Error('Retained managed document hash changed: '+input.job_id);
    const saved=envelopeSchema.parse(JSON.parse(bytes.toString('utf8')));
    if(saved.operation!==input.operation||saved.artifact_sha256!==input.artifact_sha256)
      throw new Error('Retained managed operation/artifact binding differs');
    const encoded=bytes.toString('base64');
    let source=sources.get(input.analysis_sha256);
    if(!source) {
      source={analysis_sha256:input.analysis_sha256,operation:saved.operation,artifact_sha256:saved.artifact_sha256,
        document_base64:encoded,carrier_evidence_id:null,occurrences:[]};
      sources.set(input.analysis_sha256,source);
    }
    source.occurrences.push({job_id:input.job_id,selected:input.selected,artifact_id:input.artifact_id??null,
      provider:input.provider??null});
    if(!input.selected)continue;
    const facet=facets[saved.operation as keyof typeof facets];
    if(!facet)throw new Error('Select retained managed artifact, members or native-boundary observations');
    if(projection[facet.key])throw new Error('Select at most one observation per managed facet');
    const identity=resultIdentitySchema.parse(saved.result);
    if(saved.artifact_sha256!==artifactSha256||identity.artifact.sha256!==saved.artifact_sha256)
      throw new Error('Retained managed inputs must describe the same artifact SHA-256');
    const carrier=createEvidence({path:identity.artifact.path,sha256:saved.artifact_sha256,format:'pe'},provider,{
      operation:facet.operation,parameters:{analysis_sha256:input.analysis_sha256,source_operation:saved.operation},
      rawResult:{analysis_sha256:input.analysis_sha256,document_base64:encoded},result:saved.result as JsonValue,
      confidence:'derived',authority:'historical-reference',
      limitations:['Historical observation projected from authenticated retained JSON; original artifact was not accessed.',
        'The projection provider is not the historical extractor; missing extractor profile/version remains unknown.']});
    projection[facet.key]=carrier;carriers.push(carrier);source.carrier_evidence_id=carrier.evidence_id;
    const recordedScope=saved.operation==='managed.members'&&saved.observation_scope!==undefined
      ?scopeSchema.parse(saved.observation_scope):null;
    scope[facet.key]={selected:true,source_coverage:identity.coverage.state,observation_scope:recordedScope,
      scope_status:saved.operation!=='managed.members'?'within-retained-observation':recordedScope===null?'unknown':
        recordedScope.type_names!==null||recordedScope.method_offset!==0||recordedScope.method_limit!==null
          ?'selected-window':'all-methods-requested'};
  }
  const graph=projectManagedApplicationGraph(projection);
  return {...graph,selection_scope:scope,retained_carriers:carriers.sort((a,b)=>a.evidence_id.localeCompare(b.evidence_id)),
    source_observations:[...sources.values()].sort((a,b)=>a.analysis_sha256.localeCompare(b.analysis_sha256)),
    retained_closure:{status:missing.length?'incomplete':'authenticated-supplied-documents',missing},
    retained_interpretation:{original_artifact_accessed:false,executed:false,
      scope:'Selected retained types, members and native boundaries; not a complete binary inventory or recovered CIL call graph.',
      coverage:'Helper coverage describes supplied evidence only. Omitted facets and unknown method windows do not establish absence.',
      locations:'Graph locations identify historical coordinates; available does not assert present filesystem availability.'}};
}
