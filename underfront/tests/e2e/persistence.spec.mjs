import {test,expect} from '@playwright/test';
import {randomUUID} from 'node:crypto';
import {execFileSync} from 'node:child_process';

test('explicit local stack restart preserves data, session and queued worker job',async({page,request})=>{
 test.skip(process.env.E2E_RESTART_STACK!=='1','Opt in only for the named local zavozik-full-e2e stack.');
 const api=process.env.E2E_API_URL||'http://localhost:8080';
 expect(api).toBe('http://localhost:8080');
 const email=`restart-${randomUUID()}@example.invalid`;const password='E2e!A1b2C3d4';
 const registration=await request.post(`${api}/v1/auth/register`,{data:{email,password,consent_pd:true}});expect(registration.status()).toBe(201);
 const headers={Authorization:`Bearer ${(await registration.json()).access_token}`};
 const created=await request.post(`${api}/v1/companies`,{headers,data:{name:'Synthetic persistence',legal_form:'ООО',industry:'Tests'}});expect(created.status()).toBe(201);const cid=(await created.json()).id;
 await page.goto('/login');await page.getByLabel('Электронная почта',{exact:true}).fill(email);await page.getByLabel('Пароль',{exact:true}).fill(password);await page.getByRole('button',{name:'Войти',exact:true}).click();await expect(page).toHaveURL(/\/overview$/);
 const counts=()=>execFileSync('docker',['exec','zavozik-full-e2e-postgres-1','psql','-U','zavozik','-d','zavozik','-tAc',`SELECT json_build_object('users',(SELECT count(*) FROM users),'companies',(SELECT count(*) FROM companies),'operations',(SELECT count(*) FROM operations),'events',(SELECT count(*) FROM planned_events),'sources',(SELECT count(*) FROM sources),'versions',(SELECT count(*) FROM onec_plan_versions),'documents',(SELECT count(*) FROM product_documents))`],{encoding:'utf8'}).trim();
 const before=counts();
 const docker=(...args)=>execFileSync('docker',args,{timeout:60000,stdio:'pipe'});
 try{
  docker('stop','zavozik-full-e2e-worker-1');
  const queued=await request.post(`${api}/v1/companies/${cid}/export`,{headers});expect(queued.status()).toBe(202);const job=(await queued.json()).id;
  const waiting=await request.get(`${api}/v1/jobs/${job}`,{headers});expect((await waiting.json()).status).toBe('queued');
  docker('restart','zavozik-full-e2e-postgres-1','zavozik-full-e2e-ml-1','zavozik-full-e2e-api-1','zavozik-full-e2e-frontend-1','zavozik-full-e2e-proxy-1');
  docker('start','zavozik-full-e2e-worker-1');
  await expect.poll(async()=>{try{return(await request.get(`${api}/readyz`)).status()}catch{return 0}},{timeout:60000}).toBe(200);
  await expect.poll(async()=>{try{return(await(await request.get(`${api}/v1/jobs/${job}`,{headers})).json()).status}catch{return 'unavailable'}},{timeout:60000}).toBe('done');
  expect(counts()).toBe(before);
  await page.reload();await expect(page).toHaveURL(/\/overview$/);await expect(page.getByRole('heading',{name:'Для прогноза нужны операции и остаток на счёте',exact:true})).toBeVisible();
  console.log('Persistence counts preserved:',before);
 }finally{docker('start','zavozik-full-e2e-worker-1');}
});
