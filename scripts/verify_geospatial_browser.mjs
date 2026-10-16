// Runs against an isolated, authenticated real companion and PostGIS dataset.
// Fault injection below tests error/empty recovery; it is NOT live-source proof.
import {createRequire} from 'node:module';
import {readFileSync,mkdirSync,writeFileSync} from 'node:fs';
import {join} from 'node:path';
import assert from 'node:assert/strict';
const require=createRequire(import.meta.url),{chromium}=require('playwright');
const out=process.env.ORQEVIA_BROWSER_EVIDENCE,token=readFileSync(process.env.ORQEVIA_BROWSER_TOKEN_FILE,'utf8');
if(!out)throw new Error('External evidence directory required');mkdirSync(out,{recursive:true});
const browser=await chromium.launch({headless:true,executablePath:process.env.ORQEVIA_TEST_CHROMIUM||undefined,args:['--use-angle=swiftshader','--enable-unsafe-swiftshader']});
const context=await browser.newContext({extraHTTPHeaders:{Authorization:'Bearer '+token}});
const page=await context.newPage(),errors=[],external=[];page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(!r.url().startsWith('http://127.0.0.1:18150/')&&!r.url().startsWith('blob:'))external.push(new URL(r.url()).origin);});
const base='http://127.0.0.1:18150';
const report={browser:'Chromium',live_data:true,tests:[]};
try{
 await page.setViewportSize({width:1440,height:1000});
 await page.goto(base+'/gods-eye/map.html');
 await page.getByText('Observations loaded · inspect a point or record',{exact:true}).waitFor({timeout:45000});
 assert(await page.locator('canvas.maplibregl-canvas').isVisible());report.tests.push('MapLibre WebGL initialization and real GeoJSON rendering');
 await page.getByRole('button',{name:'Zoom in',exact:true}).click();report.tests.push('Zoom navigation');
 await page.getByLabel('Latitude',{exact:true}).fill('1.3');await page.getByLabel('Longitude',{exact:true}).fill('103.8');await page.getByRole('button',{name:'Go to coordinates',exact:true}).click();report.tests.push('Geographic coordinate navigation');
 await page.getByLabel('Observations',{exact:true}).uncheck();await page.getByLabel('Observations',{exact:true}).check();report.tests.push('Observation layer controls');
 await page.getByLabel('Source',{exact:true}).selectOption('USGS');await page.getByText('Observations loaded · inspect a point or record',{exact:true}).waitFor();report.tests.push('Real source filtering');
 await page.locator('.command-map-evidence button').first().click();await page.getByRole('link',{name:'Original USGS evidence'}).waitFor();assert((await page.getByRole('link',{name:'Original USGS evidence'}).getAttribute('href')).startsWith('https://earthquake.usgs.gov/'));report.tests.push('Observation inspection, provenance and evidence link');
 await page.waitForTimeout(1500);await page.screenshot({path:join(out,'gods-eye-desktop.png'),fullPage:true});
 await page.setViewportSize({width:390,height:844});await page.waitForTimeout(500);assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));await page.screenshot({path:join(out,'gods-eye-mobile.png'),fullPage:true});report.tests.push('390px mobile layout without horizontal overflow');
 await page.route('**/geo/features?**',route=>route.fulfill({status:503,contentType:'application/json',body:'{"detail":"controlled fault injection"}'}));await page.getByRole('button',{name:'Refresh observations',exact:true}).click();await page.getByText(/Observations unavailable:/).waitFor();report.tests.push('Explicit API error state (fault injection)');await page.unroute('**/geo/features?**');
 await page.getByRole('button',{name:'Refresh observations',exact:true}).click();await page.getByText('Observations loaded · inspect a point or record',{exact:true}).waitFor();report.tests.push('Recovery to live API');
 await page.route('**/geo/features?**',route=>route.fulfill({status:200,contentType:'application/json',body:'{"type":"FeatureCollection","features":[]}'}));await page.getByRole('button',{name:'Refresh observations',exact:true}).click();await page.getByText('No observations match these filters.',{exact:true}).waitFor();report.tests.push('Explicit empty state (fault injection)');await page.unroute('**/geo/features?**');
 assert.deepEqual(errors,[]);assert.deepEqual(external,[]);report.tests.push('No browser errors or third-party tile/style requests');report.passed=report.tests.length;
}finally{writeFileSync(join(out,'browser-result.json'),JSON.stringify({...report,errors,external},null,2));await browser.close();}
console.log(JSON.stringify(report,null,2));
