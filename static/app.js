'use strict';
let state = {jobs:[], applications:[], evidence:[], sources:[], events:[], profile:{}};
let session = {}, currentPage = 'discover', eligibleOnly = true, noticeTimer;
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const titleCase = s => s.replaceAll('_',' ').replace(/^./, c=>c.toUpperCase());
const date = value => new Date(value).toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
const split = value => value.split(',').map(s=>s.trim()).filter(Boolean);
function tell(message, error=false) {
  clearTimeout(noticeTimer); $('#notice').textContent = message; $('#notice').className = error ? 'error' : ''; $('#notice').hidden = false;
  noticeTimer = setTimeout(()=>$('#notice').hidden=true, error ? 14000 : 8000);
}
async function api(path, method='GET', body) {
  const headers = {'X-Jon-Token':session.token || ''};
  const options = {method,headers};
  if(body instanceof FormData) options.body=body;
  else if(body !== undefined) {headers['Content-Type']='application/json'; options.body=JSON.stringify(body);}
  const response = await fetch('/api'+path,options);
  if(!response.ok) {
    const payload = await response.json().catch(()=>({detail:'Request failed.'}));
    const detail = Array.isArray(payload.detail) ? payload.detail.map(e=>`${e.loc.slice(1).join('.')}: ${e.msg}`).join('; ') : payload.detail;
    throw new Error(detail || `Request failed (${response.status}).`);
  }
  return response.json();
}
async function download(path, name) {
  const response = await fetch('/api'+path, {headers:{'X-Jon-Token':session.token}});
  if(!response.ok) throw new Error('Download failed. Reload the app and try again.');
  const url=URL.createObjectURL(await response.blob());
  const anchor=document.createElement('a'); anchor.href=url; anchor.download=name; anchor.click();
  setTimeout(()=>URL.revokeObjectURL(url),5000);
}
function bind(selector, event, action) {
  $(selector).addEventListener(event, async e=>{
    if(event==='submit') e.preventDefault();
    const button=event==='submit' ? e.target.querySelector('[type=submit]') : e.currentTarget;
    try { if(button.tagName==='BUTTON') button.disabled=true; await action(e); }
    catch(error) {tell(error.message,true);}
    finally {if(button.tagName==='BUTTON') button.disabled=false;}
  });
}
function navigate(page) {
  currentPage=page;
  $$('.page').forEach(el=>el.hidden=el.id!=='page-'+page);
  $$('.nav-item').forEach(el=>el.classList.toggle('active',el.dataset.page===page));
  const labels={discover:'OPPORTUNITIES',profile:'YOUR PREFERENCES',evidence:'EVIDENCE & RESUMES',applications:'APPLICATIONS',sources:'CONNECTED SOURCES'};
  $('#breadcrumb').innerHTML='WORKSPACE <b>/</b> '+labels[page];
  window.scrollTo({top:0});
}
document.addEventListener('click', e=>{const target=e.target.closest('[data-page]');if(target)navigate(target.dataset.page);});
function empty(icon,heading,copy,buttons='') {return `<div class="empty"><div class="empty-mark">${icon}</div><h2>${heading}</h2><p>${copy}</p>${buttons}</div>`;}
function badge(status) {
  const kind=['submitted','submitted_manual','offer','interview','approved'].includes(status)?'green':['needs_review','needs_manual','unknown','submitting'].includes(status)?'amber':'gray';
  return `<span class="badge ${kind}">${esc(titleCase(status))}</span>`;
}
function renderJobs() {
  const term=$('#search').value.toLowerCase(), provider=$('#provider-filter').value;
  const jobs=state.jobs.filter(j=>(!eligibleOnly||j.match.eligible)&&(!provider||j.provider===provider)&&`${j.title} ${j.company} ${j.description}`.toLowerCase().includes(term));
  $('#eligible-count').textContent=state.jobs.filter(j=>j.match.eligible).length;
  $('#result-count').textContent=jobs.length+' opportunities';
  if(!jobs.length) {
    $('#job-list').innerHTML=empty('◈',state.jobs.length?'No roles match these filters.':'Your next opportunity is out there.',state.jobs.length?'Try All discovered, adjust your preferences, or change your search.':'Connect a company job board and discover open roles, or import a listing you already have.',`<button class="secondary" data-page="sources">Connect a source →</button><button class="secondary" id="empty-import">Import a listing</button>`);
    $('#empty-import')?.addEventListener('click',importJob);return;
  }
  $('#job-list').innerHTML=jobs.map(j=>{
    const existing=state.applications.find(a=>a.job_id===j.id);
    return `<article class="job-card"><div class="job-top"><div class="company-info"><div class="company-mark">${esc(j.company.slice(0,2).toUpperCase())}</div><div><strong>${esc(j.company)}</strong><small>${esc(j.provider==='manual'?'Imported listing':j.provider)}</small></div></div><span class="badge ${j.match.eligible?'green':'gray'}">${j.match.score}% overlap</span></div><h3>${esc(j.title)}</h3><div class="job-meta">${esc(j.location||'Location undisclosed')} · ${esc(j.job_type||'Type undisclosed')}</div><div class="job-description">${esc(j.description)}</div><div class="tags">${j.remote?'<span class="tag">Remote</span>':''}${j.match.matched_skills.slice(0,4).map(s=>`<span class="tag">${esc(s)}</span>`).join('')}${!j.match.eligible?'<span class="tag">Outside preferences</span>':''}${j.match.unknowns.length?'<span class="tag">Details to verify</span>':''}</div><div class="job-bottom"><span>${existing?'Application started':'Seen '+esc(date(j.last_seen))}</span><button class="secondary job-open" data-job="${esc(j.id)}">${existing?'View application':'View opportunity'} ↗</button></div></article>`;
  }).join('');
  $$('.job-open').forEach(b=>b.addEventListener('click',()=>openJob(b.dataset.job)));
}
function render() {
  const p=state.profile;
  $('#user-name').textContent=p.name||'Your workspace';$('#avatar').textContent=(p.name||'Y').slice(0,1).toUpperCase();
  $('#job-count').textContent=state.jobs.length;$('#app-count').textContent=state.applications.length;
  const ready=state.applications.filter(a=>a.status==='needs_review').length;
  const submitted=state.applications.filter(a=>['submitted','submitted_manual','interview','offer','rejected'].includes(a.status)).length;
  const interviews=state.applications.filter(a=>['interview','offer'].includes(a.status)).length;
  $('#stats').innerHTML=[['Matched opportunities',state.jobs.filter(j=>j.match.eligible).length,'Across your connected sources','◈'],['Ready for review',ready,'Your next step','▤'],['Applications sent',submitted,'Confirmed or recorded by you','↗'],['In conversation',interviews,'Interviews & offers','◎']].map(([label,value,note,icon])=>`<div class="stat"><div class="stat-top">${label}<span class="stat-icon">${icon}</span></div><div class="stat-value">${value}</div><div class="stat-note ${value?'green':''}">${note}</div></div>`).join('');
  $('#setup-banner').hidden=Boolean(p.name&&state.sources.length&&state.evidence.some(e=>e.verified));
  const form=$('#profile-form');
  for(const [key,value] of Object.entries(p)) {const field=form.elements.namedItem(key);if(!field)continue;if(field.type==='checkbox')field.checked=value;else field.value=Array.isArray(value)?value.join(', '):value;}
  renderJobs();renderEvidence();renderApplications();renderSources();
}
function renderEvidence() {
  $('#evidence-list').innerHTML=state.evidence.length?state.evidence.map(e=>`<article class="evidence-card"><div class="evidence-main"><div class="detail-meta"><span class="badge gray">${esc(titleCase(e.category))}</span><span class="badge ${e.verified?'green':'amber'}">${e.verified?'Verified by you':'Needs your review'}</span></div><h3>${esc(e.title)}</h3><p>${esc(e.text)}</p><small>Source: ${esc(e.source)}</small></div><div class="evidence-actions"><button class="secondary evidence-edit" data-id="${e.id}">Review & edit</button><button class="text-button evidence-delete" data-id="${e.id}">Remove</button></div></article>`).join(''):empty('▤','Your experience is the starting point.','Add a project, work experience or education. Verify the facts once, then reuse them across tailored resumes.');
  $$('.evidence-edit').forEach(b=>b.addEventListener('click',()=>evidenceForm(state.evidence.find(e=>e.id===+b.dataset.id))));
  $$('.evidence-delete').forEach(b=>b.addEventListener('click',async()=>{if(!confirm('Remove this evidence? Existing application snapshots retain their original copy.'))return;try{await api('/evidence/'+b.dataset.id,'DELETE');await reload();}catch(e){tell(e.message,true);}}));
}
function renderApplications() {
  $('#tracker-count').textContent=state.applications.length+' tracked';
  $('#application-list').innerHTML=state.applications.map(a=>`<tr><td><strong>${esc(a.job.title)}</strong><small>${esc(a.job.company)}</small></td><td>${badge(a.status)}</td><td>${esc(date(a.updated_at))}</td><td><button class="secondary app-open" data-id="${a.id}">Open →</button></td></tr>`).join('');
  $('#application-empty').innerHTML=state.applications.length?'':empty('↗','Make your first move.','Open an opportunity and prepare a tailored resume. Its history will appear here.','<button class="secondary" data-page="discover">Explore opportunities →</button>');
  $$('.app-open').forEach(b=>b.addEventListener('click',()=>openApplication(+b.dataset.id)));
  $('#events').innerHTML=state.events.length?state.events.map(e=>`<div class="event"><div class="event-time">${esc(date(e.created_at))}</div><div><strong>${esc(titleCase(e.kind))}${e.application_id?' · Application '+e.application_id:''}</strong><p>${esc(e.detail)}</p></div></div>`).join(''):'<p>Your application history will appear here.</p>';
}
function renderSources() {
  $('#source-list').innerHTML=state.sources.map(s=>`<div class="source-row"><span class="card-icon">⌘</span><div><strong>${esc(s.company)}</strong><small>${esc(titleCase(s.provider))} · ${esc(s.board)}</small></div><span class="badge green">Board configured</span><button class="text-button source-delete" data-id="${s.id}">Remove</button></div>`).join('');
  $$('.source-delete').forEach(b=>b.addEventListener('click',async()=>{try{await api('/sources/'+b.dataset.id,'DELETE');await reload();}catch(e){tell(e.message,true);}}));
  $('#model-label').textContent=session.model_configured?session.model:'Evidence-only mode';
  $('#model-status').textContent=session.model_configured?'Endpoint configured':'No endpoint';
  $('#model-description').textContent=session.model_configured?'Optional AI selection sends job text and verified evidence to your configured endpoint. Contact fields are excluded from the profile payload; review evidence for personal details. The model selects evidence IDs; it cannot invent resume claims.':'The app works without an AI connection. To enable model-assisted evidence selection, set JON_MODEL_URL, JON_MODEL and optionally JON_MODEL_KEY, then restart the app.';
}
async function reload() {state=await api('/state');render();}
function modal(title,body) {$('#dialog-title').textContent=title;$('#dialog-body').innerHTML=body;if(!$('#dialog').open)$('#dialog').showModal();}
function closeModal() {$('#dialog').close();}
bind('#close-dialog','click',closeModal);
function evidenceForm(e={}) {
  modal(e.id?'Review your evidence':'Add your evidence',`<form class="form-grid evidence-form" id="evidence-form"><label>Category<select name="category">${['project','experience','education','achievement'].map(v=>`<option value="${v}" ${e.category===v?'selected':''}>${titleCase(v)}</option>`).join('')}</select></label><label>Title<input name="title" required maxlength="200" value="${esc(e.title||'')}" placeholder="Project or role name"></label><label class="full">Facts & contribution<textarea name="text" required minlength="10" maxlength="5000" placeholder="What did you build or accomplish? Include tools, dates and measurable results only when supported.">${esc(e.text||'')}</textarea><small>Up to 5,000 characters per entry. Split a long resume into separate roles and projects for better tailoring.</small></label><label class="full">Evidence source<input name="source" maxlength="1000" value="${esc(e.source||'User supplied')}" placeholder="Resume, project URL, certificate…"></label><label class="check full"><input type="checkbox" name="verified" ${e.verified?'checked':''}> I confirm this describes my actual experience and contribution.</label><div class="form-actions full"><small>Unverified entries are never included in generated resumes.</small><button class="primary" type="submit">Save evidence →</button></div></form>`);
  bind('#evidence-form','submit',async event=>{const f=event.target;const data=Object.fromEntries(new FormData(f));data.verified=f.elements.verified.checked;await api('/evidence'+(e.id?'/'+e.id:''),e.id?'PUT':'POST',data);closeModal();await reload();tell('Evidence saved.');});
}
function importJob() {
  modal('Bring an opportunity into Jon',`<form class="form-grid" id="job-form"><label>Role title<input name="title" required maxlength="200"></label><label>Company<input name="company" required maxlength="150"></label><label class="full">Original listing URL<input type="url" name="url" required placeholder="https://…" maxlength="2000"></label><label>Location<input name="location" maxlength="300"></label><label>Employment type<select name="job_type"><option value="">Unknown</option><option>Full-time</option><option>Part-time</option><option>Internship</option><option>Contract</option></select></label><label class="full">Job description<textarea name="description" required minlength="20" maxlength="60000" rows="8" placeholder="Paste the full listing, including requirements and eligibility."></textarea></label><label>Salary minimum<input name="salary_min" type="number" min="0"></label><label>Salary maximum<input name="salary_max" type="number" min="0"></label><label>Salary currency<select name="currency"><option value="">Undisclosed</option><option>INR</option><option>USD</option><option>EUR</option><option>GBP</option></select></label><label>Salary period<select name="salary_period"><option value="unknown">Unknown</option><option value="year">Annual</option><option value="month">Monthly</option><option value="hour">Hourly</option></select></label><label class="check full"><input type="checkbox" name="remote"> Listing explicitly permits remote work</label><div class="form-actions full"><small>The URL is stored, not crawled. Imported listings use browser handoff.</small><button class="primary" type="submit">Import opportunity →</button></div></form>`);
  bind('#job-form','submit',async e=>{const data=Object.fromEntries(new FormData(e.target));data.remote=e.target.elements.remote.checked;for(const k of ['salary_min','salary_max'])data[k]=data[k]===''?null:Number(data[k]);await api('/jobs','POST',data);closeModal();await reload();tell('Opportunity imported.');});
}
function openJob(id) {
  const a=state.applications.find(a=>a.job_id===id);if(a){openApplication(a.id);return;}
  const j=state.jobs.find(j=>j.id===id);
  modal(j.title,`<p>${esc(j.company)} · ${esc(j.location||'Location undisclosed')}</p><div class="detail-meta"><span class="badge green">${j.match.score}% preference / skill overlap</span><span class="badge gray">${esc(j.provider)}</span></div><div class="callout">${j.match.reasons.map(esc).join(' · ')}${j.match.matched_skills.length?'<br>Skills found: '+j.match.matched_skills.map(esc).join(', '):''}</div>${j.match.blockers.length||j.match.unknowns.length?`<div class="callout warning">${[...j.match.blockers,...j.match.unknowns].map(esc).join('<br>')}</div>`:''}<div class="dialog-copy">${esc(j.description)}</div><label class="dialog-check"><input type="checkbox" id="use-model" ${session.model_configured?'':'disabled'}> Use the configured model to select relevant evidence. ${session.model_configured?'This sends job text and verified evidence to your endpoint.':'Configure a model endpoint to enable this.'}</label><p class="footnote">Drafts use only verified evidence. You can edit phrasing during review. No predicted shortlist probability is claimed.</p><div class="dialog-actions"><a class="secondary" href="${esc(j.url)}" target="_blank" rel="noopener noreferrer">Original listing ↗</a><button class="primary" id="draft-button">Prepare tailored resume →</button></div>`);
  bind('#draft-button','click',async()=>{const result=await api('/jobs/'+encodeURIComponent(id)+'/draft','POST',{use_model:$('#use-model').checked});await reload();openApplication(result.id);tell('Draft prepared. Review every claim before approving.');});
}
function openApplication(id) {
  const a=state.applications.find(a=>a.id===id);const locked=!['needs_review','approved','needs_manual'].includes(a.status);
  modal(a.job.title,`<p>${esc(a.job.company)} · Application #${a.id}</p><div class="detail-meta">${badge(a.status)}<span class="subtle">${esc(a.model)}</span></div><div class="callout">This resume uses a frozen snapshot of your profile and evidence. ${a.snapshot.user_edited?'You have edited the wording; verify any added claims.':'Generated claims are taken directly from your verified evidence.'}</div><label class="field">Resume preview & editor<textarea id="resume-editor" class="resume-editor" maxlength="40000" ${locked?'readonly':''}>${esc(a.resume)}</textarea></label><div class="dialog-actions">${['pdf','docx','txt'].map(f=>`<button class="secondary resume-download" data-format="${f}">↓ ${f.toUpperCase()}</button>`).join('')}${!locked?'<button class="secondary" id="save-revision">Save changes</button>':''}</div><details><summary class="subtle">Evidence used & version</summary><p class="footnote break">Version ${esc(a.hash)}</p>${a.snapshot.evidence.map(e=>`<p class="footnote">${esc(e.title)} — ${esc(e.source)}</p>`).join('')}</details>${a.receipt?`<div class="callout warning">${esc(a.receipt)}</div>`:''}${!locked?'<label class="dialog-check"><input type="checkbox" id="confirm-facts"> I reviewed the saved resume and contact details. All claims are accurate, and I approve this version for this role.</label>':''}<div class="dialog-actions"><a class="secondary" href="${esc(a.snapshot.job.url)}" target="_blank" rel="noopener noreferrer">Open employer application ↗</a>${['needs_review','needs_manual'].includes(a.status)?'<button class="primary" id="approve-button">Approve saved resume →</button>':''}${a.status==='approved'?`<button class="primary" id="submit-button">${a.direct_submission?'Submit approved application →':'Prepare browser handoff →'}</button>`:''}</div>${a.status==='approved'&&!a.direct_submission?'<p class="footnote">This source uses a manual browser handoff. Download your resume, complete the employer form, then record the outcome below.</p>':''}${!['needs_review','submitting','withdrawn','rejected','offer'].includes(a.status)?`<form id="outcome-form" class="outcome-form"><h2>Record an outcome</h2><div class="inline"><select name="status" aria-label="Outcome">${( ['approved','needs_manual','unknown'].includes(a.status)?['submitted_manual',...(a.status==='unknown'?[]:['withdrawn'])]:['interview','offer','rejected','withdrawn']).map(s=>`<option value="${s}">${s==='submitted_manual'?'I submitted / verified submission':titleCase(s)}</option>`).join('')}</select><input name="note" required minlength="5" maxlength="2000" placeholder="Confirmation reference or outcome note" aria-label="Outcome note"><button class="secondary" type="submit">Record</button></div><small>Only record submission after you have received or verified confirmation from the employer.</small></form>`:''}`);
  $$('.resume-download').forEach(b=>b.addEventListener('click',async()=>{try{await download(`/applications/${id}/resume/${b.dataset.format}`,`resume-${id}.${b.dataset.format}`);}catch(e){tell(e.message,true);}}));
  if(!locked)bind('#save-revision','click',async()=>{await api(`/applications/${id}/resume`,'PUT',{text:$('#resume-editor').value});await reload();openApplication(id);tell('Changes saved. Review and approve this new version.');});
  function verifyUnchanged(){if($('#resume-editor').value!==a.resume)throw new Error('Save your changes before approval or submission.');if(!$('#confirm-facts').checked)throw new Error('Please confirm you have reviewed the saved resume and facts.');}
  if($('#approve-button'))bind('#approve-button','click',async()=>{verifyUnchanged();await api(`/applications/${id}/approve`,'POST',{hash:a.hash,confirmed:true});await reload();openApplication(id);tell('Exact resume version approved.');});
  if($('#submit-button'))bind('#submit-button','click',async()=>{verifyUnchanged();const result=await api(`/applications/${id}/submit`,'POST',{hash:a.hash,confirmed:true});await reload();openApplication(id);tell(result.detail);});
  if($('#outcome-form'))bind('#outcome-form','submit',async e=>{await api(`/applications/${id}/outcome`,'POST',Object.fromEntries(new FormData(e.target)));await reload();openApplication(id);tell('Outcome recorded.');});
}
bind('#profile-form','submit',async e=>{const form=e.target;const data=Object.fromEntries(new FormData(form));for(const k of ['roles','locations','companies','skills','job_types'])data[k]=split(data[k]);for(const k of ['remote_only','allow_unknown_salary'])data[k]=form.elements[k].checked;data.salary_min=Number(data.salary_min||0);await api('/profile','PUT',data);await reload();tell('Preferences saved. Your shortlist has been updated.');});
bind('#source-form','submit',async e=>{await api('/sources','POST',Object.fromEntries(new FormData(e.target)));e.target.reset();await reload();tell('Board connected. Use Discover jobs to fetch listings.');});
bind('#discover-button','click',async()=>{tell('Checking your company boards…');const result=await api('/discover','POST',{});await reload();const errors=result.results.filter(r=>r.error);tell(result.results.map(r=>`${r.company}: ${r.error||r.count+' jobs'+(r.skipped?', '+r.skipped+' skipped':'')}`).join(' · '),Boolean(errors.length));});
bind('#refresh','click',reload);
bind('#add-evidence','click',()=>evidenceForm());
bind('#import-job','click',importJob);
bind('#export-csv','click',()=>download('/export','jon-applications.csv'));
bind('#github-form','submit',async e=>{tell('Reading public repository metadata…');const result=await api('/github','POST',Object.fromEntries(new FormData(e.target)));await reload();tell(result.added+' repositories added for review. '+result.note);});
bind('#resume-upload','change',async e=>{const file=e.target.files[0];if(!file)return;try{if(file.size>5000000)throw new Error('Resume must be smaller than 5 MB.');const form=new FormData();form.append('file',file);const result=await api('/resume/extract','POST',form);evidenceForm({title:file.name,source:file.name,text:result.text,category:'experience'});if(result.text.length>5000)tell('Extraction complete. Split this resume into entries of at most 5,000 characters before saving.');}finally{e.target.value='';}});
$('#search').addEventListener('input',renderJobs);$('#provider-filter').addEventListener('change',renderJobs);
$('#eligible-tab').addEventListener('click',()=>{eligibleOnly=true;$('#eligible-tab').classList.add('active');$('#all-tab').classList.remove('active');renderJobs();});
$('#all-tab').addEventListener('click',()=>{eligibleOnly=false;$('#all-tab').classList.add('active');$('#eligible-tab').classList.remove('active');renderJobs();});
(async()=>{try{session=await api('/session');await reload();}catch(e){tell('Could not load the workspace: '+e.message,true);}})();
