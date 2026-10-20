/** Complete function dimensions from retained native dossiers, without a live provider. */
import {createHash} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {z} from 'zod';
import {functionDossierSchema} from './src/domain/hopperValues.js';
import {relationshipCoverageSchema} from './src/domain/relationshipCoverage.js';
import {createEvidence} from './src/domain/evidence.js';
import {compareFunctions} from './src/domain/functionComparison.js';
import {overallStatus,summarize,unresolvedDimension} from './src/domain/functionComparisonResults.js';
import type {JsonValue} from './src/domain/jsonValue.js';
import {retainedInputSchema} from './retained-evidence.js';

type Input=z.infer<typeof retainedInputSchema>;
const providerSchema=z.object({id:z.string().min(1),version:z.string().min(1),profile_sha256:z.string().regex(/^[a-f0-9]{64}$/),
  analysis_revision:z.number().int().min(0)}).strict();
const savedSchema=z.object({operation:z.literal('binary.analyze_function'),artifact_sha256:z.string().regex(/^[a-f0-9]{64}$/),
  session_id:z.string().min(1),result:z.object({value:functionDossierSchema,limitations:z.array(z.string()),relationship_coverage:relationshipCoverageSchema})});

export async function compareRetainedFunctions(inputs:Input[],roles:{reference_job_id:string;candidate_job_id:string}) {
  const closure:unknown[]=[],bindings:unknown[]=[],facts:ReturnType<typeof createEvidence>[]=[],profiles:string[]=[],blockers:string[]=[];
  for(const [side,key] of [['reference',roles.reference_job_id],['candidate',roles.candidate_job_id]] as const) {
    const input=inputs.find(row=>row.job_id===key&&row.selected);
    if(!input?.path||!input.analysis_sha256)throw new Error('Missing selected function input: '+side);
    const bytes=await readFile(input.path),sha=createHash('sha256').update(bytes).digest('hex');
    if(sha!==input.analysis_sha256)throw new Error('Retained function document hash changed');
    const raw=JSON.parse(bytes.toString('utf8')) as {operation?:string;artifact_sha256?:string};
    if(raw.operation!==input.operation||raw.artifact_sha256!==input.artifact_sha256)throw new Error('Retained function operation or artifact identity differs');
    // Stable closure excludes machine-local job IDs and file paths, so the same
    // retained comparison can be independently recomputed after transfer.
    closure.push({side,operation:input.operation,analysis_sha256:sha,artifact_sha256:input.artifact_sha256,
      provider:input.provider,document_base64:bytes.toString('base64')});
    const saved=savedSchema.safeParse(raw),provider=providerSchema.safeParse(input.provider);
    if(!saved.success||!provider.success){blockers.push('Incomplete function dossier or provider identity: '+side);continue;}
    const value=saved.data;
    profiles.push(provider.data.profile_sha256);
    const evidence=createEvidence({path:'retained-json://'+sha,sha256:value.artifact_sha256,format:'unknown'},
      {id:provider.data.id,name:provider.data.id,version:provider.data.version},
      {operation:'analyze_function',parameters:{analysis_sha256:sha,profile_sha256:provider.data.profile_sha256,
        analysis_revision:provider.data.analysis_revision,context_id:value.session_id},
        result:value.result.value as unknown as JsonValue,rawResult:value.result as unknown as JsonValue,
        confidence:'observed',authority:'historical-reference',limitations:value.result.limitations,
        relationshipCoverage:value.result.relationship_coverage});
    facts.push(evidence);
    bindings.push({side,analysis_sha256:sha,artifact_sha256:value.artifact_sha256,evidence_id:evidence.evidence_id,
      provider:provider.data});
  }
  const context={format:'vitruvius.retained-function-comparison/1',behavior_status:'not-evaluated',retained_inputs:bindings,closure,
    limitations:['Only complete, retained function dossiers were compared; no original path or live engine was accessed.',
      'The caller selects both functions explicitly. Text, annotations, calls and other static dimensions are behavior candidates, not observed execution.',
      'The closure retains source bytes and producer identities; hashes establish integrity, not authenticity or truth.']};
  if(blockers.length)return {...context,status:'unknown',dimensions:[],changes:[],blockers};
  const compared=compareFunctions(facts[0]!,facts[1]!);
  const compatible=profiles[0]===profiles[1];
  const dimensions=compared.dimensions.map(row=>!compatible&&['pseudocode','assembly'].includes(row.dimension)?
    unresolvedDimension({dimension:row.dimension,links:row.evidence_links,leftCount:row.left_count,rightCount:row.right_count,
      limitations:[...row.limitations,'Exact provider text requires matching retained analysis profiles.']}):row);
  return {...compared,...context,status:overallStatus(dimensions,compared.function_match.status),dimensions,
    changes:dimensions.filter(row=>row.status!=='unchanged'),summary:summarize(dimensions),analysis_profiles_compatible:compatible,
    limitations:[...context.limitations,...compared.limitations],blockers:[]};
}
