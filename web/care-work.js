(() => {
  const escape = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const examples = [
    ["respiratory_followup", "Экстренная госпитализация", "Shoshilinch yotqizish"],
    ["homilador", "Беременность", "Homiladorlik"],
    ["first_birth_care", "После первых родов", "Birinchi tug‘ruqdan keyin"],
    ["vaccine_child", "Прививка ребёнку", "Bolani emlash"],
    ["vaccine_adult", "Прививка взрослому", "Kattalarni emlash"],
    ["hiv_followup", "Сопровождение при ВИЧ", "OIV bo‘yicha kuzatuv"],
    ["sti_followup", "Наблюдение при ИППП", "JYBI bo‘yicha kuzatuv"]
  ];
  const eventNames = { transport:["Доставка","Olib borish"], admission:["Госпитализация","Yotqizish"], discharge:["Выписка","Uyga chiqarish"] };
  const statuses = {
    scheduled:["Назначена","Rejalashtirilgan"], given:["Выполнена","Bajarilgan"], deferred:["Отложена","Qoldirilgan"],
    cancelled:["Отменено","Bekor qilingan"], rejalashtirilgan:["Запланирован","Rejalashtirilgan"], jarayonda:["Идёт опрос","So‘rov davom etmoqda"],
    tugadi:["Завершён","Yakunlangan"], javobsiz:["Без ответа","Javobsiz"]
  };
  const resourceNames = {
    Encounter:["Эпизод лечения","Davolash epizodi"], Condition:["Диагноз врача","Shifokor tashxisi"],
    ImmunizationRecommendation:["Назначение прививки","Emlash tayinlovi"], Task:["Задача сотрудника","Xodim vazifasi"],
    QuestionnaireResponse:["Ответы пациента","Bemor javoblari"], Observation:["Измерение","O‘lchov"],
    Patient:["Данные пациента","Bemor ma’lumotlari"], Consent:["Согласие","Rozilik"]
  };
  let page = 0;
  async function render({root, api, lang, id, role}) {
    const revision = ++page;
    const tr = (ru, uz) => lang === "uz" ? uz : ru;
    const lookup = (dict, key) => dict[key] ? tr(...dict[key]) : key;
    const when = value => value ? new Intl.DateTimeFormat(lang === "ru" ? "ru-RU" : "uz-UZ", {
      timeZone:"Asia/Tashkent",day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit",hour12:false
    }).format(new Date(value)) : "—";
    const date = value => value ? value.slice(0,10).split("-").reverse().join(".") : "—";
    const testLabel = `<span class="test-label">${tr("Тестовая DMED","Sinov DMED")}</span>`;
    const empty = message => `<p class="empty">${message}</p>`;
    const fresh = () => revision === page && /^#\/care(?:\/|$)/.test(location.hash);
    const showError = err => { const box = root.querySelector(".care-report"); if (box) box.textContent = err.message; };
    function pending(button, fn) {
      button.disabled = true;
      Promise.resolve().then(fn).catch(showError).finally(() => { button.disabled = false; });
    }
    if (!id) {
      root.innerHTML = `<section class="care"><div class="care-lead"><div><h1>${tr("Маршрут пациента","Bemor yo‘li")}</h1>
        <p>${tr("Выберите пациента, чтобы увидеть путь из стационара домой, план обзвона и записи в медкарте.","Bemorni tanlab, shifoxonadan uygacha yo‘lini, qo‘ng‘iroqlarini va tibbiy yozuvlarini ko‘ring.")}</p></div>${testLabel}</div>
        <div class="care-head"><section class="card"><h2>${tr("Найти в реестре","Reyestrdan topish")}</h2>
        <form class="care-search"><input aria-label="${tr("Имя пациента","Bemor ismi")}" type="search" maxlength="120" placeholder="${tr("Фамилия или имя","Familiya yoki ism")}">
        <button class="btn">${tr("Найти","Topish")}</button></form><div class="care-results"></div></section>
        ${role !== "hamshira" ? `<section class="card"><h2>${tr("Учебные случаи","O‘quv holatlari")}</h2><div class="care-examples">${examples.map(([key,ru,uz]) => `<button type="button" data-case="${key}">${tr(ru,uz)}</button>`).join("")}</div></section>` : ""}</div>
        <div class="care-report" role="status"></div></section>`;
      const form = root.querySelector(".care-search");
      async function search() {
        const q = form.elements[0].value.trim();
        const patients = await api("/patients?limit=6&q="+encodeURIComponent(q));
        if (!fresh()) return;
        root.querySelector(".care-results").innerHTML = patients.map(p => `<a class="care-result" href="#/care/${Number(p.id)}">${escape(p.name)}</a>`).join("") || empty(tr("Совпадений нет.","Mos keladigan bemor yo‘q."));
      }
      form.onsubmit = e => { e.preventDefault(); pending(form.querySelector("button"),search); };
      for (const button of root.querySelectorAll("[data-case]")) button.onclick = () => pending(button, async () => {
        const d = await api("/care/examples/"+button.dataset.case+"?lang="+lang,{method:"POST"});
        if (fresh()) location.hash = "#/care/"+d.patient_id;
      });
      await search();
      return;
    }
    if (!/^\d+$/.test(id)) throw new Error(tr("Неверная карта","Karta xato"));
    const base = "/care/patients/"+id;
    const d = await api(base);
    if (!fresh()) return;
    const cp = d.profile;
    const link = call => {
      if (!call) return "";
      const actionable = ["rejalashtirilgan","jarayonda"].includes(call.status);
      return `<div class="small">${escape(call.title?.[lang] || call.scenario)} · ${when(call.at)} · ${escape(lookup(statuses,call.status))}
        ${actionable ? `<a class="btn ghost sm" target="_blank" rel="noopener" href="${escape(call.url)}">${tr("Открыть опрос","So‘rovni ochish")} ↗</a>` : ""}</div>`;
    };
    const input = (name,label,type="text",value="",attrs="") => `<label>${label}<input type="${type}" name="${name}" value="${escape(value)}" ${attrs}></label>`;
    const check = (name,label,checked) => `<label class="check wide"><input type="checkbox" name="${name}" ${checked?"checked":""}>${label}</label>`;
    const btn = caption => `<button class="btn wide" type="submit">${caption}</button>`;
    const fieldset = (name,title,fields) => `<details class="care-details"><summary>${title}</summary><form class="care-form" data-form="${name}">${fields}</form></details>`;
    const editor = d.can_edit ? `<section class="card"><h2>${tr("Внести в учебную карту","Sinov kartasiga kiritish")}</h2>
      ${fieldset("event",tr("Доставка, госпитализация или выписка","Olib borish, yotqizish yoki uyga chiqarish"),
        `<label>${tr("Событие","Hodisa")}<select name="kind">${["discharge","transport","admission"].map(v=>`<option value="${v}">${lookup(eventNames,v)}</option>`).join("")}</select></label>`+
        input("occurred_at",tr("Дата и время, Ташкент","Sana va vaqt, Toshkent"),"datetime-local",new Date(Date.now()+5*3600000).toISOString().slice(0,16),"required")+
        input("hospital",tr("Больница или отделение","Shifoxona yoki bo‘lim"),"text","","required maxlength=140")+
        input("episode",tr("Номер эпизода","Epizod raqami"),"text",d.events[0]?.episode || "","required maxlength=64")+
        input("transport",tr("Бригада или транспорт","Brigada yoki transport"),"text","","maxlength=120")+
        input("doctor",tr("Кто передал сведения","Ma’lumotni bergan xodim"),"text","","maxlength=120")+
        input("reason",tr("Причина / заключение","Sabab / xulosa"),"text","","maxlength=240")+
        input("icd",tr("Подтверждённый код МКБ-10","Tasdiqlangan XKT-10 kodi"),"text",cp.icd || "","maxlength=12")+
        btn(tr("Принять событие","Hodisani qabul qilish")))}
      ${fieldset("vaccine",tr("Назначить прививку","Emlashni tayinlash"),
        input("name",tr("Прививка по назначению врача","Shifokor tayinlagan emlash"),"text","","required maxlength=90")+
        input("age_months",tr("Возраст по плану, месяцев","Rejadagi yosh, oy"),"number","","min=0 max=1440")+
        input("due",tr("Или установленная дата","Yoki belgilangan sana"),"date")+
        btn(tr("Записать назначение","Tayinlovni saqlash")))}
      ${fieldset("context",tr("Профиль и согласия","Profil va roziliklar"),
        input("birthday",tr("Дата рождения","Tug‘ilgan sana"),"date",cp.birthday)+
        input("icd",tr("Подтверждённый код МКБ-10","Tasdiqlangan XKT-10 kodi"),"text",cp.icd || "","maxlength=12")+
        input("guardian_id",tr("ID представителя из реестра","Vakilning reyestr ID raqami"),"number",cp.guardian_id || "","min=1")+
        (d.kind==="tuqqan" ? check("first_birth",tr("Это первые роды","Bu birinchi tug‘ruq"),cp.first_birth) : "")+
        check("guardian_consent",tr("Представитель подтвердил участие","Vakil ishtirokni tasdiqladi"),cp.guardian_consent)+
        check("private_consent",tr("Пациент разрешил конфиденциальный опрос","Bemor maxfiy so‘rovga rozilik berdi"),cp.private_consent)+btn(tr("Сохранить профиль","Profilni saqlash")))}</section>` : "";
    const events = d.events.map(e=>`<article class="care-event"><div class="small">${when(e.when)} · ${escape(e.episode)}</div>
      <h3>${lookup(eventNames,e.kind)} · ${escape(e.hospital)}</h3>
      <div>${[e.transport,e.reason,e.icd,e.doctor].filter(Boolean).map(escape).join(" · ")}</div>${link(e.call)}</article>`).join("");
    const plans = d.vaccines.map((v,i)=>`<article class="care-plan"><h3>${escape(v.name)}</h3><div>${date(v.due)} · ${lookup(statuses,v.status)}</div>
      <span class="small">${tr("Кому позвонить","Qo‘ng‘iroq oluvchi")}: ${escape(v.recipient || tr("Ожидается подтверждение","Tasdiqlash kutilmoqda"))}</span>${link(v.call)}
      ${d.can_edit && v.status==="scheduled" ? `<div class="row-b mt"><button class="btn sm ghost" data-plan="${i}" data-status="given">${tr("Подтвердить выполнение","Bajarilganini tasdiqlash")}</button>
        <button class="btn sm ghost" data-plan="${i}" data-status="deferred">${tr("Отложить","Qoldirish")}</button></div>`:""}</article>`).join("");
    const records = d.records.map(r=>{
      const items = r.resource.item || [];
      const answers = items.map(q => {
        const a = q.answer?.[0] || {};
        const value = "valueBoolean" in a ? (a.valueBoolean ? tr("Да","Ha") : tr("Нет","Yo‘q")) : a.valueDecimal ?? a.valueString ?? "—";
        return `<span class="care-question">${escape(q.text)} <b>${escape(value)}</b></span>`;
      }).join("");
      return `<details class="care-record"><summary>${escape(lookup(resourceNames,r.type))} · ${r.direction==="in"?tr("из тестовой DMED","sinov DMEDdan"):tr("в тестовую DMED","sinov DMEDga")}</summary>
        <div class="small">${when(r.at)}</div>${answers}<details><summary>FHIR JSON</summary><pre>${escape(JSON.stringify(r.resource,null,2))}</pre></details></details>`;
    }).join("");
    root.innerHTML = `<section class="care"><a href="#/care" class="small">← ${tr("Все маршруты","Barcha yo‘llar")}</a>
      <div class="care-lead"><div><h1>${escape(d.name)}</h1><div class="care-meta"><span>${tr("Лечащий врач","Davolovchi shifokor")} · ${escape(d.doctor || "—")}</span>
      ${cp.birthday ? `<span>${tr("Дата рождения","Tug‘ilgan sana")} · ${date(cp.birthday)}</span>`:""}${cp.icd ? `<span>${tr("МКБ-10","XKT-10")} · ${escape(cp.icd)}</span>`:""}</div></div>${testLabel}</div>
      <div class="care-columns"><div class="care-stack"><section class="card"><h2>${tr("Перемещения и выписка","Harakatlanish va uyga chiqarish")} <span class="small">· ${tr("время Ташкента","Toshkent vaqti")}</span></h2>
      ${events || empty(tr("События из стационара пока не поступали.","Shifoxonadan hodisalar kelmagan."))}</section>
      <section class="card"><h2>${tr("План вакцинации","Emlash rejasi")}</h2>${plans || empty(tr("Назначений в карте пока нет.","Kartada tayinlov yo‘q."))}</section>
      <section class="card"><h2>${tr("Тестовая медкарта DMED","DMED sinov tibbiy kartasi")}</h2>${records || empty(tr("Записи появятся после первого события или завершённого опроса.","Birinchi hodisa yoki so‘rovdan keyin yozuvlar chiqadi."))}</section></div>
      <div class="care-stack"><section class="card"><h2>${tr("Персональные опросы","Shaxsiy so‘rovlar")}</h2>
      ${d.calls.map(c=>`<div class="care-plan">${link(c)}</div>`).join("") || empty(tr("Звонков пока нет.","Qo‘ng‘iroqlar yo‘q."))}
      ${d.can_edit && d.eligible.some(s=>s.id!=="tashrif_tasdiq") ? `<form data-form="call" class="care-form"><label class="wide">${tr("Подходит этому пациенту","Shu bemorga mos")}
      <select name="scenario">${d.eligible.filter(s=>s.id!=="tashrif_tasdiq").map(s=>`<option value="${escape(s.id)}">${escape(s.title[lang])}</option>`).join("")}</select></label>${btn(tr("Назначить опрос","So‘rov tayinlash"))}</form>`:""}
      <a class="btn ghost sm" href="#/bemor/${id}">${tr("Полная карта пациента","Bemorning to‘liq kartasi")}</a></section>${editor}
      <div class="care-report" role="status"></div></div></div></section>`;
    async function reload() { if (fresh()) await render({root,api,lang,id,role}); }
    for (const form of root.querySelectorAll("[data-form]")) {
      const key=crypto.randomUUID();
      form.onsubmit = e => {
        e.preventDefault();
        pending(form.querySelector("button"),async()=>{
          const fields=Object.fromEntries(new FormData(form));
          switch (form.dataset.form) {
            case "event":
              await api(base+"/events",{json:{...fields,event_id:key,occurred_at:fields.occurred_at+":00+05:00",icd:fields.icd.trim().toUpperCase()}}); break;
            case "context":
              await api(base+"/context",{method:"PUT",json:{...fields,birthday:fields.birthday || null,icd:fields.icd.trim().toUpperCase(),
                guardian_id:Number(fields.guardian_id)||null,first_birth:!!fields.first_birth,private_consent:!!fields.private_consent,guardian_consent:!!fields.guardian_consent}}); break;
            case "vaccine":
              if (Boolean(fields.due)===Boolean(fields.age_months)) throw Error(tr("Укажите дату или возраст в месяцах.","Sanani yoki oylardagi yoshni kiriting."));
              await api(base+"/vaccination",{method:"PUT",json:{plan_id:key,name:fields.name,due:fields.due||null,age_months:fields.age_months===""?null:Number(fields.age_months)}}); break;
            case "call": await api("/patients/"+id+"/calls",{json:{scenario:fields.scenario,lang}}); break;
          }
          await reload();
        });
      };
    }
    for (const button of root.querySelectorAll("[data-plan]")) button.onclick=()=>pending(button,async()=>{
      const plan=d.vaccines[Number(button.dataset.plan)];
      await api(base+"/vaccination",{method:"PUT",json:{plan_id:plan.id,name:plan.name,due:plan.due,status:button.dataset.status}});
      await reload();
    });
  }
  window.MehrCare = {render};
})();
