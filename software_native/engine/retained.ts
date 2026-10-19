/** Native derived observations over hash-verified analysis documents. */
import {basename,extname} from 'node:path';
import {createHash} from 'node:crypto';
import {stat} from 'node:fs/promises';
import {directoryEntries} from './directory.js';
import {createHistoricalSourceGraph} from './src/domain/referenceSourceGraph.js';
import {createEvidence} from './src/domain/evidence.js';
import {importManagedReconstruction,managedReconstructionImportInputSchema} from './src/domain/managed/managedReconstruction.js';
import type {JsonValue} from './src/domain/jsonValue.js';

export async function sourceGraph(path:string,bytes:Buffer):Promise<unknown> {
  const rows=(await stat(path)).isDirectory()?await directoryEntries(path):
    [[basename(path),'file',createHash('sha256').update(bytes).digest('hex'),bytes.length] as [string,string,string,number]];
  const language=(name:string):string|null=>({'.js':'javascript','.cjs':'javascript','.mjs':'javascript','.jsx':'javascript',
    '.ts':'typescript','.tsx':'typescript','.py':'python','.cs':'csharp','.rs':'rust','.go':'go'} as Record<string,string>)[extname(name)]??null;
  const entries=rows.map(([path,kind,sha256,size])=>{
    const common={path,classifications:basename(path)==='package.json'?['manifest']:language(path)?['source']:['unknown'],limitations:[]};
    return kind==='directory'?{...common,kind:'directory',tree_state:'enumerated'}:
      kind==='file'?{...common,kind:'file',language:language(path),sha256,size,content_state:'hashed'}:
      {...common,kind:'unknown',limitations:['Linked or special entry contents were not inventoried.']};
  });
  return createHistoricalSourceGraph({schema:'HistoricalSourceGraph',authority:'historical-reference',root_alias:'$REFERENCE_ROOT',
    inventory_state:rows.some(row=>!['file','directory'].includes(row[1]))?'partial':'complete',entries,relationships:[],parse_failures:[],
    exclusions:[],languages:[...new Set(rows.map(row=>language(row[0])).filter((x):x is string=>x!==null))].sort(),
    manifests:rows.filter(row=>basename(row[0])==='package.json'&&row[1]==='file').map(row=>row[0]),vcs:null,
    provenance:{importer:'Theseus',importer_version:'1',caller:'local-artifact-analysis'},
    limitations:rows.some(row=>!['file','directory'].includes(row[1]))?['Linked or special entry contents were not inventoried.']:[]});
}

export function managedReconstruction(bytes:Buffer,query:unknown):unknown {
  const saved=JSON.parse(bytes.toString('utf8'));
  if(saved.operation!=='managed.members') throw new Error('Select a retained managed.members analysis');
  const result=saved.result;
  const carrier=createEvidence({path:result.artifact.path,sha256:saved.artifact_sha256,format:'pe'},
    {id:'theseus-managed',name:'Theseus managed analysis',version:'1'},
    {operation:'inspect_managed_members',parameters:{},result:result as JsonValue,rawResult:null,confidence:'observed',authority:'shipped-artifact'});
  return importManagedReconstruction(managedReconstructionImportInputSchema.parse({...(query as object),static_members:carrier}));
}
