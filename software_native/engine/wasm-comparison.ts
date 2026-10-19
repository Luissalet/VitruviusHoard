/** Typed interface comparison, adapted from the MIT pinned source comparison. */
import {wasmInterfaceSchema,type WasmInterfaceEntry} from './src/domain/wasm/wasmInterface.js';

export function compareWasm(reference:unknown,candidate:unknown,scope='both') {
  if(!['both','imports','exports'].includes(scope)) throw new Error('Choose imports, exports or both');
  const left=wasmInterfaceSchema.parse(reference),right=wasmInterfaceSchema.parse(candidate);
  const groups=new Map<string,{left:WasmInterfaceEntry[];right:WasmInterfaceEntry[]}>();
  for(const [side,value] of [['left',left],['right',right]] as const) for(const entry of value.entries) {
    if(scope!=='both' && entry.direction!==(scope==='imports'?'import':'export')) continue;
    const key=JSON.stringify([entry.direction,entry.module,entry.name]);
    const group=groups.get(key)??{left:[],right:[]};group[side].push(entry);groups.set(key,group);
  }
  const summary={added:0,removed:0,changed:0,unchanged:0,unknown:0};
  const changes=[...groups.entries()].sort(([a],[b])=>a<b?-1:a>b?1:0).map(([key,group])=>{
    const l=group.left[0],r=group.right[0];let state:keyof typeof summary;
    const unresolved=left.state!=='complete'||right.state!=='complete'||group.left.length>1||group.right.length>1||
      [l,r].some(entry=>entry&&(entry.kind==='unknown'||entry.signature===null||entry.issue!==null));
    state=unresolved?'unknown':!l?'added':!r?'removed':l.kind!==r.kind||JSON.stringify(l.signature)!==JSON.stringify(r.signature)?'changed':'unchanged';
    summary[state]++;
    return {key,state,...group,reason:unresolved?'Incomplete, duplicate or unresolved interface facts cannot establish equality or absence.':null};
  });
  return {scope,changes,summary,coverage:summary.unknown?'partial':'complete-within-inputs',
    limitations:['Declared interface equality is not successful linking, runtime behavior or general ABI compatibility.']};
}
