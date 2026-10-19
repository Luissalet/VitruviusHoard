/** Contrast retained managed declarations with individually identified native observations. */
import {readFile} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {createEvidence,type Evidence,type EvidenceSubjectTarget} from './src/domain/evidence.js';
import {verifyManagedNativeBoundaries} from './src/domain/managed/managedNativeVerification.js';
import {managedNativeVerificationInputSchema} from './src/domain/managed/managedNativeVerificationSchemas.js';
import type {JsonValue} from './src/domain/jsonValue.js';

export interface NativeObservationInput {
  path:string;sha256:string;artifact_path:string;artifact_sha256:string;artifact_format:'pe'|'elf'|'mach-o'|'unknown';version:string;job_id:string;
}

export async function managedNativeVerification(bytes:Buffer,inputs:NativeObservationInput[]):Promise<unknown> {
  const saved=JSON.parse(bytes.toString('utf8'));
  if(saved.operation!=='managed.native_boundaries') throw new Error('Select a retained managed native-boundary analysis');
  const managed=createEvidence({path:saved.result.artifact.path,sha256:saved.artifact_sha256,format:'pe'},
    {id:'theseus-managed',name:'Theseus managed analysis',version:'1'},
    {operation:'inspect_managed_native_boundaries',parameters:{},result:saved.result as JsonValue,
      rawResult:null,confidence:'observed',authority:'shipped-artifact'});
  const sources:{name:string;evidence:Evidence;source_job_ids:string[]}[]=[{name:'Managed declarations',evidence:managed,source_job_ids:[]}];
  const native=[];
  for(const input of inputs) {
    const raw=await readFile(input.path);
    if(createHash('sha256').update(raw).digest('hex')!==input.sha256) throw new Error('Retained native observation changed; its receipt hash no longer matches');
    const document=JSON.parse(raw.toString('utf8'));
    if(document.operation!=='binary.analyze_function' || document.artifact_sha256!==input.artifact_sha256)
      throw new Error('Native observation operation or original artifact identity does not match its receipt');
    const target:EvidenceSubjectTarget={path:input.artifact_path,sha256:input.artifact_sha256,format:input.artifact_format};
    const dossier=document.result.value;
    const evidence=createEvidence(target,{id:'theseus-ghidra-retained',name:'Theseus retained Ghidra observations',version:input.version},
      {operation:'analyze_function',parameters:{},result:dossier as JsonValue,rawResult:null,
        confidence:'observed',authority:'shipped-artifact',limitations:dossier.limitations??[]});
    const existing=sources.find(row=>row.evidence.evidence_id===evidence.evidence_id);
    if(existing) existing.source_job_ids.push(input.job_id);
    else {
      native.push(evidence);
      sources.push({name:dossier.procedure.name,evidence,source_job_ids:[input.job_id]});
    }
  }
  return {verification:verifyManagedNativeBoundaries(managedNativeVerificationInputSchema.parse({managed_boundaries:managed,native_observations:native})),
    source_observations:sources};
}
