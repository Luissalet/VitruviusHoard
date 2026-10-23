/** Native file-analysis worker. No reference CLI/MCP or target runtime is used. */
import {createHash} from 'node:crypto';
import {readFile, writeFile, rename,stat} from 'node:fs/promises';
import {resolve} from 'node:path';
import {z} from 'zod';
import {inspectManagedArtifactBytes} from './src/dotnet/ManagedArtifactInspector.js';
import {inspectManagedMembersBytes} from './src/dotnet/ManagedMemberInspector.js';
import {inspectManagedNativeBoundariesBytes} from './src/dotnet/ManagedNativeBoundaryInspector.js';
import {readManagedPeLayout} from './src/dotnet/ManagedPeReader.js';
import type {BinaryTarget} from './src/domain/binaryTargetTypes.js';
import {analyzeFormat} from './formats.js';
import {compareRetained} from './comparisons.js';
import {directoryIdentity} from './directory.js';
import {analyzePortfolio} from './portfolio.js';
import {recoverSources} from './recovery.js';
import {sourceGraph,managedReconstruction} from './retained.js';
import {managedNativeVerification} from './managed-native.js';
import {traceWebSources} from './web-sources.js';
import {callPaths,retainedInputSchema} from './retained-evidence.js';
import {compareRetainedFunctions} from './retained-functions.js';
import {retainedManagedGraph} from './managed-graph.js';
import {inspectWasm} from './wasm-inspection.js';
import {publishWasmPrefix} from './wasm-recording.js';

const portfolioOperations=['artifact.inventory','artifact.extract','managed.graph','apple.application',
  'android.application','harmony.application','apple.interface_builder','apple.assets','apple.dylibs'] as const;

const requestSchema = z.object({
  operation:z.enum(['managed.artifact','managed.members','managed.native_boundaries','go.build','rust.dependencies',
    'electron.fuses','apple.macho','apple.dispatch','apple.keyed_archive','apple.nib','pe.resources','wasm.artifact','evm.interface','flutter.elf','flutter.build','flutter.aot','javascript.application','javascript.query','javascript.feature',
    'artifact.compare','managed.compare','javascript.compare_versions','javascript.compare_exports','javascript.recover','source.graph',
    'javascript.compare_source','managed.reconstruction','managed.verify_native','managed.graph_retained','wasm.compare_interfaces','javascript.trace_source','javascript.trace_imports','evidence.call_paths','evidence.compare_functions',...portfolioOperations]),
  path:z.string().min(1),
  parameters:z.object({type_names:z.array(z.string()).optional(), method_offset:z.number().int().min(0).optional(),
    method_limit:z.number().int().min(0).optional(), user_strings:z.boolean().optional(),
    encoding:z.enum(['raw','hex']).optional(), root:z.string().optional(), offset:z.number().int().min(0).optional(),
    limit:z.number().int().min(0).optional(), symbols:z.array(z.string()).optional(),
    snapshot_offsets:z.array(z.number().int().min(0)).optional(),abi:z.string().regex(/^[a-z0-9_-]{2,16}$/u).optional(),source_paths:z.array(z.string()).optional(),query:z.unknown().optional(),
    glue_paths:z.array(z.string().min(1)).optional(),candidate_paths:z.array(z.string().min(1)).optional(),
    output_directory:z.string().optional(),architecture:z.enum(['arm64','x86_64']).optional(),max_records:z.number().int().min(1).optional()}).strict().default({}),
  expected_input_sha256:z.string().optional(),source_artifact_sha256:z.string().optional(),
  candidate_path:z.string().optional(),expected_candidate_sha256:z.string().optional(),
  source_inputs:z.array(retainedInputSchema).optional(),
  source_input_roles:z.object({reference_job_id:z.string(),candidate_job_id:z.string()}).strict().optional(),
  native_inputs:z.array(z.object({path:z.string(),sha256:z.string(),artifact_path:z.string(),artifact_sha256:z.string(),artifact_format:z.enum(['pe','elf','mach-o','unknown']),version:z.string(),job_id:z.string()}).strict()).optional(),
}).strict();

async function main() {
  const [inputFile, outputFile] = process.argv.slice(2);
  if (!inputFile || !outputFile) throw new Error('Expected a native request file and analysis output file');
  const request = requestSchema.parse(JSON.parse(await readFile(inputFile,'utf8')));
  const path = resolve(request.path);
  const directory=(await stat(path)).isDirectory();
  const bytes = directory ? Buffer.alloc(0) : await readFile(path);
  const inputSha256 = directory ? await directoryIdentity(path) : createHash('sha256').update(bytes).digest('hex');
  if (request.expected_input_sha256 && request.expected_input_sha256!==inputSha256) throw new Error('Retained analysis document changed; its receipt hash no longer matches');
  const sha256=request.source_artifact_sha256??inputSha256;
  const envelope={operation:request.operation,artifact_sha256:sha256,input_sha256:inputSha256,
    engine:'Theseus native analysis core',runtime:process.version};
  const parameters = request.parameters;
  let result:unknown;
  if(request.operation==='managed.graph_retained') {
    result=await retainedManagedGraph(request.source_inputs??[],sha256);
  } else if(request.operation==='evidence.compare_functions') {
    if(!request.source_input_roles)throw new Error('Explicit retained function pair is required');
    result=await compareRetainedFunctions(request.source_inputs??[],request.source_input_roles);
  } else if(request.operation==='evidence.call_paths') {
    result=await callPaths(request.source_inputs??[],parameters.query);
  } else if (request.candidate_path && request.expected_candidate_sha256) {
    result=await compareRetained(request.operation,bytes,request.candidate_path,request.expected_candidate_sha256,parameters.query);
  } else if(request.operation==='javascript.trace_source'||request.operation==='javascript.trace_imports') {
    result=traceWebSources(request.operation,bytes,parameters.query);
  } else if(request.operation==='source.graph') {
    result=await sourceGraph(path,bytes);
  } else if(request.operation==='managed.reconstruction') {
    result=managedReconstruction(bytes,parameters.query);
  } else if(request.operation==='managed.verify_native') {
    result=await managedNativeVerification(bytes,request.native_inputs??[]);
  } else if(request.operation==='javascript.recover') {
    if(!parameters.output_directory) throw new Error('Recovery output directory is required');
    result=await recoverSources(bytes,path,parameters.output_directory,parameters.query);
  } else if((portfolioOperations as readonly string[]).includes(request.operation)) {
    result=await analyzePortfolio(request.operation,bytes,path,sha256,parameters);
  } else if (request.operation.startsWith('managed.')) {
    const pe = readManagedPeLayout(bytes);
    const target: BinaryTarget = {path,sha256,kind:'executable',format:'pe',architecture:pe.architecture,
      availableArchitectures:[pe.architecture],peMachine:pe.machine,managed:pe.cliDirectoryState !== 'absent',
      executableRole:(pe.characteristics & 0x2000) ? 'shared-library' : (pe.characteristics & 2) ? 'application' : 'non-executable'};
    result=request.operation === 'managed.artifact' ? inspectManagedArtifactBytes(bytes,target) :
      request.operation === 'managed.native_boundaries' ? inspectManagedNativeBoundariesBytes(bytes,target) :
      inspectManagedMembersBytes(bytes,target,{
        ...(parameters.type_names===undefined ? {} : {typeNames:parameters.type_names}),
        ...(parameters.method_offset===undefined ? {} : {methodOffset:parameters.method_offset}),
        ...(parameters.method_limit===undefined ? {} : {methodLimit:parameters.method_limit}),
        ...(parameters.user_strings===undefined ? {} : {userStrings:parameters.user_strings})});
  } else if(request.operation==='wasm.artifact') {
    result=await inspectWasm(bytes,path,parameters,observation=>publishWasmPrefix(outputFile,envelope,observation));
  } else result=await analyzeFormat(request.operation,bytes,path,parameters);
  const output = {...envelope,result,
    ...(request.operation==='managed.members'?{observation_scope:{
      type_names:parameters.type_names??null,method_offset:parameters.method_offset??0,
      method_limit:parameters.method_limit??null,user_strings:parameters.user_strings??true}}:{})};
  const temporary = outputFile + '.' + process.pid + '.tmp';
  await writeFile(temporary,JSON.stringify(output,null,2),'utf8');
  await rename(temporary,outputFile);
  process.stdout.write(JSON.stringify({ok:true,operation:request.operation,artifact_sha256:sha256})+'\n');
}

main().catch(error => {
  process.stderr.write((error instanceof Error ? error.stack : String(error))+'\n');
  process.exitCode=1;
});
