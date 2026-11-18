/* Patient side of an AI call. Opens from a link or QR; in production the same dialogue runs over a phone line.
   Questions are pre-synthesised (cached WAV), answers are recorded, recognised (Uzbek/Russian STT) and classified. */
(() => {
  // "Line" mode: this page is the voice of a real phone call. A program next to a phone with a SIM card opens
  // it when the person called picks up; the computer's speakers and microphone are joined to that phone.
  // Nobody looks at this screen and nobody can press its buttons, so everything goes by voice.
  const opts = new URLSearchParams(location.search),
    LINE = opts.get("line") === "1",
    VAD = Number(opts.get("vad")) || 6; // how loud counts as speech; a quiet line may need a lower number
  const token = location.pathname.split("/").pop(),
    box = document.getElementById("call"),
    player = document.getElementById("player");
  const T = {
    uz: {
      incoming: "Kiruvchi qo'ng'iroq",
      from: "Poliklinika · Nigoh AI yordamchi",
      accept: "Javob berish",
      decline: "Rad etish",
      listen: "Tinglayapman… javob bering",
      tap: "Mikrofon ishlamayapti — javobni tugma bilan tanlang",
      wait: "Savol o'qilmoqda…",
      yes: "Ha",
      no: "Yo'q",
      done: "Qo'ng'iroq tugadi",
      thanks: "Rahmat!",
      ai: "Men sun'iy intellektman: tashxis qo'ymayman va davo tayinlamayman. Maslahatlarim JSST tavsiyalari asosidagi eslatmadan. Shoshilinch holatda 103 ga qo'ng'iroq qiling.",
      missed: "Qo'ng'iroq qabul qilinmadi. Uchta urinishdan keyin hamshiraga uyga borish vazifasi beriladi.",
      heard: "Eshitildi",
      ended: "Bu qo'ng'iroq allaqachon yakunlangan.",
      idk: "Bilmayman",
      send: "Yuborish",
      proc: "Javoblar qayta ishlanmoqda…",
      again: "Qayta qo'ng'iroq",
      oper: "Operator bilan gaplashish",
      oper_h: "So'rovingiz qabul qilindi",
      call_now: "Hozir qo'ng'iroq qilish:",
      ask_h: "Sizning savolingiz",
      no_q: "Savolim yo'q",
      finish: "Tugatdim",
      type_here: "Savolingizni yoki shifokorga aytmoqchi bo'lgan gapingizni shu yerga yozing",
      src: "Manba",
      tips_h: "Qisqa maslahatlar",
      to_doctor: "Oilaviy shifokoringizga yuborildi",
      to_nurse: "Patronaj hamshirasiga yuborildi",
    },
    ru: {
      incoming: "Входящий звонок",
      from: "Поликлиника · ИИ-помощник Nigoh",
      accept: "Ответить",
      decline: "Отклонить",
      listen: "Слушаю… отвечайте",
      tap: "Микрофон недоступен — выберите ответ кнопкой",
      wait: "Читаю вопрос…",
      yes: "Да",
      no: "Нет",
      done: "Звонок завершён",
      thanks: "Спасибо!",
      ai: "Я искусственный интеллект: диагнозов не ставлю и лечение не назначаю. Советы — из памятки по рекомендациям ВОЗ. В экстренном случае звоните 103.",
      missed: "Звонок не принят. После трёх попыток медсестра получит задачу навестить на дому.",
      heard: "Услышано",
      ended: "Этот звонок уже завершён.",
      idk: "Не знаю",
      send: "Отправить",
      proc: "Обрабатываю ответы…",
      again: "Позвонить снова",
      oper: "Поговорить с сотрудником",
      oper_h: "Запрос принят",
      call_now: "Позвонить сейчас:",
      ask_h: "Ваш вопрос",
      no_q: "Вопросов нет",
      finish: "Готово",
      type_here: "Напишите здесь ваш вопрос или то, что передать врачу",
      src: "Источник",
      tips_h: "Короткие советы",
      to_doctor: "Передано вашему семейному врачу",
      to_nurse: "Передано патронажной медсестре",
    },
  };
  let info,
    t,
    stream,
    ctx,
    ringTimer,
    pending = [];
  const esc = (s) => String(s ?? "").replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]);

  function ring(on) {
    clearInterval(ringTimer);
    if (!on) return;
    const beep = () => {
      try {
        ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
        [0, 0.35].forEach((d) => {
          const o = ctx.createOscillator(),
            g = ctx.createGain();
          o.frequency.value = 520;
          g.gain.value = 0.07;
          o.connect(g);
          g.connect(ctx.destination);
          o.start(ctx.currentTime + d);
          o.stop(ctx.currentTime + d + 0.22);
        });
      } catch {}
    };
    beep();
    ringTimer = setInterval(beep, 2200);
  }
  const src = (part) => `/api/call/${token}/audio/${part}${part.includes("?") ? "&" : "?"}l=${info.lang}`;
  const play = (part, text) =>
    new Promise((res) => {
      let done = false;
      const fin = () => {
        if (!done) {
          done = true;
          res();
        }
      };
      if (!info.tts) return setTimeout(fin, Math.min(6000, 1200 + text.length * 45));
      player.src = src(part);
      player.onended = fin;
      player.onerror = () => setTimeout(fin, 1200 + text.length * 45);
      player.play().catch(() => setTimeout(fin, 1200 + text.length * 45));
    });

  function record(maxMs = 9000, quietMs = 1300, idleMs = 0) {
    // resolves with a Blob, or null if the patient used a button instead; with `idleMs`, also null when she
    // did not begin to speak within that time (an open question may simply have no answer)
    return new Promise((res) => {
      if (!stream) return res(null);
      const rec = new MediaRecorder(stream),
        chunks = [];
      let finished = false,
        spoke = false,
        silence = 0,
        waited = 0;
      const an = ctx.createAnalyser(),
        src = ctx.createMediaStreamSource(stream),
        buf = new Uint8Array(1024);
      an.fftSize = 1024;
      src.connect(an);
      const stop = () => {
        if (!finished) {
          finished = true;
          clearInterval(iv);
          clearTimeout(to);
          try {
            rec.stop();
          } catch {}
        }
      };
      rec.ondataavailable = (e) => e.data.size && chunks.push(e.data);
      rec.onstop = () => {
        try {
          src.disconnect();
        } catch {}
        res(record.cancel || (idleMs && !spoke) ? null : new Blob(chunks, { type: rec.mimeType || "audio/webm" }));
      };
      const bar = document.querySelector(".bar i");
      const iv = setInterval(() => {
        an.getByteTimeDomainData(buf);
        let s = 0;
        for (const v of buf) s += (v - 128) * (v - 128);
        const rms = Math.sqrt(s / buf.length);
        if (bar) bar.style.width = Math.min(100, rms * 6) + "%";
        if (rms > VAD) {
          spoke = true;
          silence = 0;
        } else if (spoke && (silence += 100) >= quietMs) stop();
        else if (!spoke && idleMs && (waited += 100) >= idleMs) stop();
      }, 100);
      const to = setTimeout(stop, maxMs);
      record.cancel = false;
      record.stop = stop;
      rec.start();
    });
  }
  const ext = (blob) => (blob.type.split("/")[1] || "webm").split(";")[0];
  const post = (qid, blob, value, to = "answer") => {
    const fd = new FormData();
    fd.append("qid", qid);
    if (blob) fd.append("audio", blob, "a." + ext(blob));
    else fd.append("value", value);
    return fetch(`/api/call/${token}/${to}`, { method: "POST", body: fd })
      .then((r) => r.json())
      .catch(() => ({}));
  };

  const say = (key) => (info.tts && info.say && info.say[key] ? play("say_" + key, info.say[key]) : Promise.resolve());
  const beep = () => {
    try {
      const o = ctx.createOscillator(),
        g = ctx.createGain();
      o.frequency.value = 880;
      g.gain.value = 0.08;
      o.connect(g);
      g.connect(ctx.destination);
      o.start();
      o.stop(ctx.currentTime + 0.18);
    } catch {}
  };
  // One question. Resolves with what was understood: {value, flagged, voice} or {operator: true}.
  // `q.to` names where the answer goes when the question is not one of the scenario's (the identity check).
  async function ask(q, label) {
    const num = q.type === "number";
    box.innerHTML = `<div><div class="ai-note">${label}</div><div class="avatar">N</div></div><div class="qtext">${esc(q.text)}</div>
      <div><div class="listen" id="st">${t.wait}</div><div class="bar"><i></i></div><div class="ans mt">${num ? `<button data-v="idk">${t.idk}</button>` : `<button data-v="yes">${t.yes}</button><button data-v="no">${t.no}</button>`}</div>
      <div class="heard mt" id="heard"></div><button class="oper" id="op">☎ ${t.oper}</button></div><div class="ai-note">${t.ai}</div>`;
    let btn = null,
      blob = null,
      tapped = () => {};
    const choose = (v) => {
      btn = v;
      record.cancel = true;
      record.stop && record.stop();
      player.pause();
      player.onended && player.onended();
      tapped();
    };
    box.querySelectorAll("[data-v]").forEach((b) => (b.onclick = () => choose(b.dataset.v)));
    document.getElementById("op").onclick = () => choose("operator");
    await play(q.audio || q.id, q.text);
    if (btn === null && stream) {
      document.getElementById("st").textContent = t.listen;
      blob = await record(num ? 8000 : 7000);
    } else if (btn === null) {
      // no microphone (refused or absent): the question waits for a tap instead of rushing on as "unclear"
      document.getElementById("st").textContent = t.tap;
      document.querySelector(".bar").style.display = "none";
      if (num) {
        const row = document.createElement("div");
        row.className = "ans mt";
        row.innerHTML = `<input id="nv" type="number" inputmode="decimal" step="0.1" style="width:120px;font-size:18px;text-align:center;border-radius:12px;padding:10px"><button id="ns">${t.send}</button>`;
        box.querySelector(".ans").after(row);
        document.getElementById("ns").onclick = () => document.getElementById("nv").value && choose(document.getElementById("nv").value);
      }
      await new Promise((res) => {
        tapped = res;
        setTimeout(res, 45000);
      });
    }
    if (btn === "operator") return { operator: true };
    const spoken = btn === null && blob && blob.size > 800;
    const sent = spoken ? post(q.id, blob, null, q.to) : post(q.id, null, btn === null ? "unclear" : btn === "idk" ? "" : btn, q.to);
    pending.push(sent);
    const r = await sent; // the next words depend on what was understood
    const h = document.getElementById("heard");
    if (spoken && h && r.transcript) h.textContent = `${t.heard}: «${r.transcript}»`;
    return r.operator ? { operator: true, said: r.transcript } : { value: r.value, flagged: r.flagged, voice: spoken };
  }

  const onLine = (state) => {
    const fd = new FormData();
    fd.append("state", state);
    return fetch(`/api/call/${token}/line`, { method: "POST", body: fd }).catch(() => {});
  };
  const hangUp = () => {
    stream && stream.getTracks().forEach((x) => x.stop());
    if (LINE) onLine("done"); // the last word is spoken: the phone may hang up now
  };

  // The caller asked for a person: staff get a task to ring back; the answers given so far are kept.
  async function operator(said) {
    const fd = new FormData();
    fd.append("said", said || "");
    const r = await fetch(`/api/call/${token}/operator`, { method: "POST", body: fd })
      .then((x) => x.json())
      .catch(() => ({}));
    await Promise.all(pending);
    fetch(`/api/call/${token}/finish?quiet=1`, { method: "POST" }).catch(() => {});
    box.innerHTML = `<div><div class="avatar">☎</div><h1>${t.oper_h}</h1></div><div class="qtext">${esc(info.say.operator_ok)}</div>
      <div>${r.phone ? `<a class="oper" href="tel:${r.phone.replace(/[^+\d]/g, "")}">${t.call_now} ${esc(r.phone)}</a>` : ""}</div><div class="ai-note">${t.ai}</div>`;
    await say("operator_ok");
    hangUp();
  }

  // The call opens by making sure the right person picked up: nothing about health is said before her "yes".
  async function identity() {
    const q = { id: "shaxs", to: "identity", audio: "hello", text: info.hello, type: "yesno" };
    let r = await ask(q, t.from);
    if (!r.operator && r.value !== "yes" && r.value !== "no") r = await ask({ ...q, audio: "say_who_retry", text: info.say.who_retry }, t.from);
    return r;
  }

  // A call that must reach nobody but the patient asks a second key after the name: the year of birth.
  async function year() {
    const q = { id: "yil", to: "identity", audio: "say_who_year", text: info.say.who_year, type: "number" };
    let r = await ask(q, t.from);
    if (!r.operator && r.value === "unclear") r = await ask(q, t.from);
    return r;
  }

  // For a first-time mother: the leaflet's main points, offered once and read only if she wants them.
  async function tips() {
    const key = info.tips.offer;
    const want = await ask({ id: "maslahat", to: "hear", audio: "say_" + key, text: info.say[key], type: "yesno" }, t.tips_h);
    if (want.operator) return want;
    if (want.value !== "yes") return;
    const texts = info.tips.texts;
    if (info.tts) texts.forEach((_, i) => fetch(src(`tip?i=${i}`)).catch(() => {}));
    for (let i = 0; i < texts.length; i++) {
      box.innerHTML = `<div><div class="ai-note">${t.tips_h} · ${i + 1} / ${texts.length}</div><div class="avatar ring">N</div></div><div class="qtext">${esc(texts[i])}</div><div class="ai-note">${t.ai}</div>`;
      await play(`tip?i=${i}`, texts[i]);
    }
  }

  // Somebody else picked up, or nobody could be understood: a polite end, and the call is made again later.
  async function goodbye(key) {
    await Promise.all(pending);
    if (key === "who_fail") fetch(`/api/call/${token}/noanswer`, { method: "POST" }).catch(() => {});
    box.innerHTML = `<div><div class="avatar">N</div><h1>${t.done}</h1></div><div class="qtext">${esc(info.say[key])}</div><div class="ai-note">${t.ai}</div>`;
    await play("say_" + key, info.say[key]);
    hangUp();
  }

  // Her own questions, in her own words. An answer is worded from the polyclinic's leaflet; what the leaflet
  // does not answer goes to her doctor as a message; a warning sign raises the alarm. Up to three questions.
  // Resolves with {operator, said} if she asked for a person instead.
  async function talk() {
    let key = info.ask_key || "ask_q"; // the invitation is worded for whom the call is for
    for (let asked = 0, misses = 0; asked < (info.max_questions || 3) && misses < 2; ) {
      const fd = new FormData();
      let pick = null,
        got = false,
        tapped = () => {};
      box.innerHTML = `<div><div class="ai-note">${t.ask_h}</div><div class="avatar ring">N</div></div><div class="qtext">${esc(info.say[key])}</div>
        <div>${stream ? `<div class="listen" id="st">${t.wait}</div><div class="bar"><i></i></div>` : `<textarea id="msg" rows="3" placeholder="${t.type_here}"></textarea>`}
        <div class="ans mt"><button data-v="none">${t.no_q}</button><button data-v="done">${stream ? t.finish : t.send}</button></div>
        <button class="oper" id="op">☎ ${t.oper}</button></div><div class="ai-note">${t.ai}</div>`;
      const choose = (v) => {
        pick = v;
        record.cancel = v !== "done"; // "done" keeps what was said; the other buttons throw it away
        record.stop && record.stop();
        player.pause();
        player.onended && player.onended();
        tapped();
      };
      box.querySelectorAll("[data-v]").forEach((b) => (b.onclick = () => choose(b.dataset.v)));
      document.getElementById("op").onclick = () => choose("operator");
      await play("say_" + key, info.say[key]);
      if (stream) {
        if (pick === "done") pick = null; // pressed during the prompt: it only cuts the prompt short
        if (pick === null) {
          beep();
          document.getElementById("st").textContent = t.listen;
          const blob = await record(30000, 2000, 7000); // a pause of two seconds or the button ends it; silence means no question
          if (blob && blob.size > 800) {
            fd.append("audio", blob, "q." + ext(blob));
            got = true;
          }
        }
      } else {
        // no microphone: the question can be typed
        if (pick === null)
          await new Promise((res) => {
            tapped = res;
            setTimeout(res, 120000);
          });
        const typed = pick === "done" ? document.getElementById("msg").value.trim() : "";
        if (typed) {
          fd.append("text", typed);
          got = true;
        }
      }
      if (pick === "operator") return { operator: true };
      if (pick === "none" || !got) return;
      box.innerHTML = `<div><div class="avatar ring">N</div></div><div class="qtext">${t.proc}</div><div class="ai-note">${t.ai}</div>`;
      const reply = fetch(`/api/call/${token}/ask`, { method: "POST", body: fd })
        .then((x) => x.json())
        .catch(() => ({}));
      // Finding the answer takes a few seconds: she hears "one moment" instead of silence.
      if ((await Promise.race([reply, new Promise((res) => setTimeout(() => res(null), 1500))])) === null) await say("ask_wait");
      const r = await reply;
      if (r.kind === "operator") return { operator: true, said: r.transcript };
      if (r.kind === "none") return;
      if (r.kind === "go") {
        key = "ask_go";
        continue;
      }
      if (!["answer", "doctor", "alarm"].includes(r.kind)) {
        key = "ask_retry"; // nothing was heard: one more try, like a person would ask again
        misses++;
        continue;
      }
      asked++;
      key = "ask_more";
      const fixed = r.kind === "alarm" ? "ask_alarm" : r.to === "hamshira" ? "ask_nurse" : "ask_doctor";
      const notes = [
        r.source && r.source.length ? `${t.src}: ${esc(r.source.join("; "))}` : "",
        r.to ? `${r.to === "hamshira" ? t.to_nurse : t.to_doctor}${r.doctor ? ": " + esc(r.doctor) : ""}` : "",
      ].filter(Boolean);
      box.innerHTML = `<div><div class="ai-note">${t.heard}: «${esc(r.transcript)}»</div><div class="avatar">${r.kind === "alarm" ? "!" : r.kind === "answer" ? "N" : "✓"}</div></div>
        <div class="qtext">${esc(r.kind === "answer" ? r.answer : info.say[fixed])}</div><div class="ai-note">${notes.join(" · ") || t.ai}</div>`;
      if (r.kind === "answer") {
        // spoken sentence by sentence: the later ones are synthesised while the first plays
        if (info.tts) r.parts.slice(1).forEach((_, i) => fetch(src(`reply?n=${r.n}&i=${i + 1}`)).catch(() => {}));
        for (let i = 0; i < r.parts.length; i++) await play(`reply?n=${r.n}&i=${i}`, r.parts[i]);
        if (r.to) await say("ask_told");
      } else await play("say_" + fixed, info.say[fixed]);
    }
  }

  async function run() {
    ring(false);
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: opts.get("ec") !== "0", noiseSuppression: !LINE || opts.get("ns") === "1" } });
    } catch {
      stream = null;
    }
    if (LINE && !stream) {
      // without a microphone the line cannot hear the person called: say so and let the phone hang up
      box.innerHTML = `<div></div><div class="qtext">Mikrofon topilmadi · Микрофон не найден</div><div></div>`;
      return onLine("nomic");
    }
    if (LINE && opts.get("hold") === "1") {
      // Opened while the phone is still ringing: everything is made ready now, so that the first word is
      // spoken the moment the person picks up and not after the browser has finished starting.
      ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
      if (ctx.state === "suspended") await ctx.resume();
      fetch(src("hello")).catch(() => {});
      box.innerHTML = `<div><div class="avatar ring">N</div></div><div class="qtext">…</div><div></div>`;
      await onLine("ready");
      for (;;) {
        const r = await fetch(`/api/call/${token}/line`)
          .then((x) => x.json())
          .catch(() => ({}));
        if (r.go) break;
        await new Promise((res) => setTimeout(res, 400));
      }
    }
    if (LINE) onLine("talking");
    ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
    if (ctx.state === "suspended") await ctx.resume();
    if (LINE) onLine("speaking: greeting");
    const who = await identity();
    if (LINE) onLine(`spoken: greeting, it is her: ${who.operator ? "operator" : who.value}`);
    if (who.operator) return operator(who.said);
    if (who.value !== "yes") return goodbye(who.value === "no" ? "who_no" : "who_fail");
    if (info.verify_year) {
      const born = await year();
      if (born.operator) return operator(born.said);
      if (born.value !== "yes") return goodbye(born.value === "no" ? "who_year_no" : "who_fail");
    }
    box.innerHTML = `<div><div class="avatar ring">N</div><h1>Nigoh</h1></div><div class="qtext">${esc(info.intro)}</div><div class="ai-note">${t.ai}</div>`;
    await play("intro", info.intro);
    await say("hint");
    let human = null,
      acks = 0,
      asked = 0;
    const got = {}; // what was understood so far: some questions are asked only after a certain answer
    for (let i = 0; i < info.questions.length; i++) {
      const q = info.questions[i];
      if (q.if && Object.entries(q.if).some(([id, value]) => got[id] !== value)) continue;
      const label = `${++asked}`;
      let r = await ask(q, label);
      if (!r.operator && r.voice && r.value === "unclear" && q.type !== "number") {
        await say("retry"); // one more try, like a person would ask again; then the call moves on
        r = await ask(q, label);
      }
      if (r.operator) {
        human = r;
        break;
      }
      got[q.id] = r.value;
      await say(r.flagged ? "ack_flag" : "ack" + (1 + (acks++ % 3))); // a short reaction before the next question
    }
    if (!human && info.tips) human = (await tips()) || null;
    if (!human) human = (await talk()) || null;
    if (human) return operator(human.said);
    box.innerHTML = `<div><div class="avatar">N</div></div><div class="qtext">${t.proc}</div><div></div>`;
    const finished = Promise.all(pending)
      .then(() => fetch(`/api/call/${token}/finish`, { method: "POST" }))
      .then((r) => r.json())
      .catch(() => ({}));
    // While the closing words are being written the caller hears a short "one moment" instead of silence.
    if (info.bridge && info.tts) await play("bridge", info.bridge);
    const res = await finished;
    const fixed = res.alert || res.verified === false ? "closing_alert" : "closing_ok";
    const text = res.closing || info[fixed];
    const parts = res.closing_parts && res.closing_parts.length ? res.closing_parts : null;
    box.innerHTML = `<div><div class="avatar">${res.alert ? "!" : "✓"}</div><h1>${t.done}</h1></div><div class="qtext">${esc(text)}</div><div class="ai-note">${t.ai}</div>`;
    if (parts && info.tts) {
      // Written closings are spoken sentence by sentence: the later ones are synthesised while the first plays.
      parts.slice(1).forEach((_, i) => fetch(src(`closing?i=${i + 1}`)).catch(() => {}));
      for (let i = 0; i < parts.length; i++) await play(`closing?i=${i}`, parts[i]);
    } else await play(res.closing ? "closing" : fixed, text);
    hangUp();
  }

  async function init() {
    info = await fetch(`/api/call/${token}`)
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null);
    if (!info) {
      box.innerHTML = `<div></div><div class="qtext">404</div><div></div>`;
      return;
    }
    t = T[info.lang] || T.uz;
    document.documentElement.lang = info.lang;
    if (info.status === "tugadi") {
      box.innerHTML = `<div><div class="avatar">✓</div></div><div class="qtext">${t.ended}</div><div class="ai-note">${t.ai}</div>`;
      if (LINE) onLine("done");
      return;
    }
    // The greeting names the patient, so it cannot be prepared for everyone in advance: it is made while the phone rings.
    if (info.tts) ["hello", "intro"].forEach((part) => fetch(src(part)).catch(() => {}));
    if (LINE) return run(); // the person has already picked up the phone: start talking
    box.innerHTML = `<div><div class="ai-note">${t.incoming}</div><div class="avatar ring">N</div><h1>Nigoh</h1><div>${t.from}</div><div class="ai-note mt">${esc(info.title)}</div></div>
      <div style="display:flex;gap:70px"><div><button class="cbtn dec" id="dec">✕</button><div class="ai-note mt">${t.decline}</div></div><div><button class="cbtn acc" id="acc">✆</button><div class="ai-note mt">${t.accept}</div></div></div><div class="ai-note">${t.ai}</div>`;
    document.body.addEventListener("pointerdown", () => ring(true), { once: true });
    document.getElementById("acc").onclick = run;
    document.getElementById("dec").onclick = async () => {
      ring(false);
      await fetch(`/api/call/${token}/noanswer`, { method: "POST" }).catch(() => {});
      box.innerHTML = `<div><div class="avatar">✕</div></div><div class="qtext">${t.missed}</div><div><button class="cbtn acc" onclick="location.reload()">↻</button><div class="ai-note mt">${t.again}</div></div>`;
    };
  }
  init();
})();
