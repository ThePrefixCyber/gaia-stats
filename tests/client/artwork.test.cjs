'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('web/art/site-art.js','utf8');
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function harness({reduced=false,paused=false}={}){
 const scripts=[],events={},buttonEvents={},prefs={},background={},header={};let idle,mutation,intersection,created=0,destroyed=0;
 const media={matches:reduced,addEventListener:(name,fn)=>{events.reduced=fn;}};
 const button={hidden:true,textContent:'',setAttribute(name,value){this[name]=value;},addEventListener:(name,fn)=>{buttonEvents[name]=fn;}};
 const body={focused:false,classList:{contains:()=>body.focused}};
 const document={hidden:false,readyState:'complete',body,head:{append:node=>scripts.push(node)},
  getElementById:id=>id==='gaia-background'?background:button,querySelector:()=>header,
  createElement:()=>({}),addEventListener:(name,fn)=>{events[name]=fn;}};
 const window={matchMedia:()=>media,requestIdleCallback:fn=>{idle=fn;},addEventListener:(name,fn)=>{events[name]=fn;},
  THREE:{},VANTA:{FOG:options=>{created++;assert.equal(options.highlightColor,0x59ff00);assert.equal(options.midtoneColor,0xef00ff);return {el:background,renderer:{domElement:{parentNode:background}},scene:{},camera:{},destroy(){destroyed++;}};}},IntersectionObserver:true};
 const sessionStorage={getItem:()=>paused?'paused':null,setItem:(key,value)=>{prefs[key]=value;}};
 const context={window,document,sessionStorage,MutationObserver:function(fn){mutation=fn;this.observe=()=>{};},IntersectionObserver:function(fn){intersection=fn;this.observe=()=>{};},setTimeout};
 vm.runInNewContext(source,context);
 return {scripts,events,button,buttonEvents,media,document,body,prefs,start:()=>idle(),mutation:()=>mutation(),visibility:v=>intersection([{isIntersecting:v}]),
  counts:()=>({created,destroyed}),async load(){scripts[0].onload();await tick();scripts[1].onload();await tick();}};
}
test('reduced motion and saved pause never request the animation libraries',()=>{
 for(const options of [{reduced:true},{paused:true}]){const h=harness(options);h.start();assert.equal(h.scripts.length,0);assert.equal(h.counts().created,0);}
});
test('art loads after idle, uses local pinned scripts and pauses around charts',async()=>{
 const h=harness();assert.equal(h.scripts.length,0);h.start();assert.equal(h.scripts[0].src,'/art/vendor/three.r119.min.js');
 await h.load();assert.equal(h.scripts[1].src,'/art/vendor/vanta.fog.min.js');assert.equal(h.counts().created,1);assert.equal(h.button.hidden,false);
 h.body.focused=true;h.mutation();assert.equal(h.counts().destroyed,1);
 h.body.focused=false;h.mutation();await tick();assert.equal(h.counts().created,2);assert.equal(h.scripts.length,2);
 h.visibility(false);assert.equal(h.counts().destroyed,2);assert.equal(h.button.hidden,false);h.visibility(true);await tick();assert.equal(h.counts().created,3);
 h.document.hidden=true;h.events.visibilitychange();assert.equal(h.counts().destroyed,3);
});
test('pause is accessible, persisted and survives late dependency completion',async()=>{
 const h=harness();h.start();h.buttonEvents.click();await h.load();assert.equal(h.counts().created,0);
 assert.equal(h.button['aria-pressed'],'true');assert.match(h.button.textContent,/Resume/);assert.equal(h.prefs['gaia-background-motion'],'paused');
 h.buttonEvents.click();await tick();assert.equal(h.counts().created,1);assert.equal(h.button['aria-pressed'],'false');
 h.media.matches=true;h.events.reduced();assert.equal(h.counts().destroyed,1);assert.equal(h.button.hidden,true);
});
test('failed libraries leave a static cover and do not retry endlessly',async()=>{
 const h=harness();h.start();h.scripts[0].onerror(new Error('offline'));await tick();h.mutation();await tick();
 assert.equal(h.scripts.length,1);assert.equal(h.counts().created,0);assert.equal(h.button.hidden,true);
});

test('returning from a cached page restores the optional effect without new requests',async()=>{
 const h=harness();h.start();await h.load();h.events.pagehide();assert.equal(h.counts().destroyed,1);
 h.events.pageshow();await tick();assert.equal(h.counts().created,2);assert.equal(h.scripts.length,2);
});

test('late dependency loads do not start animation after pagehide',async()=>{
 const h=harness();h.start();h.events.pagehide();await h.load();assert.equal(h.counts().created,0);
 h.events.pageshow();await tick();assert.equal(h.counts().created,1);
});
