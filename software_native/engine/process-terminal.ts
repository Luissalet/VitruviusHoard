/** Replay observed terminal output into a maintained headless terminal, never target code. */
import {readFile,writeFile,rename} from 'node:fs/promises';
import {createRequire} from 'node:module';
import type {Terminal as HeadlessTerminal} from '@xterm/headless';
import {z} from 'zod';

const size=z.number().int().positive();
const require=createRequire(import.meta.url);
const {Terminal}=require('@xterm/headless') as typeof import('@xterm/headless');
const {SerializeAddon}=require('@xterm/addon-serialize') as typeof import('@xterm/addon-serialize');
const requestSchema=z.object({terminal:z.object({columns:size,rows:size,scrollback:z.number().int().nonnegative()}),
  frames:z.array(z.discriminatedUnion('kind',[
    z.object({kind:z.literal('output'),event_id:z.string(),text:z.string()}),
    z.object({kind:z.literal('resize'),event_id:z.string(),columns:size,rows:size}),
  ]))}).strict();

export async function renderTerminal(input:unknown) {
  const request=requestSchema.parse(input);
  const terminal=new Terminal({cols:request.terminal.columns,rows:request.terminal.rows,
    scrollback:request.terminal.scrollback,allowProposedApi:true});
  const serializer=new SerializeAddon();
  // SerializeAddon uses only the shared headless buffer API at runtime.
  terminal.loadAddon(serializer as unknown as Parameters<HeadlessTerminal['loadAddon']>[0]);
  function snapshot() {
    const active=terminal.buffer.active;
    const lines=[];
    for(let index=0;index<active.length;index++) lines.push(active.getLine(index)?.translateToString(true)??'');
    return {columns:terminal.cols,rows:terminal.rows,cursor_x:active.cursorX,cursor_y:active.cursorY,
      base_y:active.baseY,active_buffer:active.type,lines,serialized_state:serializer.serialize()};
  }
  try {
    const frames=[];
    for(const frame of request.frames) {
      if(frame.kind==='output') await new Promise<void>(resolve=>terminal.write(frame.text,resolve));
      else terminal.resize(frame.columns,frame.rows);
      frames.push({event_id:frame.event_id,...snapshot()});
    }
    return {engine:{name:'xterm-headless',version:require('@xterm/headless/package.json').version,
      serializer_version:require('@xterm/addon-serialize/package.json').version},frames,final:snapshot(),
      limitations:['Rendered frames interpret the recorded terminal output and resize order; they do not infer ordering in other process channels.']};
  } finally {serializer.dispose();terminal.dispose();}
}

if(process.argv[1]?.replaceAll('\\','/').endsWith('/process-terminal.js')) {
  const [request,output]=process.argv.slice(2);
  renderTerminal(JSON.parse(await readFile(request,'utf8'))).then(async result=>{
    const temporary=output+'.'+process.pid+'.tmp';await writeFile(temporary,JSON.stringify(result),'utf8');await rename(temporary,output);
  }).catch(error=>{process.stderr.write(String(error)+'\n');process.exitCode=1;});
}
