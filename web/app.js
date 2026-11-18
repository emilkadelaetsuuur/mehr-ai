/* Nigoh web app: registry, patient card, voice input with offline queue, tasks, AI calls. No build step. */
(() => {
  const $ = (s, r = document) => r.querySelector(s);
  const S = {
    lang: localStorage.lang || "uz",
    role: localStorage.role || "rahbar",
    meta: null,
    filter: { zone: "", kind: "", q: "", silent: 0 },
    voice: null,
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
  function toast(msg, ms = 3200) {
    document.querySelectorAll(".toast").forEach((e) => e.remove());
    const d = document.createElement("div");
    d.className = "toast";
    d.textContent = msg;
    document.body.appendChild(d);
    setTimeout(() => d.remove(), ms);
  }
  function modal(html) {
    closeModal();
    const m = document.createElement("div");
    m.className = "modal";
    m.innerHTML = `<div class="card">${html}</div>`;
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
  const kindLabel = (p) =>
    t(p.kind || "boshqa") +
    (p.kind === "homilador" && p.weeks ? `, ${p.weeks} ${t("weeks")}` : "") +
    (p.kind === "chaqaloq" && p.born_at ? `, ${Math.max(0, Math.floor((Date.now() - new Date(p.born_at)) / 864e5))} ${t("age_days")}` : "");
  const reasonText = (r) => (r ? `${esc(r[S.lang] || r.uz)} ${esc(r.value || "")}` : "—");

  /* ---------- shell ---------- */
  function shell() {
    const r = (location.hash || "#/").split("/")[1] || "";
    const tab = (h, k) => `<a href="#/${h}" class="${r === h ? "on" : ""}">${t(k)}</a>`;
    // with accounts on, the role comes from the signed-in user; the switch exists only in open demo mode
    const who = S.meta?.auth
      ? `<button id="me" title="${t("profile")}">${esc(S.me?.name || "")} · ${t("r_" + S.role)}</button>`
      : `<select id="role" title="${t("role")}">${["rahbar", "mutaxassis", "shifokor", "hamshira"].map((x) => `<option value="${x}" ${S.role === x ? "selected" : ""}>${t("r_" + x)}</option>`).join("")}</select>`;
    $("#top").innerHTML = `<a class="logo" href="#/"><span class="dots"><i></i><i></i><i></i></span>Nigoh</a>
      <span class="sub">${esc(S.meta?.district || "")}</span><span class="sp"></span>${who}<button id="lang">${S.lang === "uz" ? "RU" : "UZ"}</button>`;
    $("#nav").innerHTML =
      tab("", "nav_home") + tab("ovoz", "nav_voice") + tab("vazifalar", "nav_tasks") + tab("qongiroqlar", "nav_calls") + tab("haqida", "nav_about");
    if ($("#role"))
      $("#role").onchange = (e) => {
        S.role = localStorage.role = e.target.value;
        route();
      };
    if ($("#me")) $("#me").onclick = profile;
    $("#lang").onclick = () => {
      S.lang = localStorage.lang = S.lang === "uz" ? "ru" : "uz";
      document.documentElement.lang = S.lang;
      route();
    };
  }
  async function profile() {
    const me = (S.me = await api("/me")),
      tg = me.telegram;
    modal(`<h2>${esc(me.name)}</h2><p class="small">${esc(me.username)} · ${t("r_" + me.role)}${me.doctor ? " · " + esc(me.doctor) : ""}</p>
      <h3>${t("tg_h")}</h3><p>${tg.linked ? `<span class="badge z-green">${t("tg_on")}</span>` : tg.link ? `<a class="btn sm" target="_blank" rel="noopener" href="${tg.link}">${t("tg_link")}</a>` : `<span class="small">${t("tg_off")}</span>`}</p>
      <h3 class="mt">${t("pw_h")}</h3><label>${t("pw_old")}</label><input id="po" type="password"><label class="mt">${t("pw_new")}</label><input id="pn" type="password">
      <div class="row-b mt"><button class="btn" id="psave">${t("save")}</button><button class="btn ghost" id="pout">${t("logout")}</button><button class="btn ghost" data-close>${t("close")}</button></div>`);
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
  }
  function showLogin() {
    S.timers.forEach(clearInterval);
    S.timers = [];
    closeModal();
    $("#nav").innerHTML = "";
    $("#top").innerHTML = `<span class="logo"><span class="dots"><i></i><i></i><i></i></span>Nigoh</span><span class="sp"></span><button id="lang">${S.lang === "uz" ? "RU" : "UZ"}</button>`;
    $("#lang").onclick = () => {
      S.lang = localStorage.lang = S.lang === "uz" ? "ru" : "uz";
      document.documentElement.lang = S.lang;
      showLogin();
    };
    const accounts = S.meta?.accounts || [],
      last = localStorage.account || "";
    // a real form: the browser can save the password, Enter submits, the phone keyboard does not capitalise
    $("#app").innerHTML = `<form class="card login" id="lf" novalidate><h2>${t("login_h")}</h2><p class="small">${t("tagline")}</p>
      <label for="un">${t("account")}</label>${
        accounts.length
          ? `<select id="un" name="username" autocomplete="username">${accounts.map((a) => `<option value="${esc(a.username)}" ${a.username === last ? "selected" : ""}>${esc(a.name)} (${esc(a.username)})</option>`).join("")}</select>`
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
  async function home() {
    const [d, ps] = await Promise.all([api("/dashboard"), api("/patients?" + new URLSearchParams(S.filter))]);
    const kpi = (cls, v, label, f) => `<div class="card kpi ${cls}" ${f ? `data-f='${f}'` : ""}><b>${v ?? "—"}</b><span>${label}</span></div>`;
    const f = S.filter,
      chip = (k, v, label) => `<span class="chip ${f[k] === v ? "on" : ""}" data-k="${k}" data-v="${v}">${label}</span>`;
    $("#app").innerHTML = `
      <div class="row-b mb"><h1>${t("tagline")}</h1><span class="badge z-gray">${t("synthetic")}</span></div>
      <div class="grid kpis mb">
        ${kpi("red", d.zones.red, t("red"), '{"zone":"red"}')}${kpi("yellow", d.zones.yellow, t("yellow"), '{"zone":"yellow"}')}${kpi("green", d.zones.green, t("green"), '{"zone":"green"}')}
        ${kpi("plain", d.closed_in_time_pct == null ? "—" : d.closed_in_time_pct + "%", t("k_intime"))}${kpi("", d.tasks_overdue, t("k_overdue"), '{"go":"vazifalar"}')}
        ${kpi("", d.silent, t("k_silent"), '{"silent":1}')}${kpi("plain", d.verified, t("k_verified"))}${kpi("plain", d.mismatch, t("k_mismatch"))}
      </div>
      <div class="grid two">
        <div class="card"><div class="row-b"><h2>${t("patients")} · ${ps.length}</h2><span class="sp" style="flex:1"></span>
            <input id="q" type="text" placeholder="${t("search")}" value="${esc(f.q)}" style="max-width:200px">${can.lab() ? `<button class="btn sm ghost" id="lab">${t("lab_btn")}</button>` : ""}</div>
          <div class="chips">${chip("zone", "", t("all"))}${chip("zone", "red", t("zred"))}${chip("zone", "yellow", t("zyellow"))}${chip("zone", "green", t("zgreen"))}
            <span style="width:8px"></span>${chip("kind", "homilador", t("homilador"))}${chip("kind", "tuqqan", t("tuqqan"))}${chip("kind", "chaqaloq", t("chaqaloq"))}
            ${f.silent ? `<span class="chip on" data-k="silent" data-v="0">${t("k_silent")} ✕</span>` : ""}</div>
          <div class="tscroll"><table><thead><tr><th>${t("th_name")}</th><th>${t("th_zone")}</th><th>${t("th_why")}</th><th>${t("th_mahalla")}</th><th>${t("th_contact")}</th></tr></thead>
          <tbody>${
            ps
              .slice(0, 120)
              .map(
                (p) => `<tr class="row" data-p="${p.id}"><td><b>${esc(p.name)}</b><div class="small">${kindLabel(p)}</div></td><td>${zb(p.zone)}</td>
            <td>${reasonText(p.top)}</td><td>${esc(p.mahalla || "")}</td><td class="small">${ago(p.last_contact)}</td></tr>`,
              )
              .join("") || `<tr><td colspan="5" class="small">${t("empty")}</td></tr>`
          }</tbody></table></div></div>
        <div class="grid" style="align-content:start">
          ${d.demo?.length ? `<div class="card"><h2>${t("demo_h")}</h2>${d.demo.map((p, i) => `<div class="row-b" style="justify-content:space-between;padding:5px 0;cursor:pointer" data-p="${p.id}"><span><b>${esc(p.name)}</b><div class="small">${t("demo_" + i)}</div></span>${zb(p.zone)}</div>`).join("")}</div>` : ""}
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
    $("#q").onchange = (e) => {
      f.q = e.target.value.trim();
      home();
    };
    if ($("#lab")) $("#lab").onclick = () => labImport(home);
    $("#app").onclick = (e) => {
      const c = e.target.closest("[data-k]"),
        k = e.target.closest("[data-f]"),
        p = e.target.closest("[data-p]");
      if (c) {
        const v = c.dataset.v;
        f[c.dataset.k] = c.dataset.k === "silent" ? 0 : f[c.dataset.k] === v ? "" : v;
        home();
      } else if (k) {
        const o = JSON.parse(k.dataset.f);
        if (o.go) location.hash = "#/" + o.go;
        else {
          Object.assign(f, { zone: "", silent: 0 }, o);
          home();
        }
      } else if (p) location.hash = "#/bemor/" + p.dataset.p;
    };
    S.timers.push(
      setInterval(() => {
        if (document.activeElement?.id !== "q" && !document.querySelector(".modal")) home();
      }, 10000),
    );
  }

  /* ---------- patient card ---------- */
  const flagLabel = (c) => {
    const m = S.meta.complaints[c];
    return m
      ? L(m)
      : { unclear: t("unclear"), tashrif_tasdiqlanmadi: t("s_nomuvofiq"), noanswer: t("c_javobsiz"), ahvol: t("f_ahvol"), dori: t("f_dori"), fikr: t("f_fikr") }[
          c
        ] || c;
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
  const callRow = (
    c,
    withP,
  ) => `<div class="card mb" style="padding:11px"><div class="row-b" style="justify-content:space-between"><b>${esc(L(c.title))}</b>
      <span class="badge ${c.status === "tugadi" ? (c.flags?.length ? "z-red" : "z-green") : c.status === "javobsiz" ? "z-yellow" : "z-info"}">${t("c_" + c.status)}</span></div>
      ${withP && c.patient ? `<div><a href="#/bemor/${c.patient.id}"><b>${esc(c.patient.name)}</b></a></div>` : ""}
      <div class="small">${c.status === "tugadi" ? `${t("flags")}: ${(c.flags || []).map(flagLabel).join(", ") || t("no_flags")} · ${dt(c.finished_at)}` : `${t("planned")}: ${dt(c.planned_at)}`}</div>
      ${
        c.status === "tugadi"
          ? Object.entries(c.answers || {})
              .map(
                ([k, a]) =>
                  `<div class="small">${esc(k)}: <b>${a.value === "yes" ? t("yes") : a.value === "no" ? t("no") : a.value == null || a.value === "unclear" ? t("unclear") : esc(a.value)}</b>${a.transcript ? ` — <span class="quote">${esc(a.transcript)}</span>` : ""}</div>`,
              )
              .join("") +
            (c.closing
              ? `<div class="small mt">${t("closing_said")} <span class="badge z-gray">${t(c.closing_by === "claude" ? "closing_claude" : "closing_tpl")}</span>: <span class="quote">${esc(c.closing)}</span></div>`
              : "")
          : `<div class="mt"><button class="btn sm ghost" data-call='${esc(JSON.stringify({ url: c.url, id: c.id }))}'>${t("begin")}</button></div>`
      }</div>`;
  function showCall(url, title, text, id) {
    const phone = S.meta?.telephony && id ? `<button class="btn" id="dial">${t("dial")}</button>` : "";
    modal(`<h2>${title || t("call_qr")}</h2><p class="small">${text || t("call_qr_text")}</p><div class="center"><img src="/api/qr?u=${encodeURIComponent(url)}" alt="QR" style="width:230px;max-width:100%"></div>
      <div class="row-b mt">${phone}<a class="btn ${phone ? "ghost" : ""}" href="${url}" target="_blank" rel="noopener">${t("open_here")}</a><button class="btn ghost" id="cp">${t("copy")}</button><button class="btn ghost" data-close>${t("close")}</button></div>`);
    $("#cp").onclick = () => navigator.clipboard?.writeText(url).then(() => toast(t("copied")));
    if ($("#dial"))
      $("#dial").onclick = async () => {
        try {
          await api(`/calls/${id}/dial`, { method: "POST" });
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
        <div class="small">${kindLabel(p)}${p.birth_year && p.kind !== "chaqaloq" ? " · " + p.birth_year : ""} · ${esc(p.mahalla || "")} · ${esc(p.phone || "")} · ${t("doctor")}: ${esc(p.doctor || "—")} · ${t("th_contact")}: ${ago(p.last_contact)}</div>
        <div class="mt"><span class="badge ${p.consent ? "z-green" : "z-yellow"}">${t(p.consent ? "consent_yes" : "consent_no")}</span>${p.consent ? "" : ` <button class="btn sm ghost" id="bcons">${t("consent_btn")}</button>`}</div>
        ${p.diagnosis ? `<div class="mt"><span class="small">${t("diagnosis")}:</span> ${esc(p.diagnosis)}</div>` : ""}
        ${p.mother ? `<div class="mt small">${t("mother")}: <a href="#/bemor/${p.mother.id}">${esc(p.mother.name)}</a></div>` : ""}
        ${p.children.length ? `<div class="mt small">${t("children")}: ${p.children.map((k) => `<a href="#/bemor/${k.id}">${esc(k.name)}</a> ${zb(k.zone)}`).join(", ")}</div>` : ""}
        <div class="row-b mt"><button class="btn" id="bcall">${t("start_call")}</button><button class="btn ghost" id="bdis">${t("discharge")}</button>
          <a class="btn ghost" target="_blank" href="/api/patients/${p.id}/referral.pdf?lang=${S.lang}">${t("referral")}</a>
          <a class="btn ghost" target="_blank" href="/api/patients/${p.id}/fhir">${t("fhir")}</a></div></div>
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
        <div class="grid" style="align-content:start"><div><h2>${t("tasks")}</h2>${p.tasks.map((x) => taskRow(x)).join("") || `<p class="small">${t("empty")}</p>`}</div>
          <div><h2>${t("calls")}</h2>${p.calls.map((c) => callRow(c)).join("") || `<p class="small">${t("empty")}</p>`}</div>
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
    $("#bdis").onclick = async () => {
      await api(`/patients/${id}/discharge`, { json: {} });
      toast(t("discharge_done"));
      patient(id);
    };
    $("#bcall").onclick = () => {
      if (!p.consent) return toast(t("consent_need"), 4500);
      const sc = S.meta.scenarios.filter((s) => s.id !== "tashrif_tasdiq");
      const def = p.kind === "chaqaloq" ? "chaqaloq_30kun" : p.kind === "homilador" ? "homilador" : "chiqarishdan_keyin";
      modal(`<h2>${t("start_call")}</h2><label>${t("scenario")}</label><select id="sc">${sc.map((s) => `<option value="${s.id}" ${s.id === def ? "selected" : ""}>${esc(L(s.title))}</option>`).join("")}</select>
        <label class="mt">${t("speech_lang")}</label><select id="cl"><option value="uz">O'zbekcha</option><option value="ru">Русский</option></select>
        <div class="row-b mt"><button class="btn" id="mk">${t("begin")}</button><button class="btn ghost" data-close>${t("close")}</button></div>`);
      $("#mk").onclick = async () => {
        const c = await api(`/patients/${id}/calls`, { json: { scenario: $("#sc").value, lang: $("#cl").value } });
        showCall(c.url, null, null, c.id);
      };
    };
    $("#app").onclick = (e) => {
      const d = e.target.closest("[data-done]"),
        c = e.target.closest("[data-call]");
      if (d) markDone(d.dataset.done, () => patient(id));
      else if (c) showCall(JSON.parse(c.dataset.call).url, null, null, JSON.parse(c.dataset.call).id);
    };
    S.timers.push(
      setInterval(() => {
        if (!document.querySelector(".modal") && document.activeElement?.tagName !== "INPUT") patient(id);
      }, 15000),
    );
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
    S.timers.push(setInterval(() => !document.querySelector(".modal") && tasks(), 20000));
  }
  async function calls() {
    const rows = await api("/calls");
    const plan = rows.filter((c) => c.status !== "tugadi" && c.status !== "javobsiz"),
      done = rows.filter((c) => c.status === "tugadi" || c.status === "javobsiz");
    $("#app").innerHTML =
      `<h1>${t("nav_calls")}</h1><div class="grid two"><div><h2>${t("c_tugadi")} · ${done.length}</h2>${done.map((c) => callRow(c, 1)).join("") || `<p class="small">${t("empty")}</p>`}</div>
      <div><h2>${t("c_rejalashtirilgan")} · ${plan.length}</h2>${plan.map((c) => callRow(c, 1)).join("") || `<p class="small">${t("empty")}</p>`}</div></div>`;
    $("#app").onclick = (e) => {
      const c = e.target.closest("[data-call]");
      if (c) showCall(JSON.parse(c.dataset.call).url, null, null, JSON.parse(c.dataset.call).id);
    };
    S.timers.push(setInterval(() => !document.querySelector(".modal") && calls(), 12000));
  }

  /* ---------- voice input with offline queue ---------- */
  const idb = () =>
    new Promise((res, rej) => {
      const r = indexedDB.open("nigoh", 1);
      r.onupgradeneeded = () => r.result.createObjectStore("queue", { keyPath: "id", autoIncrement: true });
      r.onsuccess = () => res(r.result);
      r.onerror = () => rej(r.error);
    });
  const qAll = async () => {
    const d = await idb();
    return new Promise((res) => {
      const r = d.transaction("queue").objectStore("queue").getAll();
      r.onsuccess = () => res(r.result);
    });
  };
  const qPut = async (item) => {
    const d = await idb();
    return new Promise((res) => {
      d.transaction("queue", "readwrite").objectStore("queue").add(item).onsuccess = res;
    });
  };
  const qDel = async (id) => {
    const d = await idb();
    return new Promise((res) => {
      d.transaction("queue", "readwrite").objectStore("queue").delete(id).onsuccess = res;
    });
  };
  async function sendVoice(blob, lang) {
    const fd = new FormData();
    fd.append("audio", blob, "voice." + (blob.type.split("/")[1] || "webm").split(";")[0]);
    fd.append("lang", lang);
    return api("/voice", { method: "POST", body: fd });
  }
  async function flushQueue() {
    if (!navigator.onLine) return;
    for (const it of await qAll()) {
      try {
        const r = it.blob ? await sendVoice(it.blob, it.lang) : await api("/extract", { json: { text: it.text } });
        await qDel(it.id);
        S.voice = { res: r, t0: it.t0 };
        toast(t("queue_sent"));
        if (location.hash.startsWith("#/ovoz")) voice();
      } catch {
        break;
      }
    }
  }
  window.addEventListener("online", flushQueue);

  async function voice() {
    const V = S.voice,
      queued = await qAll().catch(() => []);
    const KINDS = ["homilador", "tuqqan", "chaqaloq", "boshqa"];
    let html = `<h1>${t("voice_h")}</h1>${!navigator.onLine || queued.length ? `<div class="offline">${t("offline")} ${t("queue")}: ${queued.length}</div>` : ""}
      <div class="grid two" style="grid-template-columns:minmax(280px,1fr) minmax(0,1.5fr)"><div class="card center" style="align-self:start"><p style="text-align:left">${t("voice_p")}</p><p class="small" style="text-align:left">${t("voice_ex")}</p>
        <div class="row-b" style="justify-content:center;margin:6px 0 14px"><label style="margin:0">${t("speech_lang")}</label><select id="vl" style="width:auto"><option value="uz">O'zbekcha</option><option value="ru">Русский</option><option value="auto">Auto</option></select></div>
        <button class="mic" id="mic">${t("rec_start")}</button><div class="small mt" id="vst"></div>
        <div style="text-align:left" class="mt"><label>${t("or_text")}</label><textarea id="vt"></textarea><button class="btn ghost mt" id="vp">${t("parse")}</button></div></div><div id="vres">`;
    if (V?.res) {
      const d = V.res.data,
        q = V.res.quotes || {},
        qq = (k) => (q[k] ? `<div class="quote">${esc(q[k])}</div>` : "");
      const inp = (k, label, type = "text") =>
        `<div><label>${label}</label><input type="${type}" data-f="${k}" value="${esc(d[k] ?? "")}">${qq(k === "bp_sys" || k === "bp_dia" ? "bp" : k)}</div>`;
      html += `<div class="card"><h2>${t("transcript")}</h2><p class="quote">${esc(V.res.transcript)}</p><div class="small">${t("engine_" + (V.res.engine === "llm" ? "llm" : "qoidalar"))}${V.res.stt_ms ? ` · STT ${V.res.stt_ms} ms` : ""}</div>
        ${V.res.dropped?.length ? `<div class="offline mt">${t("dropped")}: ${V.res.dropped.join(", ")}</div>` : ""}
        <h2 class="mt">${t("card")}</h2><div class="form">${inp("full_name", t("f_name"))}${inp("birth_year", t("f_year"), "number")}
          <div><label>${t("f_kind")}</label><select data-f="kind">${KINDS.map((k) => `<option value="${k}" ${d.kind === k ? "selected" : ""}>${t(k)}</option>`).join("")}</select>${qq("kind")}</div>
          ${inp("weeks", t("f_weeks"), "number")}${inp("mahalla", t("f_mahalla"))}${inp("phone", t("f_phone"))}${inp("bp_sys", t("sys"), "number")}${inp("bp_dia", t("dia"), "number")}
          ${inp("hb", t("hb"), "number")}${inp("glucose", t("glucose"), "number")}${inp("temp", t("temp"), "number")}${inp("pulse", t("pulse"), "number")}</div>
        <div class="form mt" style="grid-template-columns:1fr 1fr">${inp("diagnosis", t("diagnosis"))}${inp("referral", t("f_ref"))}</div>
        <label class="mt">${t("complaints")}</label><div class="chips">${Object.entries(S.meta.complaints)
          .map(
            ([c, m]) =>
              `<span class="chip ${d.complaints?.includes(c) ? "on" : ""}" data-c="${c}" title="${esc(q.complaints?.[c] || "")}">${esc(L(m))}</span>`,
          )
          .join("")}</div>
        ${Object.entries(q.complaints || {})
          .map(([c, s]) => `<div class="small">${esc(L(S.meta.complaints[c]))}: <span class="quote">${esc(s)}</span></div>`)
          .join("")}
        <label class="mt" style="display:flex;gap:8px;align-items:flex-start;font-size:14px;color:var(--text)"><input type="checkbox" id="vcons" style="width:auto;margin-top:3px"> ${t("consent_chk")}</label>
        <div class="mt"><button class="btn" id="vok">${t("confirm")}</button></div></div>`;
    } else if (V?.saved) {
      const s = V.saved;
      html += `<div class="card"><h2>${t("saved")} ${zb(s.zone)}</h2>${s.reasons.map((r) => `<div class="reason ${r.zone}"><b>${reasonText(r)}</b>${r.quote ? `<div class="quote">${esc(r.quote)}</div>` : ""}</div>`).join("") || `<p>${t("why_none")}</p>`}
        ${V.sec ? `<p><b>${t("elapsed")}: ${V.sec} ${t("sec")}</b></p>` : ""}<div class="row-b"><a class="btn" href="#/bemor/${s.id}">${t("open_card")}</a>
        <a class="btn ghost" target="_blank" href="/api/patients/${s.id}/referral.pdf?lang=${S.lang}&to=${encodeURIComponent(s.referral || "")}">${t("referral")}</a></div></div>`;
    }
    $("#app").innerHTML = html + `</div></div>`;
    const st = (m) => ($("#vst").textContent = m);
    let rec = null,
      chunks = [],
      t0 = 0;
    const handle = async (fn, item) => {
      st(t("processing"));
      try {
        if (!navigator.onLine) throw new Error("offline");
        S.voice = { res: await fn(), t0 };
        voice();
      } catch (e) {
        if (!navigator.onLine || /Failed to fetch|offline|NetworkError/i.test(e.message)) {
          await qPut({ ...item, t0 });
          toast(t("offline"), 5000);
          voice();
        } else st(t("stt_fail"));
      }
    };
    $("#mic").onclick = async () => {
      if (rec) {
        rec.stop();
        return;
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        rec = new MediaRecorder(stream);
        chunks = [];
        t0 = Date.now();
        rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
        rec.onstop = () => {
          stream.getTracks().forEach((x) => x.stop());
          const blob = new Blob(chunks, { type: rec.mimeType || "audio/webm" }),
            lang = $("#vl").value;
          rec = null;
          $("#mic").classList.remove("rec");
          $("#mic").textContent = t("rec_start");
          handle(() => sendVoice(blob, lang), { blob, lang });
        };
        rec.start();
        $("#mic").classList.add("rec");
        $("#mic").textContent = t("rec_stop");
        st("● REC");
      } catch {
        st(t("no_mic"));
      }
    };
    $("#vp").onclick = () => {
      const text = $("#vt").value.trim();
      if (!text) return;
      t0 = Date.now();
      handle(() => api("/extract", { json: { text } }), { text });
    };
    if ($("#vok")) {
      $("#vres").onclick = (e) => {
        const c = e.target.closest("[data-c]");
        if (c) c.classList.toggle("on");
      };
      $("#vok").onclick = async () => {
        const fields = {};
        document.querySelectorAll("[data-f]").forEach((i) => {
          if (i.value !== "") fields[i.dataset.f] = i.type === "number" ? +i.value : i.value;
        });
        fields.complaints = [...document.querySelectorAll("[data-c].on")].map((c) => c.dataset.c);
        if (!fields.full_name) return toast(t("f_name") + "?");
        const saved = await api("/patients/confirm", {
          json: { fields, quotes: V.res.quotes, transcript: V.res.transcript, author: t("r_" + S.role), consent: $("#vcons").checked },
        });
        S.voice = { saved, sec: V.t0 ? Math.round((Date.now() - V.t0) / 1000) : 0 };
        voice();
      };
    }
  }

  /* ---------- about ---------- */
  async function about() {
    const m = (S.meta = await api("/meta")),
      R = m.rules,
      vl = m.voicelab,
      row = (a, y, r) => `<tr><td>${a}</td><td>${y}</td><td>${r}</td></tr>`;
    $("#app").innerHTML = `<h1>${t("about_h")}</h1><div class="grid two"><div class="grid" style="align-content:start">
      <div class="card"><ol class="steps">${[1, 2, 3, 4, 5].map((i) => `<li>${t("about_" + i)}</li>`).join("")}</ol></div>
      <div class="card"><h2>${t("rules_h")} · v${esc(R.version)}</h2><div class="tscroll"><table><thead><tr><th>${t("ind")}</th><th>${t("zyellow")}</th><th>${t("zred")}</th></tr></thead><tbody>
        ${row(t("bp"), "≥ " + R.bp.yellow.join("/"), "≥ " + R.bp.red.join("/"))}${row(t("hb"), "< " + R.hb.yellow_below + "; ↓ ≥ " + R.hb.drop_yellow, "< " + R.hb.red_below)}
        ${row(t("glucose"), "≥ " + R.glucose.yellow_from, "≥ " + R.glucose.red_from)}${row(t("temp"), "≥ " + R.temp_adult.yellow_from, "≥ " + R.temp_adult.red_from)}
        ${row(t("chaqaloq") + ": " + t("temp"), "—", "≥ " + R.newborn_temp.red_from + " / < " + R.newborn_temp.red_below)}${row(t("th_contact"), "≥ " + R.silent_days.yellow, "≥ " + R.silent_days.red)}
        ${row(t("complaints"), R.yellow_complaints.map((c) => L(m.complaints[c])).join(", "), R.red_complaints.map((c) => L(m.complaints[c])).join(", "))}</tbody></table></div><p class="small mt">${t("rules_note")}</p></div>
      <div class="card"><h2>${t("scen_h")}</h2>${m.scenarios.map((s) => `<div class="reason"><b>${esc(L(s.title))}</b> · ${s.questions} ${t("qn")}<div class="small">${t("basis")}: ${esc(s.basis)}</div></div>`).join("")}</div></div>
      <div class="grid" style="align-content:start"><div class="card"><h2>${t("ai_h")}</h2>
        <p><b>${t("ai_stt")}:</b> VoiceLab — <span class="badge ${vl.enabled ? "z-green" : "z-yellow"}">${vl.enabled ? t("ai_on") : t("ai_off")}</span></p>
        <p><b>${t("ai_llm")}:</b> ${esc(vl.model || "—")}</p>
        <p><b>${t("ai_closing")}:</b> ${m.claude?.enabled ? `Claude (${esc(m.claude.model)}) — <span class="badge z-green">${t("ai_on")}</span>` : t("closing_tpl")}</p>
        <p><b>${t("ai_ml")}:</b> ${m.ml ? `${m.ml.records} ${t("records")}; ${t("acc")}: <b>${Math.round(m.ml.accuracy * 100)}%</b>; ${t("rec_red")}: <b>${Math.round(m.ml.recall_red * 100)}%</b>` : "—"}</p>
        <h3 class="mt">${t("eval_h")}</h3><p class="small">${t("eval_note")}</p>${
          m.eval
            ? `<p><b>${m.eval.fields_ok}/${m.eval.fields_total} ${t("fields_ok")} (${Math.round((100 * m.eval.fields_ok) / m.eval.fields_total)}%)</b> · ${m.eval.phrases} ${t("phrases")} · ${esc(m.eval.date)}</p>
          <div class="tscroll"><table><tbody>${m.eval.by_lang.map((x) => `<tr><td>${x.lang}</td><td>${x.ok}/${x.total}</td><td>${Math.round((100 * x.ok) / x.total)}%</td></tr>`).join("")}</tbody></table></div>`
            : `<p class="small">${t("eval_none")}</p>`
        }</div>
      <div class="card"><h2>${t("law_h")}</h2><ol class="steps">${[1, 2, 3, 4].map((i) => `<li>${t("law_" + i)}</li>`).join("")}</ol></div>
      ${can.reset() ? `<div class="card"><button class="btn ghost" id="rs">${t("reset")}</button></div>` : ""}</div></div>`;
    if ($("#rs"))
      $("#rs").onclick = async () => {
        if (confirm(t("sure"))) {
          await api("/demo/reset", { method: "POST" });
          toast(t("reset_ok"));
        }
      };
  }

  /* ---------- router ---------- */
  async function route() {
    S.timers.forEach(clearInterval);
    S.timers = [];
    $("#app").onclick = null;
    shell();
    const [, r, id] = (location.hash || "#/").split("/");
    try {
      if (r === "bemor") await patient(id);
      else if (r === "ovoz") await voice();
      else if (r === "vazifalar") await tasks();
      else if (r === "qongiroqlar") await calls();
      else if (r === "haqida") await about();
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
    flushQueue();
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
  // a failed button action must be visible, not silent
  window.addEventListener("unhandledrejection", (e) => {
    const msg = e.reason?.message;
    if (msg && msg !== "auth") toast(msg, 5000);
  });
  boot();
})();
