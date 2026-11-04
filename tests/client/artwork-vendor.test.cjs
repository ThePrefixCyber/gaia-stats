'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs');
const {JSDOM,VirtualConsole}=require('jsdom');
const tick=()=>new Promise(resolve=>setImmediate(resolve));

// Run the unmodified, pinned Three and Vanta sources. Only the WebGL renderer is
// replaced because these tests have no GPU; real scene/material/geometry and
// Vanta's constructor, failure handling, event setup and destroy code are used.
async function harness(failure){
 const dom=new JSDOM('<body><div id="gaia-background"></div><header class="gaia-masthead"></header><button id="art-motion"></button></body>',{runScripts:'outside-only',pretendToBeVisual:true,virtualConsole:new VirtualConsole()});
 const w=dom.window,el=w.document.getElementById('gaia-background'),button=w.document.getElementById('art-motion');
 Object.defineProperty(el,'offsetWidth',{value:800});Object.defineProperty(el,'offsetHeight',{value:600});
 let idle,intersection,mediaChange,created=0,disposed=0,lost=0,materials=0,geometries=0;
 const frames=new Map();let frameId=0;
 w.requestAnimationFrame=fn=>{frames.set(++frameId,fn);return frameId;};w.cancelAnimationFrame=id=>frames.delete(id);
 w.requestIdleCallback=fn=>{idle=fn;};
 const media={matches:false,addEventListener:(_,fn)=>{mediaChange=fn;}};w.matchMedia=()=>media;
 w.IntersectionObserver=class{constructor(fn){intersection=fn;}observe(){}};
 w.eval(fs.readFileSync('web/art/vendor/three.r119.min.js','utf8'));
 class Renderer{
  constructor(){created++;this.domElement=w.document.createElement('canvas');}
  setSize(){if(failure==='resize')throw Error('Initial resize failed');}
  setPixelRatio(){} setClearColor(){}
  render(){if(failure==='render')throw Error('Initial render failed');}
  dispose(){disposed++;if(failure==='dispose')throw Error('Renderer disposal failed');}
  forceContextLoss(){lost++;}
 }
 w.THREE.WebGLRenderer=Renderer;
 const materialDispose=w.THREE.Material.prototype.dispose,geometryDispose=w.THREE.Geometry.prototype.dispose;
 w.THREE.Material.prototype.dispose=function(){materials++;return materialDispose.call(this);};
 w.THREE.Geometry.prototype.dispose=function(){geometries++;return geometryDispose.call(this);};
 if(failure==='shader')w.THREE.ShaderMaterial=class{constructor(){throw Error('Shader initialization failed');}};
 w.eval(fs.readFileSync('web/art/vendor/vanta.fog.min.js','utf8'));
 await tick(); // Let jsdom finish its document load before adding the wrapper.
 w.eval(fs.readFileSync('web/art/site-art.js','utf8'));idle();
 const scripts=w.document.querySelectorAll('script');scripts[0].onload();await tick();
 w.document.querySelectorAll('script')[1].onload();await tick();
 return {w,el,button,dom,media,counts:()=>({created,disposed,lost,materials,geometries}),
  visible:async value=>{intersection([{isIntersecting:value}]);await tick();},
  reduce:async()=>{media.matches=true;mediaChange();await tick();}};
}
test('actual Vanta lifecycle releases every renderer, context, geometry and material',async()=>{
 const h=await harness();
 try{
  assert.equal(h.button.hidden,false);
  for(let i=0;i<3;i++){await h.visible(false);assert.equal(h.el.querySelectorAll('canvas').length,0);await h.visible(true);}
  h.button.click();await tick();
  assert.deepEqual(h.counts(),{created:4,disposed:4,lost:4,materials:4,geometries:4});
  assert.equal(h.el.querySelectorAll('canvas').length,0);assert.equal(h.w.VANTA.current,null);
  assert.equal(h.button.getAttribute('aria-pressed'),'true');
 }finally{h.dom.window.close();}
});
for(const failure of ['shader','resize','render'])test(`actual Vanta ${failure} failure is cleaned and stays static`,async()=>{
 const h=await harness(failure);
 try{
  assert.equal(h.button.hidden,true);assert.equal(h.el.querySelectorAll('canvas').length,0);assert.equal(h.w.VANTA.current,null);
  assert.deepEqual(h.counts(),{created:1,disposed:1,lost:1,materials:failure==='shader'?0:1,geometries:failure==='shader'?0:1});
  await h.visible(false);await h.visible(true);await h.reduce();
  assert.equal(h.counts().created,1);assert.equal(h.counts().disposed,1);
 }finally{h.dom.window.close();}
});
test('a renderer disposal exception does not prevent context release or later restart',async()=>{
 const h=await harness('dispose');
 try{await h.visible(false);assert.equal(h.counts().lost,1);assert.equal(h.el.querySelectorAll('canvas').length,0);await h.visible(true);assert.equal(h.counts().created,2);await h.reduce();assert.equal(h.counts().lost,2);}
 finally{h.dom.window.close();}
});
