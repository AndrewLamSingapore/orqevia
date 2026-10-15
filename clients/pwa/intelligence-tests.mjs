import assert from 'node:assert/strict';
import test from 'node:test';
import {safeSource,freshness,mapPoint} from './intelligence.mjs';
test('map validates coordinates and preserves both hemispheres',()=>{
 assert.deepEqual(mapPoint({lat:0,lon:0}),[480,240]);assert.deepEqual(mapPoint({lat:90,lon:-180}),[0,0]);
 for(const location of [{lat:91,lon:0},{lat:0,lon:181},{lat:NaN,lon:1},{lat:'1',lon:2}])assert.equal(mapPoint(location),null);
});
test('untrusted provenance cannot inject scripts or plaintext transport',()=>{
 for(const url of ['javascript:alert(1)','data:text/html,x','http://example.com','/relative'])assert.equal(safeSource(url),null);
 assert.equal(safeSource('https://earthquake.usgs.gov/earthquakes/eventpage/test'),'https://earthquake.usgs.gov/earthquakes/eventpage/test');
});
test('freshness distinguishes actual dated records from future or missing times',()=>{
 const now=Date.parse('2026-10-15T08:00:00Z');assert.equal(freshness('2026-10-15T07:59:00Z',now),'FRESH');
 assert.equal(freshness('2026-10-15T07:00:00Z',now),'STALE');assert.equal(freshness('2026-10-16T08:00:00Z',now),'UNKNOWN');assert.equal(freshness(null,now),'UNKNOWN');
});
