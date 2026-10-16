import {test} from 'node:test';
import assert from 'node:assert/strict';
import {graticule,observationFeatures,safeEvidence} from '../clients/pwa/command-map.mjs';
test('coordinate grid has no external tile dependency',()=>{const grid=graticule();assert.equal(grid.type,'FeatureCollection');assert(grid.features.length>10);});
test('only valid supplied coordinates become map points',()=>{const data=observationFeatures([{event_id:'a',location:{lat:1.3,lon:103.8}},{location:{lat:91,lon:0}},{location:null},{location:{lat:NaN,lon:0}}]);assert.equal(data.features.length,1);assert.deepEqual(data.features[0].geometry.coordinates,[103.8,1.3]);});
test('evidence links are restricted to the real HTTPS USGS provider',()=>{assert(safeEvidence('https://earthquake.usgs.gov/eventpage/abc'));for(const v of ['javascript:alert(1)','https://evil.test','https://earthquake.usgs.gov.evil.test','https://user:secret@earthquake.usgs.gov/'])assert.equal(safeEvidence(v),null);});
