'use strict';
const {test}=require('node:test'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
function files(root){return fs.readdirSync(root,{withFileTypes:true}).flatMap(entry=>entry.isDirectory()?files(path.join(root,entry.name)):[path.join(root,entry.name)]);}
test('all shipped JavaScript and inline HTML scripts parse',()=>{
 for(const file of files('web')){
  if(file.endsWith('.js'))new vm.Script(fs.readFileSync(file,'utf8'),{filename:file});
  if(file.endsWith('.html')){
   const content=fs.readFileSync(file,'utf8');let index=0;
   for(const match of content.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)){
    if(/\bsrc\s*=/.test(match[1])||/type\s*=\s*["']application\/json/i.test(match[1]))continue;
    new vm.Script(match[2],{filename:`${file}:inline-${++index}`});
   }
  }
 }
});
