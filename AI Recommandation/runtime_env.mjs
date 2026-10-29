import fs from 'node:fs';
import path from 'node:path';
export function loadEnv(root){
 const file=path.join(root,'.env'),values={};
 if(fs.existsSync(file))for(const line of fs.readFileSync(file,'utf8').split(/\r?\n/)){
  if(!line.includes('=')||line.trimStart().startsWith('#'))continue;
  const [key,...rest]=line.split('=');values[key.trim()]=rest.join('=').trim().replace(/^(['"])(.*)\1$/,'$2');
 }
 return {...values,...process.env};
}
