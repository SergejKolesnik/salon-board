
const HOURS=Array.from({length:10},(_,i)=>`${String(i+9).padStart(2,"0")}:00`);
const DAYS=["Нд","Пн","Вт","Ср","Чт","Пт","Сб"];
const MONTHS=["січня","лютого","березня","квітня","травня","червня","липня","серпня","вересня","жовтня","листопада","грудня"];
let appointments=[],breaks=[],masterId=null,services=[];
let viewDays=7,periodStart=getMonday(new Date());
let weekStart=getMonday(new Date());
let editingId=null,mobileDay=new Date();

function setView(n){
  viewDays=n;
  if(n===1) periodStart=new Date(mobileDay);
  else if(n===3){ const d=new Date(mobileDay); d.setDate(d.getDate()-1); periodStart=d; }
  else periodStart=getMonday(new Date());
  weekStart=new Date(periodStart);
  ["v1","v3","v7"].forEach(id=>{
    const el=document.getElementById(id);
    if(el){el.style.background=id==="v"+n?"var(--accent)":"var(--surface)";el.style.color=id==="v"+n?"#121214":"var(--muted)";el.style.borderColor=id==="v"+n?"var(--accent)":"var(--border)";}
  });
  loadWeek();
}
function changePeriod(d){periodStart=addDays(periodStart,d*viewDays);weekStart=new Date(periodStart);loadWeek();}
function getMonday(d){const r=new Date(d),day=r.getDay(),diff=r.getDate()-day+(day===0?-6:1);r.setDate(diff);r.setHours(0,0,0,0);return r;}
function isoDate(d){const y=d.getFullYear(),mo=String(d.getMonth()+1).padStart(2,"0"),dy=String(d.getDate()).padStart(2,"0");return y+"-"+mo+"-"+dy;}
function addDays(d,n){const r=new Date(d);r.setDate(r.getDate()+n);return r;}
function fmtDate(iso){const[y,m,day]=iso.split("-");return `${parseInt(day)} ${MONTHS[parseInt(m)-1]}`;}
function toMin(t){const[h,m]=t.split(":").map(Number);return h*60+m;}
async function loadWeek(){
  if(!masterId){
    const me=await fetch("/api/me").then(r=>r.json());
    if(me.master_id) masterId=me.master_id;
    else { const ms=await fetch("/api/masters").then(r=>r.json());if(ms.length)masterId=ms[0].id; }
  }
  if(!masterId)return;
  // Оновлюємо ім'я майстра в хедері
  if(!window._masterName){
    const me=await fetch("/api/me").then(r=>r.json());
    if(me.name){window._masterName=me.name;const b=document.getElementById("masterNameBadge");if(b)b.textContent=me.name;}
  }
  // Оновлюємо кнопку Сьогодні
  (function(){
    const now=new Date();
    const days=["Нд","Пн","Вт","Ср","Чт","Пт","Сб"];
    const months=["січ","лют","бер","кві","тра","чер","лип","сер","вер","жов","лис","гру"];
    const btn=document.getElementById("todayBtn");
    if(btn) btn.innerHTML="&#128197; "+days[now.getDay()]+", "+now.getDate()+" "+months[now.getMonth()];
  })();
  if(!services.length){services=await fetch("/api/services").then(r=>r.json());updateDatalist();}
  const isMobile=window.innerWidth<=640;
  const loadDays=isMobile?14:viewDays;
  const loadStart=isMobile?addDays(periodStart,-1):periodStart;
  const days=Array.from({length:loadDays},(_,i)=>isoDate(addDays(loadStart,i)));
  const from=days[0],to=days[days.length-1];
  const[ap,br]=await Promise.all([
    fetch(`/api/appointments/range?master_id=${masterId}&from_date=${from}&to_date=${to}`).then(r=>r.json()),
    fetch(`/api/breaks/range?master_id=${masterId}&from_date=${from}&to_date=${to}`).then(r=>r.json()),
  ]);
  appointments=ap;breaks=br;renderAll();
}
function updateDatalist(){
  const sel=document.getElementById("fService");
  if(sel&&services.length) sel.innerHTML=services.map(s=>`<option value="${s.name}">${s.name}</option>`).join("");
}
function renderAll(){
  const days=Array.from({length:viewDays},(_,i)=>addDays(periodStart,i));
  const today=isoDate(new Date());
  const f=fmtDate(isoDate(days[0])),t=viewDays>1?fmtDate(isoDate(days[days.length-1])):"";
  document.getElementById("weekLabel").textContent=viewDays===1?`${DAYS[days[0].getDay()]}, ${fmtDate(isoDate(days[0]))}`:(`${f} — ${t}`);
  renderGrid(days,today);
  renderScrollCalendar();
}

function renderGrid(days,today){
  const g=document.getElementById("weekGrid");
  g.style.gridTemplateColumns=`52px repeat(${days.length},1fr)`;
  let h=`<div class="wh"></div>`;
  days.forEach(d=>{const iso=isoDate(d),iT=iso===today;h+=`<div class="wh${iT?" today":""}"><div class="wh-day">${DAYS[d.getDay()]}</div><div class="wh-date">${d.getDate()}</div></div>`;});
  // Track occupied slots
  const occupied={};
  appointments.forEach(a=>{
    const startM=toMin(a.start_time);
    const slots=Math.ceil(a.duration_min/30);
    for(let i=0;i<slots;i++){
      const slotM=startM+i*30;
      const slotH=String(Math.floor(slotM/60)).padStart(2,"0")+":"+String(slotM%60).padStart(2,"0");
      occupied[a.appt_date+"_"+slotH]=i===0?a:"blocked";
    }
  });
  HOURS.forEach(hr=>{
    h+=`<div class="time-col">${hr}</div>`;
    days.forEach(d=>{
      const iso=isoDate(d);
      const key=iso+"_"+hr;
      const occ=occupied[key];
      const isB=breaks.some(b=>b.break_date===iso&&toMin(b.start_time)<=toMin(hr)&&toMin(b.end_time)>toMin(hr));
      if(isB){h+=`<div class="slot break-slot"></div>`;}
      else if(occ==="blocked"){h+=`<div class="slot slot-blocked"></div>`;}
      else if(occ&&occ.id){
        const rows=Math.ceil(occ.duration_min/30);
        const px=(rows*110)+"px";
        h+=`<div class="slot slot-appt-wrap" style="height:${px};z-index:2"><div class="appt" onclick="openDetail(${occ.id})"><div class="an">${occ.client_name}</div><div class="as">${occ.service}</div><div class="ad">${occ.duration_min} хв</div></div></div>`;
      }
      else{h+=`<div class="slot" onclick="openAddOnSlot('${iso}','${hr}')"></div>`;}
    });
  });
  g.innerHTML=h;
if(viewDays===7){const wrap=document.querySelector(".week-wrap");if(wrap)wrap.scrollLeft=0;}
}
function renderMobileDays(days,today){}
function renderMobileList(){}

function renderScrollCalendar(){
  const cal=document.getElementById("scrollCal");
  if(!cal)return;
  const today=isoDate(new Date());
  // Show 14 days starting from periodStart - 1 (so current day is in middle column)
  const startDay=addDays(periodStart,-1);
  const numDays=14;
  const hours=[];for(let h=9;h<=18;h++){hours.push(String(h).padStart(2,"0")+":00");if(h<18)hours.push(String(h).padStart(2,"0")+":30");}

  // Remove old fab if exists
  const oldFab=document.getElementById("calFab");
  if(oldFab)oldFab.remove();

  cal.innerHTML=Array.from({length:numDays},(_,di)=>{
    const d=addDays(startDay,di);
    const iso=isoDate(d);
    const isToday=iso===today;
    const da=appointments.filter(a=>a.appt_date===iso);
    const db=breaks.filter(b=>b.break_date===iso);
    const slots=hours.map(hr=>{
      const isB=db.some(b=>toMin(b.start_time)<=toMin(hr)&&toMin(b.end_time)>toMin(hr));
      const ap=da.find(a=>a.start_time===hr);
      let inner="";
      if(isB) inner=`<div class="cal-break">Перерва</div>`;
      else if(ap) inner=`<div class="cal-appt" onclick="event.stopPropagation();openDetail(${ap.id})"><div class="cal-appt-name">${ap.client_name}</div><div class="cal-appt-svc">${ap.service}</div><div class="cal-appt-dur">${ap.duration_min}хв</div></div>`;
      return `<div class="cal-slot" onclick="openAddOnSlot('${iso}','${hr}')"><div class="cal-slot-time">${hr}</div><div class="cal-slot-content">${inner}</div></div>`;
    }).join("");
    return `<div class="cal-day-col${isToday?" today":""}">
      <div class="cal-day-header"><div class="cal-day-name">${DAYS[d.getDay()]}</div><div class="cal-day-num">${d.getDate()}</div></div>
      <div class="cal-slots">${slots}</div>
    </div>`;
  }).join("");

  // Scroll to today (3rd column = index 1 which is periodStart)
  setTimeout(()=>{
    const cols=cal.querySelectorAll(".cal-day-col");
    if(cols[1]) cols[1].scrollIntoView({behavior:"instant",inline:"start"});
  },50);

  // Add FAB
  const fab=document.createElement("button");
  fab.id="calFab";
  fab.className="cal-fab";
  fab.textContent="+ Новий запис";
  fab.onclick=()=>openAddModal(isoDate(periodStart),"10:00");
  document.querySelector(".mobile-wrap").appendChild(fab);
}
function changeWeek(d){weekStart=addDays(weekStart,d*7);loadWeek();}
function goToday(){
  periodStart=viewDays===7?getMonday(new Date()):new Date();
  weekStart=new Date(periodStart);
  mobileDay=new Date();
  loadWeek();
}
function openDatePicker(){
  const dp=document.getElementById("datePicker");
  dp.value=isoDate(periodStart);
  try{dp.showPicker();}catch(e){dp.click();}
}
function goToDate(iso){
  if(!iso)return;
  periodStart=new Date(iso+"T12:00:00");
  weekStart=new Date(periodStart);
  mobileDay=new Date(periodStart);
  loadWeek();
}
function setMobileDay(iso){mobileDay=new Date(iso+"T12:00:00");}
function openAddModal(date,time){
  editingId=null;
  document.getElementById("modalTitle").textContent="Новий запис";
  document.getElementById("deleteBtn").classList.add("hidden");
  document.getElementById("fClient").value="";
  var ph=document.getElementById("fPhone");if(ph)ph.value="";
  document.getElementById("fService").value="";
  document.getElementById("fDate").value=date||isoDate(mobileDay||new Date());
  document.getElementById("fTime").value=(time||"10:00").slice(0,5);
  document.getElementById("fDuration").value="60";
  document.getElementById("fNotes").value="";
  buildTimeGrid();updateTimeBtns();
  setDur(60);
  document.getElementById("modalOverlay").classList.remove("hidden");
  setTimeout(()=>document.getElementById("fClient").focus(),100);
}
function openAddOnSlot(date,time){openAddModal(date,time);}
function closeModal(){document.getElementById("modalOverlay").classList.add("hidden");}
function openDetail(id){
  const a=appointments.find(x=>x.id==id);if(!a)return;
  document.getElementById("detailName").textContent=a.client_name;
  document.getElementById("detailBody").innerHTML=`<div class="detail-row"><span class="dl">Послуга</span><span class="dv">${a.service}</span></div><div class="detail-row"><span class="dl">Дата</span><span class="dv">${fmtDate(a.appt_date)}</span></div><div class="detail-row"><span class="dl">Час</span><span class="dv">${a.start_time}, ${a.duration_min} хв</span></div>${a.notes?`<div class="detail-row"><span class="dl">Нотатки</span><span class="dv">${a.notes}</span></div>`:""}`;
  document.getElementById("detailEditBtn").onclick=()=>{
    editingId=a.id;
    document.getElementById("modalTitle").textContent="Редагувати";
    document.getElementById("deleteBtn").classList.remove("hidden");
    document.getElementById("fClient").value=a.client_name;
    document.getElementById("fService").value=a.service;
    document.getElementById("fDate").value=a.appt_date;
    document.getElementById("fTime").value=a.start_time;
    document.getElementById("fDuration").value=a.duration_min;
    document.getElementById("fNotes").value=a.notes||"";
    closeDetail();
    document.getElementById("modalOverlay").classList.remove("hidden");
  };
  document.getElementById("detailOverlay").classList.remove("hidden");
}
function closeDetail(){document.getElementById("detailOverlay").classList.add("hidden");}
document.getElementById("modalOverlay").addEventListener("click",e=>{if(e.target===e.currentTarget)closeModal();});
document.getElementById("detailOverlay").addEventListener("click",e=>{if(e.target===e.currentTarget)closeDetail();});
async function saveAppt(){
  const body={master_id:masterId,client_name:document.getElementById("fClient").value.trim(),phone:(document.getElementById("fPhone")||{value:""}).value.trim(),service:document.getElementById("fService").value.trim(),appt_date:document.getElementById("fDate").value,start_time:document.getElementById("fTime").value.slice(0,5),duration_min:parseInt(document.getElementById("fDuration").value),notes:document.getElementById("fNotes").value.trim()};
  if(!body.client_name||!body.service){alert("Заповніть ім\u0027я і послугу");return;}
  const url=editingId?`/api/appointments/${editingId}`:"/api/appointments";
  const res=await fetch(url,{method:editingId?"PUT":"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  if(!res.ok){const e=await res.json();alert(e.detail||"Помилка");return;}
  closeModal();showToast(editingId?"Оновлено":"Збережено");
  mobileDay=new Date(body.appt_date+"T12:00:00");
  await loadWeek();
}
async function deleteAppt(){
  if(!editingId||!confirm("Видалити запис?"))return;
  await fetch(`/api/appointments/${editingId}`,{method:"DELETE"});
  closeModal();showToast("Видалено");await loadWeek();
}
function showToast(msg){const t=document.getElementById("toast");t.textContent=msg;t.classList.add("show");setTimeout(()=>t.classList.remove("show"),2500);}
// Force mobile layout check
function applyLayout(){
  const isMobile=window.innerWidth<=768||('ontouchstart' in window&&window.innerWidth<=1024);
  document.querySelector(".content").style.display=isMobile?"none":"";
  document.querySelector(".mobile-wrap").style.display=isMobile?"flex":"none";
}
applyLayout();
window.addEventListener("resize",applyLayout);



// Time quick-pick buttons
function buildTimeGrid(){
  var grid=document.getElementById("timeGrid");
  if(!grid)return;
  var times=["09:00","09:30","10:00","10:30","11:00","11:30","12:00","12:30","13:00","13:30","14:00","14:30","15:00","15:30","16:00","16:30","17:00","17:30","18:00"];
  grid.innerHTML=times.map(function(t){return '<button type="button" class="time-btn" onclick="selectTime(\'' + t + '\')">'+t+'</button>';}).join("");
}
function selectTime(t){
  document.getElementById("fTime").value=t;
  updateTimeBtns();
}
function updateTimeBtns(){
  var cur=document.getElementById("fTime").value;
  document.querySelectorAll(".time-btn").forEach(function(b){
    b.classList.toggle("active",b.textContent===cur);
  });
}
// Init overlay handlers and load grid
function safeOn(id,evt,fn){var el=document.getElementById(id);if(el)el.addEventListener(evt,fn);}
function safeClick(id,fn){var el=document.getElementById(id);if(el)el.onclick=fn;}
safeOn("modalOverlay","click",function(e){if(e.target===this)closeModal();});
safeOn("detailOverlay","click",function(e){if(e.target===this)closeDetail();});
safeClick("detailEditBtn",function(){
  var a=window._curAppt;if(!a)return;
  editingId=a.id;
  document.getElementById("modalTitle").textContent="Редагувати";
  document.getElementById("deleteBtn").classList.remove("hidden");
  document.getElementById("fClient").value=a.client_name;
  document.getElementById("fService").value=a.service;
  document.getElementById("fDate").value=a.appt_date;
  document.getElementById("fTime").value=a.start_time;
  document.getElementById("fDuration").value=a.duration_min;
  document.getElementById("fNotes").value=a.notes||"";
  closeDetail();
  document.getElementById("modalOverlay").classList.remove("hidden");
});
loadWeek();
function setDur(min){
  document.getElementById("fDuration").value=min;
  document.querySelectorAll(".dur-btn").forEach(b=>{
    b.classList.toggle("active",parseInt(b.textContent)===min||(min===60&&b.textContent==="1 год")||(min===90&&b.textContent==="1.5 год")||(min===120&&b.textContent==="2 год"));
  });
}
function fmtPhone(el){
  var raw=el.value.replace(/\D/g,"");
  if(raw.startsWith("380")) raw=raw.slice(2);
  else if(raw.startsWith("38")) raw=raw.slice(2);
  raw=raw.slice(0,10);
  var res="";
  if(raw.length>0) res="+38 ("+raw.slice(0,3);
  if(raw.length>3) res+=") "+raw.slice(3,6);
  if(raw.length>6) res+="-"+raw.slice(6,8);
  if(raw.length>8) res+="-"+raw.slice(8,10);
  el.value=res;
}
