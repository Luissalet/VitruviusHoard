/** Execution-free syntax recovery with original UTF-8 byte ranges and source maps. */
import {createHash} from 'node:crypto';
import {mkdir,writeFile} from 'node:fs/promises';
import {basename,extname,join} from 'node:path';
import {parse} from '@babel/parser';
import {generate} from '@babel/generator';
import * as t from '@babel/types';
import {z} from 'zod';

const options=z.object({extraction_mode:z.enum(['structural','heuristic','inspection']).default('structural'),
  rewrite_level:z.enum(['minimal','standard','aggressive']).default('standard')}).strict();

function rewrite(node:t.Node,level:string):t.Node {
  for(const key of t.VISITOR_KEYS[node.type]??[]) {
    const record=node as unknown as Record<string,unknown>, child=record[key];
    if(Array.isArray(child)) record[key]=child.map(item=>item&&typeof item.type==='string'?rewrite(item,level):item);
    else if(child && typeof child==='object' && 'type' in child) record[key]=rewrite(child as t.Node,level);
  }
  if(level!=='minimal' && t.isMemberExpression(node) && node.computed && t.isStringLiteral(node.property)
    && t.isValidIdentifier(node.property.value)) return t.inherits(t.memberExpression(node.object,t.identifier(node.property.value),false),node);
  if(level==='aggressive' && t.isBinaryExpression(node) && t.isNumericLiteral(node.left) && t.isNumericLiteral(node.right)) {
    const a=node.left.value,b=node.right.value;
    const result=node.operator==='+'?a+b:node.operator==='-'?a-b:node.operator==='*'?a*b:node.operator==='/'?a/b:node.operator==='%'?a%b:null;
    if(result!==null && Number.isFinite(result) && !Object.is(result,-0)) return t.numericLiteral(result);
  }
  return node;
}

export async function recoverSources(bytes:Buffer,path:string,outputDirectory:string,rawOptions:unknown):Promise<unknown> {
  const chosen=options.parse(rawOptions??{});
  const source=new TextDecoder('utf-8',{fatal:true,ignoreBOM:true}).decode(bytes);
  const ast=parse(source,{sourceType:'unambiguous',plugins:['typescript','jsx'],allowReturnOutsideFunction:false});
  const boundaries:Array<{name:string;node:t.Node;basis:string}>=[];
  // An explicit stack keeps child-object and child-array traversal independent.
  const pending:t.Node[]=[ast];
  while(pending.length) {
    const node=pending.pop()!;
    if(t.isObjectExpression(node)) {
      for(const property of node.properties) {
        if(!t.isObjectProperty(property)) continue;
        const name=t.isIdentifier(property.key)?property.key.name:t.isStringLiteral(property.key)||t.isNumericLiteral(property.key)?String(property.key.value):null;
        const value=t.isArrayExpression(property.value)?property.value.elements[0]:property.value;
        if(name!==null && value && (t.isFunctionExpression(value)||t.isArrowFunctionExpression(value)) &&
          (chosen.extraction_mode==='heuristic'||(value.params.length>=3&&(/^\d+$/.test(name)||name.includes('/')))))
          boundaries.push({name,node:value,basis:t.isArrayExpression(property.value)?'browserify-shaped-table':'module-function-table'});
      }
    }
    for(const key of t.VISITOR_KEYS[node.type]??[]) {
      const child=(node as unknown as Record<string,unknown>)[key];
      if(Array.isArray(child)) {for(const item of child) if(item&&typeof item.type==='string') pending.push(item);}
      else if(child&&typeof child==='object'&&'type' in child) pending.push(child as t.Node);
    }
  }
  if(chosen.extraction_mode==='inspection') boundaries.splice(0,boundaries.length,...ast.program.body.map((node,index)=>({name:String(index),node,basis:'top-level-inspection'})));
  await mkdir(outputDirectory);
  const artifacts:Array<{relative_path:string;sha256:string;bytes_written:number}>=[];
  const emit=async(name:string,content:string)=>{
    const raw=Buffer.from(content);
    await writeFile(join(outputDirectory,name),raw,{flag:'wx'});
    const record={relative_path:name,sha256:createHash('sha256').update(raw).digest('hex'),bytes_written:raw.length};
    artifacts.push(record);return record;
  };
  const extension=/^\.(?:ts|tsx|jsx)$/.test(extname(path))?extname(path):'.js';
  const program=rewrite(t.cloneNode(ast,true),chosen.rewrite_level);
  const generated=generate(program,{sourceMaps:true,sourceFileName:basename(path),comments:true,compact:false},source);
  await emit('program'+extension,generated.code+'\n');
  if(generated.map) await emit('program'+extension+'.map',JSON.stringify(generated.map));
  const modules=[];
  boundaries.sort((a,b)=>(a.node.start??0)-(b.node.start??0));
  for(const [index,boundary] of boundaries.entries()) {
    const start=boundary.node.start??0,end=boundary.node.end??0;
    const recovered=rewrite(t.cloneNode(boundary.node,true),chosen.rewrite_level);
    const wrapped=t.isFunctionExpression(recovered)||t.isArrowFunctionExpression(recovered)||t.isFunctionDeclaration(recovered)?t.exportDefaultDeclaration(recovered):recovered;
    const printed=generate(wrapped,{sourceMaps:true,sourceFileName:basename(path),comments:true},source);
    const artifact=await emit('module-'+index+extension,printed.code+'\n');
    const sourceMap=printed.map?await emit('module-'+index+extension+'.map',JSON.stringify(printed.map)):null;
    modules.push({name:boundary.name,basis:boundary.basis,artifact,source_map:sourceMap,
      byte_ranges:[{start:Buffer.byteLength(source.slice(0,start)),end:Buffer.byteLength(source.slice(0,end))}],
      range_semantics:'half-open-utf8-bytes',original_text:source.slice(start,end)});
  }
  return {source_sha256:createHash('sha256').update(bytes).digest('hex'),options:chosen,modules,artifacts,output_root:outputDirectory,
    limitations:['Recovered source is derived syntax, not original identifiers or a proof of runtime equivalence.',
      'Module-table shapes are structural inferences; function wrappers preserve unresolved parameters and are not executed.',
      'Inspection mode emits selected top-level regions. Nonliteral deobfuscation and missing runtime context remain unknown.',
      'Byte ranges refer to the original UTF-8 input; emitted source maps describe the generator projection.']};
}
