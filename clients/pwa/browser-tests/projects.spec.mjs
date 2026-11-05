import {expect,test} from '@playwright/test';
import {mockSession,expectNoHorizontalOverflow} from './fixtures.mjs';

test('project service failure is visible, has no unhandled exception, and recovers by refresh',async({page})=>{
 await mockSession(page);const errors=[];page.on('pageerror',error=>errors.push(error.message));let available=false;
 await page.route('**/pwa/api/project-workflows/templates',route=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify({templates:[{template_id:'sme-profitability.v1',agent_count:21}]})}));
 await page.route('**/pwa/api/project-workflows?limit=20',route=>route.fulfill({status:available?200:503,contentType:'application/json',body:JSON.stringify(available?{runs:[]}:{detail:'Controlled fixture outage'})}));
 await page.goto('/pwa/projects.html');await expect(page.locator('#session-state')).toHaveText('Owner connected');await expect(page.locator('#workflow-message')).toContainText('Controlled fixture outage');expect(errors).toEqual([]);
 available=true;await page.locator('#refresh-runs').click();await expect(page.locator('#runs')).toContainText('No workflow runs yet.');await expect(page.locator('#workflow-message')).toHaveText('Project runs refreshed.');await expectNoHorizontalOverflow(page);
 await page.setViewportSize({width:390,height:844});await expectNoHorizontalOverflow(page);
});
