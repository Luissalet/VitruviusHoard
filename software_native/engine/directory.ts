import {createHash} from 'node:crypto';
import {lstat,readdir,readFile,readlink} from 'node:fs/promises';
import {join,relative,sep} from 'node:path';

/** The same directory-1 content commitment used by the native project store. */
export async function directoryEntries(root:string):Promise<Array<[string,string,string,number]>> {
  const rows:Array<[string,string,string,number]>=[];
  const pending=[root];
  while(pending.length) {
    const directory=pending.pop()!;
    for(const name of await readdir(directory)) {
      const path=join(directory,name), metadata=await lstat(path);
      const logical=relative(root,path).split(sep).join('/');
      if(metadata.isSymbolicLink()) rows.push([logical,'link',await readlink(path),0]);
      else if(metadata.isDirectory()) {rows.push([logical,'directory','',0]);pending.push(path);}
      else if(metadata.isFile()) rows.push([logical,'file',createHash('sha256').update(await readFile(path)).digest('hex'),metadata.size]);
      else rows.push([logical,'special','',0]);
    }
  }
  rows.sort((a,b)=>Buffer.compare(Buffer.from(a[0]),Buffer.from(b[0])));
  return rows;
}

export async function directoryIdentity(root:string):Promise<string> {
  return createHash('sha256').update(JSON.stringify(await directoryEntries(root))).digest('hex');
}
