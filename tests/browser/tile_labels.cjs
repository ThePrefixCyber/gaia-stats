// Run: python -c "from gaia_stats.cohort import response; print(response(None,'/cohort/tile-labels.js',{})[0].decode())" | node tests/browser/tile_labels.cjs
const assert=require('node:assert/strict'), vm=require('node:vm'), fs=require('node:fs');
const context={window:{}}; vm.createContext(context);vm.runInContext(fs.readFileSync(0,'utf8'),context);
const T=context.window.GaiaTiles;
assert.match(T.label('advanced','advtech4'),/^Immediate: 2 VP per current mine \[advtech4\]$/);
assert.match(T.label('advanced','advtech14'),/^Each mine built: 3 VP/);
assert.match(T.label('advanced','advtech-deep'),/Immediate: 4 VP/);
assert.match(T.label('advanced','advtech-deeppass'),/Pass: 2 VP/);
assert.match(T.label('basic','k_per_terra'),/planet type/);
assert.match(T.label('advanced','1vp_per_terra_pass'),/planet type/);
assert.match(T.label('advanced','new-tile'),/^Unmapped advanced tile \[new-tile\]$/);
assert.match(T.metric('advanced-tech-score','advtech1 / adv-terra'),/Pass: 3 VP.*Terraforming position \[adv-terra\]/);
assert.match(T.metric('point-sources','adv-terra'),/^VP from Terraforming position/);
assert.doesNotMatch(T.metric('point-sources','adv-terra'),/Pass|Immediate/);
assert.equal(T.metric('point-sources','gaia'),'gaia'); // raw source != final tile
assert.match(T.metric('round-scoring','Round 1 / score7'),/^Round 1 \/ This round: 5 VP/);
assert.match(T.metric('final-scoring','gaia / structure'),/Most colonized Gaia planets.*Most structures/);
assert.match(T.metric('point-sources','booster6'),/pass: 1 VP per mine/);
assert.match(T.metric('point-sources','qic2'),/rescore one owned federation token/);
assert.match(T.metric('basic-tech-frequency','ship-tech-resource / rebellion'),/Immediate: gain 1 ore and 3 knowledge.*\[rebellion\]/);
assert.notEqual(T.label('round','score7'),T.label('round','score10'));
console.log('18 presentation assertions passed');
