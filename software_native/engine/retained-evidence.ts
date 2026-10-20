/** Direct call paths from complete, hash-bound retained function dossiers. */
import {createHash} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {z} from 'zod';
import {functionDossierSchema,type FunctionDossier} from './src/domain/hopperValues.js';
import {relationshipCoverageSchema} from './src/domain/relationshipCoverage.js';
import {isCallerOnlyIncompleteCoverage} from './src/domain/functionCallCoverage.js';
import {parseCallPathAddress} from './src/domain/callPathSchemas.js';

export const retainedInputSchema=z.object({job_id:z.string(),selected:z.boolean(),path:z.string().optional(),
  operation:z.string().optional(),artifact_id:z.string().optional(),artifact_sha256:z.string().optional(),
  analysis_sha256:z.string().optional(),provider:z.unknown().optional(),error:z.string().optional()}).strict();
type Input=z.infer<typeof retainedInputSchema>;
const hash=(bytes:Buffer)=>createHash('sha256').update(bytes).digest('hex');
const canonical=(value:unknown):string=>Array.isArray(value)?'['+value.map(canonical).join(',')+']':
  value!==null&&typeof value==='object'?'{'+Object.entries(value).sort(([a],[b])=>a<b?-1:a>b?1:0).map(([k,v])=>JSON.stringify(k)+':'+canonical(v)).join(',')+'}':JSON.stringify(value);
const providerSchema=z.object({id:z.string().min(1),version:z.string().min(1),profile_sha256:z.string().regex(/^[a-f0-9]{64}$/),
  analysis_revision:z.number().int().min(0)}).strict();
const savedSchema=z.object({operation:z.literal('binary.analyze_function'),artifact_sha256:z.string().regex(/^[a-f0-9]{64}$/),
  session_id:z.string().min(1),result:z.object({value:functionDossierSchema,limitations:z.array(z.string()),
    relationship_coverage:relationshipCoverageSchema})});
type Node={dossier:FunctionDossier;links:string[];complete:boolean;targets:string[]};

export async function callPaths(inputs:Input[],query:unknown) {
  const parameters=z.object({start:z.string(),goal:z.string()}).strict().parse(query);
  const start=parseCallPathAddress(parameters.start),goal=parseCallPathAddress(parameters.goal);
  const nodes=new Map<string,Node>(),contexts=new Set<string>(),blockers:string[]=[],diagnostics:string[]=[],closure:unknown[]=[];
  const links:string[]=[];
  for(const input of inputs) {
    if(!input.selected)continue;
    if(!input.path||!input.analysis_sha256){blockers.push('Selected function document is missing: '+input.job_id);continue;}
    const bytes=await readFile(input.path);
    if(hash(bytes)!==input.analysis_sha256)throw new Error('Retained function document hash changed: '+input.job_id);
    const link='analysis:'+input.analysis_sha256;links.push(link);
    closure.push({...input,path:undefined,document_base64:bytes.toString('base64')});
    const parsed=savedSchema.safeParse(JSON.parse(bytes.toString('utf8')));
    const provider=providerSchema.safeParse(input.provider);
    if(!parsed.success||!provider.success){blockers.push('Incomplete function dossier or provider identity: '+input.job_id);continue;}
    const saved=parsed.data,dossier=saved.result.value;
    if(saved.artifact_sha256!==input.artifact_sha256||input.operation!==saved.operation)throw new Error('Retained function artifact/operation identity differs');
    contexts.add(canonical({artifact:saved.artifact_sha256,provider:provider.data,context:saved.session_id}));
    const address=parseCallPathAddress(dossier.procedure.address);
    const coverage=saved.result.relationship_coverage;
    const complete=(coverage.status==='complete'||isCallerOnlyIncompleteCoverage(coverage))&&
      dossier.facet_availability?.callees?.available===true&&(dossier.unresolved_calls?.length??0)===0;
    diagnostics.push(...saved.result.limitations,...dossier.limitations,...(coverage.diagnostics??[]));
    const targets=[...new Set(dossier.callees.map(row=>parseCallPathAddress(row.address)))].sort();
    const existing=nodes.get(address);
    if(existing) {
      if(canonical(existing.dossier)!==canonical(dossier)||existing.complete!==complete)blockers.push('Conflicting dossiers at '+address);
      existing.links.push(link);
    } else nodes.set(address,{dossier,links:[link],complete,targets});
  }
  if(contexts.size!==1)blockers.push('Functions do not share one complete artifact, provider, profile, revision and context');
  if(!nodes.has(start))blockers.push('Missing start function dossier');
  if(!nodes.has(goal))blockers.push('Missing goal function dossier');
  const distance=new Map<string,number>([[start,0]]),parents=new Map<string,Set<string>>(),queue=[start];
  let depth=0,edges=0,goalDistance=start===goal?0:Infinity;
  for(let index=0;index<queue.length;index++) {
    const address=queue[index]!,d=distance.get(address)!;
    if(d>=goalDistance)continue;
    depth=Math.max(depth,d);
    const node=nodes.get(address);
    if(!node){blockers.push('Missing reachable function dossier: '+address);continue;}
    if(!node.complete)blockers.push('Direct callee coverage is incomplete: '+address);
    for(const target of node.targets) {
      edges++;
      const prior=distance.get(target);
      if(prior===undefined){distance.set(target,d+1);queue.push(target);}
      if(prior===undefined||prior===d+1){
        if(!parents.has(target))parents.set(target,new Set());parents.get(target)!.add(address);
      }
      if(target===goal)goalDistance=d+1;
    }
  }
  const unique=(values:string[])=>[...new Set(values)].sort();
  const paths:unknown[]=[];
  if(!blockers.length&&Number.isFinite(goalDistance)) {
    // Iterative traversal of the shortest-path predecessor DAG: no arbitrary
    // depth or path count cap and no recursive stack limit.
    const stack=[{at:goal,reverse:[goal]}];
    while(stack.length) {
      const item=stack.pop()!;
      if(item.at===start) {
        const ordered=[...item.reverse].reverse();
        const citedNodes=ordered.map(address=>({address,name:nodes.get(address)!.dossier.procedure.name,
          evidence_links:unique(nodes.get(address)!.links)}));
        const citedEdges=ordered.slice(1).map((target,index)=>({source:ordered[index]!,target,
          evidence_links:unique(nodes.get(ordered[index]!)!.links)}));
        paths.push({hops:ordered.length-1,nodes:citedNodes,edges:citedEdges,
          evidence_links:unique(citedNodes.flatMap(node=>node.evidence_links))});
      } else for(const parent of [...(parents.get(item.at)??[])].sort().reverse())stack.push({at:parent,reverse:[...item.reverse,parent]});
    }
  }
  return {format:'vitruvius.retained-call-paths/1',status:blockers.length?'unknown':paths.length?'found':'not_found',start,goal,
    shortest_hops:blockers.length||!paths.length?null:goalDistance,search_scope:{exhaustive:!blockers.length},paths,
    explored:{nodes:distance.size,edges,depth_reached:depth},evidence_links:unique(links),
    blockers:unique(blockers),diagnostics:unique(diagnostics),closure,
    limitations:['All shortest direct-callee paths in the selected retained dossiers are enumerated; no runtime call is asserted.',
      'Names are labels, never identity. Addresses retain their address spaces. Indirect calls, missing dossiers and mixed analysis contexts remain unknown.',
      'The original program and analysis engine were not accessed. Producer completeness remains a retained claim.']};
}
