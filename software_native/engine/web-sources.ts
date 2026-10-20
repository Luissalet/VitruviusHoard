/** Retained web bytes only: no target imports, execution, filesystem fallback or fetch. */
import {createHash} from 'node:crypto';
import {parse} from '@babel/parser';
import {TraceMap, decodedMappings} from '@jridgewell/trace-mapping';
import {z} from 'zod';
import {sourceMapJsonText} from './src/domain/sourceMapEnvelope.js';

const entrySchema=z.object({id:z.string(),kind:z.string(),url:z.string(),state:z.string(),
  sha256:z.string().optional(),bytes:z.number().int().nonnegative().optional(),content_base64:z.string().optional()}).passthrough();
type Entry=z.infer<typeof entrySchema>;
const exportSchema=z.object({operation:z.literal('browser.export_scripts'),result:z.object({
  format:z.literal('vitruvius.web-sources/1'),capture_sha256:z.string(),entries:z.array(entrySchema),
}).passthrough()}).passthrough();
const commonQuery={script_id:z.string(),importer_url:z.string().optional()};
const sourceQuery=z.object({...commonQuery,map_id:z.string(),line:z.number().int().positive(),column:z.number().int().nonnegative()}).strict();
const importQuery=z.object({...commonQuery,import_map:z.record(z.string(),z.unknown()).optional(),import_map_base_url:z.string().optional()}).strict();
const hash=(bytes:Uint8Array)=>createHash('sha256').update(bytes).digest('hex');

function content(entry:Entry):Buffer {
  if(entry.state!=='captured'||entry.content_base64===undefined) throw new Error('Selected exported occurrence has no captured content');
  const encoded=entry.content_base64;
  if(!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/u.test(encoded)) throw new Error('Invalid exported content base64');
  const bytes=Buffer.from(encoded,'base64');
  if(hash(bytes)!==entry.sha256||bytes.length!==entry.bytes) throw new Error('Exported content SHA-256 or byte length does not match');
  return bytes;
}
function select(entries:Entry[],id:string):Entry {
  const matches=entries.filter(row=>row.id===id);
  if(matches.length!==1) throw new Error('Select one unique exported occurrence ID');
  return matches[0];
}
function text(bytes:Buffer):string {return new TextDecoder('utf-8',{fatal:true}).decode(bytes);}
const integer=z.number().int().nonnegative();
const leafSchema=z.object({version:z.literal(3),sources:z.array(z.string().nullable()),names:z.array(z.string()),
  sourceRoot:z.string().optional(),sourcesContent:z.array(z.string().nullable()).nullable().optional(),mappings:z.string(),
}).passthrough();
const indexSchema=z.object({version:z.literal(3),sections:z.array(z.object({
  offset:z.object({line:integer,column:integer}).strict(),map:z.unknown(),
}).strict())}).passthrough();
type Position={line:number;column:number};
type Mapping=Position&{section:number[];source_index?:number;source_name?:string|null;source_root?:string|null;
  resolved_url?:string|null;source_content?:string|null;original_line?:number;original_column?:number;name?:string|null};
const before=(a:Position,b:Position)=>a.line<b.line||(a.line===b.line&&a.column<b.column);
const add=(base:Position,offset:Position):Position=>({line:base.line+offset.line,column:offset.column+(offset.line===0?base.column:0)});

function validateVlq(mappings:string):void {
  const alphabet='ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/';
  for(const line of mappings.split(';')) {
    if(line==='') continue;
    for(const segment of line.split(',')) {
      let fields=0,shift=0n,value=0n;
      for(const character of segment) {
        const digit=alphabet.indexOf(character);
        if(digit<0) throw new Error('Invalid source-map VLQ character');
        value|=BigInt(digit&31)<<shift;
        if(value>0xffffffffn) throw new Error('Source-map VLQ exceeds the codec unsigned 32-bit representation');
        if(digit&32) shift+=5n;
        else {fields++;shift=0n;value=0n;}
      }
      if(shift!==0n||![1,4,5].includes(fields)) throw new Error('Incomplete or invalid source-map VLQ segment');
    }
  }
}

function mapSegments(value:unknown,mapUrl:string,base:Position={line:0,column:0},stop?:Position,section:number[]=[]):Mapping[] {
  if(value&&typeof value==='object'&&'sections' in value) {
    const indexed=indexSchema.parse(value);
    if('mappings' in indexed) throw new Error('A source map cannot contain both sections and mappings');
    const output:Mapping[]=[];
    for(let i=0;i<indexed.sections.length;i++) {
      const item=indexed.sections[i];
      if(i>0&&!before(indexed.sections[i-1].offset,item.offset)) throw new Error('Source-map sections must have strictly increasing offsets');
      const next=indexed.sections[i+1];
      const nextStop=next?add(base,next.offset):stop;
      const bound=stop&&nextStop&&before(stop,nextStop)?stop:nextStop;
      for(const row of mapSegments(item.map,mapUrl,add(base,item.offset),bound,[...section,i])) output.push(row);
    }
    return output;
  }
  const leaf=leafSchema.parse(value);
  validateVlq(leaf.mappings);
  const map=new TraceMap({version:3,names:leaf.names,mappings:leaf.mappings,sources:leaf.sources.map(source=>source??''),
    ...(leaf.sourceRoot===undefined?{}:{sourceRoot:leaf.sourceRoot}),
    ...(leaf.sourcesContent==null?{}:{sourcesContent:leaf.sourcesContent})},mapUrl);
  const decoded=decodedMappings(map),output:Mapping[]=[];
  for(let line=0;line<decoded.length;line++) for(const segment of decoded[line]) {
    if(![1,4,5].includes(segment.length)||segment.some(value=>!Number.isSafeInteger(value)||value<0)) throw new Error('Invalid decoded source-map segment');
    const position=add(base,{line,column:segment[0]});
    if(stop&&!before(position,stop)) continue;
    const row:Mapping={...position,section};
    if(segment.length!==1) {
      const sourceIndex=segment[1];
      if(sourceIndex>=leaf.sources.length) throw new Error('Source-map source index is outside its declarations');
      Object.assign(row,{source_index:sourceIndex,source_name:leaf.sources[sourceIndex],source_root:leaf.sourceRoot??null,
        resolved_url:leaf.sources[sourceIndex]===null?null:map.resolvedSources[sourceIndex],
        source_content:leaf.sourcesContent?.[sourceIndex]??null,original_line:segment[2]+1,original_column:segment[3],name:null});
      if(segment.length===5) {
        if(segment[4]>=leaf.names.length) throw new Error('Source-map name index is outside its declarations');
        row.name=leaf.names[segment[4]];
      }
    }
    output.push(row);
  }
  return output;
}

function traceSource(entries:Entry[],script:Entry,query:unknown) {
  const selected=sourceQuery.parse(query),map=select(entries,selected.map_id);
  const bytes=content(map);
  const importer=selected.importer_url??script.url;
  const mapUrl=map.kind==='inline-source-map'?importer:map.url;
  const mappings=mapSegments(JSON.parse(sourceMapJsonText(text(bytes))),mapUrl);
  const requested={line:selected.line-1,column:selected.column};
  let greatest:Position|undefined;
  for(const row of mappings) if(!before(requested,row)&&(!greatest||before(greatest,row))) greatest=row;
  const matches=greatest?mappings.filter(row=>row.line===greatest.line&&row.column===greatest.column):[];
  return {state:matches.length===0?'no-mapping':matches.some(row=>row.source_index!==undefined)?'mapped':'unmapped',
    script:{id:script.id,sha256:script.sha256,url:script.url},map:{id:map.id,sha256:map.sha256,url:map.url,resolution_base_url:mapUrl},
    requested:{line:selected.line,column:selected.column,columns:'UTF-16-code-units'},
    generated_position:greatest?{line:greatest.line+1,column:greatest.column}:null,
    mappings:matches.map(row=>({...row,line:row.line+1,state:row.source_index===undefined?'unmapped':'mapped'})),
    limitations:['The selected script/map pairing is caller-declared, not authenticated deployment evidence.',
      'All segments at the greatest generated position at or before the request are preserved, including duplicates and unmapped segments.',
      'Only inline indexed sections are supported; external section URLs are not fetched.']};
}

const object=(value:unknown):value is Record<string,unknown>=>value!==null&&typeof value==='object'&&!Array.isArray(value);
function urlLike(specifier:string,base:string):URL|null {
  return /^(?:\/|\.\/|\.\.\/)/u.test(specifier)?URL.parse(specifier,base):URL.parse(specifier);
}
type SpecifierMap=Map<string,string|null>;
function normalizeMap(raw:unknown,base:string,warnings:string[],context:string):SpecifierMap {
  const output:SpecifierMap=new Map();
  if(raw===undefined) return output;
  if(!object(raw)) throw new Error(context+' must be an object');
  for(const [key,value] of Object.entries(raw)) {
    if(!key) {warnings.push(context+': empty key ignored');continue;}
    const normalized=urlLike(key,base)?.href??key;
    const address=typeof value==='string'?urlLike(value,base):null;
    if(!address||(key.endsWith('/')&&!address.href.endsWith('/'))) {
      output.set(normalized,null);
      if(value!==null) warnings.push(context+': invalid address blocks '+key);
    } else output.set(normalized,address.href);
  }
  return new Map([...output].sort(([a],[b])=>a<b?1:a>b?-1:0));
}
function importMatch(normalized:string,asUrl:URL|null,map:SpecifierMap):string|null {
  for(const [key,address] of map) {
    const exact=key===normalized;
    const prefix=key.endsWith('/')&&normalized.startsWith(key)&&(!asUrl||['ftp:','file:','http:','https:','ws:','wss:'].includes(asUrl.protocol));
    if(!exact&&!prefix) continue;
    if(address===null) throw new Error('Import-map entry blocks '+key);
    if(exact) return address;
    const resolved=URL.parse(normalized.slice(key.length),address);
    if(!resolved||!resolved.href.startsWith(address)) throw new Error('Import-map prefix resolution escapes or cannot resolve '+key);
    return resolved.href;
  }
  return null;
}

function traceImports(entries:Entry[],script:Entry,source:string,query:unknown) {
  const selected=importQuery.parse(query),importer=selected.importer_url??script.url;
  if(!URL.parse(importer)) throw new Error('An absolute importer_url is required for scripts without an absolute captured URL');
  const base=selected.import_map_base_url??importer;
  if(!URL.parse(base)) throw new Error('Import-map base must be an absolute URL');
  const supplied=selected.import_map??{},warnings:string[]=[];
  const imports=normalizeMap(supplied.imports,base,warnings,'imports');
  const scopes:{prefix:string;map:SpecifierMap}[]=[];
  if(supplied.scopes!==undefined) {
    if(!object(supplied.scopes)) throw new Error('Import-map scopes must be an object');
    for(const [key,value] of Object.entries(supplied.scopes)) {
      const prefix=URL.parse(key,base);
      if(!prefix) {warnings.push('Invalid scope URL ignored: '+key);continue;}
      if(!object(value)) {warnings.push('Non-object scope ignored: '+key);continue;}
      scopes.push({prefix:prefix.href,map:normalizeMap(value,base,warnings,'scope '+key)});
    }
    scopes.sort((a,b)=>a.prefix<b.prefix?1:a.prefix>b.prefix?-1:0);
  }
  function resolve(specifier:string):string {
    const asUrl=urlLike(specifier,importer),normalized=asUrl?.href??specifier;
    for(const scope of scopes) if(scope.prefix===importer||(scope.prefix.endsWith('/')&&importer.startsWith(scope.prefix))) {
      const match=importMatch(normalized,asUrl,scope.map);
      if(match!==null) return match;
    }
    const result=importMatch(normalized,asUrl,imports)??asUrl?.href;
    if(result===undefined) throw new Error('Bare module specifier has no declared mapping');
    return result;
  }
  const ast=parse(source,{sourceType:'unambiguous',createImportExpressions:true});
  const found:Record<string,unknown>[]=[];
  const pending:unknown[]=[ast];
  while(pending.length) {
    const node=pending.pop();
    if(!object(node)) continue;
    let kind:string|undefined,expression:unknown;
    if(node.type==='ImportDeclaration') {kind='static-import';expression=node.source;}
    else if(node.type==='ExportNamedDeclaration'&&node.source) {kind='reexport';expression=node.source;}
    else if(node.type==='ExportAllDeclaration') {kind='reexport-all';expression=node.source;}
    else if(node.type==='ImportExpression') {kind='dynamic-import';expression=node.source;}
    else if(node.type==='CallExpression'&&object(node.callee)&&node.callee.type==='Identifier'&&node.callee.name==='require') {
      kind='commonjs-require';expression=Array.isArray(node.arguments)?node.arguments[0]:undefined;
    }
    if(kind) {
      const specifier=object(expression)&&expression.type==='StringLiteral'&&typeof expression.value==='string'?expression.value:null;
      const loc=object(node.loc)&&object(node.loc.start)?node.loc.start:{};
      const row:Record<string,unknown>={kind,specifier,line:loc.line,column:loc.column,utf16_offset:node.start,
        state:specifier===null?'computed-unknown':kind==='commonjs-require'?'runtime-resolution-unknown':'unresolved'};
      if(specifier!==null&&kind!=='commonjs-require') {
        try {
          const resolved=resolve(specifier);
          Object.assign(row,{state:'resolved',resolved_url:resolved,
            captured_matches:entries.filter(entry=>entry.url===resolved).map(entry=>({id:entry.id,state:entry.state,sha256:entry.sha256??null}))});
        } catch(error) {row.reason=error instanceof Error?error.message:String(error);}
      }
      found.push(row);
    }
    for(const value of Object.values(node)) {
      if(Array.isArray(value)) for(const child of value) pending.push(child);
      else if(object(value)&&typeof value.type==='string') pending.push(value);
    }
  }
  found.sort((a,b)=>Number(a.utf16_offset)-Number(b.utf16_offset));
  return {script:{id:script.id,sha256:script.sha256,url:script.url},importer_url:importer,import_map_base_url:base,
    import_map:supplied,imports:found,warnings,
    limitations:['The importer URL and import map are explicit interpretation context, not observations of a deployed import map.',
      'Literal ES module resolution follows HTML URL/import-map rules without loading any module.',
      'Computed imports, CommonJS require and bundler runtime resolution remain unknown; captured URL matches do not prove execution.']};
}

export function traceWebSources(operation:string,bytes:Buffer,query:unknown):unknown {
  const document=exportSchema.parse(JSON.parse(bytes.toString('utf8'))),entries=document.result.entries;
  const selected=operation==='javascript.trace_source'?sourceQuery.parse(query):importQuery.parse(query);
  const script=select(entries,selected.script_id),source=content(script);
  if(script.kind!=='page-script'&&script.kind!=='network-response') throw new Error('Select an exported script or response occurrence');
  return operation==='javascript.trace_source'?traceSource(entries,script,query):traceImports(entries,script,text(source),query);
}
