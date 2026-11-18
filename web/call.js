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
      ai: "Men sun'iy intellektman. Davolash bo'yicha maslahat bermayman. Shoshilinch holatda 103 ga qo'ng'iroq qiling.",
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
      msg_h: "Shifokorga murojaat",
      speak: "Murojaatingizni ayting",
      finish: "Tugatdim",
      type_here: "Murojaatingizni shu yerga yozing",
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
      ai: "Я искусственный интеллект. Советов по лечению не даю. В экстренном случае звоните 103.",
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
      msg_h: "Обращение к врачу",
      speak: "Говорите ваше обращение",
      finish: "Готово",
      type_here: "Напишите ваше обращение здесь",
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
      player.src = `/api/call/${token}/audio/${part}`;
      player.onended = fin;
      player.onerror = () => setTimeout(fin, 1200 + text.length * 45);
      player.play().catch(() => setTimeout(fin, 1200 + text.length * 45));
    });

  function record(maxMs = 9000, quietMs = 1300) {
    // resolves with a Blob, or null if the patient used a button instead
    return new Promise((res) => {
      if (!stream) return res(null);
      const rec = new MediaRecorder(stream),
        chunks = [];
      let finished = false,
        spoke = false,
        silence = 0;
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
        res(record.cancel ? null : new Blob(chunks, { type: rec.mimeType || "audio/webm" }));
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
      }, 100);
      const to = setTimeout(stop, maxMs);
      record.cancel = false;
      record.stop = stop;
      rec.start();
    });
  }
  const post = (qid, blob, value) => {
    const fd = new FormData();
    fd.append("qid", qid);
    if (blob) fd.append("audio", blob, "a." + (blob.type.split("/")[1] || "webm").split(";")[0]);
    else fd.append("value", value);
    return fetch(`/api/call/${token}/answer`, { method: "POST", body: fd })
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
  const hear = (blob) => {
    const fd = new FormData();
    fd.append("audio", blob, "a." + (blob.type.split("/")[1] || "webm").split(";")[0]);
    return fetch(`/api/call/${token}/hear`, { method: "POST", body: fd })
      .then((r) => r.json())
      .catch(() => ({}));
  };

  // One question. Resolves with what was understood: {value, flagged, voice} or {operator: true}.
  // `q.local` is a question outside the scenario (the offer to leave a message): its answer is not stored.
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
    if (q.local) {
      if (!spoken) return { value: btn || "unclear", voice: false };
      const r = await hear(blob);
      return r.operator ? { operator: true, said: r.transcript } : { value: r.value || "unclear", voice: true };
    }
    const sent = spoken ? post(q.id, blob) : post(q.id, null, btn === null ? "unclear" : btn === "idk" ? "" : btn);
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

  // The offer at the end: leave a message for the doctor. Returns "operator" if she asked for a person instead.
  async function appeal() {
    const want = await ask({ id: "murojaat", audio: "say_appeal_q", text: info.say.appeal_q, type: "yesno", local: true }, t.msg_h);
    if (want.operator) return "operator";
    if (want.value !== "yes") return;
    const fd = new FormData();
    const screen = (inner) =>
      (box.innerHTML = `<div><div class="ai-note">${t.msg_h}</div><div class="avatar ring">●</div></div><div class="qtext">${t.speak}</div><div>${inner}</div><div class="ai-note">${t.ai}</div>`);
    if (stream) {
      screen(`<div class="listen" id="st">${t.wait}</div><div class="bar"><i></i></div><div class="ans mt"><button id="done">${t.finish}</button></div>`);
      await say(LINE ? "appeal_go_line" : "appeal_go");
      beep();
      document.getElementById("st").textContent = t.listen;
      document.getElementById("done").onclick = () => record.stop && record.stop();
      const blob = await record(45000, 2600); // up to 45 seconds; a long pause or the button ends it
      if (blob && blob.size > 800) fd.append("audio", blob, "m." + (blob.type.split("/")[1] || "webm").split(";")[0]);
    } else {
      // no microphone: the message can be typed
      screen(`<textarea id="msg" rows="4" placeholder="${t.type_here}"></textarea><div class="ans mt"><button id="done">${t.send}</button></div>`);
      await new Promise((res) => (document.getElementById("done").onclick = res));
      fd.append("text", document.getElementById("msg").value);
    }
    box.innerHTML = `<div><div class="avatar">N</div></div><div class="qtext">${t.proc}</div><div></div>`;
    const r = await fetch(`/api/call/${token}/appeal`, { method: "POST", body: fd })
      .then((x) => x.json())
      .catch(() => ({}));
    if (!r.ok) return say("appeal_fail");
    const nurse = r.to === "hamshira";
    box.innerHTML = `<div><div class="avatar">✓</div><div class="ai-note mt">${nurse ? t.to_nurse : t.to_doctor}${r.doctor ? ": " + esc(r.doctor) : ""}</div></div>
      <div class="qtext">«${esc(r.transcript)}»</div><div class="ai-note">${t.ai}</div>`;
    await say(nurse ? "appeal_ok_nurse" : "appeal_ok");
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
      fetch(`/api/call/${token}/audio/greeting`).catch(() => {});
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
    box.innerHTML = `<div><div class="avatar ring">N</div><h1>Nigoh</h1></div><div class="qtext">${esc(info.greeting)}</div><div class="ai-note">${t.ai}</div>`;
    if (LINE) onLine("speaking: greeting");
    await play("greeting", info.greeting);
    if (LINE) onLine("spoken: greeting");
    await say("hint");
    let human = null,
      acks = 0;
    for (let i = 0; i < info.questions.length; i++) {
      const q = info.questions[i],
        label = `${i + 1} / ${info.questions.length}`;
      let r = await ask(q, label);
      if (!r.operator && r.voice && r.value === "unclear" && q.type !== "number") {
        await say("retry"); // one more try, like a person would ask again; then the call moves on
        r = await ask(q, label);
      }
      if (r.operator) {
        human = r;
        break;
      }
      await say(r.flagged ? "ack_flag" : "ack" + (1 + (acks++ % 3))); // a short reaction before the next question
    }
    if (!human && info.say && (await appeal()) === "operator") human = {};
    if (human) return operator(human.said);
    box.innerHTML = `<div><div class="avatar">N</div></div><div class="qtext">${t.proc}</div><div></div>`;
    const audio = (part) => `/api/call/${token}/audio/${part}`;
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
      parts.slice(1).forEach((_, i) => fetch(audio(`closing?i=${i + 1}`)).catch(() => {}));
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
