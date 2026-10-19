/** Native composed analyses request typed observations from their owning session. */
import {readFile} from 'node:fs/promises';
import {createInterface} from 'node:readline';
import {traceNativeValues} from './src/application/native/NativeValueTrace.js';
import {createAnalysisExecution,type AnalysisOperationPort} from './src/application/AnalysisProvider.js';
import {createEvidence,type EvidenceSubjectTarget} from './src/domain/evidence.js';
import {AnalysisCapabilityUnavailableError} from './src/domain/analysisErrorCore.js';
import {ok,err} from './src/domain/result.js';
import type {JsonValue} from './src/domain/jsonValue.js';

async function main():Promise<void> {
  const request=JSON.parse(await readFile(process.argv[2]!,'utf8')) as {
    target:EvidenceSubjectTarget;version:string;parameters:{procedure:string;query?:Record<string,unknown>}};
  const provider={id:'theseus-ghidra',name:'Theseus native binary engine',version:request.version};
  const lines=createInterface({input:process.stdin,crlfDelay:Infinity});
  const input=lines[Symbol.asyncIterator]();
  const observations:JsonValue[]=[];
  const analysis:AnalysisOperationPort={async execute(operation,parameters) {
    process.stdout.write(JSON.stringify({kind:'observation-request',operation,parameters})+'\n');
    const next=await input.next();
    if(next.done) throw new Error('The owning native session closed its observation channel');
    const response=JSON.parse(next.value) as {ok:boolean;result?:Record<string,unknown>;error?:unknown};
    if(!response.ok) {
      const reason=JSON.stringify(response.error);
      observations.push({name:operation+' · '+JSON.stringify(parameters),operation,parameters:parameters as JsonValue,error:reason});
      return err(new AnalysisCapabilityUnavailableError(provider.id,operation,reason));
    }
    const raw=response.result!;
    const value=(operation==='analyze_function'?raw.value:raw) as JsonValue;
    const limitations=Array.isArray(raw.limitations)?raw.limitations.filter((v):v is string=>typeof v==='string'):[];
    const execution=createAnalysisExecution(value,provider,{subject:request.target,limitations});
    const evidence=createEvidence(request.target,provider,{operation,parameters:parameters as Record<string,JsonValue>,
      result:value,rawResult:null,limitations,locations:[]});
    observations.push({name:operation+' · '+JSON.stringify(parameters),evidence:evidence as unknown as JsonValue});
    return ok(execution);
  }};
  try {
    const result=await traceNativeValues(analysis,{...request.parameters.query,procedure:request.parameters.procedure});
    if(!result.ok) throw result.error;
    process.stdout.write(JSON.stringify({kind:'result',value:{trace:result.value,source_observations:observations}})+'\n');
  } finally {lines.close();process.stdin.destroy();}
}

main().catch(error=>{process.stderr.write((error instanceof Error?error.stack:String(error))+'\n');process.exitCode=1;});
