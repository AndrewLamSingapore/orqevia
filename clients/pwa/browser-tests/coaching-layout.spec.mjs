// Layout regression fixtures, not agent acceptance or runtime qualification.
import { expect, test } from '@playwright/test';
import { mockSession, mockTaskApi, waitForSession, expectNoHorizontalOverflow, sessionBody, PROTOCOL } from './fixtures.mjs';

for(const width of [1440,390])test(`coaching grades and long role labels remain inside the ${width}px viewport`,async({page})=>{
 await page.setViewportSize({width,height:1000});await mockSession(page);await mockTaskApi(page);
 const now=new Date().toISOString();
 const agents=Array.from({length:21},(_,index)=>({agent_id:'a'+String(index+1).padStart(2,'0'),role:'Long fixture reasoning responsibility '+('x'.repeat(80)),phase:'acceptance',state:'AWAITING_EXTERNAL_REVIEW',baseline_pass:true,practice_pass:false,acceptance_pass:null,last_transition_at:now}));
 await page.route('**/interface/v1/telemetry',route=>route.fulfill({status:200,contentType:'application/json',headers:{'X-ORQEVIA-Protocol':PROTOCOL,'Cache-Control':'no-store'},body:JSON.stringify({schema_version:'orqevia.telemetry.v1',observed_at:now,freshness_seconds:60,audience:{client_id:sessionBody().clientId},source:{instance:'fixture',revision:'a'.repeat(40)},metrics:[],agents:[],coaching:{status:'OBSERVED',last_event_at:now,cohort_id:'fixture-'+('c'.repeat(80)),cohort_source_revision:'a'.repeat(40),controller:{availability:'OBSERVED',last_state:'WAITING',last_tick_at:now},agents,normal_followup:{status:'OBSERVED',normal_denominator:21,agents,normal_pass_count:0,normal_fail_count:0,reassessed_count:0}}})}));
 await page.goto('/pwa/');await waitForSession(page);
 if(width<760){await page.locator('#mobile-more-open').click();await page.locator('#mobile-more-dialog [data-view="coaching"]').click();}
 else await page.locator('.desktop-navigation [data-view="coaching"]').click();
 await expect(page.locator('#coaching-view')).toBeVisible();await expect(page.locator('#coaching-roles .coaching-role')).toHaveCount(42);await expect(page.locator('#coaching-roles .coaching-marks')).toHaveCount(21);await expect(page.locator('.coaching-marks').first()).toContainText('Synthetic acceptance');await expect(page.locator('#coaching-summary .coaching-stat')).toHaveCount(4);await expectNoHorizontalOverflow(page);
 const clipped=await page.locator('#coaching-view').evaluate(view=>[...view.querySelectorAll('.coaching-role,.coaching-stat')].some(node=>node.scrollWidth>node.clientWidth+1));expect(clipped).toBe(false);
});
