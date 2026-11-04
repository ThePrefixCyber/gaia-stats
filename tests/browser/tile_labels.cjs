// Supply generated tile-labels.js on stdin; no browser dependency.
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const context={window:{}};vm.createContext(context);vm.runInContext(fs.readFileSync(0,'utf8'),context);
const T=context.window.GaiaTiles;
for(const [id,text] of Object.entries({tech9:'4pw Action',tech8:'4c Income',tech4:'7vp',tech3:'4pip PI/AC',tech1:'1o1q','ship-tech-resource':'1o3k','ship-tech-range':'+1 Range','ship-tech-terraform':'2tf Mine'}))assert.equal(T.label('basic',id),text);
assert.equal(T.label('basic','1q_1o'),T.label('basic','tech1'));
assert.equal(T.label('round','score7'),T.label('round','score10')); // Shared shorthand, distinct coordinates.
assert.match(T.label('advanced','advtech4'),/Now/);assert.doesNotMatch(T.label('advanced','advtech14'),/Now/);
assert.equal(T.label('basic','unknown'), 'Unknown tile');assert.equal(T.position('tech-free1'),'Free 1');
assert.equal(T.metric('point-sources','round1'),'Round 1');assert.equal(T.metric('point-sources','tfmars'),'TF Mars');
assert.equal(T.metric('point-sources','tech-free1'),'Tech Free 1');assert.equal(T.metric('point-sources','gaia'),'Gaia Research');
const forbidden=/advtech\d|tech\d|ship-tech-|tech-free|\[|_per_/;
for(const value of [T.metric('advanced-tech-score','advtech1 / adv-terra'),T.metric('basic-tech-score','ship-tech-resource / tfmars'),T.metric('round-scoring','Round 1 / score7'),T.metric('final-scoring','gaia / structure'),T.move('terrans tech free3. up nav'),T.move('terrans tech ship-tech-resource')])assert.doesNotMatch(value,forbidden);
console.log('24 shorthand and identifier-separation assertions passed');
