
const HOURS=(()=>{const s=[];for(let h=9;h<=18;h++){s.push(String(h).padStart(2,"0")+":00");if(h<18)s.push(String(h).padStart(2,"0")+":30");}return s;})();
const DAYS=["Нд","Пн","Вт","Ср","Чт","Пт","Сб"];
const MONTHS=["січня","лютого","березня","квітня","травня","червня","липня","серпня","вересня","жовтня","листопада","грудня"];
let appointments=[],breaks=[],masterId=null,services=[],selectedServiceIds=[];
let viewDays=7,periodStart=getMonday(new Date());
let weekStart=getMonday(new Date());
let editingId=null,editingBreakId=null,mobileDay=new Date();
let selectedClientId=null;
let shouldSmartScrollDesktop=true;
let clientsDirectory=[];
let clientsDirectoryLoaded=false;
let contactPickerProperties=[];
let currentClientCard=null;
let currentClientHistory=[];
let didInitialMobileFastLoad=false;
let pendingMobileScrollIso=isoDate(new Date());
let scheduleStatusTimer=null;
let mobileScrollTimer=null;
const mobileDaysAutoPositioned=new Set();
const APPT_STATUS_LABELS={
  scheduled:"\u0417\u0430\u043f\u043b\u0430\u043d\u043e\u0432\u0430\u043d\u043e",
  confirmed:"\u041f\u0456\u0434\u0442\u0432\u0435\u0440\u0434\u0436\u0435\u043d\u043e",
  completed:"\u0412\u0438\u043a\u043e\u043d\u0430\u043d\u043e",
  cancelled:"\u0421\u043a\u0430\u0441\u043e\u0432\u0430\u043d\u043e",
  no_show:"\u041d\u0435 \u043f\u0440\u0438\u0439\u0448\u043e\u0432"
};
const APPT_STATUS_CLASSES={
  scheduled:"status-scheduled",
  confirmed:"status-confirmed",
  completed:"status-completed",
  cancelled:"status-cancelled",
  no_show:"status-no-show"
};

function setView(n){
  shouldSmartScrollDesktop=true;
  viewDays=n;
  if(n===1) periodStart=new Date(mobileDay);
  else if(n===3){ const d=new Date(mobileDay); d.setDate(d.getDate()-1); periodStart=d; }
  else periodStart=getMonday(new Date());
  weekStart=new Date(periodStart);
  pendingMobileScrollIso=isoDate(mobileDay);
  ["v1","v3","v7"].forEach(id=>{
    const el=document.getElementById(id);
    if(el){el.style.background=id==="v"+n?"var(--accent)":"var(--surface)";el.style.color=id==="v"+n?"#121214":"var(--muted)";el.style.borderColor=id==="v"+n?"var(--accent)":"var(--border)";}
  });
  loadWeek();
}
function changePeriod(d){shouldSmartScrollDesktop=true;periodStart=addDays(periodStart,d*viewDays);weekStart=new Date(periodStart);mobileDay=new Date(periodStart);pendingMobileScrollIso=isoDate(periodStart);loadWeek();}
function getMonday(d){const r=new Date(d),day=r.getDay(),diff=r.getDate()-day+(day===0?-6:1);r.setDate(diff);r.setHours(0,0,0,0);return r;}
function isoDate(d){const y=d.getFullYear(),mo=String(d.getMonth()+1).padStart(2,"0"),dy=String(d.getDate()).padStart(2,"0");return y+"-"+mo+"-"+dy;}
function addDays(d,n){const r=new Date(d);r.setDate(r.getDate()+n);return r;}
function fmtDate(iso){const[y,m,day]=iso.split("-");return `${parseInt(day)} ${MONTHS[parseInt(m)-1]}`;}
function toMin(t){const[h,m]=t.split(":").map(Number);return h*60+m;}
function statusValue(status){return status||"scheduled";}
function statusLabel(status){return APPT_STATUS_LABELS[statusValue(status)]||APPT_STATUS_LABELS.scheduled;}
function statusBadgeHtml(status){
  const s=statusValue(status);
  return `<span class="status-badge ${APPT_STATUS_CLASSES[s]||APPT_STATUS_CLASSES.scheduled}">${statusLabel(s)}</span>`;
}
function ensureScheduleStatusUi(){
  let el=document.getElementById("scheduleStatus");
  if(el)return el;
  el=document.createElement("div");
  el.id="scheduleStatus";
  el.className="schedule-status hidden";
  el.textContent="Завантаження розкладу...";
  document.body.appendChild(el);
  return el;
}
function showScheduleStatus(msg,isError){
  const el=ensureScheduleStatusUi();
  el.textContent=msg;
  el.classList.toggle("error",!!isError);
  el.classList.remove("hidden");
}
function hideScheduleStatus(){
  if(scheduleStatusTimer){clearTimeout(scheduleStatusTimer);scheduleStatusTimer=null;}
  const el=document.getElementById("scheduleStatus");
  if(el)el.classList.add("hidden");
}
function startScheduleSlowTimer(){
  if(scheduleStatusTimer)clearTimeout(scheduleStatusTimer);
  scheduleStatusTimer=setTimeout(function(){
    showScheduleStatus("Інтернет повільний, дані завантажуються...");
  },3000);
}
function clearScheduleSlowTimer(){
  if(scheduleStatusTimer){clearTimeout(scheduleStatusTimer);scheduleStatusTimer=null;}
}
function fetchJson(url){
  return fetch(url).then(function(r){
    if(!r.ok)throw new Error("fetch failed");
    return r.json();
  });
}
async function fetchScheduleRange(masterId,from,to){
  return Promise.all([
    fetchJson(`/api/appointments/range?master_id=${masterId}&from_date=${from}&to_date=${to}`),
    fetchJson(`/api/breaks/range?master_id=${masterId}&from_date=${from}&to_date=${to}`),
  ]);
}
function renderScheduleData(ap,br){
  appointments=ap;
  breaks=br;
  renderAll();
}
async function loadExpandedMobileSchedule(){
  const loadStart=addDays(periodStart,-1);
  const days=Array.from({length:14},(_,i)=>isoDate(addDays(loadStart,i)));
  const from=days[0],to=days[days.length-1];
  try{
    startScheduleSlowTimer();
    const data=await fetchScheduleRange(masterId,from,to);
    renderScheduleData(data[0],data[1]);
    hideScheduleStatus();
  }catch(e){
    clearScheduleSlowTimer();
    showScheduleStatus("Не вдалося завантажити розклад. Спробуйте оновити.",true);
  }
}
async function loadWeek(){
  showScheduleStatus("Завантаження розкладу...");
  startScheduleSlowTimer();
  try{
    if(!masterId){
      const me=await fetchJson("/api/me");
      if(me.master_id) masterId=me.master_id;
      else { const ms=await fetchJson("/api/masters");if(ms.length)masterId=ms[0].id; }
    }
    if(!masterId){hideScheduleStatus();return;}
    if(!window._masterName){
      const me=await fetchJson("/api/me");
      if(me.name){window._masterName=me.name;const b=document.getElementById("masterNameBadge");if(b)b.textContent=me.name;}
    }
    (function(){
      const now=new Date();
      const days=["Нд","Пн","Вт","Ср","Чт","Пт","Сб"];
      const months=["січ","лют","бер","кві","тра","чер","лип","сер","вер","жов","лис","гру"];
      const btn=document.getElementById("todayBtn");
      if(btn) btn.innerHTML="&#128197; "+days[now.getDay()]+", "+now.getDate()+" "+months[now.getMonth()];
    })();
    if(!services.length){services=await fetchJson("/api/services");updateDatalist();}
    const isMobile=window.innerWidth<=640;
    const useFastMobileLoad=isMobile&&!didInitialMobileFastLoad;
    const loadDays=useFastMobileLoad?3:(isMobile?14:viewDays);
    const loadStart=isMobile?addDays(periodStart,-1):periodStart;
    const days=Array.from({length:loadDays},(_,i)=>isoDate(addDays(loadStart,i)));
    const from=days[0],to=days[days.length-1];
    const data=await fetchScheduleRange(masterId,from,to);
    renderScheduleData(data[0],data[1]);
    clearScheduleSlowTimer();
    if(useFastMobileLoad){
      didInitialMobileFastLoad=true;
      hideScheduleStatus();
      loadExpandedMobileSchedule();
    }else{
      hideScheduleStatus();
    }
  }catch(e){
    clearScheduleSlowTimer();
    showScheduleStatus("Не вдалося завантажити розклад. Спробуйте оновити.",true);
  }
}
function updateDatalist(){
  const sel=document.getElementById("fService");
  if(sel&&services.length) sel.innerHTML=services.map(s=>`<option value="${s.name}">${s.name}</option>`).join("");
  renderServicePicker();
}
function renderAll(){
  const days=Array.from({length:viewDays},(_,i)=>addDays(periodStart,i));
  const today=isoDate(new Date());
  const f=fmtDate(isoDate(days[0])),t=viewDays>1?fmtDate(isoDate(days[days.length-1])):"";
  document.getElementById("weekLabel").textContent=viewDays===1?`${DAYS[days[0].getDay()]}, ${fmtDate(isoDate(days[0]))}`:(`${f} — ${t}`);
  renderGrid(days,today);
  renderScrollCalendar();
  if(pendingMobileScrollIso){
    const iso=pendingMobileScrollIso;
    pendingMobileScrollIso=null;
    setTimeout(()=>scrollMobileToRelevantTime(iso,true),80);
  }
}

function renderGrid(days,today){
  const g=document.getElementById("weekGrid");
  const columns=`52px repeat(${days.length},1fr)`;
  const wrap=document.querySelector(".week-wrap");
  let header=document.getElementById("desktopWeekHeader");
  if(!header&&wrap){
    header=document.createElement("div");
    header.id="desktopWeekHeader";
    header.className="desktop-week-header";
    wrap.insertBefore(header,g);
  }
  g.style.gridTemplateColumns=columns;
  if(header){
    header.style.gridTemplateColumns=columns;
    let headerHtml=`<div class="desktop-week-header-spacer"></div>`;
    days.forEach(d=>{
      const iso=isoDate(d);
      const iT=iso===today;
      headerHtml+=`<div class="wh${iT?" today":""}">
        <div class="wh-day">${DAYS[d.getDay()]}</div>
        <div class="wh-date">${d.getDate()}</div>
      </div>`;
    });
    header.innerHTML=headerHtml;
  }

  let h=``;

  const occupied={};

  appointments.forEach(a=>{
    const slotH=a.start_time.slice(0,5);
    occupied[a.appt_date+"_"+slotH]=a;
  });

  HOURS.forEach(hr=>{
    h+=`<div class="time-col">${hr.endsWith(":00")?hr:""}</div>`;

    days.forEach(d=>{
      const iso=isoDate(d);
      const key=iso+"_"+hr;
      const occ=occupied[key];

      const br=breaks.find(b=>
        b.break_date===iso &&
        toMin(b.start_time)<=toMin(hr) &&
        toMin(b.end_time)>toMin(hr)
      );

      if(br){
        const label=hr===br.start_time.slice(0,5)?escapeHtml(br.label||"Зайнято"):"";
        h+=`<div class="slot break-slot" onclick="event.stopPropagation();openBreakDetail(${br.id})">${label?`<div class="break-label">${label}</div>`:""}</div>`;
      }
      else if(occ && occ.id){
        const rows=Math.ceil(occ.duration_min/30);
        const px=(rows*55)+"px";

        h+=`<div class="slot slot-appt-wrap" onclick="openAddOnSlot('${iso}','${hr}')">
          <div class="appt" style="height:${px};z-index:2" onclick="event.stopPropagation();openDetail(${occ.id})">
            <div class="an">${occ.client_name}</div>
            <div class="as">${occ.service}</div>
            <div class="ad">${occ.duration_min} хв</div>
          </div>
        </div>`;
      }
      else{
        h+=`<div class="slot" onclick="openAddOnSlot('${iso}','${hr}')"></div>`;
      }
    });
  });

  g.innerHTML=h;
  scrollDesktopToRelevantTime(days);

  if(viewDays===7){
    if(wrap)wrap.scrollLeft=0;
  }
}
function scrollDesktopToRelevantTime(days){
  if(!shouldSmartScrollDesktop||window.innerWidth<=768)return;
  const wrap=document.querySelector(".week-wrap");
  if(!wrap)return;
  const visibleDates=days.map(d=>isoDate(d));
  const dayAppointments=appointments.filter(a=>visibleDates.includes(a.appt_date));
  let targetMin=12*60;
  if(dayAppointments.length){
    const minStart=Math.min(...dayAppointments.map(a=>toMin(a.start_time)));
    targetMin=Math.max(9*60,minStart-60);
  }
  const slotHeight=55;
  const headerHeight=58;
  const startMin=9*60;
  const slotIndex=Math.max(0,Math.floor((targetMin-startMin)/30));
  wrap.scrollTop=headerHeight+slotIndex*slotHeight;
  shouldSmartScrollDesktop=false;
}
function renderMobileDays(days,today){}
function renderMobileList(){}

function renderScrollCalendar(){
  const cal=document.getElementById("scrollCal");
  if(!cal)return;
  let keepMobileIso=null,keepMobileTop=0;
  if(!pendingMobileScrollIso){
    const calRect=cal.getBoundingClientRect();
    let best=null,bestDist=Infinity;
    cal.querySelectorAll(".cal-day-col[data-date]").forEach(col=>{
      const dist=Math.abs(col.getBoundingClientRect().left-calRect.left);
      if(dist<bestDist){best=col;bestDist=dist;}
    });
    if(best){
      keepMobileIso=best.dataset.date;
      const slots=best.querySelector(".cal-slots");
      keepMobileTop=slots?slots.scrollTop:0;
    }
  }
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
      const br=db.find(b=>toMin(b.start_time)<=toMin(hr)&&toMin(b.end_time)>toMin(hr));
      const ap=da.find(a=>a.start_time===hr);
      let inner="";
      if(br) inner=`<div class="cal-break" onclick="event.stopPropagation();openBreakDetail(${br.id})">${escapeHtml(br.label||"Зайнято")}</div>`;
      else if(ap){
        const rows=Math.ceil(ap.duration_min/30);
        const px=rows*52-8;
        inner=`<div class="cal-appt" style="position:absolute;left:40px;right:4px;top:4px;height:${px}px;z-index:5" onclick="event.stopPropagation();openDetail(${ap.id})"><div class="cal-appt-name">${ap.client_name}</div><div class="cal-appt-svc">${ap.service}</div><div class="cal-appt-dur">${ap.duration_min}хв</div></div>`;
      }
      return `<div class="cal-slot" onclick="openAddOnSlot('${iso}','${hr}')"><div class="cal-slot-time">${hr}</div><div class="cal-slot-content">${inner}</div></div>`;
    }).join("");
    const countBadge=da.length?`<div class="cal-day-count">${appointmentCountLabel(da.length)}</div>`:"";
    return `<div class="cal-day-col${isToday?" today":""}" data-date="${iso}">
      <div class="cal-day-header"><div class="cal-day-name">${DAYS[d.getDay()]}</div><div class="cal-day-num">${d.getDate()}</div>${countBadge}</div>
      <div class="cal-slots">${slots}</div>
    </div>`;
  }).join("");

  cal.onscroll=function(){
    clearTimeout(mobileScrollTimer);
    mobileScrollTimer=setTimeout(()=>autoPositionVisibleMobileDay(),140);
  };

  // Add FAB
  const fab=document.createElement("button");
  fab.id="calFab";
  fab.className="cal-fab";
  fab.textContent="+ Новий запис";
  fab.onclick=()=>openAddModal(isoDate(periodStart),"10:00");
  document.querySelector(".mobile-wrap").appendChild(fab);
  if(keepMobileIso){
    setTimeout(()=>{
      const col=cal.querySelector(`.cal-day-col[data-date="${keepMobileIso}"]`);
      if(!col)return;
      col.scrollIntoView({behavior:"instant",inline:"start"});
      const slots=col.querySelector(".cal-slots");
      if(slots)slots.scrollTop=keepMobileTop;
    },50);
  }
}
function appointmentCountLabel(count){
  const mod10=count%10,mod100=count%100;
  const word=mod10===1&&mod100!==11?"запис":(mod10>=2&&mod10<=4&&(mod100<12||mod100>14)?"записи":"записів");
  return `${count} ${word}`;
}
function autoPositionVisibleMobileDay(){
  if(window.innerWidth>768)return;
  const cal=document.getElementById("scrollCal");
  if(!cal)return;
  const calRect=cal.getBoundingClientRect();
  let closest=null,closestDistance=Infinity;
  cal.querySelectorAll(".cal-day-col[data-date]").forEach(function(col){
    const distance=Math.abs(col.getBoundingClientRect().left-calRect.left);
    if(distance<closestDistance){closest=col;closestDistance=distance;}
  });
  if(closest)scrollMobileToRelevantTime(closest.dataset.date,false);
}
function scrollMobileToRelevantTime(targetIso,force){
  if(window.innerWidth>768)return;
  if(!force&&mobileDaysAutoPositioned.has(targetIso))return;
  const cal=document.getElementById("scrollCal");
  if(!cal||!targetIso)return;
  const col=cal.querySelector(`.cal-day-col[data-date="${targetIso}"]`);
  if(!col)return;
  col.scrollIntoView({behavior:"instant",inline:"start"});
  const calSlots=col.querySelector(".cal-slots");
  if(!calSlots)return;
  const dayAppointments=appointments.filter(a=>a.appt_date===targetIso);
  const dayBreaks=breaks.filter(b=>b.break_date===targetIso);
  const todayIso=isoDate(new Date());
  const now=new Date();
  const nowMin=now.getHours()*60+now.getMinutes();
  let targetMin=targetIso===todayIso?Math.max(9*60,nowMin-60):9*60;
  const starts=[];
  dayAppointments.forEach(a=>starts.push(toMin(a.start_time)));
  dayBreaks.forEach(b=>starts.push(toMin(b.start_time)));
  if(starts.length){
    const relevant=targetIso===todayIso?starts.filter(value=>value>=nowMin):starts;
    const selectedStart=Math.min(...(relevant.length?relevant:starts));
    targetMin=Math.max(9*60,selectedStart-60);
  }
  const slotHeight=52;
  const startMin=9*60;
  const slotIndex=Math.max(0,Math.floor((targetMin-startMin)/30));
  calSlots.scrollTop=slotIndex*slotHeight;
  mobileDaysAutoPositioned.add(targetIso);
}
function changeWeek(d){shouldSmartScrollDesktop=true;weekStart=addDays(weekStart,d*7);periodStart=new Date(weekStart);mobileDay=new Date(periodStart);pendingMobileScrollIso=isoDate(periodStart);loadWeek();}
function goToday(){
  shouldSmartScrollDesktop=true;
  periodStart=viewDays===7?getMonday(new Date()):new Date();
  weekStart=new Date(periodStart);
  mobileDay=new Date();
  pendingMobileScrollIso=isoDate(mobileDay);
  loadWeek();
}
function openDatePicker(){
  const dp=document.getElementById("datePicker");
  dp.value=isoDate(periodStart);
  try{dp.showPicker();}catch(e){dp.click();}
}
function goToDate(iso){
  if(!iso)return;
  shouldSmartScrollDesktop=true;
  periodStart=new Date(iso+"T12:00:00");
  weekStart=new Date(periodStart);
  mobileDay=new Date(periodStart);
  pendingMobileScrollIso=iso;
  loadWeek();
}
function setMobileDay(iso){mobileDay=new Date(iso+"T12:00:00");}
function rowOf(id){const el=document.getElementById(id);return el?el.closest(".form-row"):null;}
function toggleEventType(){updateEventTypeUi();}
function ensureEventTypeUi(){
  const existingType=document.getElementById("fEventType");
  if(existingType){
    existingType.onchange=toggleEventType;
    ensureClientCreatorUi(rowOf("fClient"));
    ensureServicePickerUi(rowOf("fService"));
    return;
  }
  const clientRow=rowOf("fClient");
  if(clientRow){
    ensureClientCreatorUi(clientRow);
    const typeRow=document.createElement("div");
    typeRow.className="form-row";
    typeRow.id="eventTypeRow";
    typeRow.innerHTML='<label>Тип події</label><select id="fEventType" onchange="toggleEventType()"><option value="appointment">Запис клієнта</option><option value="break">Зайнятий час</option></select>';
    clientRow.parentNode.insertBefore(typeRow,clientRow);
    document.getElementById("fEventType").addEventListener("change",toggleEventType);
  }
  const serviceRow=rowOf("fService");
  if(serviceRow){
    ensureServicePickerUi(serviceRow);
    const reasonRow=document.createElement("div");
    reasonRow.className="form-row hidden";
    reasonRow.id="breakReasonRow";
    reasonRow.innerHTML='<label>Назва / причина</label><input id="fBreakLabel" type="text" placeholder="Зайнято">';
    serviceRow.parentNode.insertBefore(reasonRow,serviceRow.nextSibling);
  }
}
function updateEventTypeUi(){
  const type=(document.getElementById("fEventType")||{value:"appointment"}).value;
  const isBreak=type==="break";
  ["fClient","fPhone","fService","fStatus"].forEach(id=>{const row=rowOf(id);if(row)row.classList.toggle("hidden",isBreak);});
  const reason=document.getElementById("breakReasonRow");if(reason)reason.classList.toggle("hidden",!isBreak);
  hideClientSuggestions();
}
function breakEndTime(start,duration){
  const mins=toMin(start)+parseInt(duration||60);
  return String(Math.floor(mins/60)).padStart(2,"0")+":"+String(mins%60).padStart(2,"0");
}
function ensureAppointmentModalActions(){
  const overlay=document.getElementById("modalOverlay");
  const modal=overlay&&overlay.querySelector(".modal");
  if(!modal)return;
  let footer=modal.querySelector(".modal-footer");
  if(!footer){
    footer=document.createElement("div");
    footer.className="modal-footer appointment-actions";
    modal.appendChild(footer);
  }else{
    footer.classList.add("appointment-actions");
  }
  let save=footer.querySelector('[data-role="save-appointment"], [onclick*="saveAppt"]');
  if(!save){
    save=document.createElement("button");
    save.type="button";
    save.className="btn btn-primary";
    save.dataset.role="save-appointment";
    save.textContent="Зберегти";
    save.onclick=saveAppt;
    footer.appendChild(save);
  }else{
    save.dataset.role="save-appointment";
    save.textContent="Зберегти";
  }
  let cancel=footer.querySelector('[data-role="cancel-appointment"], [onclick*="closeModal"]');
  if(!cancel){
    cancel=document.createElement("button");
    cancel.type="button";
    cancel.className="btn";
    cancel.dataset.role="cancel-appointment";
    cancel.textContent="Скасувати";
    cancel.onclick=closeModal;
    footer.insertBefore(cancel,save);
  }else{
    cancel.dataset.role="cancel-appointment";
    cancel.textContent="Скасувати";
  }
}
function openAddModal(date,time){
  editingId=null;
  editingBreakId=null;
  selectedClientId=null;hideClientSuggestions();
  selectedServiceIds=[];
  ensureEventTypeUi();
  ensureAppointmentModalActions();
  document.getElementById("modalTitle").textContent="Новий запис";
  document.getElementById("deleteBtn").classList.add("hidden");
  var et=document.getElementById("fEventType");if(et)et.value="appointment";
  var bl=document.getElementById("fBreakLabel");if(bl)bl.value="";
  document.getElementById("fClient").value="";
  var ph=document.getElementById("fPhone");if(ph)ph.value="";
  document.getElementById("fService").value="";
  renderServicePicker();
  document.getElementById("fDate").value=date||isoDate(mobileDay||new Date());
  document.getElementById("fTime").value=(time||"10:00").slice(0,5);
  document.getElementById("fDuration").value="60";
  document.getElementById("fNotes").value="";
  var fs=document.getElementById("fStatus");if(fs)fs.value="scheduled";
  updateEventTypeUi();
  buildTimeGrid();updateTimeBtns();
  setDur(60);
  document.getElementById("modalOverlay").classList.remove("hidden");
  setTimeout(()=>document.getElementById("fClient").focus(),100);
}
function openAddOnSlot(date,time){openAddModal(date,time);}
function closeModal(){document.getElementById("modalOverlay").classList.add("hidden");}
async function openDetail(id){
editingBreakId=null;
const a=appointments.find(x=>x.id==id);if(!a)return;
const editBtn=document.getElementById("detailEditBtn");if(editBtn){editBtn.textContent="Редагувати";editBtn.classList.remove("btn-danger");editBtn.classList.add("btn-primary");}
document.getElementById("detailName").textContent=a.client_name;
document.getElementById("detailBody").innerHTML=
'<div class="detail-row"><span class="dl">\u0421\u0442\u0430\u0442\u0443\u0441</span><span class="dv">'+statusBadgeHtml(a.status)+'</span></div>'
+'<div class="detail-row"><span class="dl">\u041f\u043e\u0441\u043b\u0443\u0433\u0430</span><span class="dv">'+a.service+'</span></div>'
+'<div class="detail-row"><span class="dl">\u0414\u0430\u0442\u0430</span><span class="dv">'+fmtDate(a.appt_date)+'</span></div>'
+'<div class="detail-row"><span class="dl">\u0427\u0430\u0441</span><span class="dv">'+a.start_time+', '+a.duration_min+' \u0445\u0432</span></div>'
+(a.notes?'<div class="detail-row"><span class="dl">\u041d\u043e\u0442\u0430\u0442\u043a\u0438</span><span class="dv">'+a.notes+'</span></div>':'');
document.getElementById("detailEditBtn").onclick=function(){
editingId=a.id;
editingBreakId=null;
ensureEventTypeUi();
ensureAppointmentModalActions();
document.getElementById("modalTitle").textContent="\u0420\u0435\u0434\u0430\u0433\u0443\u0432\u0430\u0442\u0438";
document.getElementById("deleteBtn").classList.remove("hidden");
var et=document.getElementById("fEventType");if(et)et.value="appointment";
document.getElementById("fClient").value=a.client_name;
document.getElementById("fService").value=a.service;
selectedServiceIds=(a.service_ids||[]).map(Number);
if(!selectedServiceIds.length){const legacy=services.find(function(s){return s.name===a.service;});if(legacy)selectedServiceIds=[Number(legacy.id)];}
renderServicePicker();
document.getElementById("fDate").value=a.appt_date;
document.getElementById("fTime").value=a.start_time;
document.getElementById("fDuration").value=a.duration_min;
document.getElementById("fNotes").value=a.notes||"";
var fs=document.getElementById("fStatus");if(fs)fs.value=statusValue(a.status);
updateEventTypeUi();
closeDetail();
document.getElementById("modalOverlay").classList.remove("hidden");
};
// CRM \u0415\u0442\u0430\u043f 2: \u0431\u043b\u043e\u043a \u043a\u043b\u0456\u0454\u043d\u0442\u0430
var clientBlock=document.getElementById("detailClientBlock");
if(!clientBlock){document.getElementById("detailOverlay").classList.remove("hidden");return;}
if(a.client_id){
fetch("/api/client/"+a.client_id)
.then(function(r){return r.json();})
.then(function(clientData){
return fetch("/api/client/"+a.client_id+"/history")
.then(function(r){return r.json();})
.then(function(historyData){
var dob=clientData.birthday?"<div class=\"detail-row\"><span class=\"dl\">\u0414\u0430\u0442\u0430 \u043d\u0430\u0440\u043e\u0434\u0436\u0435\u043d\u043d\u044f</span><span class=\"dv\">"+clientData.birthday+"</span></div>":"";
var notes2=clientData.notes?"<div class=\"detail-row\"><span class=\"dl\">\u041d\u043e\u0442\u0430\u0442\u043a\u0438</span><span class=\"dv\">"+clientData.notes+"</span></div>":"";
var fullName=(clientData.first_name||"")+" "+(clientData.last_name||"");fullName=fullName.trim()||a.client_name;
var phone=formatPhoneDisplay(clientData.phone||"")||"\u2014";
var visits="<div class=\"crm-no-visits\">\u041f\u043e\u043f\u0435\u0440\u0435\u0434\u043d\u0456\u0445 \u0432\u0456\u0437\u0438\u0442\u0456\u0432 \u043d\u0435\u043c\u0430\u0454</div>";
if(Array.isArray(historyData)&&historyData.length>0){
visits=historyData.slice(0,5).map(function(v){return "<div class=\"crm-visit\">"+v.appt_date+" \u2014 "+v.service+" \u2014 "+v.duration_min+" \u0445\u0432</div>";}).join("");
}
clientBlock.innerHTML=
"<div class=\"crm-section-title\">\u041a\u043b\u0456\u0454\u043d\u0442</div>"
+"<div class=\"detail-row\"><span class=\"dl\">\u0406\u043c'\u044f</span><span class=\"dv\">"+fullName+"</span></div>"
+"<div class=\"detail-row\"><span class=\"dl\">\u0422\u0435\u043b\u0435\u0444\u043e\u043d</span><span class=\"dv\">"+phone+"</span></div>"
+dob+notes2
+"<div class=\"crm-section-title crm-history-title\">\u0406\u0441\u0442\u043e\u0440\u0456\u044f \u0432\u0456\u0437\u0438\u0442\u0456\u0432</div>"
+"<div class=\"crm-history-list\">"+visits+"</div>";
clientBlock.style.display="";
document.getElementById("detailOverlay").classList.remove("hidden");
});
})
.catch(function(){
clientBlock.innerHTML="<div class=\"crm-section-title\">\u041a\u043b\u0456\u0454\u043d\u0442</div><div class=\"crm-no-visits\">\u041d\u0435 \u0432\u0434\u0430\u043b\u043e\u0441\u044f \u0437\u0430\u0432\u0430\u043d\u0442\u0430\u0436\u0438\u0442\u0438 \u0434\u0430\u043d\u0456 \u043a\u043b\u0456\u0454\u043d\u0442\u0430</div>";
clientBlock.style.display="";
document.getElementById("detailOverlay").classList.remove("hidden");
});
}else{
clientBlock.innerHTML="<div class=\"crm-no-client\">\u041a\u043b\u0456\u0454\u043d\u0442 \u0449\u0435 \u043d\u0435 \u043f\u0440\u0438\u0432'\u044f\u0437\u0430\u043d\u0438\u0439 \u0434\u043e \u0431\u0430\u0437\u0438.</div>";
clientBlock.style.display="";
document.getElementById("detailOverlay").classList.remove("hidden");
}
}

function openBreakDetail(id){
const b=breaks.find(x=>x.id==id);if(!b)return;
editingBreakId=b.id;
editingId=null;
const duration=toMin(b.end_time)-toMin(b.start_time);
document.getElementById("detailName").textContent=b.label||"Зайнято";
document.getElementById("detailBody").innerHTML=
'<div class="detail-row"><span class="dl">Тип</span><span class="dv">Зайнятий час</span></div>'
+'<div class="detail-row"><span class="dl">Дата</span><span class="dv">'+fmtDate(b.break_date)+'</span></div>'
+'<div class="detail-row"><span class="dl">Час</span><span class="dv">'+b.start_time+', '+duration+' хв</span></div>';
const clientBlock=document.getElementById("detailClientBlock");if(clientBlock){clientBlock.innerHTML="";clientBlock.style.display="none";}
const editBtn=document.getElementById("detailEditBtn");
if(editBtn){
  editBtn.textContent="Видалити";
  editBtn.classList.remove("btn-primary");
  editBtn.classList.add("btn-danger");
  editBtn.onclick=function(){deleteBreak(b.id);};
}
document.getElementById("detailOverlay").classList.remove("hidden");
}

function closeDetail(){document.getElementById("detailOverlay").classList.add("hidden");}
document.getElementById("modalOverlay").addEventListener("click",e=>{if(e.target===e.currentTarget)closeModal();});
document.getElementById("detailOverlay").addEventListener("click",e=>{if(e.target===e.currentTarget)closeDetail();});
async function saveAppt(){
  const eventType=(document.getElementById("fEventType")||{value:"appointment"}).value;
  if(eventType==="break"){
    const start=document.getElementById("fTime").value.slice(0,5);
    const body={master_id:masterId,break_date:document.getElementById("fDate").value,start_time:start,end_time:breakEndTime(start,document.getElementById("fDuration").value),label:(document.getElementById("fBreakLabel")||{value:""}).value.trim()||"Зайнято"};
    const url=editingBreakId?`/api/breaks/${editingBreakId}`:"/api/breaks";
    const res=await fetch(url,{method:editingBreakId?"PUT":"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
    if(!res.ok){const e=await res.json();alert(e.detail||"Помилка");return;}
    closeModal();showToast(editingBreakId?"Оновлено":"Збережено");
    mobileDay=new Date(body.break_date+"T12:00:00");
    if(window.innerWidth<=768){
      periodStart=new Date(body.break_date+"T12:00:00");
      weekStart=new Date(periodStart);
      pendingMobileScrollIso=body.break_date;
    }
    shouldSmartScrollDesktop=false;
    await loadWeek();
    return;
  }
  const body={master_id:masterId,client_name:document.getElementById("fClient").value.trim(),phone:(document.getElementById("fPhone")||{value:""}).value.trim(),service:document.getElementById("fService").value.trim(),appt_date:document.getElementById("fDate").value,start_time:document.getElementById("fTime").value.slice(0,5),duration_min:parseInt(document.getElementById("fDuration").value),notes:document.getElementById("fNotes").value.trim(),client_id:selectedClientId||null,status:(document.getElementById("fStatus")||{value:"scheduled"}).value||"scheduled"};
  body.service_ids=selectedServiceIds.slice();
  if(!body.client_name||!body.service){alert("Заповніть ім\u0027я і послугу");return;}
  const url=editingId?`/api/appointments/${editingId}`:"/api/appointments";
  const res=await fetch(url,{method:editingId?"PUT":"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)});
  if(!res.ok){const e=await res.json();alert(e.detail||"Помилка");return;}
  closeModal();showToast(editingId?"Оновлено":"Збережено");
  mobileDay=new Date(body.appt_date+"T12:00:00");
  if(window.innerWidth<=768){
    periodStart=new Date(body.appt_date+"T12:00:00");
    weekStart=new Date(periodStart);
    pendingMobileScrollIso=body.appt_date;
  }
  shouldSmartScrollDesktop=false;
  await loadWeek();
}
async function deleteAppt(){
  if(!editingId||!confirm("Видалити запис?"))return;
  await fetch(`/api/appointments/${editingId}`,{method:"DELETE"});
  shouldSmartScrollDesktop=false;
  closeModal();showToast("Видалено");await loadWeek();
}
async function deleteBreak(id){
  const breakId=id||editingBreakId;
  if(!breakId||!confirm("Видалити блокування?"))return;
  const res=await fetch(`/api/breaks/${breakId}`,{method:"DELETE"});
  if(!res.ok){const e=await res.json();alert(e.detail||"Помилка");return;}
  editingBreakId=null;
  shouldSmartScrollDesktop=false;
  closeDetail();closeModal();showToast("Видалено");await loadWeek();
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
  selectedServiceIds=(a.service_ids||[]).map(Number);
  if(!selectedServiceIds.length){const legacy=services.find(function(s){return s.name===a.service;});if(legacy)selectedServiceIds=[Number(legacy.id)];}
  renderServicePicker();
  document.getElementById("fDate").value=a.appt_date;
  document.getElementById("fTime").value=a.start_time;
  document.getElementById("fDuration").value=a.duration_min;
  document.getElementById("fNotes").value=a.notes||"";
  var fs=document.getElementById("fStatus");if(fs)fs.value=statusValue(a.status);
  closeDetail();
  document.getElementById("modalOverlay").classList.remove("hidden");
});
function ensureClientsDirectoryUi(){
  if(!document.getElementById("clientsBtn")){
    const topbar=document.querySelector(".topbar");
    const spacer=document.querySelector(".topbar .spacer");
    if(topbar&&spacer){
      const btn=document.createElement("button");
      btn.id="clientsBtn";
      btn.className="clients-btn";
      btn.type="button";
      btn.textContent="👥 Клієнти";
      btn.onclick=openClientsModal;
      topbar.insertBefore(btn,spacer.nextSibling);
    }
  }
  if(!document.getElementById("clientsOverlay")){
    const overlay=document.createElement("div");
    overlay.id="clientsOverlay";
    overlay.className="overlay hidden";
    overlay.innerHTML=
      '<div class="modal clients-modal">'
      +'<h2>Клієнти</h2>'
      +'<input id="clientsSearch" class="clients-search" type="search" placeholder="Пошук за ім&#39;ям, прізвищем або телефоном">'
      +'<div class="clients-table-wrap"><table class="clients-table">'
      +'<thead><tr><th>Прізвище</th><th>Ім&#39;я</th><th>Телефон</th><th>Візитів</th><th>Останній візит</th></tr></thead>'
      +'<tbody id="clientsTableBody"><tr><td colspan="5" class="clients-empty">Немає даних</td></tr></tbody>'
      +'</table></div>'
      +'<div class="modal-footer"><button class="btn" onclick="closeClientsModal()">Закрити</button></div>'
      +'</div>';
    document.body.appendChild(overlay);
    overlay.addEventListener("click",function(e){if(e.target===this)closeClientsModal();});
    const search=overlay.querySelector("#clientsSearch");
    if(search)search.addEventListener("input",renderClientsTable);
  }
  if(!document.getElementById("clientCardOverlay")){
    const cardOverlay=document.createElement("div");
    cardOverlay.id="clientCardOverlay";
    cardOverlay.className="overlay hidden";
    cardOverlay.innerHTML=
      '<div class="modal client-card-modal">'
      +'<h2 id="clientCardTitle">Картка клієнта</h2>'
      +'<div id="clientCardBody"></div>'
      +'<div class="crm-section-title crm-history-title">Останні 10 візитів</div>'
      +'<div id="clientCardHistory" class="client-card-history"></div>'
      +'<div class="modal-footer">'
      +'<button class="btn" onclick="closeClientCardModal()">Закрити</button>'
      +'<button class="btn btn-primary" id="clientCardEditBtn" onclick="editClientCard()">Редагувати</button>'
      +'<button class="btn btn-primary hidden" id="clientCardSaveBtn" onclick="saveClientCard()">Зберегти</button>'
      +'</div>'
      +'</div>';
    document.body.appendChild(cardOverlay);
    cardOverlay.addEventListener("click",function(e){if(e.target===this)closeClientCardModal();});
  }
  if(!document.getElementById("newClientOverlay")){
    const createOverlay=document.createElement("div");
    createOverlay.id="newClientOverlay";
    createOverlay.className="overlay hidden new-client-overlay";
    createOverlay.innerHTML=
      '<div class="modal new-client-modal">'
      +'<h2>Новий клієнт</h2>'
      +'<div class="new-client-hint">Телефон і дата народження бажані для повної картки, але клієнта можна зберегти й без них.</div>'
      +'<button class="contact-picker-btn" id="contactPickerBtn" type="button" onclick="pickPhoneContact()">📇 Обрати з контактів телефону</button>'
      +'<div class="client-card-grid">'
      +clientCardInput("new_first_name","Ім\'я","")
      +clientCardInput("new_last_name","Прізвище","")
      +clientCardInput("new_phone","Телефон","")
      +clientCardInput("new_birthday","Дата народження","")
      +'<label class="client-card-field client-card-notes"><span>Нотатки</span><textarea id="cc_new_notes" rows="3"></textarea></label>'
      +'</div>'
      +'<div class="modal-footer">'
      +'<button class="btn" type="button" onclick="closeNewClientModal()">Скасувати</button>'
      +'<button class="btn btn-primary" id="newClientSaveBtn" type="button" onclick="saveNewClient()">Додати клієнта</button>'
      +'</div>'
      +'</div>';
    document.body.appendChild(createOverlay);
    createOverlay.addEventListener("click",function(e){if(e.target===this)closeNewClientModal();});
    prepareContactPicker();
  }
}

function contactPickerSupported(){
  return window.isSecureContext&&"contacts" in navigator&&typeof navigator.contacts.select==="function";
}
async function prepareContactPicker(){
  const button=document.getElementById("contactPickerBtn");
  if(!button)return;
  contactPickerProperties=["name","tel"];
  if(!contactPickerSupported()){
    button.title="Для вибору контактів відкрийте Body Balance у Google Chrome на Android";
    return;
  }
  try{
    const supported=typeof navigator.contacts.getProperties==="function"
      ?await navigator.contacts.getProperties()
      :["name","tel"];
    contactPickerProperties=["name","tel"].filter(function(property){return supported.includes(property);});
    button.title=contactPickerProperties.includes("tel")?"Вибрати ім'я та номер із телефонної книги":"Браузер не дозволяє передати номер контакту";
  }catch(error){
    // Some Android browsers expose select() but fail getProperties().
    // Keep the common name/tel request available and let the native picker decide.
    contactPickerProperties=["name","tel"];
  }
}
function firstContactValue(value){
  return Array.isArray(value)?String(value[0]||"").trim():String(value||"").trim();
}
async function pickPhoneContact(){
  if(!contactPickerSupported()){
    alert("Телефонна книга недоступна в цьому браузері. Відкрийте сайт salon-board.onrender.com у Google Chrome на Android.");
    return;
  }
  if(!contactPickerProperties.includes("tel")){
    alert("Цей браузер не дозволяє передати номер із телефонної книги.");
    return;
  }
  try{
    const contacts=await navigator.contacts.select(contactPickerProperties,{multiple:false});
    const contact=contacts&&contacts[0];
    if(!contact)return;
    const fullName=firstContactValue(contact.name);
    const nameParts=fullName.split(/\s+/).filter(Boolean);
    const firstName=document.getElementById("cc_new_first_name");
    const lastName=document.getElementById("cc_new_last_name");
    const phone=document.getElementById("cc_new_phone");
    if(firstName&&fullName)firstName.value=nameParts.shift()||"";
    if(lastName&&fullName)lastName.value=nameParts.join(" ");
    if(phone){phone.value=firstContactValue(contact.tel);fmtPhone(phone);}
    showToast("Контакт підставлено. Перевірте дані перед збереженням");
  }catch(error){
    if(error&&error.name!=="AbortError")alert("Не вдалося відкрити контакти телефону");
  }
}

function ensureClientCreatorUi(clientRow){
  if(!clientRow||document.getElementById("addClientBtn"))return;
  const button=document.createElement("button");
  button.id="addClientBtn";
  button.type="button";
  button.className="add-client-btn";
  button.textContent="+ Додати клієнта";
  button.onclick=openNewClientModal;
  clientRow.appendChild(button);
}

function openNewClientModal(){
  ensureClientsDirectoryUi();
  hideClientSuggestions();
  const name=(document.getElementById("fClient")||{value:""}).value.trim().split(/\s+/,2);
  const values={
    cc_new_first_name:name[0]||"",
    cc_new_last_name:name[1]||"",
    cc_new_phone:(document.getElementById("fPhone")||{value:""}).value.trim(),
    cc_new_birthday:"",
    cc_new_notes:""
  };
  Object.keys(values).forEach(function(id){const el=document.getElementById(id);if(el)el.value=values[id];});
  document.getElementById("newClientOverlay").classList.remove("hidden");
  if(window.innerWidth>640){
    setTimeout(function(){const first=document.getElementById("cc_new_first_name");if(first)first.focus();},50);
  }
}
function closeNewClientModal(){
  const overlay=document.getElementById("newClientOverlay");
  if(overlay)overlay.classList.add("hidden");
}
async function saveNewClient(){
  const payload={
    first_name:(document.getElementById("cc_new_first_name")||{value:""}).value.trim(),
    last_name:(document.getElementById("cc_new_last_name")||{value:""}).value.trim(),
    phone:(document.getElementById("cc_new_phone")||{value:""}).value.trim(),
    birthday:(document.getElementById("cc_new_birthday")||{value:""}).value.trim(),
    notes:(document.getElementById("cc_new_notes")||{value:""}).value.trim()
  };
  if(!payload.first_name){alert("Вкажіть ім'я клієнта");return;}
  const missingDetails=[];
  if(!payload.phone)missingDetails.push("телефон");
  if(!payload.birthday)missingDetails.push("дату народження");
  const saveButton=document.getElementById("newClientSaveBtn");
  if(saveButton){saveButton.disabled=true;saveButton.textContent="Збереження...";}
  try{
    const res=await fetch("/api/clients",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
    if(res.status===409&&payload.phone){
      const existing=await findClientByExactPhone(payload.phone);
      if(existing){
        const fullName=((existing.first_name||"")+" "+(existing.last_name||"")).trim();
        selectClient(Number(existing.id),fullName,existing.phone||"");
        closeNewClientModal();
        showToast("Цей номер уже є в базі — вибрано наявного клієнта");
        return;
      }
    }
    if(!res.ok){const error=await res.json();alert(error.detail||"Не вдалося додати клієнта");return;}
    const client=await res.json();
    const fullName=((client.first_name||"")+" "+(client.last_name||"")).trim();
    selectClient(Number(client.id),fullName,client.phone||"");
    clientsDirectory.unshift({...client,visits_count:0,last_visit:""});
    closeNewClientModal();
    showToast(missingDetails.length?"Клієнта додано. Пізніше додайте "+missingDetails.join(" і "):"Клієнта додано до запису");
  }catch(error){
    alert("Не вдалося додати клієнта. Перевірте з'єднання та спробуйте ще раз.");
  }finally{
    if(saveButton){saveButton.disabled=false;saveButton.textContent="Додати клієнта";}
  }
}
function phoneMatchKey(value){
  const digits=String(value||"").replace(/\D/g,"");
  return digits.length>=10?digits.slice(-10):digits;
}
async function findClientByExactPhone(phone){
  const key=phoneMatchKey(phone);
  if(!key)return null;
  try{
    const list=await fetch("/api/clients/search?q="+encodeURIComponent(phone)).then(function(response){return response.json();});
    return (Array.isArray(list)?list:[]).find(function(client){return phoneMatchKey(client.phone)===key;})||null;
  }catch(error){
    return null;
  }
}
async function openClientsModal(){
  ensureClientsDirectoryUi();
  const overlay=document.getElementById("clientsOverlay");
  const search=document.getElementById("clientsSearch");
  if(search)search.value="";
  overlay.classList.remove("hidden");
  const body=document.getElementById("clientsTableBody");
  if(body)body.innerHTML='<tr><td colspan="5" class="clients-empty">Завантаження...</td></tr>';
  try{
    clientsDirectory=await fetch("/api/clients").then(r=>r.json());
    clientsDirectoryLoaded=true;
  }catch(e){
    clientsDirectory=[];
    clientsDirectoryLoaded=false;
    if(body)body.innerHTML='<tr><td colspan="5" class="clients-empty">Не вдалося завантажити клієнтів</td></tr>';
    return;
  }
  renderClientsTable();
  setTimeout(()=>{if(search)search.focus();},50);
}
function closeClientsModal(){
  const overlay=document.getElementById("clientsOverlay");
  if(overlay)overlay.classList.add("hidden");
}
function renderClientsTable(){
  const body=document.getElementById("clientsTableBody");
  if(!body)return;
  const q=(document.getElementById("clientsSearch")||{value:""}).value.trim().toLowerCase();
  const list=clientsDirectory.filter(c=>{
    const hay=[c.first_name||"",c.last_name||"",c.phone||""].join(" ").toLowerCase();
    return !q||hay.includes(q);
  });
  if(!list.length){
    body.innerHTML='<tr><td colspan="5" class="clients-empty">Клієнтів не знайдено</td></tr>';
    return;
  }
  body.innerHTML=list.map(c=>
    '<tr onclick="openClientCardModal('+c.id+')">'
    +'<td>'+escapeHtml(c.last_name||"")+'</td>'
    +'<td>'+escapeHtml(c.first_name||"")+'</td>'
    +'<td>'+escapeHtml(formatPhoneDisplay(c.phone||""))+'</td>'
    +'<td>'+Number(c.visits_count||0)+'</td>'
    +'<td>'+escapeHtml(c.last_visit||"—")+'</td>'
    +'</tr>'
  ).join("");
}
async function openClientCardModal(id){
  ensureClientsDirectoryUi();
  const overlay=document.getElementById("clientCardOverlay");
  const body=document.getElementById("clientCardBody");
  const history=document.getElementById("clientCardHistory");
  if(body)body.innerHTML='<div class="clients-empty">Завантаження...</div>';
  if(history)history.innerHTML="";
  overlay.classList.remove("hidden");
  try{
    const data=await Promise.all([
      fetch("/api/client/"+id).then(r=>r.json()),
      fetch("/api/client/"+id+"/history").then(r=>r.json())
    ]);
    currentClientCard=data[0];
    currentClientHistory=Array.isArray(data[1])?data[1]:[];
    renderClientCard(false);
  }catch(e){
    currentClientCard=null;
    currentClientHistory=[];
    if(body)body.innerHTML='<div class="clients-empty">Не вдалося завантажити картку клієнта</div>';
  }
}
function closeClientCardModal(){
  const overlay=document.getElementById("clientCardOverlay");
  if(overlay)overlay.classList.add("hidden");
}
function renderClientCard(editing){
  if(!currentClientCard)return;
  const c=currentClientCard;
  const title=document.getElementById("clientCardTitle");
  const body=document.getElementById("clientCardBody");
  const history=document.getElementById("clientCardHistory");
  const editBtn=document.getElementById("clientCardEditBtn");
  const saveBtn=document.getElementById("clientCardSaveBtn");
  const fullName=((c.first_name||"")+" "+(c.last_name||"")).trim()||"Картка клієнта";
  if(title)title.textContent=fullName;
  if(editBtn)editBtn.classList.toggle("hidden",editing);
  if(saveBtn)saveBtn.classList.toggle("hidden",!editing);
  if(body){
    if(editing){
      body.innerHTML=
        '<div class="client-card-grid">'
        +clientCardInput("first_name","Ім'я",c.first_name||"")
        +clientCardInput("last_name","Прізвище",c.last_name||"")
        +clientCardInput("phone","Телефон",formatPhoneDisplay(c.phone||""))
        +clientCardInput("birthday","Дата народження",c.birthday||"")
        +'<label class="client-card-field client-card-notes"><span>Нотатки</span><textarea id="cc_notes" rows="4">'+escapeHtml(c.notes||"")+'</textarea></label>'
        +'</div>';
    }else{
      body.innerHTML=
        '<div class="detail-row"><span class="dl">Ім&#39;я</span><span class="dv">'+escapeHtml(c.first_name||"")+'</span></div>'
        +'<div class="detail-row"><span class="dl">Прізвище</span><span class="dv">'+escapeHtml(c.last_name||"")+'</span></div>'
        +'<div class="detail-row"><span class="dl">Телефон</span><span class="dv">'+escapeHtml(formatPhoneDisplay(c.phone||""))+'</span></div>'
        +'<div class="detail-row"><span class="dl">Дата народження</span><span class="dv">'+escapeHtml(c.birthday||"Не вказано")+'</span></div>'
        +'<div class="detail-row"><span class="dl">Нотатки</span><span class="dv">'+escapeHtml(c.notes||"")+'</span></div>';
    }
  }
  if(history){
    const visits=currentClientHistory.slice(0,10);
    if(!visits.length){
      history.innerHTML='<div class="crm-no-visits">Попередніх візитів немає</div>';
    }else{
      history.innerHTML='<table class="client-history-table"><thead><tr><th>Дата</th><th>Послуга</th><th>Тривалість</th></tr></thead><tbody>'
        +visits.map(v=>'<tr><td>'+escapeHtml(v.appt_date||"")+'</td><td>'+escapeHtml(v.service||"")+'</td><td>'+Number(v.duration_min||0)+' хв</td></tr>').join("")
        +'</tbody></table>';
    }
  }
}
function clientCardInput(id,label,value){
  const phoneAttrs=id.endsWith("phone")?' inputmode="tel" oninput="fmtPhone(this)"':'';
  return '<label class="client-card-field"><span>'+label+'</span><input id="cc_'+id+'" value="'+escapeHtml(value)+'"'+phoneAttrs+'></label>';
}
function editClientCard(){renderClientCard(true);}
async function saveClientCard(){
  if(!currentClientCard)return;
  const payload={
    first_name:(document.getElementById("cc_first_name")||{value:""}).value.trim(),
    last_name:(document.getElementById("cc_last_name")||{value:""}).value.trim(),
    phone:(document.getElementById("cc_phone")||{value:""}).value.trim(),
    birthday:(document.getElementById("cc_birthday")||{value:""}).value.trim(),
    notes:(document.getElementById("cc_notes")||{value:""}).value.trim()
  };
  const res=await fetch("/api/client/"+currentClientCard.id,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
  if(!res.ok){alert("Не вдалося зберегти клієнта");return;}
  currentClientCard={...currentClientCard,...payload};
  clientsDirectory=clientsDirectory.map(c=>c.id===currentClientCard.id?{...c,...payload}:c);
  renderClientsTable();
  renderClientCard(false);
}
function escapeHtml(v){
  return String(v).replace(/[&<>"']/g,function(ch){
    return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[ch];
  });
}
ensureClientsDirectoryUi();
if("serviceWorker" in navigator){
  window.addEventListener("load",function(){
    navigator.serviceWorker.register("/static/sw.js",{scope:"/"}).catch(function(){});
  });
}
loadWeek();
// ─── CRM Stage 3: client autocomplete ─────────────────────────────────────
let _clientSearchTimer=null;
let _clientRequestSequence=0;
function onClientInput(){
  selectedClientId=null;
  const q=document.getElementById("fClient").value.trim();
  clearTimeout(_clientSearchTimer);
  if(q.length<2){hideClientSuggestions();return;}
  _clientSearchTimer=setTimeout(function(){searchClients(q);},250);
}
function onPhoneInput(){
  selectedClientId=null;
  const q=document.getElementById("fPhone")?document.getElementById("fPhone").value.trim():"";
  clearTimeout(_clientSearchTimer);
  if(q.length<2){hideClientSuggestions();return;}
  _clientSearchTimer=setTimeout(function(){searchClients(q);},250);
}
function searchClients(q){
  const requestSequence=++_clientRequestSequence;
  fetch("/api/clients/search?q="+encodeURIComponent(q))
  .then(function(r){return r.json();})
  .then(function(list){if(requestSequence===_clientRequestSequence)showClientSuggestions(list);})
  .catch(function(){if(requestSequence===_clientRequestSequence)hideClientSuggestions();});
}
function showRecentClients(){
  const input=document.getElementById("fClient");
  const q=input?input.value.trim():"";
  if(q.length>=2){searchClients(q);return;}
  const requestSequence=++_clientRequestSequence;
  const useCached=clientsDirectoryLoaded;
  const request=useCached?Promise.resolve(clientsDirectory):fetch("/api/clients").then(function(r){return r.json();});
  request.then(function(list){
    if(requestSequence!==_clientRequestSequence)return;
    clientsDirectory=Array.isArray(list)?list:[];
    clientsDirectoryLoaded=true;
    showClientSuggestions(clientsDirectory.slice(0,15));
  }).catch(function(){if(requestSequence===_clientRequestSequence)hideClientSuggestions();});
}
function showClientSuggestions(list){
  var wrap=document.getElementById("clientSuggestWrap");
  if(!wrap)return;
  if(!list||list.length===0){hideClientSuggestions();return;}
  wrap.innerHTML=list.map(function(c,index){
    var fullName=((c.first_name||"")+" "+(c.last_name||"")).trim();
    var phone=formatPhoneDisplay(c.phone||"");
    return '<button type="button" class="client-suggest-item" data-client-index="'+index+'">'
      +'<span class="cs-name">'+escapeHtml(fullName)+'</span>'
      +(phone?'<span class="cs-phone">'+escapeHtml(phone)+'</span>':'')
      +'</button>';
  }).join("");
  wrap.querySelectorAll(".client-suggest-item").forEach(function(item){
    item.addEventListener("click",function(){
      const client=list[Number(item.dataset.clientIndex)];
      if(!client)return;
      const fullName=((client.first_name||"")+" "+(client.last_name||"")).trim();
      selectClient(Number(client.id),fullName,client.phone||"");
    });
  });
  wrap.style.display="block";
}
function hideClientSuggestions(){
  var wrap=document.getElementById("clientSuggestWrap");
  if(wrap)wrap.style.display="none";
}
function selectClient(id,name,phone){
  _clientRequestSequence++;
  selectedClientId=id;
  var fc=document.getElementById("fClient");
  if(fc)fc.value=name;
  var fp=document.getElementById("fPhone");
  if(fp)fp.value=formatPhoneDisplay(phone);
  hideClientSuggestions();
}
document.addEventListener("click",function(e){
  var wrap=document.getElementById("clientSuggestWrap");
  if(wrap&&!wrap.contains(e.target)&&e.target.id!=="fClient"&&e.target.id!=="fPhone"){
    hideClientSuggestions();
  }
});
safeOn("fClient","input",onClientInput);
safeOn("fClient","focus",showRecentClients);
safeOn("fPhone","input",onPhoneInput);
// ──────────────────────────────────────────────────────────────────────────────

function setDur(min){
  document.getElementById("fDuration").value=min;
  document.querySelectorAll(".dur-btn").forEach(b=>{
    b.classList.toggle("active",parseInt(b.textContent)===min||(min===60&&b.textContent==="1 год")||(min===90&&b.textContent==="1.5 год")||(min===120&&b.textContent==="2 год"));
  });
}
function fmtPhone(el){
  el.value=formatPhoneDisplay(el.value);
}
function formatPhoneDisplay(value){
  var original=String(value||"").trim();
  var raw=original.replace(/\D/g,"");
  if(original.startsWith("+")&&!raw.startsWith("38"))return original;
  if(raw.startsWith("380")) raw=raw.slice(2);
  else if(raw.startsWith("38")) raw=raw.slice(2);
  else if(raw.startsWith("80")&&raw.length>=11) raw=raw.slice(1);
  else if(raw.length===9) raw="0"+raw;
  raw=raw.slice(0,10);
  var res="";
  if(raw.length>0) res="+38 ("+raw.slice(0,3);
  if(raw.length>3) res+=") "+raw.slice(3,6);
  if(raw.length>6) res+="-"+raw.slice(6,8);
  if(raw.length>8) res+="-"+raw.slice(8,10);
  return res;
}

// Multi-service appointment picker and catalog management for masters.
function ensureServicePickerUi(serviceRow){
  if(!serviceRow||document.getElementById("servicePicker"))return;
  const select=document.getElementById("fService");
  if(!select)return;
  select.style.display="none";
  const picker=document.createElement("div");
  picker.id="servicePicker";
  picker.className="service-picker";
  picker.innerHTML='<select id="servicePickerSelect" aria-label="Додати процедуру"></select><button type="button" class="service-add-btn" onclick="addSelectedService()">+ Додати</button><button type="button" class="service-manage-btn" onclick="openServiceManager()">⚙ Процедури</button>';
  select.parentNode.insertBefore(picker,select);
  const chips=document.createElement("div");
  chips.id="serviceChips";
  chips.className="service-chips";
  picker.appendChild(chips);
  renderServicePicker();
}

function renderServicePicker(){
  const picker=document.getElementById("servicePicker");
  if(!picker)return;
  const selected=new Set(selectedServiceIds.map(Number));
  const select=document.getElementById("servicePickerSelect");
  if(select){
    const available=services.filter(function(s){return !selected.has(Number(s.id));}).sort(function(a,b){return a.name.localeCompare(b.name,"uk",{sensitivity:"base"});});
    select.innerHTML='<option value="">Оберіть процедуру...</option>'+available.map(function(s){return '<option value="'+s.id+'">'+escapeHtml(s.name)+'</option>';}).join("");
  }
  const chips=document.getElementById("serviceChips");
  if(chips){
    chips.innerHTML=selectedServiceIds.map(function(id){
      const service=services.find(function(s){return Number(s.id)===Number(id);});
      if(!service)return "";
      return '<span class="service-chip">'+escapeHtml(service.name)+'<button type="button" aria-label="Видалити '+escapeHtml(service.name)+'" onclick="removeSelectedService('+Number(id)+')">×</button></span>';
    }).join("");
  }
  const hidden=document.getElementById("fService");
  if(hidden){hidden.value=selectedServiceIds.map(function(id){const s=services.find(function(x){return Number(x.id)===Number(id);});return s?s.name:"";}).filter(Boolean).join(" + ");}
}

function addSelectedService(){
  const select=document.getElementById("servicePickerSelect");
  const id=select&&Number(select.value);
  if(!id||selectedServiceIds.indexOf(id)!==-1)return;
  selectedServiceIds.push(id);
  if(select)select.value="";
  renderServicePicker();
}
function removeSelectedService(id){
  selectedServiceIds=selectedServiceIds.filter(function(value){return Number(value)!==Number(id);});
  renderServicePicker();
}

function ensureMasterServiceUi(){
  const topbar=document.querySelector(".topbar");
  const spacer=document.querySelector(".topbar .spacer");
  if(topbar&&spacer&&!document.getElementById("servicesBtn")){
    const button=document.createElement("button");
    button.id="servicesBtn";button.type="button";button.className="services-btn";button.textContent="⚙ Послуги";
    button.onclick=openServiceManager;
    topbar.insertBefore(button,spacer.nextSibling);
  }
  if(!document.getElementById("serviceManagerOverlay")){
    const overlay=document.createElement("div");
    overlay.id="serviceManagerOverlay";overlay.className="overlay hidden";
    overlay.innerHTML='<div class="modal"><h2>Керування послугами</h2><div id="serviceManagerList" class="service-manager-list"></div><div class="service-picker"><input id="newMasterServiceName" type="text" placeholder="Нова процедура..."><button type="button" class="service-add-btn" onclick="createMasterService()">+ Додати</button></div><div class="modal-footer"><button class="btn" type="button" onclick="closeServiceManager()">Закрити</button></div></div>';
    document.body.appendChild(overlay);
    overlay.addEventListener("click",function(e){if(e.target===overlay)closeServiceManager();});
  }
}
async function openServiceManager(){
  ensureMasterServiceUi();
  document.getElementById("serviceManagerOverlay").classList.remove("hidden");
  await refreshMasterServices();
}
function closeServiceManager(){const el=document.getElementById("serviceManagerOverlay");if(el)el.classList.add("hidden");}
async function refreshMasterServices(){
  const res=await fetch("/api/services");
  if(!res.ok){alert("Не вдалося завантажити послуги");return;}
  services=await res.json();
  updateDatalist();
  const list=document.getElementById("serviceManagerList");
  if(!list)return;
  const sortedServices=services.slice().sort(function(a,b){return a.name.localeCompare(b.name,"uk",{sensitivity:"base"});});
  list.innerHTML=sortedServices.length?sortedServices.map(function(s){return '<div class="service-manager-row"><span>'+escapeHtml(s.name)+'</span><button type="button" onclick="renameMasterService('+s.id+')">✎</button><button type="button" onclick="deleteMasterService('+s.id+')">×</button></div>';}).join(""): '<div style="padding:12px;color:var(--hint)">Послуг ще немає</div>';
}
async function createMasterService(){
  const input=document.getElementById("newMasterServiceName");
  const name=input.value.trim();if(!name)return;
  const res=await fetch("/api/services",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name,sort_order:services.length})});
  if(!res.ok){const e=await res.json();alert(e.detail||"Не вдалося додати послугу");return;}
  input.value="";showToast("Послугу додано");await refreshMasterServices();
}
async function renameMasterService(id){
  const service=services.find(function(s){return Number(s.id)===Number(id);});if(!service)return;
  const name=prompt("Нова назва:",service.name);if(!name||name.trim()===service.name)return;
  const res=await fetch("/api/services/"+id,{method:"PUT",headers:{"Content-Type":"application/json"},body:JSON.stringify({name:name.trim(),sort_order:service.sort_order,price_cents:service.price_cents,duration_min:service.duration_min})});
  if(!res.ok){const e=await res.json();alert(e.detail||"Не вдалося перейменувати послугу");return;}
  showToast("Послугу оновлено");await refreshMasterServices();
}
async function deleteMasterService(id){
  if(!confirm("Видалити послугу з каталогу? Старі записи збережуть її назву."))return;
  const res=await fetch("/api/services/"+id,{method:"DELETE"});
  if(!res.ok){const e=await res.json();alert(e.detail||"Не вдалося видалити послугу");return;}
  removeSelectedService(id);showToast("Послугу видалено");await refreshMasterServices();
}

ensureMasterServiceUi();
