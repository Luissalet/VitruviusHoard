/** Native WASM observations over selected bytes and explicit local glue files. */
import {createHash} from 'node:crypto';
import {readFile} from 'node:fs/promises';
import {createRequire} from 'node:module';
import {basename,dirname} from 'node:path';
import * as t from '@babel/types';
import wabtFactory from 'wabt';
import {absoluteCallerPath} from './src/filesystem/callerPath.js';
import {parseJavaScriptSource} from './src/domain/javascript/javascriptSourceParser.js';
import {traverseJavaScriptAst} from './src/domain/javascript/javascriptSemanticTraversal.js';
import {parseWabtWat} from './src/wasm/WabtWat.js';

export interface WasmParameters {glue_paths?:string[]|undefined;candidate_paths?:string[]|undefined}
export type WasmObservation=Record<string,unknown>;
export type WasmPublisher=(observation:WasmObservation)=>Promise<void>;
const hash=(bytes:Buffer|string)=>createHash('sha256').update(bytes).digest('hex');
const identity=(path:string,bytes:Buffer)=>({path:absoluteCallerPath(path),sha256:hash(bytes),bytes:bytes.length});
const sectionKinds=['custom','type','import','function','table','memory','global','export','start','element','code','data','data_count','tag'];

function sectionRanges(bytes:Buffer,sections:WasmObservation[]) {
  if(bytes.length<8||!bytes.subarray(0,8).equals(Buffer.from('0061736d01000000','hex')))
    throw new Error('The reader requires a complete version 1 WebAssembly core-module header.');
  let offset=8;
  while(offset<bytes.length) {
    const headerStart=offset,id=bytes[offset++]!;
    let size=0,terminated=false;
    for(let index=0;index<5;index++) {
      const value=bytes[offset++];
      if(value===undefined||(index===4&&(value&0xf0)!==0))throw new Error('Malformed section-size u32 encoding.');
      size+=(value&0x7f)*2**(7*index);
      if((value&0x80)===0){terminated=true;break;}
    }
    if(!terminated)throw new Error('Unterminated section-size u32 encoding.');
    const start=offset,end=start+size;
    if(end>bytes.length)throw new Error('A declared section payload extends beyond the selected bytes.');
    const payload=bytes.subarray(start,end),header=bytes.subarray(headerStart,start);
    sections.push({kind:sectionKinds[id]??'section-'+id,id,start,end,bytes:size,
      header:{start:headerStart,end:start,bytes:header.length,base64:header.toString('base64'),sha256:hash(header)},
      payload_base64:payload.toString('base64'),payload_sha256:hash(payload)});
    offset=end;
  }
}

function glueReferences(source:string,path:string,candidates:string[]) {
  const ast=parseJavaScriptSource(source.startsWith('\uFEFF#!')?source.slice(1):source,path);
  const references:WasmObservation[]=[];
  if(ast===null)return {parse_status:'failed',references,parse_issues:['The selected JavaScript source could not be parsed.']};
  traverseJavaScriptAst(ast,{enter(node){
    let value:string|null|undefined;
    if(t.isStringLiteral(node))value=node.value;
    else if(t.isDirectiveLiteral(node)) {
      const cooked=node.extra?.expressionValue;
      if(typeof cooked==='string')value=cooked;
    } else if(t.isTemplateLiteral(node)&&node.expressions.length===0)value=node.quasis[0]?.value.cooked;
    if(typeof value!=='string'||!/\.wasm(?:[?#].*)?$/iu.test(value)||node.loc==null)return;
    const stripped=value.split(/[?#]/u)[0]??value;
    const local=!/^[a-z][a-z\d+.-]*:|^\/\//iu.test(value)&&!value.startsWith('/')&&!/[?#]/u.test(value);
    const target=local?absoluteCallerPath(value,{cwd:dirname(path)}):undefined;
    const exact=target===undefined?[]:candidates.filter(candidate=>absoluteCallerPath(candidate)===target);
    const matches=exact.length?exact:candidates.filter(candidate=>basename(candidate)===basename(stripped));
    references.push({value,line:node.loc.start.line,column:node.loc.start.column,candidate_paths:matches,
      association:exact.length?'local-path-candidate':matches.length?'basename-candidates':'unresolved',evidence_kind:'static-literal'});
  }});
  return {parse_status:ast.errors.length?'partial':'complete',references,
    parse_issues:ast.errors.map(error=>String(error.message))};
}

/** A publisher observes prefixes only; its caller decides how to retain them. */
export async function inspectWasm(bytes:Buffer,path:string,parameters:WasmParameters={},publish?:WasmPublisher) {
  const selected=identity(path,bytes);
  const result:WasmObservation={format:'vitruvius.wasm-observation/1',artifact:selected,
    producer:{pid:process.pid,executable:process.execPath,arguments:process.argv},
    validation:'not-established',completion_status:'unknown',
    selected_inputs:{glue_paths:(parameters.glue_paths??[]).map(value=>absoluteCallerPath(value)),
      candidate_paths:(parameters.candidate_paths??[]).map(value=>absoluteCallerPath(value))},
    runtime_execution:'not-performed',network_fetch:'not-performed',
    limitations:['WAT is a decoded representation; generated names do not establish original source identifiers or binary round-trip identity.',
      'Glue references are visible literal associations with selected candidates, not data flow, loading, runtime behavior or URL-to-file identity.',
      'Only the bundled reader and its advertised enabled features establish validation; other tool versions or execution environments are not certified.']};
  const checkpoint=async(phase:string)=>{result.phase=phase;if(publish)await publish({...result});};
  let module:ReturnType<Awaited<ReturnType<typeof wabtFactory>>['readWasm']>|undefined;
  try {
    await checkpoint('initializing-reader');
    const require=createRequire(import.meta.url);
    const packagePath=require.resolve('wabt/package.json'),implementationPath=require.resolve('wabt');
    const packageBytes=await readFile(packagePath),implementationBytes=await readFile(implementationPath);
    const packageInfo=JSON.parse(packageBytes.toString('utf8')) as {version?:string};
    const wabt=await wabtFactory();
    const advertised=(wabt as unknown as {FEATURES?:Record<string,boolean>}).FEATURES??{};
    const features=Object.fromEntries(Object.keys(advertised).map(key=>[key,true]));
    result.engine_profile={name:'wabt.js',version:packageInfo.version??null,runtime:process.version,
      package_identity:identity(packagePath,packageBytes),implementation_identity:identity(implementationPath,implementationBytes),
      feature_policy:Object.keys(advertised).length?'all-advertised-features':'reader-defaults',enabled_features:Object.keys(features),
      validation_method:'WasmModule.validate',decoding_method:'WasmModule.toText'};
    result.module_header={bytes:Math.min(8,bytes.length),base64:bytes.subarray(0,8).toString('base64'),complete:bytes.length>=8};
    const sections:WasmObservation[]=[];result.sections=sections;result.sections_complete=false;
    await checkpoint('reading-section-ranges');sectionRanges(bytes,sections);result.sections_complete=true;
    // The bundled reader sizes typed-array views by their whole backing buffer, so it receives an exact copy.
    const exact=new Uint8Array(bytes);
    await checkpoint('host-validating');
    const hostValid=(globalThis as unknown as {WebAssembly:{validate(bytes:Uint8Array):boolean}}).WebAssembly.validate(exact);
    result.host_validation={method:'WebAssembly.validate',runtime:process.version,v8:process.versions.v8,valid:hostValid,
      scope:'Decoding and validation by the host runtime that runs the reader; no compilation result, instantiation or execution is retained.'};
    await checkpoint('reading-module');module=wabt.readWasm(exact,{...features,readDebugNames:true,check:true});
    // The published typings omit validate's runtime feature options; without them the reader validates with its defaults.
    await checkpoint('validating-module');
    (module.validate as (options:Record<string,boolean>)=>void).call(module,features);result.validation='valid';
    result.validators_agree=hostValid;
    await checkpoint('decoding-module');module.generateNames();module.applyNames();
    const text=module.toText({foldExprs:false,inlineExport:false}),parsed=parseWabtWat(text);
    Object.assign(result,parsed,{wat:text,wat_sha256:hash(text),wat_bytes:Buffer.byteLength(text,'utf8'),wat_representation:'decoded-wat',
      interface_entries:parsed.interface.entries,
      definitions:parsed.forms.map((definition,index)=>({name:/^\(\w+\s+([^\s()]+)/.exec(definition)?.[1]||String(index),definition}))});
    const candidates=[selected];result.candidates=candidates;result.candidates_complete=false;
    await checkpoint('reading-selected-candidates');
    for(const input of parameters.candidate_paths??[]) {
      const selectedPath=absoluteCallerPath(input),raw=await readFile(selectedPath);
      candidates.push(identity(selectedPath,raw));await checkpoint('reading-selected-candidates');
    }
    result.candidates_complete=true;
    const glue:WasmObservation[]=[];result.glue=glue;result.glue_complete=false;
    await checkpoint('reading-selected-glue');
    for(const input of parameters.glue_paths??[]) {
      const selectedPath=absoluteCallerPath(input),raw=await readFile(selectedPath);
      let source:string;
      try {source=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(raw);}
      catch {
        glue.push({artifact:identity(selectedPath,raw),parse_status:'failed',references:[],
          parse_issues:['The selected glue bytes are not valid UTF-8.'],invalid_utf8:true});
        await checkpoint('reading-selected-glue');continue;
      }
      glue.push({artifact:identity(selectedPath,raw),invalid_utf8:false,...glueReferences(source,selectedPath,candidates.map(row=>row.path))});
      await checkpoint('reading-selected-glue');
    }
    result.glue_complete=true;result.completion_status='complete';result.phase='complete';
    return result;
  } catch(error) {
    result.failure={phase:result.phase,name:error instanceof Error?error.name:'ReaderError',message:error instanceof Error?error.message:String(error)};
    const host=result.host_validation as {valid?:boolean}|undefined;
    if(host&&(result.phase==='reading-module'||result.phase==='validating-module'))result.validators_agree=host.valid===false;
    result.completion_status='unknown';
    if(publish)await publish({...result});
    throw error;
  } finally {module?.destroy();}
}
