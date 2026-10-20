/** Publish a recorded observation prefix, never the completed analysis path. */
import {writeFile,rename} from 'node:fs/promises';
import type {WasmObservation} from './wasm-inspection.js';

export async function publishWasmPrefix(outputFile:string,envelope:Record<string,unknown>,observation:WasmObservation) {
  const destination=outputFile+'.partial.json',temporary=destination+'.'+process.pid+'.tmp';
  await writeFile(temporary,JSON.stringify({...envelope,result:observation},null,2),'utf8');
  for(let attempt=0;attempt<50;attempt++) {
    try {await rename(temporary,destination);return;}
    catch(error) {
      const code=(error as NodeJS.ErrnoException).code;
      if(process.platform!=='win32'||!['EPERM','EACCES','EBUSY'].includes(code??'')||attempt===49)throw error;
      await new Promise(resolve=>setTimeout(resolve,10));
    }
  }
}
