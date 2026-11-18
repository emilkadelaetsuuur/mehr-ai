/* Patient side of an AI call. Opens from a link or QR; in production the same dialogue runs over a phone line.
   Questions are pre-synthesised (cached WAV), answers are recorded, recognised (Uzbek/Russian STT) and classified. */
(() => {
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

  function record(maxMs = 9000) {
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
        if (rms > 6) {
          spoke = true;
          silence = 0;
        } else if (spoke && (silence += 100) >= 1300) stop();
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

  async function ask(q, i) {
    const num = q.type === "number";
    box.innerHTML = `<div><div class="ai-note">${i + 1} / ${info.questions.length}</div><div class="avatar">N</div></div><div class="qtext">${esc(q.text)}</div>
      <div><div class="listen" id="st">${t.wait}</div><div class="bar"><i></i></div><div class="ans mt">${num ? `<button data-v="idk">${t.idk}</button>` : `<button data-v="yes">${t.yes}</button><button data-v="no">${t.no}</button>`}</div>
      <div class="heard mt" id="heard"></div></div><div class="ai-note">${t.ai}</div>`;
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
    await play(q.id, q.text);
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
    if (btn !== null) pending.push(post(q.id, null, btn === "idk" ? "" : btn));
    else if (blob && blob.size > 800)
      pending.push(
        post(q.id, blob).then((r) => {
          const h = document.getElementById("heard");
          if (h && r.transcript) h.textContent = `${t.heard}: «${r.transcript}»`;
          return r;
        }),
      );
    else pending.push(post(q.id, null, "unclear"));
  }

  async function run() {
    ring(false);
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch {
      stream = null;
    }
    ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
    if (ctx.state === "suspended") await ctx.resume();
    box.innerHTML = `<div><div class="avatar ring">N</div><h1>Nigoh</h1></div><div class="qtext">${esc(info.greeting)}</div><div class="ai-note">${t.ai}</div>`;
    await play("greeting", info.greeting);
    for (let i = 0; i < info.questions.length; i++) await ask(info.questions[i], i);
    box.innerHTML = `<div><div class="avatar">N</div></div><div class="qtext">${t.proc}</div><div></div>`;
    await Promise.all(pending);
    const res = await fetch(`/api/call/${token}/finish`, { method: "POST" })
      .then((r) => r.json())
      .catch(() => ({}));
    const fixed = res.alert || res.verified === false ? "closing_alert" : "closing_ok";
    const text = res.closing || info[fixed];
    box.innerHTML = `<div><div class="avatar">${res.alert ? "!" : "✓"}</div><h1>${t.done}</h1></div><div class="qtext">${esc(text)}</div><div class="ai-note">${t.ai}</div>`;
    await play(res.closing ? "closing" : fixed, text);
    stream && stream.getTracks().forEach((x) => x.stop());
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
      return;
    }
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
