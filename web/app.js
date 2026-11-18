/* Nigoh web app: registry, patient card, voice input with offline queue, tasks, AI calls. No build step. */
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const S = {
    lang: (new URLSearchParams(location.search).get("lang") || localStorage.lang || "ru") === "uz" ? "uz" : "ru",
    role: localStorage.role || "rahbar",
    meta: null,
    patientPage: 1,
    filter: { zone: "", kind: "", q: "", silent: 0, group: "", vax: 0, hospital: 0 },
    timers: [],
  };
  const li = () => (S.lang === "ru" ? 1 : 0);
  const t = (k) => (window.I18N[k] || [k, k])[li()];
  const L = (o) => (o ? o[S.lang] || o.uz : "");
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const zb = (z) => `<span class="badge z-${z}">${t("z" + z)}</span>`;

  async function api(path, opt = {}) {
    if (opt.json) {
      opt.method = opt.method || "POST";
      opt.headers = { "Content-Type": "application/json" };
      opt.body = JSON.stringify(opt.json);
    }
    opt.headers = { ...(opt.headers || {}), "X-Role": S.role };
    const r = await fetch("/api" + path, { credentials: "same-origin", ...opt });
    const build = r.headers.get("X-Nigoh-Build");
    if (build && S.build && build !== S.build) S.stale = true; // the site was updated while this tab was open
    if (build && !S.build) S.build = build;
    if (r.status === 401) {
      showLogin();
      throw new Error("auth");
    }
    if (r.status === 403) throw new Error(t("forbidden"));
    if (!r.ok) throw new Error((await r.text()).slice(0, 200) || r.status);
    return r.json();
  }
  // What the signed-in role may do; the server enforces the same rules.
  const can = {
    reset: () => S.role === "rahbar",
    lab: () => S.role === "rahbar" || S.role === "mutaxassis",
    close: (x) =>
      S.role === "rahbar" || (S.role === x.role && !(S.role === "shifokor" && S.me?.doctor && x.patient?.doctor && x.patient.doctor !== S.me.doctor)),
  };
  // One refresh timer per screen. A screen redraws itself (a filter, a button, the timer's own tick), and every
  // redraw used to add a timer on top of the old ones: their number doubled on each tick, and a tab left open
  // for a few minutes sent hundreds of requests a second. The timer is now replaced, a tick is skipped while
  // the previous one is still loading, and a tab nobody is looking at does not ask at all.
  function refreshEvery(ms, redraw, idle = () => true) {
    S.timers.forEach(clearInterval);
    let busy = false;
    S.timers = [
      setInterval(async () => {
        if (busy || document.hidden || document.querySelector(".modal") || !idle()) return;
        if (S.stale) return location.reload(); // pick up the new version at a quiet moment
        busy = true;
        try {
          await redraw();
        } catch {
          /* the next tick tries again */
        } finally {
          busy = false;
        }
      }, ms),
    ];
  }
  function toast(msg, ms = 3200) {
    document.querySelectorAll(".toast").forEach((e) => e.remove());
    const d = document.createElement("div");
    d.className = "toast";
    d.textContent = msg;
    document.body.appendChild(d);
    setTimeout(() => d.remove(), ms);
  }
  function modal(html, cls = "") {
    closeModal();
    const m = document.createElement("div");
    m.className = "modal";
    m.innerHTML = `<div class="card ${cls}">${html}</div>`;
    m.addEventListener("click", (e) => {
      if (e.target === m || e.target.dataset.close !== undefined) closeModal();
    });
    document.body.appendChild(m);
  }
  const closeModal = () => document.querySelectorAll(".modal").forEach((e) => e.remove());
  const ago = (iso) => {
    if (!iso) return "—";
    const d = Math.floor((Date.now() - new Date(iso)) / 864e5);
    return d <= 0 ? t("today") : `${d} ${t("days_ago")}`;
  };
  const dt = (iso) =>
    iso
      ? new Date(iso).toLocaleString(S.lang === "ru" ? "ru-RU" : "uz-UZ", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
      : "—";
  function timer(due, status) {
    if (status !== "ochiq") return "";
    const ms = new Date(due) - Date.now(),
      a = Math.abs(ms),
      h = Math.floor(a / 36e5),
      m = Math.floor((a % 36e5) / 6e4);
    return `<span class="timer ${ms < 0 ? "late" : "ok"}">${h} ${t("hour")} ${m} ${t("min")} ${ms < 0 ? "— " + t("late") : t("left")}</span>`;
  }
  const childAge = (p) => {
    const d = Math.max(0, Math.floor((Date.now() - new Date(p.born_at)) / 864e5));
    return d < 31 ? `${d} ${t("age_days")}` : d < 731 ? `${Math.floor(d / 30.44)} ${t("age_m")}` : `${Math.floor(d / 365.25)} ${t("age_y")}`;
  };
  const kindLabel = (p) =>
    t(p.kind || "boshqa") +
    (p.kind === "homilador" && p.weeks ? `, ${p.weeks} ${t("weeks")}` : "") +
    ((p.kind === "chaqaloq" || p.kind === "bola") && p.born_at ? `, ${childAge(p)}` : "");
  // The marks a patient carries: dispensary groups (a confidential one in red), a stay in a hospital,
  // a vaccination that has come due. Which confidential group it is, the server tells only to those who may know.
  const marksOf = (p) =>
    (p.marks || []).map((m) => `<span class="badge mark ${m.secret ? "z-red" : "z-info"}">${esc(L(m))}</span>`).join("") +
    ((p.marks || []).length ? `<span class="badge mark ${p.private_consent ? "z-green" : "z-yellow"}">${t(p.private_consent ? "pc_yes" : "pc_no")}</span>` : "") +
    (p.in_hospital ? `<span class="badge mark z-red">${t("b_hospital")}</span>` : "") +
    (p.vax ? `<span class="badge mark ${p.vax === "overdue" ? "z-red" : "z-yellow"}">${t(p.vax === "overdue" ? "b_vax_over" : "b_vax_due")}</span>` : "");
  const stayRow = (s, withP) =>
    `<div><span class="badge ${s.discharged_at ? "z-green" : s.emergency ? "z-red" : "z-yellow"}">${t(s.discharged_at ? "stay_out" : s.emergency ? "stay_emerg" : "stay_plan")}</span>
      ${withP ? `<a href="#/bemor/${s.patient.id}"><b>${esc(s.patient.name)}</b></a> · ` : ""}<b>${esc(ruText(s.hospital) || "—")}</b>
      <div class="small">${t("stay_since")}: ${dt(s.admitted_at)}${s.discharged_at ? ` · ${t("stay_until")}: ${dt(s.discharged_at)}` : ""}${s.brought_by ? ` · ${t("stay_by")}: ${esc(ruText(s.brought_by))}` : ""}</div>
      ${s.reason ? `<div class="small">${t("stay_reason")}: ${esc(ruText(s.reason))}</div>` : ""}${s.diagnosis || s.icd10 ? `<div class="small">${t("stay_dx")}: <b>${esc([s.icd10, ruText(s.diagnosis)].filter(Boolean).join(" · "))}</b></div>` : ""}
      ${s.advice ? `<div class="quote">${esc(ruText(s.advice))}</div>` : ""}</div>`;
  const reasonText = (r) => (r ? `${esc(r[S.lang] || r.uz)} ${esc(ruText(r.value || ""))}` : "—");

  /* ---------- shell ---------- */
  const icon = name => `<svg class="ui-icon" aria-hidden="true" focusable="false"><use href="/brand/navigation.svg#${name}"></use></svg>`;
  const brand = '<a class="logo" href="/#/" aria-label="Mehr AI"><img src="/brand/mehr-wave-blue.svg" alt="" width="33" height="33"><span>Mehr AI</span></a>';
  const languageControl = () => `<mehr-language value="${S.lang}"></mehr-language>`;
  function connectLanguage(redraw) {
    $("#top mehr-language").addEventListener("mehr-language-change", e => {
      S.lang = e.detail;
      document.documentElement.lang = S.lang;
      redraw();
    });
  }
  function accountLabel(account) {
    return account?.username === "rahbar" && account.role === "rahbar" ? t("r_rahbar") : account?.username;
  }
  function identity(account) {
    const stored = account?.name?.trim() || "";
    const lead = account?.role === "rahbar" && account?.username === "rahbar" &&
      ["","rahbar","Tuman tibbiyot birlashmasi rahbari","Dilnoza Rahimova","Дилноза Рахимова"].includes(stored);
    const name = lead ? (S.lang === "ru" ? "Дилноза Рахимова" : "Dilnoza Rahimova") : stored || accountLabel(account) || t("profile");
    const parts = name.split(/\s+/);
    return {name, lead, first:lead || account?.role === "rahbar" ? parts[0] : (account?.doctor || name),
      initials:(parts[0][0] + (parts.length>1 ? parts.at(-1)[0] : "")).toLocaleUpperCase()};
  }
  function avatar(person) {
    return `<span class="staff-avatar${person.lead ? " staff-photo" : ""}" aria-hidden="true">${person.lead ? "" : esc(person.initials)}</span>`;
  }
  function shell() {
    const routeName = (location.hash || "#/").split("/")[1] || "";
    const active = routeName === "bemor" ? "" : routeName;
    const tab = (path,key,pict,short=key) => `<a href="#/${path}" class="${active===path?"on":""}" ${active===path?'aria-current="page"':""} aria-label="${t(key)}" title="${t(key)}">
      ${icon(pict)}<span class="nav-full">${t(key)}</span><span class="nav-short" aria-hidden="true">${t(short)}</span></a>`;
    const person = identity(S.me);
    $("#top").innerHTML = `${brand}<span class="sp"></span>${languageControl()}
      <button id="me" class="staff-profile" type="button" aria-haspopup="dialog" title="${t("profile")}" aria-label="${t("profile")} · ${esc(person.name)}">
        <span class="staff-copy"><strong><span class="staff-hello">${t("greeting")}, </span>${esc(person.first)}</strong><small>${t("r_" + S.role)}</small></span>${avatar(person)}</button>`;
    $("#nav").setAttribute("aria-label",t("nav_sections"));
    $("#nav").innerHTML = `<div id="nav-items">${tab("","nav_home","registry")}${tab("care","nav_care","route","nav_care_short")}${tab("ovoz","nav_voice","mic","nav_voice_short")}${tab("vazifalar","nav_tasks","tasks")}${tab("qongiroqlar","nav_calls","phone","nav_calls_short")}${can.lab() ? tab("dmed","nav_dmed","exchange") : ""}</div>
      <button type="button" id="rail-switch" aria-controls="nav-items">${icon("panel")}<span></span></button>`;
    const toggle = $("#rail-switch");
    function compact(value) {
      document.body.classList.toggle("rail-compact",value);
      toggle.setAttribute("aria-expanded",String(!value));
      const label=t(value ? "nav_expand" : "nav_collapse");
      toggle.title=label;
      toggle.setAttribute("aria-label",label);
      toggle.querySelector("span").textContent=label;
    }
    compact(localStorage.getItem("mehr.rail.compact")==="1");
    toggle.onclick = () => {
      const next=!document.body.classList.contains("rail-compact");
      compact(next);localStorage.setItem("mehr.rail.compact",next?"1":"0");
    };
    $("#me").onclick = profile;
    connectLanguage(route);
  }
  async function profile() {
    const me = (S.me = await api("/me")), tg = me.telegram;
    const person=identity(me);
    const roles=["rahbar","mutaxassis","shifokor","hamshira"];
    modal(`<div class="profile-heading">${avatar(person)}<div><h2 id="profile-title">${esc(person.name)}</h2><p>${t("r_"+me.role)}</p></div></div>
      <div class="profile-account"><span>${t("account")}</span><strong>${esc(accountLabel(me))}</strong></div>
      ${!S.meta.auth ? `<label class="mt" for="role">${t("role")}</label><select id="role">${roles.map(r=>`<option value="${r}" ${r===S.role?"selected":""}>${t("r_"+r)}</option>`).join("")}</select>` : ""}
      ${tg?.enabled && (tg.linked || tg.link) ? `<h3 class="mt">${t("tg_h")}</h3><p>${tg.linked
        ? `<span class="badge z-green">${t("tg_on")}</span>`
        : `<a class="btn sm" target="_blank" rel="noopener" href="${esc(tg.link)}">${t("tg_link")}</a>`}</p>` : ""}
      <h3 class="mt">${t("pw_h")}</h3><label for="po">${t("pw_old")}</label><input id="po" type="password" autocomplete="current-password"><label class="mt" for="pn">${t("pw_new")}</label><input id="pn" type="password" autocomplete="new-password">
      <div class="row-b mt"><button class="btn" id="psave">${t("save")}</button><button class="btn ghost" id="pout">${t("logout")}</button><button class="btn ghost" data-close>${t("close")}</button></div>
      ${can.reset() ? `<div class="profile-reset"><h3>${t("reset_h")}</h3><p class="small">${t("reset_note")}</p><button type="button" class="btn ghost" id="preset">${t("reset")}</button></div>` : ""}`);
    const dialog=$(".modal .card");
    dialog.classList.add("profile-card");
    dialog.setAttribute("role","dialog"); dialog.setAttribute("aria-modal","true"); dialog.setAttribute("aria-labelledby","profile-title");
    dialog.tabIndex=-1;dialog.focus();
    dialog.addEventListener("keydown",e=>{
      if(e.key==="Escape"){closeModal();$("#me")?.focus();}
      if(e.key==="Tab"){
        const available=dialog.querySelectorAll("button,a[href],input,select");
        const first=available[0],last=available[available.length-1];
        if(e.shiftKey && (document.activeElement===first || document.activeElement===dialog)){e.preventDefault();last.focus();}
        else if(!e.shiftKey && document.activeElement===last){e.preventDefault();first.focus();}
      }
    });
    dialog.querySelector("[data-close]").onclick=()=>{closeModal();$("#me")?.focus();};
    if ($("#role")) $("#role").onchange=async e=>{
      S.role=localStorage.role=e.target.value; S.me=await api("/me"); S.patientPage=1; closeModal(); await route();
    };
    $("#psave").onclick = async () => {
      try {
        await api("/me/password", { json: { old: $("#po").value, new: $("#pn").value } });
        toast(t("pw_ok"));
        closeModal();
      } catch {
        toast(t("wrong"));
      }
    };
    $("#pout").onclick = async () => {
      await fetch("/api/logout", { method: "POST" });
      closeModal();
      showLogin();
    };
    // the head puts the demonstration back to its starting state before each showing
    if ($("#preset"))
      $("#preset").onclick = async (e) => {
        if (!confirm(t("sure"))) return;
        const b = e.currentTarget;
        b.disabled = true;
        b.textContent = t("reset_wait");
        try {
          await api("/demo/reset", { method: "POST" });
          toast(t("reset_ok"));
          closeModal();
          S.patientPage = 1;
          await route();
        } catch (err) {
          b.disabled = false;
          b.textContent = t("reset");
          toast(err.message, 5000);
        }
      };
  }
  function showLogin() {
    voiceStudio.reset();
    S.me = null;
    S.timers.forEach(clearInterval);
    S.timers = [];
    closeModal();
    $("#nav").innerHTML = "";
    registryVersion++;
    document.body.classList.remove("rail-compact");
    $("#top").innerHTML = `${brand}<span class="sp"></span>${languageControl()}`;
    connectLanguage(showLogin);
    const accounts = S.meta?.accounts || [],
      last = localStorage.account || "";
    // a real form: the browser can save the password, Enter submits, the phone keyboard does not capitalise
    $("#app").innerHTML = `<form class="card login" id="lf" novalidate><h2>${t("login_h")}</h2><p class="small">${t("tagline")}</p>
      <label for="un">${t("account")}</label>${
        accounts.length
          ? `<select id="un" name="username" autocomplete="username">${accounts.map((a) => `<option value="${esc(a.username)}" ${a.username === last ? "selected" : ""}>${esc(identity(a).name)} (${esc(accountLabel(a))})</option>`).join("")}</select>`
          : `<input id="un" name="username" type="text" autocomplete="username" autocapitalize="none" autocorrect="off" spellcheck="false" value="${esc(last)}">`
      }
      <label class="mt" for="pw">${t("password")}</label>
      <div class="pwrow"><input id="pw" name="password" type="password" autocomplete="current-password" autocapitalize="none" autocorrect="off" spellcheck="false"><button type="button" class="btn ghost sm" id="eye">${t("pw_show")}</button></div>
      <p class="err" id="lerr" role="alert" hidden></p>
      <div class="mt"><button class="btn" id="go" type="submit">${t("enter")}</button></div></form>`;
    const fail = (key) => {
      $("#lerr").textContent = t(key);
      $("#lerr").hidden = false;
    };
    $("#eye").onclick = () => {
      const shown = $("#pw").type === "text";
      $("#pw").type = shown ? "password" : "text";
      $("#eye").textContent = t(shown ? "pw_show" : "pw_hide");
      $("#pw").focus();
    };
    $("#lf").onsubmit = async (e) => {
      e.preventDefault();
      if ($("#go").disabled) return;
      if (!$("#pw").value.trim()) return fail("pw_empty");
      $("#go").disabled = true;
      $("#lerr").hidden = true;
      let status = 0;
      try {
        const r = await fetch("/api/login", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username: $("#un").value, password: $("#pw").value }),
        });
        status = r.status;
      } catch {
        status = 0; // no connection
      }
      if (status === 200) {
        localStorage.account = $("#un").value;
        return boot();
      }
      $("#go").disabled = false;
      fail(status === 401 ? "wrong" : status === 429 ? "too_many" : "login_down");
      if (status === 401) $("#pw").select();
    };
    $("#pw").focus();
  }

  /* ---------- registry ---------- */
  const patientsPerPage = 10;
  let registryVersion = 0;
  document.addEventListener("pointerdown",e=>{
    const extra=document.querySelector("#extra-filter[open]");
    if(extra && !extra.contains(e.target)) extra.open=false;
  });
  function registryFilters(f) {
    const select = (name,label,values) => `<label class="registry-filter"><span>${t(label)}</span><select id="filter-${name}" data-filter="${name}">
      ${values.map(([value,key])=>`<option value="${value}" ${f[name]===value?"selected":""}>${t(key)}</option>`).join("")}</select></label>`;
    const extra=[["vax","chip_vax"],["group","chip_disp"],["hospital","chip_hosp"]];
    const active=extra.filter(([key])=>Boolean(f[key]));
    const label=active.length===0 ? t("filter_any") : active.length===1 ? t(active[0][1]) : t("filter_selected")+" · "+active.length;
    return `<div class="registry-filters">
      ${select("zone","th_zone",[["","filter_zone_all"],["red","zred"],["yellow","zyellow"],["green","zgreen"]])}
      ${select("kind","patients_filter",[["","filter_kind_all"],["homilador","homilador"],["tuqqan","tuqqan"],["chaqaloq","chaqaloq"],["bola","bola"]])}
      <div class="registry-filter"><span id="extra-label">${t("filter_others")}</span><details id="extra-filter">
        <summary id="filter-extra" aria-labelledby="extra-label extra-value"><span id="extra-value">${label}</span></summary><div class="extra-options" role="group" aria-labelledby="extra-label">
        ${extra.map(([key,title])=>`<label><input type="checkbox" data-extra="${key}" ${f[key]?"checked":""}><span>${t(title)}</span></label>`).join("")}
        <button type="button" class="btn ghost sm" id="apply-extra">${t("filter_done")}</button></div></details></div></div>
      ${f.silent ? `<span class="badge z-yellow">${t("k_silent")}</span>` : ""}${Object.values(f).some(Boolean) ? `<button type="button" class="registry-reset">${t("filter_clear")}</button>` : ""}`;
  }
  function registryPager(result) {
    const {page,pages,size,total}=result;
    const pageButton=(n,contents,tip,disabled=false,current=false)=>`<button type="button" data-pg="${n}" aria-label="${tip}" ${disabled?"disabled":""} ${current?'aria-current="page"':""}>${contents}</button>`;
    const shown=new Set([1,pages,page-1,page,page+1]);
    if(page<=2)shown.add(3);
    if(page>=pages-1)shown.add(pages-2);
    let previous=0,numbers="";
    for(const n of [...shown].filter(n=>n>=1 && n<=pages).sort((a,b)=>a-b)){
      if(previous && n-previous===2)numbers+=pageButton(n-1,n-1,t("page_no")+" "+(n-1));
      if(previous && n-previous>2)numbers+='<span class="pager-gap" aria-hidden="true">…</span>';
      numbers+=pageButton(n,n,t("page_no")+" "+n,false,n===page);previous=n;
    }
    const start=total ? (page-1)*size+1 : 0;
    return `<nav class="registry-pager" aria-label="${t("patient_pages")}"><span class="pager-range" aria-live="polite">${start}–${Math.min(page*size,total)} ${t("page_of")} ${total}</span>
      <div class="pager-controls">${pageButton(page-1,icon("chevron-left"),t("page_previous"),page<=1)}<span class="page-numbers">${numbers}</span>
      <span class="pager-mobile">${page} / ${pages}</span>${pageButton(page+1,icon("chevron-right"),t("page_next"),page>=pages)}</div></nav>`;
  }
  async function home({ focus = "", listTop = false, openExtra = false } = {}) {
    const version=++registryVersion;
    const query=new URLSearchParams({...S.filter,page:S.patientPage,limit:patientsPerPage});
    const [d, result] = await Promise.all([api("/dashboard"), api("/patients?" + query)]);
    if(version!==registryVersion) return;
    const restoreExtra = !!document.querySelector("#extra-filter[open]");
    const activeField = document.activeElement;
    const focusId = !listTop && activeField?.closest("#registry-list") && activeField.id ? activeField.id : focus;
    const searchSelection = activeField?.id === "q" ? [activeField.selectionStart,activeField.selectionEnd] : null;
    S.patientPage=result.page;
    const ps=result.items;
    const kpi = (cls, value, label, filter) => {
      const body = `<b>${value ?? "—"}</b><span>${label}</span>`;
      return filter ? `<button type="button" class="card kpi ${cls}" data-f='${filter}'>${body}</button>` : `<div class="card kpi ${cls}">${body}</div>`;
    };
    const f = S.filter;
    $("#app").innerHTML = `
      <header class="registry-lead"><div><h1>${t("registry_title")}</h1><p>${t("registry_hint")}</p></div></header>
      <div class="registry-kpis">
        ${kpi("red", d.zones.red, t("red"), '{"zone":"red"}')}
        ${kpi("yellow", d.tasks_overdue, t("k_overdue"), '{"go":"vazifalar"}')}
        ${kpi("", d.in_hospital, t("k_hospital"), '{"hospital":1}')}
        ${kpi("", d.vaccines.overdue + d.vaccines.due, t("k_vax"), '{"vax":1}')}
      </div>
      <details class="registry-more" ${sessionStorage.moreKpis==="true" ? "open" : ""}><summary>${t("registry_more")}</summary><div class="registry-kpis">
        ${kpi("yellow", d.zones.yellow, t("yellow"), '{"zone":"yellow"}')}${kpi("green", d.zones.green, t("green"), '{"zone":"green"}')}
        ${kpi("plain", d.closed_in_time_pct == null ? "—" : d.closed_in_time_pct + "%", t("k_intime"))}
        ${kpi("", d.silent, t("k_silent"), '{"silent":1}')}${kpi("plain", d.verified, t("k_verified"))}${kpi("plain", d.mismatch, t("k_mismatch"))}
        ${kpi("plain", d.vaccines.in_time_pct == null ? "—" : d.vaccines.in_time_pct + "%", t("k_vax_pct"))}${kpi("", d.dispensary, t("k_disp"), '{"group":"any"}')}
      </div></details>
      <div class="grid two">
        <section class="card registry-list" id="registry-list" aria-labelledby="registry-heading"><div class="row-b list-head"><h2 id="registry-heading" tabindex="-1">${t("patients")} <span class="result-count">${result.total}</span></h2><span class="sp" style="flex:1"></span>
            <input id="q" type="search" aria-label="${t("search")}" placeholder="${t("search")}" value="${esc(f.q)}" style="max-width:200px">${can.lab() ? `<button class="btn sm ghost" id="lab">${t("lab_btn")}</button>` : ""}</div>
          ${registryFilters(f)}
          <div class="tscroll"><table><thead><tr><th>${t("th_name")}</th><th>${t("th_zone")}</th><th>${t("th_why")}</th><th>${t("th_mahalla")}</th><th>${t("th_contact")}</th></tr></thead>
          <tbody>${
            ps.map(
                (p) => `<tr class="row" data-p="${p.id}"><td><a class="patient-name" href="#/bemor/${p.id}">${esc(p.name)}</a><div class="small">${kindLabel(p)}</div>${marksOf(p)}</td><td>${zb(p.zone)}</td>
            <td>${reasonText(p.top)}</td><td>${esc(p.mahalla || "")}</td><td class="small">${ago(p.last_contact)}</td></tr>`,
              )
              .join("") || `<tr><td colspan="5" class="small">${t("empty")}</td></tr>`
          }</tbody></table></div>${registryPager(result)}</section>
        <div class="grid" style="align-content:start">
          ${d.demo?.length ? `<div class="card"><h2>${t("demo_h")}</h2>${d.demo.map((p, i) => `<div class="row-b" style="justify-content:space-between;padding:5px 0;cursor:pointer" data-p="${p.id}"><span><b>${esc(p.name)}</b><div class="small">${t("demo_" + i)}</div></span>${zb(p.zone)}</div>`).join("")}</div>` : ""}
          ${d.stays?.length ? `<div class="card"><h2>${t("stays_h")}</h2><div class="feed">${d.stays.slice(0, 6).map((s) => stayRow(s, 1)).join("")}</div></div>` : ""}
          <div class="card"><h2>${t("notices")}</h2><div class="feed">${
            d.notices
              .slice(0, 9)
              .map(
                (n) => `<div ${n.patient_id ? `data-p="${n.patient_id}" style="cursor:pointer"` : ""}>
            <span class="badge z-${n.level}">${t("r_" + n.role)}</span> ${esc(n[S.lang] || n.uz)}<div class="small">${dt(n.at)}</div></div>`,
              )
              .join("") || `<span class="small">${t("empty")}</span>`
          }</div></div>
          ${
            S.role === "rahbar" && d.doctors?.length
              ? `<div class="card"><h2>${t("doctors_h")}</h2><div class="tscroll"><table><thead><tr><th>${t("doctor")}</th><th>${t("d_open")}</th><th>${t("d_over")}</th><th>${t("d_time")}</th><th>${t("d_mis")}</th></tr></thead><tbody>
            ${d.doctors
              .slice(0, 8)
              .map(
                (x) =>
                  `<tr><td>${esc(x.doctor)}</td><td>${x.open}</td><td>${x.overdue ? `<b style="color:var(--red)">${x.overdue}</b>` : 0}</td><td>${x.in_time_pct == null ? "—" : x.in_time_pct + "%"}</td><td>${x.mismatch || 0}</td></tr>`,
              )
              .join("")}</tbody></table></div></div>`
              : ""
          }
          <div class="card"><h2>${t("signal")}</h2>${d.clusters.map((c) => `<div class="row-b" style="justify-content:space-between;padding:4px 0"><span>${esc(c.mahalla)}</span><span class="badge z-${c.zone}">${c.count}</span></div>`).join("") || `<span class="small">${t("empty")}</span>`}
            <p class="small mt">${t("signal_note")}</p></div>
        </div></div>`;
    function changeFilter(update,focusId,openExtra=false) {
      Object.assign(f,update);
      S.patientPage=1;
      return home({focus:focusId,openExtra});
    }
    $("#q").oninput = e => {
      const input=e.currentTarget;
      registryVersion++;
      clearTimeout(S.searchDelay);
      f.q=input.value.trim(); S.patientPage=1;
      S.searchDelay=setTimeout(()=>{
        if(input.isConnected)home({focus:document.activeElement===input?"q":""});
      },260);
    };
    for(const select of document.querySelectorAll("[data-filter]")){
      select.onchange=()=>changeFilter({[select.dataset.filter]:select.value},select.id);
    }
    const extra=$("#extra-filter");
    extra.open=restoreExtra;
    for(const box of extra.querySelectorAll("[data-extra]")){
      const key=box.dataset.extra;
      box.id="more-"+key;
      box.onchange=()=>changeFilter({[key]:key==="group" ? (box.checked?"any":"") : Number(box.checked)},box.id,true);
    }
    function closeExtra(){extra.open=false;$("#filter-extra").focus();}
    $("#apply-extra").onclick=closeExtra;
    extra.onkeydown=e=>{if(e.key==="Escape"){e.preventDefault();closeExtra();}};
    if ($("#lab")) $("#lab").onclick = () => labImport(home);
    $(".registry-more").ontoggle = event => { sessionStorage.moreKpis = String(event.currentTarget.open); };
    $("#app").onclick = e => {
      const pg=e.target.closest("[data-pg]");
      const k=e.target.closest("[data-f]");
      const patient=e.target.closest("[data-p]");
      if(e.target.closest(".registry-reset")) {
        changeFilter({zone:"",kind:"",q:"",silent:0,group:"",vax:0,hospital:0},"filter-zone");
      } else if(pg && !pg.disabled && Number(pg.dataset.pg)!==S.patientPage) {
        S.patientPage=Number(pg.dataset.pg);home({focus:"registry-heading",listTop:true});
      } else if(k) {
        const o=JSON.parse(k.dataset.f);
        if(o.go)location.hash="#/"+o.go;
        else changeFilter({zone:"",silent:0,vax:0,hospital:0,group:"",...o},"registry-heading");
      } else if(patient && !e.target.closest("a")) location.hash="#/bemor/"+patient.dataset.p;
      if(extra.open && !extra.contains(e.target)) extra.open=false;
    };
    if(listTop) $("#registry-list").scrollIntoView({block:"start"});
    if (focusId && (!openExtra || restoreExtra)) {
      const field = document.getElementById(focusId);
      field?.focus({preventScroll:true});
      if (field?.id === "q" && searchSelection) field.setSelectionRange(...searchSelection);
    }
    refreshEvery(15000,home,()=>!extra.open && !$("#registry-list").contains(document.activeElement));
  }

  /* ---------- patient card ---------- */
  const flagLabel = (c) => {
    const m = S.meta.complaints[c];
    return m
      ? L(m)
      : { unclear: t("unclear"), tashrif_tasdiqlanmadi: t("s_nomuvofiq"), noanswer: t("c_javobsiz"), ahvol: t("f_ahvol"), dori: t("f_dori"), fikr: t("f_fikr"), murojaat: t("f_murojaat"), operator: t("f_operator") }[
          c
        ] ||
          (S.meta.flags?.[c] ? L(S.meta.flags[c]) : c);
  };
  const obsText = (d) => {
    const a = [];
    if (d.bp_sys) a.push(`${t("bp")} ${d.bp_sys}/${d.bp_dia || "?"}`);
    if (d.hb) a.push(`Hb ${d.hb}`);
    if (d.glucose) a.push(`${t("glucose")} ${d.glucose}`);
    if (d.temp) a.push(`t ${d.temp}°C`);
    if (d.pulse) a.push(`${t("pulse")} ${d.pulse}`);
    (d.complaints || []).forEach((c) => a.push(flagLabel(c)));
    (d.extra_flags || []).forEach((c) => a.push(flagLabel(c)));
    return a.join(" · ") || "—";
  };
  const taskRow = (
    x,
    withP,
  ) => `<div class="card mb" style="padding:11px"><div class="row-b" style="justify-content:space-between"><b>${t("t_" + x.type)}</b>
      <span class="badge ${x.status === "ochiq" ? (x.escalated ? "z-red" : "z-yellow") : x.status === "nomuvofiq" ? "z-red" : x.status === "tasdiqlandi" ? "z-green" : "z-info"}">${t("s_" + x.status)}</span></div>
      ${withP && x.patient ? `<div><a href="#/bemor/${x.patient.id}"><b>${esc(x.patient.name)}</b></a> ${zb(x.patient.zone)} <span class="small">${esc(x.patient.mahalla || "")} · ${esc(x.patient.phone || "")}</span></div>` : ""}
      <div class="small">${esc(x.reason || "")}</div><div class="row-b mt" style="justify-content:space-between"><span>${timer(x.due_at, x.status) || `<span class="small">${dt(x.done_at)}</span>`}</span>
      ${x.status === "ochiq" && can.close(x) ? `<button class="btn sm" data-done="${x.id}">${t("mark_done")}</button>` : ""}</div></div>`;
  // One exchange of the free part of a call: what the patient asked and what the assistant did with it.
  const talkRow = (x) =>
    `<div class="small">${t("q_asked")}: <span class="quote">${esc(x.q)}</span><br>→ ${
      x.kind === "answer"
        ? `${t("q_answer")} <span class="badge z-gray">${t(x.by === "claude" ? "closing_claude" : "closing_voicelab")}</span>: <span class="quote">${esc(x.a)}</span>${
            x.source?.length ? ` (${t("q_src")}: ${esc(x.source.join("; "))})` : ""
          }${x.to ? ` · ${t("q_told")}` : ""}`
        : x.kind === "alarm"
          ? `<b>${t("q_alarm")}</b>`
          : t(x.to === "hamshira" ? "q_nurse" : "q_doctor")
    }</div>`;
  const callRow = (
    c,
    withP,
  ) => `<div class="card mb" style="padding:11px"><div class="row-b" style="justify-content:space-between"><b>${esc(L(c.title))}</b>
      <span class="badge ${c.status === "tugadi" ? (c.flags?.length ? "z-red" : "z-green") : c.status === "javobsiz" ? "z-yellow" : "z-info"}">${t("c_" + c.status)}</span></div>
      ${withP && c.patient ? `<div><a href="#/bemor/${c.patient.id}"><b>${esc(c.patient.name)}</b></a></div>` : ""}
      <div class="small">${c.status === "tugadi" ? `${t("flags")}: ${(c.flags || []).map(flagLabel).join(", ") || t("no_flags")} · ${dt(c.finished_at)}` : `${t("planned")}: ${dt(c.planned_at)}`}</div>
      ${
        c.status === "cancelled" ? "" : c.status === "tugadi"
          ? Object.entries(c.answers || {})
              .map(([k, a]) =>
                k === "suhbat"
                  ? (a.items || []).map(talkRow).join("")
                  : `<div class="small">${k === "shaxs" ? t("a_shaxs") : esc(k)}: <b>${a.value === "yes" ? t("yes") : a.value === "no" ? t("no") : a.value == null || a.value === "unclear" ? t("unclear") : esc(a.value)}</b>${a.transcript ? ` — <span class="quote">${esc(a.transcript)}</span>` : ""}</div>`,
              )
              .join("") +
            (c.closing
              ? `<div class="small mt">${t("closing_said")} <span class="badge z-gray">${t(c.closing_by === "claude" ? "closing_claude" : c.closing_by === "voicelab" ? "closing_voicelab" : "closing_tpl")}</span>: <span class="quote">${esc(c.closing)}</span></div>`
              : "")
          : `<div class="mt"><button class="btn sm ghost" data-call='${esc(JSON.stringify({ url: c.url, id: c.test_line ? null : c.id }))}'>${t("begin")}</button></div>`
      }</div>`;
  function showCall(url, title, text, id) {
    const phone = S.meta?.telephony && id ? `<button class="btn" id="dial">${t("dial")}</button>` : "";
    const sim = S.meta?.sim && id ? `<button class="btn" id="sim">${t("sim_dial")}</button>` : "";
    const other = phone || sim ? `<label class="mt">${t("dial_to")}</label><input id="dn" type="text" inputmode="tel" placeholder="+998 90 123-45-67">` : "";
    modal(`<h2>${title || t("call_qr")}</h2><p class="small">${text || t("call_qr_text")}</p><div class="center"><img src="/api/qr?u=${encodeURIComponent(url)}" alt="QR" style="width:230px;max-width:100%"></div>${other}
      <div class="row-b mt">${sim}${phone}<a class="btn ${phone || sim ? "ghost" : ""}" href="${url}" target="_blank" rel="noopener">${t("open_here")}</a><button class="btn ghost" id="cp">${t("copy")}</button><button class="btn ghost" data-close>${t("close")}</button></div>`);
    $("#cp").onclick = () => navigator.clipboard?.writeText(url).then(() => toast(t("copied")));
    if ($("#sim"))
      $("#sim").onclick = async () => {
        try {
          await api(`/calls/${id}/sim`, { json: { phone: $("#dn")?.value || "" } });
          toast(t("sim_ok"), 6000);
        } catch (e) {
          toast(/line/.test(e.message) ? t("sim_off") : e.message, 6000);
        }
      };
    if ($("#dial"))
      $("#dial").onclick = async () => {
        try {
          await api(`/calls/${id}/dial`, { json: { phone: $("#dn")?.value || "" } });
          toast(t("dial_ok"));
        } catch (e) {
          toast(e.message);
        }
      };
  }
  async function markDone(id, after) {
    const r = await api(`/tasks/${id}/done`, { json: {} });
    if (r.call) showCall(r.call.url, t("verify_title"), t("verify_text"), r.call.id);
    else toast(t("no_verify"), 5000);
    after && after();
  }
  function labImport(after) {
    modal(`<h2>${t("lab_h")}</h2><p class="small">${t("lab_p")}</p><textarea id="csv" style="min-height:150px;font-family:monospace;font-size:12.5px">full_name,birth_year,hb,bp_sys,bp_dia\nSodiqova Dilnoza,1998,92,148,94</textarea>
      <div class="row-b mt"><button class="btn" id="lgo">${t("lab_run")}</button><button class="btn ghost" data-close>${t("close")}</button></div><div id="lres" class="mt"></div>`);
    $("#lgo").onclick = async () => {
      const r = await api("/import/lab", { json: { csv: $("#csv").value } });
      $("#lres").innerHTML =
        `<b>${r.matched}/${r.rows} ${t("lab_res")}: ${r.changed.length}</b>${r.changed.map((c) => `<div><a href="#/bemor/${c.id}" data-close>${esc(c.name)}</a>: ${zb(c.from)} → ${zb(c.to)}</div>`).join("")}${r.not_found.length ? `<div class="small">? ${r.not_found.map(esc).join(", ")}</div>` : ""}${r.invalid?.length ? `<div class="small">⚠ ${t("lab_invalid")}: ${r.invalid.map(esc).join(", ")}</div>` : ""}`;
      after && after();
    };
  }

  async function patient(id) {
    const p = await api("/patients/" + id),
      v = p.values || {};
    const val = (label, x) =>
      x != null && x !== "" ? `<div class="card" style="padding:9px 12px"><div class="small">${label}</div><b>${x}</b></div>` : "";
    $("#app").innerHTML = `
      <div class="row-b mb"><a href="#/" class="small">← ${t("nav_home")}</a></div>
      <div class="card mb"><div class="row-b" style="justify-content:space-between"><h1>${esc(p.name)}</h1>${zb(p.zone)}</div>
        ${marksOf({ ...p, in_hospital: p.stays.some((s) => !s.discharged_at) }) ? `<div class="mb">${marksOf({ ...p, in_hospital: p.stays.some((s) => !s.discharged_at) })}</div>` : ""}
        <div class="small">${kindLabel(p)}${p.birth_year && p.kind !== "chaqaloq" ? " · " + p.birth_year : ""} · ${esc(p.mahalla || "")} · ${esc(p.phone || "")} · ${t("doctor")}: ${esc(p.doctor || "—")} · ${t("th_contact")}: ${ago(p.last_contact)}</div>
        <div class="mt"><span class="badge ${p.consent ? "z-green" : "z-yellow"}">${t(p.consent ? "consent_yes" : "consent_no")}</span>${p.consent ? "" : ` <button class="btn sm ghost" id="bcons">${t("consent_btn")}</button>`}</div>
        ${p.diagnosis || p.icd10 ? `<div class="mt"><span class="small">${t("diagnosis")}:</span> ${esc([p.icd10, p.diagnosis].filter(Boolean).join(" · "))}</div>` : ""}
        ${(p.marks || []).some((m) => m.code === "maxfiy") ? `<div class="mt small">${t("secret_note")}</div>` : ""}
        ${(p.marks || []).length ? `<div class="mt small">${p.private_consent_at ? `${t("pc_card")}: <b>${dt(p.private_consent_at)}</b>` : t("pc_card_no")}${!p.private_consent_at && p.may_record_private ? ` <button class="btn sm ghost" id="bpc">${t("pc_btn")}</button>` : ""}</div>` : ""}
        ${p.pinfl || p.parity === 0 ? `<div class="mt small">${p.pinfl ? "PINFL: " + esc(p.pinfl) : ""}${p.parity === 0 ? (p.pinfl ? " · " : "") + t("first_child") : ""}</div>` : ""}
        ${p.mother ? `<div class="mt small">${t("mother")}: <a href="#/bemor/${p.mother.id}">${esc(p.mother.name)}</a></div>` : ""}
        ${p.children.length ? `<div class="mt small">${t("children")}: ${p.children.map((k) => `<a href="#/bemor/${k.id}">${esc(k.name)}</a> ${zb(k.zone)}`).join(", ")}</div>` : ""}
        <div class="row-b mt"><button class="btn" id="bcall">${t("start_call")}</button><a class="btn ghost" href="#/care/${p.id}">${t("nav_care")} · DMED</a>
          <a class="btn ghost" target="_blank" href="/api/patients/${p.id}/referral.pdf?lang=${S.lang}">${t("referral")}</a>
          <a class="btn ghost" target="_blank" href="/api/patients/${p.id}/fhir">${t("fhir")}</a>${can.lab() ? `<button class="btn ghost" id="bdmed">${t("dmed_btn")}</button>` : ""}</div></div>
      <div class="grid two">
        <div class="grid" style="align-content:start">
          <div class="card"><h2>${t("why")}</h2>${p.reasons.map((r) => `<div class="reason ${r.zone}"><b>${reasonText(r)}</b> <span class="small">· ${t("rule")}: ${esc(r.rule)}</span>${r.quote ? `<div class="quote">${esc(r.quote)}</div>` : ""}</div>`).join("") || `<p>${t("why_none")}</p>`}
            ${p.ml ? `<div class="mt small"><b>${t("ml")}:</b> ${zb(p.ml.zone)} ${t("conf")} ${Math.round(p.ml.confidence * 100)}%${p.ml.assumed.length ? ` (${p.ml.assumed.map((a) => t(a)).join(", ")}: ${t("ml_assumed")})` : ""}. ${t("ml_note")}</div>` : ""}</div>
          <div class="card"><h2>${t("summary")}</h2><ol class="steps">${p.summary[S.lang].map((s) => `<li>${esc(s)}</li>`).join("")}</ol></div>
          <div class="card"><h2>${t("values")}</h2><div class="grid kpis">${val(t("bp"), v.bp_sys ? `${v.bp_sys}/${v.bp_dia || "?"}` : null)}${val(t("hb"), v.hb != null ? v.hb + (p.prev.hb ? ` <span class="small">(${p.prev.hb})</span>` : "") : null)}${val(t("glucose"), v.glucose)}${val(t("temp"), v.temp)}${val(t("pulse"), v.pulse)}</div>
            <h3 class="mt">${t("add_lab")}</h3><div class="form">${[
              ["bp_sys", "sys"],
              ["bp_dia", "dia"],
              ["hb", "hb"],
              ["glucose", "glucose"],
              ["temp", "temp"],
            ]
              .map(([k, l]) => `<div><label>${t(l)}</label><input type="number" step="0.1" data-in="${k}"></div>`)
              .join("")}
              <div><button class="btn" id="bsave">${t("save")}</button></div></div></div>
          <div class="card"><h2>${t("history")}</h2><div class="feed">${
            p.observations
              .map(
                (o) => `<div><span class="badge z-gray">${t("src_" + o.source)}</span> ${esc(obsText(o.data || {}))}
            <div class="small">${dt(o.at)} · ${esc(o.author || "")}</div>${o.text && o.source !== "tahlil" ? `<div class="quote">${esc(o.text.slice(0, 260))}</div>` : ""}</div>`,
              )
              .join("") || t("empty")
          }</div></div>
        </div>
        <div class="grid" style="align-content:start">
          ${p.stays.length ? `<div class="card"><h2>${t("stays_card")}</h2><div class="feed">${p.stays.map((s) => stayRow(s)).join("")}</div></div>` : ""}
          ${
            p.vaccines.length
              ? `<div class="card"><h2>${t("vax_h")}</h2>${Object.entries(
                  p.vaccines.reduce((a, d) => ((a[d.age] = a[d.age] || { label: d.label, doses: [] }).doses.push(d), a), {}),
                )
                  .map(
                    ([, g]) =>
                      `<div class="row-b" style="padding:3px 0"><span class="small" style="min-width:74px">${esc(L(g.label))}</span>${g.doses.map((d) => `<span class="vx ${d.state}" title="${t("vax_" + d.state)}${d.done_at ? " · " + dt(d.done_at) : ""}">${esc(d.short)}</span>`).join("")}</div>`,
                  )
                  .join("")}
              <p class="small mt">${["done", "said", "due", "overdue", "later"].map((x) => `<span class="vx ${x}">${t("vax_" + x)}</span>`).join("")}</p><p class="small">${t("vax_note")}</p></div>`
              : ""
          }
          <div><h2>${t("tasks")}</h2>${p.tasks.map((x) => taskRow(x)).join("") || `<p class="small">${t("empty")}</p>`}</div>
          <div><h2>${t("calls")}</h2>${p.calls.map((c) => callRow(c)).join("") || `<p class="small">${t("empty")}</p>`}</div>
          ${p.dmed.length ? `<div class="card"><h2>${t("dmed_card")}</h2><div class="feed">${p.dmed.map((m) => `<div><span class="badge ${m.direction === "in" ? "z-info" : "z-gray"}">${m.direction === "in" ? "DMED →" : "→ DMED"}</span> <b>${esc(kindTitle(m.kind))}</b> <span class="small">· ${esc(dmedSummary(m))} · ${t("st_" + m.status)} · ${dt(m.at)}</span></div>`).join("")}</div></div>` : ""}
          <div class="card"><h2>${t("audit_h")}</h2><div class="feed">${p.audit.map((a) => `<div><span class="badge z-gray">${esc(a.actor || (t("r_" + a.role) === "r_" + a.role ? a.role : t("r_" + a.role)))}</span> ${esc(a.action)} <span class="small">· ${esc(a.detail || "")} · ${dt(a.at)}</span></div>`).join("") || `<span class="small">${t("empty")}</span>`}</div></div></div>
      </div>`;
    $("#bsave").onclick = async () => {
      const body = {};
      document.querySelectorAll("[data-in]").forEach((i) => {
        if (i.value !== "") body[i.dataset.in] = +i.value;
      });
      if (!Object.keys(body).length) return;
      const r = await api(`/patients/${id}/observations`, { json: body });
      toast(r.zone !== r.old ? `${t("zone_changed")}: ${t("z" + r.old)} → ${t("z" + r.zone)}` : t("zone_same"));
      patient(id);
    };
    if ($("#bcons"))
      $("#bcons").onclick = async () => {
        await api(`/patients/${id}/consent`, { method: "POST" });
        patient(id);
      };
    if ($("#bdmed")) $("#bdmed").onclick = () => dmedEvent(p, () => patient(id));
    if ($("#bpc"))
      $("#bpc").onclick = async () => {
        if (!confirm(t("pc_sure"))) return;
        await api(`/patients/${id}/consent/private`, { method: "POST" });
        patient(id);
      };
    // the discharge button is not drawn any more (DMED reports discharges); a missing button must not break the card
    if ($("#bdis"))
      $("#bdis").onclick = async () => {
        await api(`/patients/${id}/discharge`, { json: {} });
        toast(t("discharge_done"));
        patient(id);
      };
    $("#bcall").onclick = async () => {
      if (!p.consent) return toast(t("consent_need"), 4500);
      const {eligible} = await api("/care/patients/"+id);
      const sc = eligible.filter(s => s.id !== "tashrif_tasdiq");
      if (!sc.length) return toast(t("no_eligible"), 4500);
      const def = sc[0].id;
      modal(`<h2>${t("start_call")}</h2><label>${t("scenario")}</label><select id="sc">${sc.map((s) => `<option value="${s.id}" ${s.id === def ? "selected" : ""}>${esc(L(s.title))}</option>`).join("")}</select>
        <label class="mt">${t("speech_lang")}</label><select id="cl"><option value="uz">O'zbekcha</option><option value="ru">Русский</option></select>
        <div class="row-b mt"><button class="btn" id="mk">${t("begin")}</button><button class="btn ghost" data-close>${t("close")}</button></div>`);
      $("#mk").onclick = async () => {
        const c = await api(`/patients/${id}/calls`, { json: { scenario: $("#sc").value, lang: $("#cl").value } });
        showCall(c.url, null, null, c.test_line ? null : c.id);
      };
    };
    $("#app").onclick = (e) => {
      const d = e.target.closest("[data-done]"),
        c = e.target.closest("[data-call]");
      if (d) markDone(d.dataset.done, () => patient(id));
      else if (c) showCall(JSON.parse(c.dataset.call).url, null, null, JSON.parse(c.dataset.call).id);
    };
    refreshEvery(15000, () => patient(id), () => document.activeElement?.tagName !== "INPUT");
  }

  /* ---------- tasks & calls ---------- */
  async function tasks() {
    const mine = S.role !== "rahbar";
    const rows = await api("/tasks");
    const open = rows.filter((x) => x.status === "ochiq"),
      rest = rows.filter((x) => x.status !== "ochiq").slice(0, 30);
    $("#app").innerHTML =
      `<h1>${mine ? t("my_tasks") + " · " + t("r_" + S.role) : t("all_tasks")}</h1><div class="grid two"><div><h2>${t("s_ochiq")} · ${open.length}</h2>${open.map((x) => taskRow(x, 1)).join("") || `<p class="small">${t("empty")}</p>`}</div>
      <div><h2>${t("k_verified")} / ${t("s_nomuvofiq")}</h2>${rest.map((x) => taskRow(x, 1)).join("") || `<p class="small">${t("empty")}</p>`}</div></div>`;
    $("#app").onclick = (e) => {
      const d = e.target.closest("[data-done]");
      if (d) markDone(d.dataset.done, tasks);
    };
    refreshEvery(20000, tasks);
  }
  async function calls() {
    const R = (S.round = S.round || { scenario: S.meta.scenarios[0]?.id, lang: S.lang === "ru" ? "ru" : "uz", zone: "", limit: 10 });
    const [rows, aud] = await Promise.all([api("/calls"), api("/calls/audience?" + new URLSearchParams({ scenario: R.scenario, zone: R.zone }))]);
    const plan = rows.filter((c) => c.status !== "tugadi" && c.status !== "javobsiz"),
      done = rows.filter((c) => c.status === "tugadi" || c.status === "javobsiz");
    const opt = (v, label, cur) => `<option value="${esc(v)}" ${String(v) === String(cur) ? "selected" : ""}>${esc(label)}</option>`;
    // The panel a calling round is started from. A trial call opens a QR code: scan it with a phone and talk to the AI.
    const panel = `<div class="card mb"><h2>${t("round_h")}</h2><p class="small">${t("round_p")}</p>
      <div class="row-b mt">
        <div><label>${t("round_sc")}</label><select id="rsc">${S.meta.scenarios.map((x) => opt(x.id, L(x.title), R.scenario)).join("")}</select></div>
        <div><label>${t("round_lang")}</label><select id="rlang">${opt("uz", "O'zbekcha", R.lang)}${opt("ru", "Русский", R.lang)}</select></div>
        <div><label>${t("round_zone")}</label><select id="rzone">${opt("", t("round_all"), R.zone)}${["red", "yellow", "green"].map((z) => opt(z, t("z" + z), R.zone)).join("")}</select></div>
        <div><label>${t("round_limit")}</label><select id="rlim">${[1, 5, 10, 20, 50].map((n) => opt(n, n, R.limit)).join("")}</select></div>
      </div>
      <p class="mt"><b>${t("round_aud")}: ${aud.fit}</b> <span class="small">· ${t("round_nocons")}: ${aud.no_consent} · ${t("round_busy")}: ${aud.already}</span></p>
      <div class="row-b mt"><button class="btn" id="rtest">${t("round_test")}</button><button class="btn ghost" id="rgo" ${aud.fit ? "" : "disabled"}>${t("round_go")} · ${Math.min(aud.fit, R.limit)}</button></div></div>`;
    $("#app").innerHTML =
      `<h1>${t("nav_calls")}</h1>${panel}<div class="grid two"><div><h2>${t("c_tugadi")} · ${done.length}</h2>${done.map((c) => callRow(c, 1)).join("") || `<p class="small">${t("empty")}</p>`}</div>
      <div><h2>${t("c_rejalashtirilgan")} · ${plan.length}</h2>${plan.map((c) => callRow(c, 1)).join("") || `<p class="small">${t("empty")}</p>`}</div></div>`;
    const pick = (id, key, num) =>
      ($("#" + id).onchange = (e) => {
        R[key] = num ? Number(e.target.value) : e.target.value;
        calls();
      });
    pick("rsc", "scenario");
    pick("rlang", "lang");
    pick("rzone", "zone");
    pick("rlim", "limit", true);
    $("#rtest").onclick = async () => {
      const r = await api("/calls/round", { json: { scenario: R.scenario, lang: R.lang, test: true } });
      if (!r.calls.length) return toast(t("round_none"));
      showCall(r.calls[0].url, t("round_test_h"), `${esc(r.calls[0].patient?.name || "")} · ${esc(L(r.calls[0].title))}. ${t("round_test_p")}`, r.calls[0].id);
    };
    $("#rgo").onclick = async () => {
      const n = Math.min(aud.fit, R.limit);
      if (!n || !confirm(`${n} ${t("round_sure")}`)) return;
      const r = await api("/calls/round", { json: { scenario: R.scenario, lang: R.lang, zone: R.zone, limit: R.limit } });
      toast(`${r.calls.length} ${t("round_done")}`, 5000);
      calls();
    };
    $("#app").onclick = (e) => {
      const c = e.target.closest("[data-call]");
      if (c) showCall(JSON.parse(c.dataset.call).url, null, null, JSON.parse(c.dataset.call).id);
    };
    refreshEvery(12000, calls, () => document.activeElement?.tagName !== "SELECT");
  }

  /* ---------- voice input with offline queue ---------- */
  const idb = () =>
    new Promise((res, rej) => {
      const r = indexedDB.open("nigoh", 1);
      r.onupgradeneeded = () => r.result.createObjectStore("queue", { keyPath: "id", autoIncrement: true });
      r.onsuccess = () => res(r.result);
      r.onerror = () => rej(r.error);
    });
  async function queueRequest(mode, action) {
    const db = await idb();
    try {
      return await new Promise((resolve,reject) => {
        const tx = db.transaction("queue",mode);
        const request = action(tx.objectStore("queue"));
        tx.oncomplete = () => resolve(request.result);
        tx.onabort = () => reject(tx.error || new Error("queue"));
        tx.onerror = () => reject(tx.error);
      });
    } finally { db.close(); }
  }
  async function sendVoice(blob, lang, transcriptOnly = false) {
    const fd = new FormData();
    fd.append("audio", blob, "voice." + (blob.type.split("/")[1] || "webm").split(";")[0]);
    fd.append("lang", lang);
    if (transcriptOnly) fd.append("transcript_only", "true");
    return api("/voice", { method: "POST", body: fd });
  }
  const voiceStudio = window.MehrVoiceStudio.create({
    root: $("#app"), t, esc, L, icon, api, sendVoice, toast, zoneBadge: zb, reasonText,
    interfaceLanguage: () => S.lang,
    account: () => S.me?.username,
    role: () => S.role,
    complaints: () => S.meta.complaints,
    questions: () => S.meta.voice_questions,
    listQueue: () => queueRequest("readonly", store => store.getAll()),
    putQueue: item => queueRequest("readwrite", store => store.put(item)),
    deleteQueue: id => queueRequest("readwrite", store => store.delete(id)),
  });
  function voice() { voiceStudio.open(); }
  window.addEventListener("online",voiceStudio.flush);
  window.addEventListener("pagehide",voiceStudio.leave);

  /* ---------- DMED: the exchange log and the stand-in ---------- */
  // An event as DMED would send it: an admission, a discharge with the diagnosis, a vaccination that was given.
  // It enters through the same door a real message does, so everything that follows is the real thing.
  function dmedEvent(p, after) {
    const child = p.kind === "bola" || p.kind === "chaqaloq";
    const opt = (v) => `<option value="${v}">${t("ev_" + v)}</option>`;
    modal(`<h2>${t("dmed_sim_h")}</h2><p class="small">${esc(p.name)} · ${t("dmed_sim_p")}</p>
      <label>${t("dmed_event")}</label><select id="dev">${child ? opt("vaccine") : ""}${opt("admit")}${opt("discharge")}</select>
      <div id="dfields"></div>
      <div class="row-b mt"><button class="btn" id="dgo">${t("dmed_send")}</button><button class="btn ghost" data-close>${t("close")}</button></div>`);
    const inp = (id, label, value = "") => `<label class="mt">${label}</label><input id="${id}" type="text" value="${esc(value)}">`;
    const draw = () => {
      const ev = $("#dev").value;
      $("#dfields").innerHTML =
        ev === "vaccine"
          ? ""
          : ev === "admit"
            ? inp("dh", t("dmed_hospital"), ruText("Tuman markaziy shifoxonasi")) +
              `<label class="mt"><input id="de" type="checkbox" checked style="width:auto"> ${t("dmed_emerg")}</label>` +
              inp("db", t("dmed_by"), ruText("103 tez yordam brigadasi")) +
              inp("dr", t("dmed_reason"), ruText("Ko'krakda og'riq, qon bosimi 190/110"))
            : inp("di", t("dmed_icd"), "I11.9") + inp("dx", t("dmed_dx"), ruText("Gipertonik kriz")) + inp("da", t("dmed_advice"), ruText("Qon bosimini kuniga ikki marta o'lchash; dorilarni uzluksiz ichish"));
    };
    $("#dev").onchange = draw;
    draw();
    $("#dgo").onclick = async () => {
      const g = (id) => $("#" + id)?.value || "";
      const body = { patient_id: p.id, event: $("#dev").value, hospital: g("dh"), emergency: $("#de") ? $("#de").checked : true, brought_by: g("db"), reason: g("dr"), icd10: g("di"), diagnosis: g("dx"), advice: g("da") };
      try {
        const r = await api("/dmed/simulate", { json: body });
        toast(`${t("dmed_sent")}: ${r.accepted.map((x) => kindTitle(x.kind)).join(", ")}`, 5000);
        closeModal();
        after && after();
      } catch (e) {
        toast(e.message, 5000);
      }
    };
  }
  /* ---------- DMED journal in words ---------- */
  // A message is shown by what it means for the patient; the FHIR type stays as a small tag and the
  // resource itself is one click away. The texts the server writes in Uzbek are put into Russian here.
  const tr = (uz, ru) => (S.lang === "ru" ? ru : uz);
  const DMED_KIND = {
    "Encounter: yotqizildi": ["Shifoxonaga yotqizildi", "Госпитализация"],
    "Encounter: chiqarildi": ["Shifoxonadan chiqarildi", "Выписка из больницы"],
    "Encounter: yangilandi": ["Shifoxonada yotish yangilandi", "Изменения по госпитализации"],
    Encounter: ["Shifoxonada yotish", "Пребывание в больнице"],
    "Immunization: emlandi": ["Emlandi", "Прививка сделана"],
    "Immunization: ota-ona so'zi": ["Emlash (ota-ona so'zi)", "Прививка со слов родителя"],
    Immunization: ["Emlash", "Прививка"],
    "Task: vazifa": ["Xodimga vazifa", "Задача сотруднику"],
    "Task: bemor murojaati": ["Bemor murojaati", "Обращение пациента"],
    Task: ["Xodimga vazifa", "Задача сотруднику"],
    "Observation: o'lchovlar": ["O'lchovlar", "Измерения"],
    Observation: ["O'lchov", "Измерение"],
    "QuestionnaireResponse: qo'ng'iroq": ["AI qo'ng'iroq javoblari", "Ответы ИИ-звонка"],
    QuestionnaireResponse: ["So'rov javoblari", "Ответы опроса"],
    "Flag: xavf belgisi": ["Xavf belgisi", "Тревожный признак"],
    Flag: ["Belgi", "Отметка в карте"],
    "Consent: maxfiy nazorat": ["Nazoratga rozilik", "Согласие на наблюдение"],
    Consent: ["Rozilik", "Согласие"],
    Condition: ["Tashxis", "Диагноз"],
    CarePlan: ["Tavsiyalar", "Рекомендации"],
    Bundle: ["Xabarlar to'plami", "Пакет сообщений"],
  };
  const fhirType = (k) => String(k || "").split(":")[0].trim();
  const kindTitle = (k) => (DMED_KIND[k] || DMED_KIND[fhirType(k)] || [k, k])[li()];
  const ROLE_TO = { mutaxassis: ["mutaxassisga", "специалисту"], shifokor: ["oilaviy shifokorga", "семейному врачу"], hamshira: ["hamshiraga", "медсестре"], rahbar: ["rahbarga", "руководителю"] };
  const FIELD = { bp_sys: ["yuqori bosim", "давление верхнее"], bp_dia: ["pastki bosim", "давление нижнее"], hb: ["gemoglobin", "гемоглобин"], glucose: ["glyukoza", "глюкоза"], temp: ["harorat", "температура"], pulse: ["puls", "пульс"], breath: ["nafas", "дыхание"] };
  const SOURCE = { ovoz: ["ovozli kiritish", "голосовой ввод"], tahlil: ["tahlil", "анализ"], korik: ["ko'rik", "осмотр"] };
  const LOINC = { "8480-6": "bp_sys", "8462-4": "bp_dia", "718-7": "hb", "2339-0": "glucose", "8310-5": "temp", "8867-4": "pulse", "9279-1": "breath" };
  const UNIT = { "mm[Hg]": ["mm sim. ust.", "мм рт. ст."], "g/L": ["g/l", "г/л"], "mmol/L": ["mmol/l", "ммоль/л"], Cel: ["°C", "°C"], "/min": ["/daq", "/мин"] };
  const TASK_ST = { requested: ["ochiq", "открыта"], completed: ["bajarildi", "выполнена"], rejected: ["tasdiqlanmadi", "не подтверждена"] };
  const RU_WORDS = [
    ["Faol chaqiruv", "Активный вызов"],
    ["Mutaxassis ko'rigi", "Осмотр специалиста"],
    ["Hamshira tashrifi", "Визит медсестры"],
    ["Bemor murojaati", "Обращение пациента"],
    ["Qayta qo'ng'iroq", "Перезвонить пациенту"],
    ["Emlashga chaqirish", "Пригласить на прививку"],
    ["bemor yoki emlash kodi topilmadi", "пациент или код прививки не найден"],
    ["bemor topilmadi", "пациент не найден"],
    ["rozilik qayd etildi", "согласие записано"],
    ["Dispanser nazorati bo'yicha AI qo'ng'iroqlarga va maxfiy ma'lumotni qayta ishlashga rozilik", "Согласие на ИИ-звонки по диспансерному наблюдению и обработку конфиденциальных данных"],
    ["AI qo'ng'iroqda xavf belgilari", "Тревожные признаки в ИИ-звонке"],
    ["xavf belgisi: 103 aytildi", "тревожный признак: пациенту сказали звонить 103"],
    ["xavf belgilari", "тревожные признаки"],
    ["savol shifokorga yuborildi", "вопрос передан врачу"],
    ["ota-ona so'zi (AI qo'ng'iroq); emlash xonasi tasdig'i kutilmoqda", "со слов родителя (ИИ-звонок); ждёт подтверждения прививочного кабинета"],
    ["Shifoxonadan chiqarildi", "Выписан из больницы"],
    ["Tuman markaziy shifoxonasi", "Районная центральная больница"],
    ["103 tez yordam brigadasi", "Бригада скорой помощи 103"],
    ["Ko'krakda og'riq, qon bosimi 190/110", "Боль в груди, давление 190/110"],
    ["Gipertonik kriz", "Гипертонический криз"],
    ["Qon bosimini kuniga ikki marta o'lchash; dorilarni uzluksiz ichish", "Измерять давление два раза в день; принимать лекарства без перерывов"],
    ["bir haftadan keyin kardiolog ko'rigi", "через неделю осмотр кардиолога"],
    ["Tuman perinatal markazi", "Районный перинатальный центр"],
    ["Viloyat perinatal markazi", "Областной перинатальный центр"],
    ["Qon bosimi 170/110, kuchli bosh og'rig'i", "Давление 170/110, сильная головная боль"],
    ["Tug'ruqdan keyingi qon ketishi", "Послеродовое кровотечение"],
    ["Qon ketishi", "Кровотечение"],
    ["Gemoglobin nazorati; 3 kundan keyin oilaviy shifokor ko'rigi", "Контроль гемоглобина; через 3 дня осмотр семейного врача"],
  ];
  // Uzbek phrases the server writes into a message, in Russian: fixed phrases, scenario titles, complaints.
  function ruText(s) {
    s = String(s ?? "");
    if (S.lang !== "ru" || !s) return s;
    const pairs = [
      ...RU_WORDS,
      ...(S.meta?.scenarios || []).map((x) => [x.title?.uz, x.title?.ru]),
      ...Object.values(S.meta?.complaints || {}).map((c) => [c.uz, c.ru]),
    ]
      .filter(([a, b]) => a && b && a !== b)
      .sort((a, b) => b[0].length - a[0].length);
    for (const [uz, ru] of pairs) s = s.split(uz).join(ru);
    return s.replace(/(\d+) kun\b/g, "$1 дн.");
  }
  // What a resource says, as label and value pairs.
  function dmedFacts(payload) {
    const list = payload?.resourceType === "Bundle" ? (payload.entry || []).map((e) => e.resource || {}) : [payload || {}];
    const out = [];
    const add = (label, v) => {
      if (v !== undefined && v !== null && String(v).trim() !== "") out.push([label, String(v)]);
    };
    const when = (v) => (v ? dt(v) : "");
    const who = (v) => (["rahbar", "mutaxassis", "shifokor", "hamshira"].includes(v) ? t("r_" + v) : v);
    for (const r of list) {
      const ty = r.resourceType;
      if (ty === "Encounter") {
        const cls = Array.isArray(r.class) ? r.class[0]?.coding?.[0]?.code : r.class?.code,
          per = r.actualPeriod || r.period || {},
          dx = r.diagnosis?.[0]?.condition?.[0]?.concept;
        add(tr("Shifoxona", "Больница"), ruText(r.serviceProvider?.display));
        add(tr("Holat", "Статус"), r.status === "in-progress" ? tr("shifoxonada", "в больнице") : ["completed", "finished"].includes(r.status) ? tr("chiqarilgan", "выписан") : r.status);
        add(tr("Yotqizish", "Госпитализация"), cls === "EMER" ? tr("shoshilinch", "экстренная") : cls === "IMP" ? tr("rejali", "плановая") : cls);
        add(tr("Yotqizilgan", "Поступил"), when(per.start));
        add(tr("Chiqarilgan", "Выписан"), when(per.end));
        add(tr("Sabab", "Причина"), ruText(r.reason?.[0]?.value?.[0]?.concept?.text || r.reasonCode?.[0]?.text));
        if (dx) add(tr("Tashxis", "Диагноз"), [dx.coding?.[0]?.code, ruText(dx.text || dx.coding?.[0]?.display)].filter(Boolean).join(" · "));
        add(tr("Kim olib kelgan", "Кто доставил"), ruText(r.admission?.admitSource?.text));
      } else if (ty === "CarePlan") add(tr("Tavsiyalar", "Рекомендации"), ruText(r.description));
      else if (ty === "Condition") {
        const code = r.code?.coding?.[0]?.code;
        add(tr("Tashxis", "Диагноз"), [code, r.code?.text && r.code.text !== code ? ruText(r.code.text) : ""].filter(Boolean).join(" · "));
        if (r.verificationStatus?.coding?.[0]?.code === "confirmed") add(tr("Holat", "Статус"), tr("tasdiqlangan", "подтверждён"));
      } else if (ty === "Immunization") {
        add(tr("Emlash", "Прививка"), r.vaccineCode?.text || r.vaccineCode?.coding?.[0]?.code);
        add(tr("Sana", "Дата"), when(r.occurrenceDateTime));
        add(tr("Manba", "Источник"), r.primarySource === false ? ruText(r.informationSource?.concept?.text) || tr("ota-ona so'zi", "со слов родителя") : tr("emlash xonasi", "прививочный кабинет"));
      } else if (ty === "Task") {
        add(tr("Vazifa", "Задача"), ruText(r.description));
        add(tr("Kimga", "Кому"), who(r.owner?.display));
        add(tr("Muddat", "Срок"), when(r.restriction?.period?.end));
        add(tr("Holat", "Статус"), (TASK_ST[r.status] || [r.status, r.status])[li()]);
        if (r.priority === "urgent") add(tr("Muhimlik", "Срочность"), tr("shoshilinch", "срочно"));
      } else if (ty === "Observation") {
        const c = r.code?.coding?.[0] || {},
          q = r.valueQuantity || {};
        add(FIELD[LOINC[c.code]]?.[li()] || c.display || c.code, [q.value, (UNIT[q.unit] || [q.unit, q.unit])[li()]].filter((x) => x != null).join(" "));
      } else if (ty === "QuestionnaireResponse") {
        add(tr("Vaqt", "Когда"), when(r.authored));
        for (const it of r.item || []) {
          const a = it.answer?.[0] || {};
          const v =
            a.valueBoolean === true ? tr("ha", "да") : a.valueBoolean === false ? tr("yo'q", "нет") : a.valueDecimal ?? (["noaniq", "unknown"].includes(a.valueString) ? tr("noaniq", "неясно") : ruText(a.valueString));
          add(it.text || it.linkId, v);
        }
      } else if (ty === "Flag") {
        add(tr("Belgi", "Признак"), ruText(r.code?.text));
        add(tr("Vaqt", "Когда"), when(r.period?.start));
      } else if (ty === "Consent") {
        add(tr("Rozilik", "Согласие"), ruText(r.category?.[0]?.text));
        add(tr("Sana", "Дата"), r.date);
      } else {
        add(tr("Tavsif", "Описание"), ruText(r.description));
        add(tr("Holat", "Статус"), r.status);
      }
    }
    return out;
  }
  // The line under a message's title in the journal.
  function dmedSummary(m) {
    const s = m.summary || "",
      k = m.kind || "";
    if (/ · тестовая карта$/.test(s) || s === fhirType(k))
      return dmedFacts(m.payload).slice(0, 2).map(([, v]) => v).join(" · ") || tr("sinov kartasi", "тестовая карта");
    if (k.startsWith("Task")) {
      const [, label, role] = s.match(/^(.*?)\s*->\s*(\w+)$/) || [];
      if (label !== undefined) return `${ruText(label === "murojaat" ? "Bemor murojaati" : label)} → ${(ROLE_TO[role] || [role, role])[li()]}`;
    }
    if (k.startsWith("Observation")) {
      const [, src, fields] = s.match(/^(\w+):\s*(.*)$/) || [];
      if (src)
        return `${(SOURCE[src] || [src, src])[li()]}: ${fields
          .split(/,\s*/)
          .filter(Boolean)
          .map((x) => (FIELD[x] || [x, x])[li()])
          .join(", ")}`;
    }
    if (k.startsWith("QuestionnaireResponse")) {
      const i = s.lastIndexOf(": ");
      if (i > 0) {
        const codes = s.slice(i + 2);
        return `${ruText(s.slice(0, i))}: ${codes === "belgi yo`q" ? tr("xavf belgisi yo'q", "тревожных признаков нет") : codes.split(/,\s*/).map(flagLabel).join(", ")}`;
      }
    }
    return ruText(s);
  }
  async function dmedPage() {
    const d = await api("/dmed");
    const row = (m) =>
      `<tr class="row" data-m="${m.id}"><td><b>${esc(kindTitle(m.kind))}</b> <span class="tag">${esc(fhirType(m.kind))}</span><div class="small">${esc(dmedSummary(m))}</div></td><td>${m.patient ? `<a href="#/bemor/${m.patient.id}">${esc(m.patient.name)}</a>` : "—"}</td>
        <td><span class="badge ${m.status === "xato" || m.status === "topilmadi" ? "z-red" : m.status === "navbatda" ? "z-yellow" : "z-green"}">${t("st_" + m.status)}</span></td><td class="small">${dt(m.sent_at || m.at)}</td></tr>`;
    const table = (rows) =>
      `<div class="tscroll"><table><thead><tr><th>${t("dmed_kind")}</th><th>${t("th_name")}</th><th>${t("dmed_status")}</th><th>${t("dmed_when")}</th></tr></thead><tbody>${rows.map(row).join("") || `<tr><td colspan="4" class="small">${t("empty")}</td></tr>`}</tbody></table></div>`;
    const kpi = (v, label, cls = "plain") => `<div class="card kpi ${cls}"><b>${v}</b><span>${label}</span></div>`;
    $("#app").innerHTML = `<div class="row-b mb"><h1>${t("dmed_h")}</h1><span class="badge ${d.mode === "jonli" ? "z-green" : "z-yellow"}">${t("dmed_mode_" + d.mode)}</span>${d.address ? `<span class="small">${esc(d.address)}</span>` : ""}</div>
      <div class="card mb"><p>${t(d.mode === "jonli" ? "dmed_live_p" : "dmed_p")}</p>
        <div class="row-b mt"><input id="dq" type="text" placeholder="${t("dmed_patient")}" style="max-width:260px"><button class="btn" id="dsim">${t("dmed_btn")}</button></div></div>
      <div class="grid kpis mb">${kpi(d.received, t("dmed_in"))}${kpi(d.sent, t("dmed_out"))}${kpi(d.waiting, t("dmed_wait"), d.waiting ? "yellow" : "plain")}${kpi(d.failed, t("dmed_fail"), d.failed ? "red" : "plain")}</div>
      <div class="grid" style="grid-template-columns:repeat(auto-fit,minmax(340px,1fr))"><div class="card"><h2>${t("dmed_in")}</h2>${table(d.messages.filter((m) => m.direction === "in"))}</div>
        <div class="card"><h2>${t("dmed_out")}</h2>${table(d.messages.filter((m) => m.direction === "out"))}</div></div>`;
    $("#dsim").onclick = async () => {
      const q = $("#dq").value.trim();
      if (!q) return $("#dq").focus();
      const found = await api("/patients?" + new URLSearchParams({ q, limit: 1 }));
      if (!found.length) return toast(t("empty"));
      dmedEvent(found[0], dmedPage);
    };
    $("#app").onclick = (e) => {
      const m = e.target.closest("[data-m]");
      if (!m || e.target.closest("a")) return;
      const x = d.messages.find((y) => String(y.id) === m.dataset.m);
      const facts = dmedFacts(x.payload);
      modal(
        `<div class="dmed-head"><h2>${esc(kindTitle(x.kind))}</h2><span class="tag">FHIR ${esc(fhirType(x.kind))}</span></div>
        <p class="small">${x.direction === "in" ? "DMED → Mehr AI" : "Mehr AI → DMED"} · ${t("st_" + x.status)} · ${dt(x.sent_at || x.at)}${x.patient ? ` · <a href="#/bemor/${x.patient.id}" data-close>${esc(x.patient.name)}</a>` : ""}</p>
        ${x.error ? `<p class="err">${esc(x.error)}</p>` : ""}
        ${facts.length ? `<dl class="facts">${facts.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>` : `<p class="small">${esc(dmedSummary(x))}</p>`}
        <details class="raw mt"><summary>${t("dmed_payload")}</summary><pre class="json">${esc(JSON.stringify(x.payload, null, 1))}</pre></details>
        <div class="row-b mt"><button class="btn ghost" data-close>${t("close")}</button></div>`,
        "wide",
      );
    };
    refreshEvery(15000, dmedPage, () => document.activeElement?.id !== "dq");
  }

  /* ---------- router ---------- */
  async function route() {
    registryVersion++;
    clearTimeout(S.searchDelay);
    if (["#/haqida","#/haqida/","#/about","#/about/"].includes(location.hash)) history.replaceState(history.state,"",location.pathname + location.search + "#/");
    S.timers.forEach(clearInterval);
    S.timers = [];
    $("#app").onclick = null;
    shell();
    const [, r, id] = (location.hash || "#/").split("/");
    if (r !== "ovoz") voiceStudio.leave();
    try {
      if (r === "bemor") await patient(id);
      else if (r === "care") await window.MehrCare.render({root:$("#app"),api,lang:S.lang,id,role:S.role});
      else if (r === "ovoz") await voice();
      else if (r === "vazifalar") await tasks();
      else if (r === "qongiroqlar") await calls();
      else if (r === "dmed") await dmedPage();
      else await home();
    } catch (e) {
      if (e.message !== "auth") $("#app").innerHTML = `<div class="card">⚠ ${esc(e.message)}</div>`;
    }
  }
  async function boot() {
    document.documentElement.lang = S.lang;
    try {
      const r = await fetch("/api/meta");
      if (!r.ok) throw new Error(r.status);
      S.meta = await r.json();
    } catch {
      // the server did not answer: say so and let the user retry instead of an endless "loading"
      $("#app").innerHTML = `<div class="card login"><h2>${t("login_down")}</h2><div class="mt"><button class="btn" id="retry">${t("retry")}</button></div></div>`;
      $("#retry").onclick = boot;
      return;
    }
    try {
      S.me = await api("/me");
      if (S.meta.auth) S.role = S.me.role;
    } catch {
      return;
    }
    window.onhashchange = route;
    await route();
    voiceStudio.flush();
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
  // a failed button action must be visible, not silent
  window.addEventListener("unhandledrejection", (e) => {
    const msg = e.reason?.message;
    if (msg && msg !== "auth") toast(msg, 5000);
  });
  boot();
})();
