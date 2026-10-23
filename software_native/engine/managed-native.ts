/** Contrast retained declarations with historical jobs or explicitly supplied Evidence. */
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {z} from 'zod';
import {createEvidence,parseEvidence,type Evidence} from './src/domain/evidence.js';
import {functionDossierSchema} from './src/domain/hopperValues.js';
import {verifyManagedNativeBoundaries} from './src/domain/managed/managedNativeVerification.js';
import {managedNativeVerificationInputSchema} from './src/domain/managed/managedNativeVerificationSchemas.js';
import type {JsonValue} from './src/domain/jsonValue.js';
import type {InspectMacho} from './src/domain/native/nativeInspection.js';

export interface NativeObservationInput {
  path:string;sha256:string;artifact_path:string;artifact_sha256:string;
  artifact_format:'pe'|'elf'|'mach-o'|'unknown';version:string|null;job_id:string;
  profile?:unknown;profile_sha256?:string|null|undefined;analysis_revision?:number|null|undefined;
}
interface ManagedSource {job_id:string;analysis_sha256:string;artifact_sha256:string}
type Source={name:string;evidence:Evidence;source_job_ids:string[];origin:string;
  evidence_value_sha256:string;evidence_value_json_base64:string;
  analysis_sha256?:string;document_base64?:string;historical_context?:unknown;
  submitted_value_sha256?:string;submitted_value_json_base64?:string};
const hash=(bytes:Buffer)=>createHash('sha256').update(bytes).digest('hex');
const serialize=(value:unknown)=>Buffer.from(JSON.stringify(value),'utf8');
const digest=z.string().regex(/^[a-f0-9]{64}$/u);
const provider={id:'theseus-retained-managed-native',name:'Theseus retained managed/native projection',version:'1'};
const savedManagedSchema=z.object({operation:z.literal('managed.native_boundaries'),artifact_sha256:digest,
  result:z.object({artifact:z.object({path:z.string(),sha256:digest}).passthrough()}).passthrough()}).passthrough();
const savedNativeSchema=z.object({operation:z.literal('binary.analyze_function'),artifact_sha256:digest,
  result:z.object({value:z.unknown()}).passthrough()}).passthrough();
const historyLimitations=['Derived from retained JSON, not a current inspection of the original file.',
  'Historical provider context and module labels do not establish the truth or completeness of the producer.'];

function sourceValue(name:string,evidence:Evidence,origin:string,jobIds:string[]):Source {
  // The full received value also binds display labels that the semantic Evidence ID excludes.
  const raw=serialize(evidence);
  return {name,evidence,origin,source_job_ids:jobIds,evidence_value_sha256:hash(raw),evidence_value_json_base64:raw.toString('base64')};
}

function inputScope(item:Source) {
  // Supported payloads were validated by the maintained verifier before this projection.
  const exports=item.evidence.operation==='inspect_macho'
    ?(item.evidence.normalized_result as unknown as InspectMacho).exports:null;
  return {evidence_id:item.evidence.evidence_id,origin:item.origin,
    module_labels:item.evidence.subject===null?null:{name:item.evidence.subject.name,local_path:item.evidence.subject.local_path},
    module_labels_authenticated_by_semantic_id:false,evidence_value_sha256:item.evidence_value_sha256,
    exports_coverage:exports===null?null:{total:exports.total,exhaustive:exports.exhaustive,limitations:exports.limitations},
    declared_limitations:item.evidence.limitations};
}

export async function managedNativeVerification(bytes:Buffer,inputs:NativeObservationInput[],query?:unknown,source?:ManagedSource):Promise<unknown> {
  const saved=savedManagedSchema.parse(JSON.parse(bytes.toString('utf8'))),managedSha=hash(bytes);
  if(source&&(source.analysis_sha256!==managedSha||source.artifact_sha256!==saved.artifact_sha256))
    throw new Error('Retained managed source differs from its receipt');
  const managed=createEvidence({path:saved.result.artifact.path,sha256:saved.artifact_sha256,format:'pe'},provider,{
    operation:'inspect_managed_native_boundaries',parameters:{analysis_sha256:managedSha},
    result:saved.result as JsonValue,rawResult:{analysis_sha256:managedSha,document_base64:bytes.toString('base64')},
    confidence:'derived',authority:'historical-reference',limitations:historyLimitations});
  const managedObservation:Source={...sourceValue('Managed declarations',managed,'retained-job-document',source?[source.job_id]:[]),
    analysis_sha256:managedSha,document_base64:bytes.toString('base64'),
    historical_context:{document_engine:saved.engine??null,document_runtime:saved.runtime??null}};
  const sources:Source[]=[managedObservation],native:Evidence[]=[],order:{origin:string;index:number;evidence_id:string}[]=[];
  const seen=new Map<string,Source>();
  for(const [index,input] of inputs.entries()) {
    const raw=await readFile(input.path);
    if(hash(raw)!==input.sha256)throw new Error('Retained native observation changed; its receipt hash no longer matches');
    const document=savedNativeSchema.parse(JSON.parse(raw.toString('utf8')));
    if(document.artifact_sha256!==input.artifact_sha256)
      throw new Error('Native observation original artifact identity does not match its receipt');
    const dossier=functionDossierSchema.parse(document.result.value);
    const context={artifact_path:input.artifact_path,artifact_sha256:input.artifact_sha256,artifact_format:input.artifact_format,
      provider_profile:input.profile??null,profile_sha256:input.profile_sha256??null,
      analysis_revision:input.analysis_revision??null,recorded_provider_version:input.version};
    const evidence=createEvidence({path:input.artifact_path,sha256:input.artifact_sha256,format:input.artifact_format},provider,{
      operation:'analyze_function',parameters:{analysis_sha256:input.sha256},result:document.result.value as JsonValue,
      rawResult:{analysis_sha256:input.sha256,document_base64:raw.toString('base64'),receipt_context:context as JsonValue},
      confidence:'derived',authority:'historical-reference',limitations:[...historyLimitations,...dossier.limitations]});
    const observation:Source={...sourceValue(dossier.procedure.name,evidence,'retained-job-document',[input.job_id]),
      analysis_sha256:input.sha256,document_base64:raw.toString('base64'),historical_context:context};
    const existing=seen.get(evidence.evidence_id);
    if(existing) {
      if(existing.evidence_value_sha256!==observation.evidence_value_sha256||existing.analysis_sha256!==input.sha256)
        throw new Error('Duplicate native Evidence ID with different retained values or module labels');
      existing.source_job_ids.push(input.job_id);
    } else {
      seen.set(evidence.evidence_id,observation);native.push(evidence);sources.push(observation);
    }
    order.push({origin:'retained-job-document',index,evidence_id:evidence.evidence_id});
  }
  const supplied=z.object({native_observations:z.array(z.unknown()).min(1)}).strict().optional().parse(query);
  for(const [index,value] of (supplied?.native_observations??[]).entries()) {
    const evidence=parseEvidence(value);
    if(seen.has(evidence.evidence_id)||evidence.evidence_id===managed.evidence_id)
      throw new Error('Duplicate native Evidence ID across supplied values or retained inputs');
    const observation=sourceValue(evidence.subject?.name??evidence.operation,evidence,'caller-supplied-retained-evidence',[]);
    const submitted=serialize(value);
    observation.submitted_value_sha256=hash(submitted);
    observation.submitted_value_json_base64=submitted.toString('base64');
    seen.set(evidence.evidence_id,observation);native.push(evidence);sources.push(observation);
    order.push({origin:observation.origin,index,evidence_id:evidence.evidence_id});
  }
  const verification=verifyManagedNativeBoundaries(managedNativeVerificationInputSchema.parse({managed_boundaries:managed,native_observations:native}));
  const resolved=new Set(sources.map(item=>item.evidence.evidence_id));
  const unresolved=[...new Set(sources.flatMap(item=>item.evidence.evidence_links).filter(id=>!resolved.has(id)))].sort();
  return {verification,source_observations:sources,input_order:order,
    retained_closure:{unresolved_evidence_links:unresolved,
      status:unresolved.length?'external-citations-not-supplied':'supplied-direct-evidence-resolved'},
    input_scope:sources.map(inputScope),
    retained_interpretation:{original_artifact_accessed:false,executed:false,
      module_identity:'Historical or caller-supplied module labels; full received values are retained without filesystem verification.',
      integrity:'Semantic IDs and full-value hashes preserve supplied content, not producer authenticity or observation truth.',
      matching:'Job observations first, then supplied Evidence, each in caller order. Maintained helper priority and first-candidate ties are preserved.',
      coverage:'Complete-within-inputs does not establish exhaustive native exports, CLR binding or token-to-native-address mapping.'}};
}
