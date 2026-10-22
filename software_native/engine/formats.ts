/** Native format operations over inert bytes and installed free analysis libraries. */
import {createHash} from 'node:crypto';
import {open} from 'node:fs/promises';
import {contractInfo} from 'evmole';
import {GoBinaryFormatFailure,GoBinaryResourceFailure,readGoBinaryImage} from './src/go/GoBinaryImage.js';
import {RustAuditableFormatFailure,RustAuditableResourceFailure} from './src/rust/RustAuditableReader.js';
import {universalMachoSlices} from './src/native/UniversalMachoSlices.js';
import {parseGoModuleBytes} from './src/go/GoModuleText.js';
import {readRustBinaryImage} from './src/rust/RustBinaryImage.js';
import {readElectronFuseImage} from './src/electron/ElectronFuseReader.js';
import {readMachoImage} from './src/artifacts/apple/MachoLoadCommandReader.js';
import {decodeKeyedArchiveBytes} from './src/artifacts/apple/KeyedArchiveReader.js';
import {decodeNibArchive} from './src/artifacts/apple/NibArchive.js';
import {InterfaceBuilderDecodeBudget} from './src/artifacts/apple/InterfaceBuilderDecodeBudget.js';
import {decodeEvmBytecodeCarrier} from './src/evm/EvmBytecodeCarrier.js';
import {inspectSolidityMetadata} from './src/evm/SolidityMetadata.js';
import {inspectWasm} from './wasm-inspection.js';
import {FULL_AOT_KIND,SPLIT_SNAPSHOT_SYMBOLS,UNIFIED_SNAPSHOT_SYMBOLS,readElfHeader,readElfSymbols,readSnapshotHeader,snapshotLayout} from './src/flutter/DartElf.js';
import {identifyFlutterBuild,inspectDartAot} from './src/flutter/FlutterApk.js';
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
  symbols?:string[]|undefined; snapshot_offsets?:number[]|undefined; abi?:string|undefined;
  source_paths?:string[]|undefined;
  glue_paths?:string[]|undefined;candidate_paths?:string[]|undefined;
  query?:unknown;
  architecture?:'arm64'|'x86_64'|undefined;max_records?:number|undefined;
}

const readGoBuild=(bytes:Buffer)=>{
  const image=readGoBinaryImage(bytes);
  const moduleBytes=image.build_info ? Buffer.from(image.build_info.module_bytes_base64,'base64') : null;
  return {...image,module:moduleBytes ? parseGoModuleBytes(moduleBytes.length ? moduleBytes.subarray(16,-16) : moduleBytes) : null};
};

/** Re-base every file offset a thin Go or Rust reading reports onto the universal file. */
const shiftFileOffsets=<T extends object>(reading:T,base:number):T=>{
  const value=reading as Record<string,any>;
  const info=value.build_info;
  const auditable=value.auditable_metadata;
  const rustc=value.rustc_commit;
  return {...value,
    ...(info ? {build_info:{...info,header_offset:info.header_offset+base,
      version_location:{...info.version_location,offset:info.version_location.offset+base},
      module_location:{...info.module_location,offset:info.module_location.offset+base}}} : {}),
    ...(auditable ? {auditable_metadata:{...auditable,file_offset:auditable.file_offset+base}} : {}),
    ...(rustc ? {rustc_commit:{...rustc,hashes:rustc.hashes.map((row:any)=>({...row,file_offset:row.file_offset+base}))}} : {}),
  } as T;
};

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
  if (operation==='go.build' || operation==='rust.dependencies') {
    const read=operation==='go.build' ? readGoBuild : readRustBinaryImage;
    const limitation=operation==='go.build'
      ? 'Missing build information does not establish that the image is not Go. Native function/type recovery is a separate analysis.'
      : 'Dependency metadata exists only in supported auditable sections. An absent section is not a verdict about source language or dependencies. Compiler commits are inferred from recorded strings.';
    const universal=universalMachoSlices(bytes);
    if (universal===null) return {...read(bytes),limitations:[limitation]};
    return {format:'macho-universal',fat_magic:universal.magic,wide_table:universal.wide,
      slices:universal.slices.map(({bytes:thin,identity_failure:identity,...slice})=>{
        if (identity!==null) return {...slice,status:'failed',failure:{category:'malformed',reason:identity}};
        try {return {...slice,status:'read',...shiftFileOffsets(read(thin),slice.file_offset)};}
        catch (cause) {
          if (!(cause instanceof GoBinaryFormatFailure || cause instanceof GoBinaryResourceFailure ||
            cause instanceof RustAuditableFormatFailure || cause instanceof RustAuditableResourceFailure)) throw cause;
          return {...slice,status:'failed',failure:{category:cause instanceof GoBinaryFormatFailure || cause instanceof RustAuditableFormatFailure ? cause.kind : 'resource',reason:cause.message}};
        }
      }),
      limitations:[limitation,'Each universal slice is read on its own bytes in table order. Every reported file offset counts from the start of the universal file. A failed slice does not hide the others.']};
  }
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
  if (operation==='wasm.artifact') return inspectWasm(bytes,path,parameters);
  if (operation==='flutter.build') return await identifyFlutterBuild(bytes,path);
  if (operation==='flutter.aot') return await inspectDartAot(bytes,path,parameters);
  if (operation==='flutter.elf') {
    const header=readElfHeader(bytes);
    if (header.failure) throw new Error(header.failure.reason);
    const defaults=parameters.symbols===undefined;
    const names=parameters.symbols??[...SPLIT_SNAPSHOT_SYMBOLS,...UNIFIED_SNAPSHOT_SYMBOLS];
    const symbols=await readElfSymbols(bytes,names);
    const layout=snapshotLayout(symbols.symbols.map(row=>row.name));
    // With the default list, the symbols of the layout family that is absent are not failures.
    const absent=layout===null?[]:(layout==='unified'?SPLIT_SNAPSHOT_SYMBOLS:UNIFIED_SNAPSHOT_SYMBOLS) as readonly string[];
    const symbolFailures=defaults?symbols.failures.filter(row=>!absent.some(name=>row.reason===`symbol ${name} is not in the dynamic symbol table`)):symbols.failures;
    const aotKind=layout===null?null:FULL_AOT_KIND[layout];
    const file=await open(path,'r');
    let build;
    try {build=await readElfBuildIds(file,bytes.length,undefined);} finally {await file.close();}
    const snapshots=[...symbols.symbols.filter(row=>row.name.endsWith('Data')).map(row=>({name:row.name,file_offset:row.offset,...readSnapshotHeader(bytes,row.offset,aotKind)})),
      ...(parameters.snapshot_offsets||[]).map(offset=>({name:'selected',file_offset:offset,...readSnapshotHeader(bytes,offset,aotKind)}))];
    return {header:header.header,layout,symbols:symbols.symbols,symbol_failures:symbolFailures,build_ids:build.candidates,
      build_id_failures:build.failures,snapshots,
      limitations:['Supported ELF/Dart layout identification only. Missing dynamic symbols or snapshot headers remain unknown; this does not reconstruct Dart source.',
        'A snapshot is complete only when its kind is FullAOT for the observed layout: 3 in the split VM/isolate layout, 2 in the unified layout of Dart 3.13; other kinds are reported as observed.']};
  }
  throw new Error('Unknown native format operation: '+operation);
}
