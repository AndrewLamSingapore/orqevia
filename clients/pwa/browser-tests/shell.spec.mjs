import {expect,test} from '@playwright/test';
import {expectNoHorizontalOverflow,mockSession,waitForSession} from './fixtures.mjs';

test.beforeEach(async({page})=>{await mockSession(page);});

test('Command Center uses the verified palette and one responsive capability directory',async({page})=>{
 await page.setViewportSize({width:1440,height:1000});await page.goto('/pwa/');await waitForSession(page);
 await expect(page).toHaveTitle(/ORQEVIA/);await expect(page.locator('#dashboard')).toBeVisible();
 await expect(page.locator('.command-grid > *')).toHaveCount(12);await expect(page.locator('[data-theme-toggle]')).toHaveCount(0);
 const design=await page.evaluate(()=>({background:getComputedStyle(document.body).backgroundColor,panel:getComputedStyle(document.querySelector('.command-card')).backgroundColor,columns:getComputedStyle(document.querySelector('.command-grid')).gridTemplateColumns.split(' ').length}));
 expect(design).toEqual({background:'rgb(247, 238, 220)',panel:'rgb(66, 68, 32)',columns:3});
 await expect(page.locator('link[rel="manifest"]')).toHaveAttribute('href','/pwa/manifest.webmanifest');await expectNoHorizontalOverflow(page);
 await page.locator('.command-grid [data-view="live-systems"]').click();
 for(const id of ['system-overview','live-system-health','active-tasks','live-activity'])await expect(page.locator('#'+id)).toBeVisible();
 await expect(page.locator('#ready-agent-count')).toBeVisible();await expect(page).toHaveURL(/view=live-systems/);
 await page.locator('.desktop-navigation [data-view="console"]').click();await expect(page.locator('#operations-view')).toBeVisible();await expect(page).toHaveURL(/view=console/);
 await expect(page.getByRole('heading',{name:'Probabilistic Intelligence Fabric (PIF)',exact:true})).toBeVisible();
 await expect(page.getByRole('heading',{name:'Model Efficiency Layer (MEL)',exact:true})).toBeVisible();
 for(const id of ['pif','mel']){await page.locator(`[data-intelligence-jump="${id}"]`).click();await expect(page.locator('#'+id+'-heading')).toBeFocused();}
 await page.locator('.desktop-navigation [data-view="agents"]').click();await expect(page.locator('#capability-title')).toHaveText('Agents');await expectNoHorizontalOverflow(page);
});

test('mobile routes preserve accessible targets and fit the viewport',async({page})=>{
 for(const width of [320,390,639]){
  await page.setViewportSize({width,height:844});await page.goto('/pwa/');await waitForSession(page);
  await expect(page.locator('.mobile-navigation')).toBeVisible();await expect(page.locator('.desktop-navigation')).toBeHidden();await expectNoHorizontalOverflow(page);
  const targets=await page.locator('.mobile-navigation > button').evaluateAll(items=>items.map(n=>({width:n.getBoundingClientRect().width,height:n.getBoundingClientRect().height})));
  expect(targets).toHaveLength(5);expect(targets.every(n=>n.width>=44&&n.height>=44)).toBe(true);
  await page.locator('#mobile-more-open').click();await expect(page.locator('#mobile-more-dialog')).toBeVisible();
  const desktop=await page.locator('.desktop-navigation [data-view]').evaluateAll(nodes=>nodes.map(n=>n.dataset.view));
  const mobile=await page.locator('#mobile-more-dialog [data-view]').evaluateAll(nodes=>nodes.map(n=>n.dataset.view));for(const name of desktop)expect(mobile).toContain(name);
  await expect(page.locator('#mobile-more-dialog a[href="/pwa/projects.html"]')).toBeVisible();
  await page.locator('#mobile-more-dialog [data-view="console"]').click();await expect(page.locator('#mobile-more-dialog')).toBeHidden();await expect(page.locator('#operations-view')).toBeVisible();await expectNoHorizontalOverflow(page);
  await page.locator('#mobile-more-open').click();await page.locator('#mobile-more-dialog [data-view="live-systems"]').click();
  for(const id of ['system-overview','live-system-health','active-tasks','live-activity'])await expect(page.locator('#'+id)).toBeVisible();await expectNoHorizontalOverflow(page);
 }
});

test('primary controls expose labels, unique identifiers and canonical aliases',async({page})=>{
 await page.goto('/pwa/?view=plane');await waitForSession(page);await expect(page).toHaveURL(/view=intelligence/);await expect(page.locator('#osip-view')).toBeVisible();
 const audit=await page.evaluate(()=>{const ids=[...document.querySelectorAll('[id]')].map(n=>n.id);return {duplicates:[...new Set(ids.filter((id,i)=>ids.indexOf(id)!==i))],unlabeled:[...document.querySelectorAll('button')].filter(n=>!n.textContent.trim()&&!n.getAttribute('aria-label')).map(n=>n.outerHTML)};});
 expect(audit).toEqual({duplicates:[],unlabeled:[]});await expect(page.locator('[data-theme-toggle]')).toHaveCount(0);
});

test('new mission shortcut creates a draft through the existing composer without executing it',async({page})=>{
 const posts=[];await page.route('**/interface/v1/objectives',route=>{posts.push(route.request().postData());return route.fulfill({status:500,body:'{}'});});
 await page.goto('/pwa/');await waitForSession(page);await page.locator('#command-objective').fill('Inspect my local research notes');await page.locator('#command-objective-form button').click();
 await expect(page).toHaveURL(/view=missions/);await expect(page.locator('#objective')).toHaveValue('Inspect my local research notes');expect(posts).toEqual([]);
});
