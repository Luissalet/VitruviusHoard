/** Native format operations over inert bytes and installed free analysis libraries. */
import {createHash} from 'node:crypto';
import {open} from 'node:fs/promises';
import wabtFactory from 'wabt';
import {contractInfo} from 'evmole';
import {readGoBinaryImage} from './src/go/GoBinaryImage.js';
import {parseGoModuleBytes} from './src/go/GoModuleText.js';
import {readRustBinaryImage} from './src/rust/RustBinaryImage.js';
import {readElectronFuseImage} from './src/electron/ElectronFuseReader.js';
import {readMachoImage} from './src/artifacts/apple/MachoLoadCommandReader.js';
import {decodeKeyedArchiveBytes} from './src/artifacts/apple/KeyedArchiveReader.js';
import {decodeNibArchive} from './src/artifacts/apple/NibArchive.js';
import {InterfaceBuilderDecodeBudget} from './src/artifacts/apple/InterfaceBuilderDecodeBudget.js';
import {decodeEvmBytecodeCarrier} from './src/evm/EvmBytecodeCarrier.js';
import {inspectSolidityMetadata} from './src/evm/SolidityMetadata.js';
import {parseWabtWat} from './src/wasm/WabtWat.js';
import {readElfHeader,readElfSymbols,readSnapshotHeader} from './src/flutter/DartElf.js';
import {readElfBuildIds} from './src/flutter/ElfBuildId.js';
import {ArtifactResourceScope} from './src/artifacts/ArtifactResourceScope.js';
import {reconstructJavaScriptArtifact} from './src/application/javascript/JavaScriptArtifactReconstruction.js';
import {z} from 'zod';
import {queryJavaScriptSemanticGraph} from './src/domain/javascript/javascriptSemanticQuery.js';
import {javaScriptSemanticGraphSchema} from './src/domain/javascript/javascriptSemanticGraph.js';
import {javascriptApplicationGraphSchema} from './src/domain/javascript/javascriptApplicationGraph.js';
import {traceApplicationFeature} from './src/domain/javascript/javascriptFeatureTrace.js';
import {applicationFeatureSeedSchema} from './src/domain/javascript/javascriptFeatureTraceSchemas.js';
import {parsePeResources} from './src/native/pe/PeResourceParser.js';
import {decodeAppleDispatchMetadata} from './src/native/AppleDispatchMetadata.js';

export interface FormatParameters {
  encoding?:'raw'|'hex'|undefined; root?:string|undefined; offset?:number|undefined; limit?:number|undefined;
  symbols?:string[]|undefined; snapshot_offsets?:number[]|undefined;
  source_paths?:string[]|undefined;
  query?:unknown;
  architecture?:'arm64'|'x86_64'|undefined;max_records?:number|undefined;
}

export async function analyzeFormat(operation:string,bytes:Buffer,path:string,parameters:FormatParameters):Promise<unknown> {
  if(operation==='apple.dispatch') {
    const image=await readMachoImage(async(offset,length)=>bytes.subarray(offset,offset+length),bytes.length);
    if(image.status!=='parsed') throw new Error('Select a supported Mach-O image');
    const supported=image.slices.find(slice=>slice.architecture.startsWith('arm64')||slice.architecture.startsWith('x86_64'));
    if(!supported) throw new Error('Dispatch metadata requires an arm64 or x86_64 Mach-O slice');
    const inferred=supported.architecture.startsWith('arm64')?'arm64':'x86_64';
    return decodeAppleDispatchMetadata(bytes,parameters.max_records??Number.MAX_SAFE_INTEGER,
      {path,sha256:createHash('sha256').update(bytes).digest('hex')},parameters.architecture??inferred);
  }
  if(operation==='pe.resources') return await parsePeResources(bytes,{path,sha256:createHash('sha256').update(bytes).digest('hex'),bytes:bytes.length},
    {path,max_file_bytes:bytes.length,max_entries:65536});
  if (operation==='javascript.query' || operation==='javascript.feature') {
    const saved=z.object({operation:z.literal('javascript.application'),artifact_sha256:z.string(),result:z.object({
      graph:javascriptApplicationGraphSchema,semantic_graph:javaScriptSemanticGraphSchema})}).parse(JSON.parse(bytes.toString('utf8')));
    if (operation==='javascript.query') return queryJavaScriptSemanticGraph(saved.result.semantic_graph,parameters.query);
    const query=z.object({seed:applicationFeatureSeedSchema,direction:z.enum(['incoming','outgoing','both']).default('both')}).strict().parse(parameters.query);
    return traceApplicationFeature({sourceEvidenceId:'ev_'+createHash('sha256').update(bytes).digest('hex'),
      graph:saved.result.graph,nativeEvidence:[],seed:query.seed,direction:query.direction});
  }
  if (operation==='javascript.application') {
    const resources=new ArtifactResourceScope();
    try {
      const result=await reconstructJavaScriptArtifact({input_path:path,format:'auto',integrity_policy:'record-and-continue',
        ...(parameters.source_paths===undefined ? {} : {source_paths:parameters.source_paths})},resources);
      if (result.format==='asar' && result.root_artifact_sha256!==createHash('sha256').update(bytes).digest('hex')) throw new Error('Application changed between snapshot and graph reconstruction');
      return result;
    } finally {await resources.close();}
  }
  if (operation==='go.build') {
    const image=readGoBinaryImage(bytes);
    const moduleBytes=image.build_info ? Buffer.from(image.build_info.module_bytes_base64,'base64') : null;
    return {...image,module:moduleBytes ? parseGoModuleBytes(moduleBytes.length ? moduleBytes.subarray(16,-16) : moduleBytes) : null,
      limitations:['Missing build information does not establish that the image is not Go. Native function/type recovery is a separate analysis.']};
  }
  if (operation==='rust.dependencies') return {...readRustBinaryImage(bytes),
    limitations:['Dependency metadata exists only in supported auditable sections. An absent section is not a verdict about source language or dependencies. Compiler commits are inferred from recorded strings.']};
  if (operation==='electron.fuses') {
    const image=await readElectronFuseImage(path);
    if (image.sha256!==createHash('sha256').update(bytes).digest('hex')) throw new Error('Artifact changed between snapshot and Electron fuse read');
    return image;
  }
  if (operation==='apple.macho') return await readMachoImage(async (offset,length)=>bytes.subarray(offset,offset+length),bytes.length);
  if (operation==='apple.keyed_archive') return decodeKeyedArchiveBytes(bytes,{
    root:parameters.root,offset:parameters.offset??0,limit:parameters.limit??Number.MAX_SAFE_INTEGER});
  if (operation==='apple.nib') return decodeNibArchive(bytes,new InterfaceBuilderDecodeBudget(Number.POSITIVE_INFINITY));
  if (operation==='evm.interface') {
    const encoding=parameters.encoding??'raw';
    const code=decodeEvmBytecodeCarrier(bytes,encoding);
    const analysis=contractInfo(Buffer.from(code).toString('hex'),{selectors:true,arguments:true,stateMutability:true,
      storage:true,disassemble:true,basicBlocks:true,controlFlowGraph:true,metadata:true});
    return {...analysis,encoding,evidence_kind:'inferred',runtime_execution:'not-performed',
      discovery_completeness:'unknown',bytecode_sha256:createHash('sha256').update(code).digest('hex'),
      functions:(analysis.functions||[]).map(row=>({...row,evidence_kind:'inferred',state_mutability_basis:'conservative-static-inference'})),
      storage:(analysis.storage||[]).map(row=>({...row,evidence_kind:'inferred'})),
      instructions:(analysis.disassembled||[]).map(([offset,instruction])=>({name:instruction,bytecode_offset:offset,instruction})),
      solidity_metadata:inspectSolidityMetadata(code),
      limitations:['Selectors, argument types, storage layout and control flow are static inferences, not original Solidity source. Offsets identify decoded bytecode; hex-carrier character positions differ. No network or chain is queried.',
        'State mutability is a conservative static inference; a pure source function can be reported as view. An independently known ABI can contradict this inference.']};
  }
  if (operation==='wasm.artifact') {
    const wabt=await wabtFactory();
    const module=wabt.readWasm(bytes,{readDebugNames:true});
    try {
      module.generateNames();module.applyNames();
      const text=module.toText({foldExprs:false,inlineExport:false});
      const parsed=parseWabtWat(text);
      return {...parsed,wat:text,interface_entries:parsed.interface.entries,
        definitions:parsed.forms.map((definition,index)=>({name:/^\(\w+\s+([^\s()]+)/.exec(definition)?.[1]||String(index),definition})),
        limitations:['WAT is a disassembly; generated names are not proof of original source identifiers. No module is instantiated.']};
    } finally {module.destroy();}
  }
  if (operation==='flutter.elf') {
    const header=readElfHeader(bytes);
    if (header.failure) throw new Error(header.failure.reason);
    const names=parameters.symbols??['_kDartVmSnapshotData','_kDartVmSnapshotInstructions','_kDartIsolateSnapshotData','_kDartIsolateSnapshotInstructions'];
    const symbols=await readElfSymbols(bytes,names);
    const file=await open(path,'r');
    let build;
    try {build=await readElfBuildIds(file,bytes.length,undefined);} finally {await file.close();}
    const snapshots=[...symbols.symbols.filter(row=>row.name.endsWith('Data')).map(row=>({name:row.name,file_offset:row.offset,...readSnapshotHeader(bytes,row.offset)})),
      ...(parameters.snapshot_offsets||[]).map(offset=>({name:'selected',file_offset:offset,...readSnapshotHeader(bytes,offset)}))];
    return {header:header.header,symbols:symbols.symbols,symbol_failures:symbols.failures,build_ids:build.candidates,
      build_id_failures:build.failures,snapshots,
      limitations:['Supported ELF/Dart layout identification only. Missing dynamic symbols or snapshot headers remain unknown; this does not reconstruct Dart source.']};
  }
  throw new Error('Unknown native format operation: '+operation);
}
