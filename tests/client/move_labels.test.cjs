'use strict';
const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const context={window:{}};vm.createContext(context);vm.runInContext(fs.readFileSync('web/cohort/tile-labels.js','utf8').replace('__TILE_REGISTRY__',fs.readFileSync('web/cohort/tile-labels.json','utf8')),context);const T=context.window.GaiaTiles;
const moves=['Jubilant-rover-3041','Modern-riddle-1723','Proper-outpost-7588','Comfy-snail-3333'].flatMap(id=>JSON.parse(fs.readFileSync('tests/fixtures/'+id+'.json')).data.moveHistory);
test('real move fixtures translate boosters, ships and numbered board actions',()=>{
 const cases=[['tinkering-power4','4pw Action'],['booster10','4c + Gaia Pass'],['booster-lostfleet-instant',''],['spaceshipAction rebellion qic','Rebellion QIC action'],['spaceshipAction tfmars credit','TF Mars Credit action'],['action power3','action 4pw → 2o'],['action qic3','action 2q → Planet VP']];
 for(const [raw,display] of cases){const examples=moves.filter(m=>m.includes(raw));assert.ok(examples.length,raw+' fixture coverage');for(const m of examples){const shown=T.move(m);assert.ok(!shown.includes(raw),shown);if(display)assert.ok(shown.includes(display),shown);}}
});
test('real fixture move text hides all supported tile IDs without mutating records',()=>{
 const before=JSON.stringify(moves);for(const m of moves){const shown=T.move(m);assert.doesNotMatch(shown,/\b(?:booster(?:\d+|-lostfleet-\w+)|spaceshipAction|tfmars|advtech\d+|ship-(?:tech|fed)-\w+|artifact-\w+|power[1-7]|qic[1-3]|fed[1-6])\b/);}
 assert.equal(JSON.stringify(moves),before);
});
test('token boundaries and move sequence preserve semantics',()=>{
 assert.equal(T.move('terrans booster booster-lostfleet-former'),'terrans booster '+T.label('booster','booster-lostfleet-former'));
 assert.equal(T.move('darkanians spaceshipAction rebellion qic'),'darkanians Rebellion QIC action');
 assert.equal(T.move('example-booster10 booster10suffix tech9_test 2A10 spend 3pw for 1o'),'example-booster10 booster10suffix tech9_test 2A10 spend 3pw for 1o');
 assert.equal(T.move('terrans tech free3. up nav'),'terrans Tech Free. Research Nav');
});
