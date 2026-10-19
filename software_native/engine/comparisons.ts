/** Native comparisons of retained, hash-bound static observations. */
import {createHash} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {z} from 'zod';
import {managedMemberInspectionSchema} from './src/domain/managed/managedArtifact.js';
import {compareManagedMembers} from './src/domain/managed/managedMemberComparison.js';
import {javascriptApplicationGraphSchema} from './src/domain/javascript/javascriptApplicationGraph.js';
import {compareJavaScriptApplicationVersions} from './src/domain/javascript/javascriptApplicationVersionComparison.js';
import {compareJavaScriptExportShapes} from './src/domain/javascript/javascriptExportShapeComparison.js';
import {parseHistoricalSourceGraph} from './src/domain/referenceSourceGraph.js';
import {compareSourceToBundle} from './src/domain/javascript/sourceToBundleComparison.js';
import {compareWasm} from './wasm-comparison.js';
import {artifactInventoryResultSchema} from './src/domain/artifactGraph.js';
import {compareArtifacts} from './src/domain/artifactComparison.js';
import {createEvidence} from './src/domain/evidence.js';
import type {JsonValue} from './src/domain/jsonValue.js';

const savedSchema=z.object({operation:z.string(),artifact_sha256:z.string(),result:z.unknown()});
const applicationSchema=z.object({graph:javascriptApplicationGraphSchema});
const selectorsSchema=z.object({reference:z.object({module_path:z.string(),export_name:z.string()}).strict(),
  candidate:z.object({module_path:z.string(),export_name:z.string()}).strict()}).strict();

export async function compareRetained(operation:string,referenceBytes:Buffer,candidatePath:string,
  expectedCandidateSha256:string,query:unknown):Promise<unknown> {
  const candidateBytes=await readFile(candidatePath);
  const candidateSha=createHash('sha256').update(candidateBytes).digest('hex');
  if (candidateSha!==expectedCandidateSha256) throw new Error('Candidate analysis changed; its receipt hash no longer matches');
  const reference=savedSchema.parse(JSON.parse(referenceBytes.toString('utf8')));
  const candidate=savedSchema.parse(JSON.parse(candidateBytes.toString('utf8')));
  const referenceId='ev_'+createHash('sha256').update(referenceBytes).digest('hex');
  const candidateId='ev_'+candidateSha;
  if(operation==='artifact.compare') {
    if(reference.operation!=='artifact.inventory'||candidate.operation!=='artifact.inventory') throw new Error('Select two complete retained inventory documents');
    const bindings=[reference,candidate].map((saved,index)=>{
      const inventory=artifactInventoryResultSchema.parse(saved.result);
      const analysisSha256=index===0?referenceId.slice(3):candidateSha;
      const evidence=createEvidence({path:'retained-json://'+analysisSha256,sha256:inventory.manifest.root_sha256,format:inventory.manifest.root_format},
        {id:'theseus-retained-inventory',name:'Theseus retained inventory',version:'1'},
        {operation:'inventory_artifact',parameters:{},result:inventory as unknown as JsonValue,rawResult:null,
          confidence:'observed',authority:'historical-reference',limitations:inventory.limitations});
      return {evidence,binding:{side:index===0?'reference':'candidate',evidence_id:evidence.evidence_id,
        analysis_sha256:analysisSha256,artifact_sha256:saved.artifact_sha256,inventory_root_sha256:inventory.manifest.root_sha256}};
    });
    const compared=compareArtifacts(bindings[0]!.evidence,bindings[1]!.evidence);
    return {...compared,changes:compared.changes.map(row=>({...row,name:row.logical_path})),
      retained_inputs:bindings.map(row=>row.binding),limitations:[...compared.limitations,
        'Only the two retained inventory JSON documents were read; each internal inventory evidence ID is bound to its source document hash in retained_inputs.',
        'An unchanged inventory describes the recorded artifact observations, not behavioral equivalence or execution coverage.']};
  }
  if(operation==='wasm.compare_interfaces') {
    if(reference.operation!=='wasm.artifact'||candidate.operation!=='wasm.artifact') throw new Error('Select two WASM analyses');
    const scope=z.object({scope:z.enum(['both','imports','exports']).default('both')}).parse(query??{}).scope;
    return compareWasm((reference.result as {interface:unknown}).interface,(candidate.result as {interface:unknown}).interface,scope);
  }
  if(operation==='javascript.compare_source') {
    if(reference.operation!=='source.graph'||candidate.operation!=='javascript.application') throw new Error('Select a source graph and a JavaScript application');
    const application=applicationSchema.parse(candidate.result);
    return compareSourceToBundle({reference:parseHistoricalSourceGraph(reference.result),application:{
      evidenceId:candidateId,rootArtifactSha256:candidate.artifact_sha256,graph:application.graph}});
  }
  if (operation==='managed.compare') {
    if (reference.operation!=='managed.members' || candidate.operation!=='managed.members') throw new Error('Select two managed member analyses');
    return compareManagedMembers({evidenceId:referenceId,result:managedMemberInspectionSchema.parse(reference.result)},
      {evidenceId:candidateId,result:managedMemberInspectionSchema.parse(candidate.result)});
  }
  if (operation==='javascript.compare_versions' || operation==='javascript.compare_exports') {
    if (reference.operation!=='javascript.application' || candidate.operation!=='javascript.application') throw new Error('Select two JavaScript application analyses');
    const left=applicationSchema.parse(reference.result),right=applicationSchema.parse(candidate.result);
    if (operation==='javascript.compare_versions') return compareJavaScriptApplicationVersions({
      left:{evidenceId:referenceId,rootArtifactSha256:reference.artifact_sha256,graph:left.graph},
      right:{evidenceId:candidateId,rootArtifactSha256:candidate.artifact_sha256,graph:right.graph},
      leftNativeEvidence:[],rightNativeEvidence:[]});
    const selectors=selectorsSchema.parse(query);
    return compareJavaScriptExportShapes({left:{evidenceId:referenceId,graph:left.graph,
      modulePath:selectors.reference.module_path,exportName:selectors.reference.export_name},
      right:{evidenceId:candidateId,graph:right.graph,modulePath:selectors.candidate.module_path,exportName:selectors.candidate.export_name}});
  }
  throw new Error('Unknown retained comparison operation: '+operation);
}
