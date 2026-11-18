(() => {
  const clockText = milliseconds => {
    const seconds = Math.max(0, Math.floor(milliseconds / 1000));
    return [Math.floor(seconds / 60), seconds % 60].map(n => String(n).padStart(2, "0")).join(":");
  };

  // A still sound ribbon introduces the recorder. While recording, the line is drawn
  // exclusively from the microphone's time-domain samples.
  function mountWave(canvas, analyser, recording) {
    if (!canvas) return () => {};
    const ctx = canvas.getContext("2d");
    if (!ctx) return () => {};
    const samples = analyser ? new Uint8Array(analyser.fftSize) : null;
    const motion = matchMedia("(prefers-reduced-motion: reduce)");
    let frame = 0, last = 0;
    function paint() {
      const w = canvas.clientWidth, h = canvas.clientHeight;
      if (!w || !h) return;
      const ratio = Math.min(devicePixelRatio || 1, 2);
      if (canvas.width !== Math.round(w * ratio) || canvas.height !== Math.round(h * ratio)) {
        canvas.width = Math.round(w * ratio);
        canvas.height = Math.round(h * ratio);
      }
      ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
      ctx.clearRect(0, 0, w, h);
      const mid = h / 2;
      const ink = ctx.createLinearGradient(0, 0, w, 0);
      for (const [at, color] of [[0,"#90e0ef"],[.20,"#00b4d8"],[.43,"#0077b6"],[.61,"#03045e"],[.83,"#0077b6"],[1,"#90e0ef"]]) ink.addColorStop(at,color);
      ctx.strokeStyle = ink;
      ctx.lineJoin = "round";
      if (recording) {
        if (samples) analyser.getByteTimeDomainData(samples);
        ctx.lineWidth = 2.25;
        ctx.beginPath();
        const n = samples ? samples.length : 2;
        for (let i = 0; i < n; i++) {
          const amplitude = samples ? (samples[i] - 128) / 128 : 0;
          const x = w * i / (n - 1), y = mid - amplitude * h * .47;
          if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
        }
        ctx.stroke();
        return;
      }
      const steps = Math.ceil(w / 3);
      for (let row = 0; row < 41; row++) {
        const lane = (row - 20) / 20;
        ctx.globalAlpha = .45 + .31 * (1 - Math.abs(lane));
        ctx.lineWidth = w < 480 ? .83 : 1.08;
        ctx.beginPath();
        for (let i = 0; i <= steps; i++) {
          const x = i / steps;
          const bump = (center, spread) => Math.exp(-((x - center) ** 2) / spread);
          const envelope = (.42 * bump(.26,.010) + .98 * bump(.50,.019) + .50 * bump(.72,.012)) * Math.sin(Math.PI*x);
          const ridge = Math.sin(17.5*x - .8 + lane*1.9) + .37*Math.sin(32*x + lane*2.6 - .2);
          const y = mid + h*.29*envelope*(ridge + lane*.73);
          if (i === 0) ctx.moveTo(0,y); else ctx.lineTo(w*x,y);
        }
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
    }
    function tick(now) {
      if (now - last > (motion.matches ? 240 : 34)) { paint(); last = now; }
      frame = requestAnimationFrame(tick);
    }
    const observer = new ResizeObserver(paint);
    observer.observe(canvas);
    paint();
    if (recording && analyser) frame = requestAnimationFrame(tick);
    return () => { observer.disconnect(); cancelAnimationFrame(frame); };
  }

  function create(env) {
    const {root, t, esc, L, icon, api} = env;
    let visible = false, session = 0, capture = 0, flushing = false;
    let mode = "mic", language = "", phase = "idle", message = "";
    let draft = null, saved = null, previousReview = null, queued = 0, elapsed = 0;
    let recorder = null, stream = null, audio = null, analyser = null, timer = 0, since = 0;
    let stopWave = () => {}, writes = Promise.resolve();
    let interview = freshInterview(), durable = false;
    const field = id => root.querySelector("#" + id);
    const staff = () => env.account() || "";
    const own = item => !item.owner || item.owner === staff();
    const inView = () => visible && location.hash.split("/")[1] === "ovoz";
    const audioLanguage = () => language || env.interfaceLanguage();
    const langName = code => ({ru:"Русский", uz:"O‘zbekcha", auto:t("studio_auto")})[code] || "";
    const choose = (value, current) => value === current ? " selected" : "";
    const questions = () => env.questions().filter(q => !q.kind || q.kind === interview.kind);
    const answer = key => (interview.answers[key] || "").trim();
    const hasAnswer = key => Boolean(answer(key) || interview.clips[key]);
    const canReview = () => answer("full_name").length >= 2 || !!interview.clips.full_name;
    const stageDescription = () => t(({permission:"studio_permission",recording:"studio_recording",processing:"processing",preparing:"studio_preparing"})[phase] || "studio_idle");

    function freshInterview() {
      const token = globalThis.crypto?.randomUUID?.() || Date.now().toString(36) + Math.random().toString(36).slice(2);
      return {id:"exam-"+token, type:"exam", kind:"", current:"full_name", answers:{}, clips:{}, skipped:[], ready:false, t0:0};
    }
    function queueLine() {
      const el = field("studio-queue");
      if (!el) return;
      el.textContent = [navigator.onLine ? "" : t("studio_offline"), queued ? t("queue")+" · "+queued : ""].filter(Boolean).join("  ·  ");
      el.hidden = !el.textContent;
    }
    function redraw(focusId = "") {
      if (!inView()) return;
      stopWave();
      const title = saved ? "studio_saved" : draft ? "studio_review" : "studio_title";
      const intro = draft ? "studio_review_intro" : "studio_intro";
      root.innerHTML = `<section class="voice-studio" aria-labelledby="studio-title">
        <header class="studio-header"><div><h1 id="studio-title" tabindex="-1">${t(title)}</h1>${saved ? "" : `<p>${t(intro)}</p>`}</div>
        ${draft || saved ? "" : `<label class="guide-kind"><span>${t("guide_kind")}</span><select id="guide-kind" ${phase!=="idle"?"disabled":""}>
          ${["","homilador","tuqqan","chaqaloq","bola"].map(k=>`<option value="${k}"${choose(k,interview.kind)}>${t(k || "guide_general")}</option>`).join("")}</select></label>`}</header>
        <p id="studio-queue" class="studio-notice" role="status" hidden></p>
        ${saved ? savedView() : draft ? reviewView() : inputView()}
        </section>`;
      queueLine();
      if (saved) wireSaved();
      else if (draft) wireReview();
      else wireInput();
      if (focusId) field(focusId)?.focus({preventScroll:true});
    }
    function newPage() {
      if (!inView()) return;
      redraw("studio-title");
      window.scrollTo({top:0,behavior:"instant"});
    }
    function stepButton(q,locked) {
      const current = q.id===interview.current;
      return `<li><button type="button" class="guide-step" data-question="${q.id}" ${current?'aria-current="step"':""} ${locked?"disabled":""}>
        <span class="guide-number" aria-hidden="true"></span><span>${esc(L(q))}</span></button></li>`;
    }
    function inputView() {
      const list=questions(), index=list.findIndex(q=>q.id===interview.current), q=list[index];
      const locked=phase!=="idle", clip=interview.clips[q.id];
      return `<div class="guide-board">
        <aside class="guide-index" aria-labelledby="guide-index-heading"><header><h2 id="guide-index-heading" tabindex="-1">${t("guide_list")}</h2><span id="guide-count"></span></header>
          <progress id="guide-progress" max="${list.length}" value="0" aria-label="${t("guide_answered")}"></progress>
          <ol>${list.map(row=>stepButton(row,locked)).join("")}</ol>
          <button type="button" id="guide-review" class="studio-secondary" ${locked?"disabled":""}>${icon("note")}${t("guide_review")}</button>
        </aside>
        <section class="guide-current" aria-labelledby="guide-question">
          <div class="guide-meta"><span>${t("guide_question")} ${index+1} ${t("guide_of")} ${list.length}${q.id==="full_name"?" · "+t("guide_mandatory"):""}</span><button class="guide-jump" id="guide-jump" type="button">${t("guide_all")} ↓</button></div>
          <h2 id="guide-question" tabindex="-1">${esc(L(q))}</h2>
          <div class="studio-toolbar"><div class="studio-tabs" role="tablist" aria-label="${t("studio_input")}">${["mic","text"].map(m=>`<button id="tab-${m}" type="button" role="tab" aria-controls="guide-editor" aria-selected="${mode===m}" tabindex="${mode===m?0:-1}" ${locked?"disabled":""}>${icon(m==="mic"?"mic":"keyboard")}${t("studio_"+m)}</button>`).join("")}</div>
            <label class="studio-language" for="vl" ${mode==="text"?"hidden":""}>${icon("globe")}<span>${t("speech_lang")}</span>
            <select id="vl" ${locked?"disabled":""}>${["ru","uz","auto"].map(v=>`<option value="${v}"${choose(v,audioLanguage())}>${langName(v)}</option>`).join("")}</select></label>
          </div>
          <div id="guide-editor" role="tabpanel" aria-labelledby="tab-${mode}">
            ${mode==="mic" ? `<div class="studio-stage" data-state="${phase}">
              <div class="studio-instruments"><span class="studio-status" role="status"><i></i>${stageDescription()}</span><span class="studio-clock">${icon("clock")}<time id="studio-time">${clockText(elapsed)}</time></span></div>
              <div class="studio-scope" aria-hidden="true"><canvas id="studio-wave"></canvas></div>
              <div class="studio-transport"><button type="button" class="studio-primary" id="mic" ${(locked&&phase!=="recording")||clip?"disabled":""}>
              ${icon(phase==="recording"?"stop":"mic")}<span>${t(phase==="recording"?"studio_stop":answer(q.id)?"guide_more":"guide_record")}</span></button></div></div>` : ""}
            <div class="guide-answer"><label for="vt">${t("guide_answer")}</label>
              <textarea id="vt" aria-describedby="guide-question" aria-required="${q.id==="full_name"}" maxlength="${q.id==="full_name"?160:4000}" rows="3" placeholder="${t(mode==="mic"?"guide_placeholder":"guide_type_answer")}" ${locked?"readonly":""}>${esc(interview.answers[q.id] || "")}</textarea>
            </div>
            ${clip ? `<div class="guide-clip"><span>${t("guide_waiting")}</span><button id="guide-retry" type="button" ${locked?"disabled":""}>${t("guide_retry")}</button><button id="guide-drop" type="button" ${locked?"disabled":""}>${t("guide_remove_audio")}</button></div>` : ""}
          </div>
          <p class="studio-feedback" role="status" ${message?"":"hidden"}>${message?t(message):""}</p>
          <div class="guide-actions"><button type="button" class="studio-secondary" id="guide-prev" ${locked||!index?"disabled":""}>${icon("chevron-left")}${t("guide_previous")}</button>
            <button type="button" class="studio-primary" id="guide-next" ${locked?"disabled":""}><span></span>${icon("chevron-right")}</button></div>
        </section></div>`;
    }
    function paintProgress() {
      const list=questions(), done=list.filter(q=>hasAnswer(q.id)).length;
      field("guide-count").textContent=done+" / "+list.length;
      field("guide-progress").value=done;
      for (const [i,btn] of [...root.querySelectorAll("[data-question]")].entries()) {
        const q=list[i], state=hasAnswer(q.id)?"answered":interview.skipped.includes(q.id)?"skipped":"open";
        btn.dataset.status=state;
        btn.querySelector(".guide-number").innerHTML=state==="answered"?icon("check"):state==="skipped"?"–":String(i+1);
        btn.setAttribute("aria-label",(i+1)+". "+L(q)+(state==="open"?"":" · "+t("guide_"+state)));
      }
      const id=interview.current, last=list.at(-1).id===id, locked=phase!=="idle";
      const next=field("guide-next");
      next.disabled=locked || (id==="full_name" && !canReview()) || (last && !canReview());
      next.querySelector("span").textContent=t(last?"guide_review":id==="full_name"||hasAnswer(id)?"guide_next":"guide_skip");
      field("guide-review").disabled=locked || !canReview();
      const mic=field("mic");
      if (mic && phase==="idle") mic.querySelector("span").textContent=t(answer(id)?"guide_more":"guide_record");
    }
    function goTo(key) {
      if (phase!=="idle") return;
      interview.current=key; elapsed=0; message=""; persistIfNeeded();
      redraw("guide-question");
      if (inView() && field("guide-jump").getClientRects().length) field("guide-question").scrollIntoView({block:"start"});
    }
    function changed() {
      previousReview=null; interview.ready=false; interview.t0 ||= Date.now();
      persistIfNeeded();
    }
    function wireInput() {
      const list=questions(), id=interview.current, idx=list.findIndex(q=>q.id===id);
      for (const btn of root.querySelectorAll("[data-question]")) btn.onclick=()=>goTo(btn.dataset.question);
      field("guide-jump").onclick=()=>{const title=field("guide-index-heading");title.focus({preventScroll:true});title.scrollIntoView({block:"start"});};
      field("guide-kind").onchange=e=>{
        interview.kind=e.target.value;
        if (!questions().some(q=>q.id===id)) interview.current="full_name";
        message=""; changed(); redraw("guide-kind");
      };
      for (const tab of root.querySelectorAll('[role="tab"]')) {
        const select=m=>{if(phase==="idle"){mode=m;message="";redraw("tab-"+m);}};
        tab.onclick=()=>select(tab.id.slice(4));
        tab.onkeydown=e=>{
          if (!["ArrowLeft","ArrowRight","Home","End"].includes(e.key)) return;
          e.preventDefault();select(e.key==="Home"?"mic":e.key==="End"?"text":mode==="mic"?"text":"mic");
        };
      }
      field("vt").oninput=e=>{
        interview.answers[id]=e.target.value;
        if(answer(id)) interview.skipped=interview.skipped.filter(key=>key!==id);
        if (["guide_required","guide_length","guide_offline_ready","studio_text_fail"].includes(message)) {
          message=""; root.querySelector(".studio-feedback").hidden=true;
        }
        changed(); paintProgress();
      };
      field("vl").onchange=e=>{language=e.target.value;};
      if (field("mic")) {
        field("mic").onclick=()=>phase==="recording"?finishRecording():startRecording();
        stopWave=mountWave(field("studio-wave"),analyser,phase==="recording");
      }
      if (field("guide-retry")) field("guide-retry").onclick=()=>resumeAudio(id);
      if (field("guide-drop")) field("guide-drop").onclick=()=>{delete interview.clips[id];message="";changed();redraw("vt");};
      field("guide-prev").onclick=()=>goTo(list[idx-1].id);
      field("guide-next").onclick=()=>{
        if(!hasAnswer(id) && !interview.skipped.includes(id)) interview.skipped.push(id);
        if(idx===list.length-1) prepare();
        else goTo(list[idx+1].id);
      };
      field("guide-review").onclick=prepare;
      paintProgress();
    }
    function reviewView() {
      const {res, fields, consent} = draft;
      const source = res.answers ? `<dl class="guide-source">${env.questions().filter(q=>res.answers[q.id]).map(q=>
        `<dt>${esc(L(q))}</dt><dd>${esc(res.answers[q.id])}</dd>`).join("")}</dl>` : `<blockquote>${esc(res.transcript)}</blockquote>`;
      const quote = key => res.quotes?.[key] ? `<small class="studio-quote">${esc(res.quotes[key])}</small>` : "";
      const input = (key, label, type="text", attrs="") => `<label class="studio-field"><span>${t(label)}</span>
        <input name="${key}" type="${type}" ${attrs} value="${esc(fields[key] ?? "")}">${quote(key.startsWith("bp_")?"bp":key)}</label>`;
      const kinds = ["homilador","tuqqan","chaqaloq","bola","boshqa"];
      return `<div class="studio-review-grid"><aside class="studio-source"><div class="studio-section-title">${icon("note")}<h2>${t(res.answers?"guide_replies":"studio_source")}</h2></div>
        ${source}
        ${res.answers ? `<button class="studio-secondary" type="button" id="guide-back" ${phase==="saving"?"disabled":""}>${t("guide_back")}</button>` : ""}
        <p class="studio-method">${t(res.engine==="llm"?"engine_llm":"engine_qoidalar")}${res.stt_ms ? " · STT "+esc(res.stt_ms)+" ms" : ""}</p>
        ${res.dropped?.length ? `<p class="studio-notice">${t("dropped")} · ${esc(res.dropped.join(", "))}</p>` : ""}</aside>
        <form id="studio-form" class="studio-form">
          <fieldset><legend>${t("card")}</legend><div class="studio-fields">
            ${input("full_name","f_name","text",'required minlength="2" maxlength="160"')}${input("birth_year","f_year","number",'min="1930" max="2100"')}
            <label class="studio-field"><span>${t("f_kind")}</span><select name="kind"><option value="">—</option>${kinds.map(k=>`<option value="${k}"${choose(k,fields.kind)}>${t(k)}</option>`).join("")}</select>${quote("kind")}</label>
            ${input("weeks","f_weeks","number",'min="1" max="45"')}${input("mahalla","f_mahalla","text",'maxlength="80"')}${input("phone","f_phone","tel",'maxlength="40"')}
          </div></fieldset>
          <fieldset><legend>${t("studio_exam")}</legend><div class="studio-fields">
            ${input("bp_sys","sys","number",'min="40" max="300" step="any"')}${input("bp_dia","dia","number",'min="20" max="200" step="any"')}
            ${input("hb","hb","number",'min="20" max="250" step="any"')}${input("glucose","glucose","number",'min="0.5" max="60" step="any"')}
            ${input("temp","temp","number",'min="30" max="43" step="any"')}${input("pulse","pulse","number",'min="20" max="260" step="any"')}
            ${input("diagnosis","diagnosis","text",'maxlength="240"')}${input("referral","f_ref","text",'maxlength="120"')}
          </div></fieldset>
          <fieldset><legend>${t("complaints")}</legend><div class="studio-chips">${Object.entries(env.complaints()).map(([key, item])=>`<label title="${esc(res.quotes?.complaints?.[key]||"")}"><input name="complaints" type="checkbox" value="${esc(key)}" ${fields.complaints?.includes(key)?"checked":""}><span>${esc(L(item))}</span></label>`).join("")}</div>
          ${Object.entries(res.quotes?.complaints || {}).map(([key,value])=>`<p class="studio-quote">${esc(L(env.complaints()[key]) || key)} · ${esc(value)}</p>`).join("")}</fieldset>
          <label class="studio-consent"><input id="vcons" type="checkbox" ${consent?"checked":""}>${t("consent_chk")}</label>
          <p class="studio-feedback" role="alert" ${message?"":"hidden"}>${message?t(message):""}</p>
          <div class="studio-form-actions"><button id="vok" class="studio-primary" type="submit" ${phase==="saving"?"disabled":""}>${icon("check")}${t(phase==="saving"?"studio_saving":"confirm")}</button>
          <button class="studio-secondary" id="studio-discard" type="button" ${phase==="saving"?"disabled":""}>${t("studio_discard")}</button></div>
        </form></div>`;
    }
    function wireReview() {
      const form=field("studio-form");
      const weeks=form.elements.namedItem("weeks");
      const showRelevantFields=()=>{
        if (!draft.res.answers) return;
        const pregnant=form.elements.namedItem("kind").value==="homilador";
        weeks.disabled=!pregnant;
        weeks.closest("label").hidden=!pregnant;
      };
      showRelevantFields();
      if(field("guide-back")) field("guide-back").onclick=()=>{
        if(phase!=="idle") return;
        previousReview=draft; draft=null; interview.ready=false; message=""; persistIfNeeded(); newPage();
      };
      const sync = () => {
        for (const input of form.querySelectorAll("[name]:not([type=checkbox])")) draft.fields[input.name]=input.value;
        draft.fields.complaints = [...form.querySelectorAll("[name=complaints]:checked")].map(box=>box.value);
        draft.consent=field("vcons").checked;
      };
      if (phase==="saving") for (const group of form.querySelectorAll("fieldset,#vcons")) group.disabled=true;
      form.oninput=sync;
      form.onchange=()=>{ showRelevantFields(); sync(); };
      form.onsubmit=async e=>{
        e.preventDefault();
        if (phase!=="idle") return;
        sync();
        const fields={...draft.fields}, current=session, entry=draft;
        for (const input of form.querySelectorAll("input[name],select[name]")) {
          if (input.type==="checkbox") continue;
          if (input.disabled || !String(fields[input.name] ?? "").trim()) delete fields[input.name];
          else if (input.type==="number") fields[input.name]=Number(fields[input.name]);
        }
        const quotes={...entry.res.quotes};
        if (weeks.disabled) delete quotes.weeks;
        phase="saving"; message="";
        for (const group of form.querySelectorAll("fieldset,#vcons")) group.disabled=true;
        field("vok").disabled=true; field("vok").textContent=t("studio_saving");field("studio-discard").disabled=true;
        try {
          const row=await api("/patients/confirm",{json:{fields,quotes,transcript:entry.res.transcript,author:t("r_"+env.role()),consent:entry.consent}});
          if (current!==session) return;
          saved={row,seconds:Math.max(0,Math.round((Date.now()-entry.t0)/1000))};
          draft=null; previousReview=null; phase="idle";
          if (entry.queueId != null) await dropQueue(entry.queueId).catch(()=>{});
          if (current!==session) return;
          newPage(); countQueue();
        } catch {
          if (current!==session) return;
          phase="idle"; message="studio_save_fail"; redraw("vok");
        }
      };
      field("studio-discard").onclick=async()=>{
        if (phase!=="idle" || !window.confirm(t("studio_discard_check"))) return;
        const current=session;
        if (draft.queueId != null) {
          try { await dropQueue(draft.queueId); }
          catch { if (current===session) { message="studio_queue_fail"; redraw(); } return; }
        }
        if (current!==session) return;
        clearInput(); newPage(); flush();
      };
    }
    function savedView() {
      const {row,seconds}=saved;
      return `<div class="studio-done"><span class="studio-success">${icon("check")}</span><div>
        <h2>${t("card")} ${env.zoneBadge(row.zone)}</h2>
        ${row.reasons?.length ? row.reasons.map(r=>`<p>${env.reasonText(r)}${r.quote?`<small class="studio-quote">${esc(r.quote)}</small>`:""}</p>`).join("") : `<p>${t("why_none")}</p>`}
        ${seconds?`<p class="studio-method">${t("elapsed")} · ${seconds} ${t("sec")}</p>`:""}
        <div class="studio-form-actions"><a class="studio-primary" href="#/bemor/${encodeURIComponent(row.id)}">${t("open_card")}</a>
        <a class="studio-secondary" href="/api/patients/${encodeURIComponent(row.id)}/referral.pdf?lang=${env.interfaceLanguage()}&amp;to=${encodeURIComponent(row.referral||"")}" target="_blank" rel="noopener">${t("referral")}</a>
        <button type="button" class="studio-secondary" id="studio-new">${t("studio_new")}</button></div></div></div>`;
    }
    function wireSaved() { field("studio-new").onclick=()=>{ clearInput(); newPage(); flush(); }; }

    function clearInput() {
      interview=freshInterview(); durable=false; previousReview=null;
      elapsed=0; draft=null; saved=null; phase="idle"; message="";
    }
    function receive(res, queueId, started) {
      draft={res, fields:{...res.data}, consent:false, t0:started || Date.now(), queueId};
      saved=null; phase="idle"; message=""; newPage();
    }
    function touched() {
      return Boolean(interview.t0 || Object.keys(interview.clips).length || interview.skipped.length);
    }
    function persistIfNeeded(force=false) {
      if (!force && !durable && (navigator.onLine || !touched())) return Promise.resolve(true);
      const current=session, g=interview;
      durable=true;
      const row={...g,owner:staff(),speech:language,answers:{...g.answers},clips:{...g.clips},skipped:[...g.skipped]};
      writes=writes.catch(()=>{}).then(()=>env.putQueue(row));
      return writes.then(()=>true,()=>{
        if (current===session && g===interview) {
          message="studio_queue_fail";
          const note=root.querySelector(".studio-feedback");
          if(inView() && note){note.hidden=false;note.textContent=t(message);}
        }
        return false;
      });
    }
    async function dropQueue(id) {
      await writes.catch(()=>{});
      return env.deleteQueue(id);
    }
    async function countQueue() {
      const current=session;
      try {
        const entries=await env.listQueue();
        if (current!==session) return;
        queued=entries.filter(row=>own(row) && row.id!==interview.id && row.id!==draft?.queueId).length;
        queueLine();
      } catch { /* online interviews can proceed when browser storage is unavailable */ }
    }
    async function transcribe(id) {
      const current=session, g=interview, clip=g.clips[id];
      const res=await env.sendVoice(clip.blob,clip.lang,true);
      if (current!==session || g!==interview || clip!==g.clips[id]) return false;
      if (!res.transcript?.trim()) throw Error("empty transcript");
      g.answers[id]=[answer(id),res.transcript.trim()].filter(Boolean).join(" ");
      delete g.clips[id];
      g.skipped=g.skipped.filter(key=>key!==id);
      await persistIfNeeded();
      return true;
    }
    async function resumeAudio(id) {
      if (!interview.clips[id] || phase!=="idle") return false;
      const current=session;
      phase="processing"; message=""; redraw();
      try {
        if (!navigator.onLine) throw Error("offline");
        if (!await transcribe(id) || current!==session) return false;
        phase="idle"; redraw();
        return true;
      } catch {
        if (current!==session) return false;
        phase="idle"; message=navigator.onLine?"stt_fail":"studio_offline";
        await persistIfNeeded(true);
        if (current===session) redraw();
        return false;
      }
    }
    async function prepare() {
      if (phase!=="idle" || draft || saved) return;
      if (previousReview) {draft=previousReview;previousReview=null;newPage();return;}
      const current=session, g=interview, list=questions();
      if(!canReview()){g.current="full_name";message="guide_required";redraw("vt");return;}
      g.ready=true;
      if (!navigator.onLine) {
        phase="preparing"; redraw();
        const ok=await persistIfNeeded(true);
        if(current===session){phase="idle";message=ok?"guide_offline_ready":"studio_queue_fail";redraw();}
        return;
      }
      phase="preparing"; message=""; redraw();
      if (durable) await persistIfNeeded();
      if (current!==session || g!==interview) return;
      let clipId="";
      try {
        for(const q of list){
          if(!g.clips[q.id]) continue;
          clipId=q.id;
          if(!await transcribe(q.id) || current!==session) return;
          clipId="";
        }
        const answers=Object.fromEntries(list.filter(q=>answer(q.id)).map(q=>[q.id,answer(q.id)]));
        if(!answers.full_name || answers.full_name.length<2 || answers.full_name.length>160) throw Error("patient_name");
        const res=await api("/voice/draft",{json:{answers,kind:g.kind || null,lang:env.interfaceLanguage()}});
        if (current!==session || g!==interview) return;
        receive(res,durable?g.id:null,g.t0);
        countQueue();
      } catch (e) {
        if (current!==session || g!==interview) return;
        phase="idle"; g.ready=false;
        if (!navigator.onLine || /Failed to fetch|NetworkError|Load failed/i.test(e.message)) {
          g.ready=true; const ok=await persistIfNeeded(true);
          if (current!==session) return;
          message=ok?"guide_offline_ready":"studio_queue_fail";
        } else if(clipId){g.current=clipId;message="stt_fail";await persistIfNeeded(true);}
        else {
          if(e.message.includes("patient_name")){g.current="full_name";message="guide_required";}
          else message=e.message.includes("answers_too_long")?"guide_length":"studio_text_fail";
          if(durable) await persistIfNeeded();
        }
        if(current===session) redraw();
      }
    }
    async function flush() {
      if (!staff() || flushing || draft || saved || phase!=="idle") return;
      const current=session;
      flushing=true;
      try {
        await writes.catch(()=>{});
        const entries=(await env.listQueue()).filter(own);
        if (current!==session || draft || saved || phase!=="idle") return;
        if (!durable && !touched() && entries.length) {
          const row=entries[0];
          if (row.type==="exam") {
            interview={...freshInterview(),...row}; language=row.speech || ""; durable=true;
            if(!questions().some(q=>q.id===interview.current)) interview.current="full_name";
            redraw();
          } else if(navigator.onLine) {
            // Recordings queued by the earlier free-dictation screen are still reviewable.
            const res=row.blob?await env.sendVoice(row.blob,row.lang):await api("/extract",{json:{text:row.text,lang:row.lang || audioLanguage()}});
            if(current===session && !touched() && !draft && !saved && phase==="idle") receive(res,row.id,row.t0);
            return;
          }
        }
        if(!navigator.onLine) return;
        if(interview.ready) await prepare();
        else {
          for(const q of questions()){
            if(current!==session || phase!=="idle" || draft || saved) break;
            if(interview.clips[q.id] && !await resumeAudio(q.id)) break;
          }
        }
      } catch { /* an unsent entry stays on the device for the next connection */ }
      finally { if(current===session){flushing=false;countQueue();} }
    }
    function releaseAudio() {
      clearInterval(timer); timer=0;
      stream?.getTracks().forEach(track=>track.stop());
      stream=null; analyser=null;
      if (audio) { audio.close().catch(()=>{}); audio=null; }
      recorder=null;
    }
    function cancelRecording() {
      ++capture;
      if (recorder) {
        recorder.onstop=null; recorder.ondataavailable=null; recorder.onerror=null;
        if (recorder.state!=="inactive") recorder.stop();
      }
      releaseAudio(); phase="idle"; elapsed=0;
    }
    async function startRecording() {
      if (phase!=="idle") return;
      const id=++capture, current=session;
      const spoken=audioLanguage(), questionId=interview.current;
      phase="permission"; message=""; elapsed=0; redraw();
      try {
        if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) throw new Error("microphone");
        const requested=await navigator.mediaDevices.getUserMedia({audio:true});
        if (id!==capture || current!==session || !inView()) { requested.getTracks().forEach(track=>track.stop()); return; }
        stream=requested;
        const rec=new MediaRecorder(stream), chunks=[];
        recorder=rec;
        try {
          const AC=window.AudioContext || window.webkitAudioContext;
          audio=new AC(); analyser=audio.createAnalyser(); analyser.fftSize=1024;
          audio.createMediaStreamSource(stream).connect(analyser);
          audio.resume().catch(()=>{});
        } catch { analyser=null; }
        const started=Date.now();
        rec.ondataavailable=e=>{ if(e.data.size) chunks.push(e.data); };
        rec.onerror=()=>{
          if (id!==capture || current!==session) return;
          cancelRecording(); message="no_mic"; redraw("mic");
        };
        rec.onstop=()=>{
          if (id!==capture || current!==session) return;
          const blob=new Blob(chunks,{type:rec.mimeType || chunks[0]?.type || "audio/webm"});
          elapsed=Date.now()-started;
          releaseAudio();
          if (blob.size<=800 || blob.size>15*1024*1024) {
            phase="idle"; message=blob.size<=800?"studio_short":"studio_long"; redraw("mic"); return;
          }
          interview.clips[questionId]={blob,lang:spoken};
          interview.t0 ||= started; previousReview=null; interview.ready=false;
          interview.skipped=interview.skipped.filter(key=>key!==questionId);
          phase="idle"; resumeAudio(questionId);
        };
        rec.start(1000); since=started; phase="recording"; redraw("mic");
        timer=setInterval(()=>{
          elapsed=Date.now()-since;
          const clock=field("studio-time"); if(clock) clock.textContent=clockText(elapsed);
        },250);
      } catch {
        if (id!==capture || current!==session) return;
        cancelRecording(); message="no_mic"; redraw("mic");
      }
    }
    function finishRecording() {
      if (!recorder || recorder.state==="inactive") return;
      phase="processing"; elapsed=Date.now()-since; clearInterval(timer);
      recorder.stop(); redraw();
    }
    function open() { visible=true; redraw(); flush(); }
    function leave() {
      visible=false; stopWave(); stopWave=()=>{};
      if (phase==="permission" || phase==="recording") cancelRecording();
    }
    function reset() {
      ++session; leave(); cancelRecording(); clearInput(); language=""; mode="mic"; queued=0; flushing=false;
    }
    window.addEventListener("offline",queueLine);
    window.addEventListener("pageshow",e=>{ if(e.persisted && location.hash.split("/")[1]==="ovoz" && staff()) open(); });
    return {open,leave,reset,flush};
  }
  window.MehrVoiceStudio={create};
})();
