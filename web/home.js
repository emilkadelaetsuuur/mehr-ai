(() => {
  const cabinet = /^#\/(bemor|ovoz|vazifalar|qongiroqlar|dmed|reyestr|care)(?:[/?]|$)/;
  function openLegacyRoute() {
    if (/^#\/(haqida|about)\/?$/.test(location.hash)) { location.replace("/cabinet/" + location.search + "#/"); return; }
    if (cabinet.test(location.hash)) location.replace("/cabinet/" + location.search + location.hash);
  }
  openLegacyRoute();
  window.addEventListener("hashchange", openLegacyRoute);
  const cases = [
    [
      ["Пациент после выписки", "Стало ли вам труднее дышать по сравнению со вчерашним днём?", "Да, сегодня дышать труднее.", "Отметку об ухудшении дыхания и задачу связаться с пациентом."],
      ["Uyga chiqarilgan bemor", "Kechagiga nisbatan nafas olishingiz qiyinlashdimi?", "Ha, bugun nafas olish qiyinroq.", "Nafas olish yomonlashgani va bemor bilan bog‘lanish vazifasi."]
    ],
    [
      ["Беременная пациентка", "Была ли в последние дни сильная головная боль?", "Да, вчера появилась сильная головная боль.", "Жалобу с датой опроса в карте беременной для оценки врачом."],
      ["Homilador bemor", "Oxirgi kunlarda kuchli bosh og‘rig‘i bo‘ldimi?", "Ha, kecha boshim qattiq og‘ridi.", "Homiladorlik kartasida shikoyat va so‘rov sanasi qayd etiladi."]
    ],
    [
      ["Мама после первых родов", "Нужна ли вам помощь медсестры с кормлением ребёнка?", "Да, у меня есть вопросы о кормлении.", "Запрос на консультацию по уходу в послеродовом наблюдении."],
      ["Ilk bor ona bo‘lgan ayol", "Bolani ovqatlantirishda hamshira yordami kerakmi?", "Ha, bolani ovqatlantirish haqida savollarim bor.", "Tug‘ruqdan keyingi kuzatuvda parvarish bo‘yicha maslahat so‘rovi."]
    ],
    [
      ["Законный представитель", "Получил ли ребёнок прививку, о которой мы напомнили?", "Пока нет. Помогите уточнить дату.", "Ответ представителя рядом с планом прививки. Введение дозы подтверждает медработник."],
      ["Qonuniy vakil", "Bola eslatilgan emlashni oldimi?", "Hali yo‘q. Sanasini aniqlashga yordam bering.", "Vakil javobi bolaning emlash rejasi yonida. Dozani tibbiyot xodimi tasdiqlaydi."]
    ],
    [
      ["Взрослый пациент", "Вы уже получили прививку, указанную в плане?", "Пока нет, прошу мне перезвонить.", "Ответ самого пациента и просьбу помочь с записью."],
      ["Voyaga yetgan bemor", "Rejada ko‘rsatilgan emlashni oldingizmi?", "Hali yo‘q, qayta qo‘ng‘iroq qilishingizni so‘rayman.", "Bemorning javobi va emlashga yozilishga yordam so‘rovi."]
    ],
    [
      ["Пациент с отдельным согласием", "Хватит ли назначенной антиретровирусной терапии до следующего визита?", "Нет, лекарства закончатся раньше.", "Уполномоченный врач увидит запрос на обратную связь. Вопрос прозвучит после проверки личности и приватности."],
      ["Alohida rozilik bergan bemor", "Keyingi qabulgacha belgilangan antiretrovirus dorilaringiz yetarlimi?", "Yo‘q, dorim oldinroq tugaydi.", "Vakolatli shifokor bog‘lanish so‘rovini ko‘radi. Savol shaxs hamda maxfiylik tekshirilgach beriladi."]
    ],
    [
      ["Пациент с отдельным согласием", "Сохраняются ли симптомы, по поводу которых вы обращались к врачу?", "Да, хочу поговорить со специалистом.", "Уполномоченному сотруднику поступит запрос на контакт. Содержание доступно после проверки личности и приватности."],
      ["Alohida rozilik bergan bemor", "Shifokorga murojaat qilishingizga sabab bo‘lgan alomatlar saqlanib qoldimi?", "Ha, mutaxassis bilan gaplashmoqchiman.", "Vakolatli xodimga bog‘lanish so‘rovi tushadi. Mazmun shaxs va maxfiylik tekshirilgach ochiladi."]
    ]
  ];
  const labels = [...document.querySelectorAll("[data-uz]")].map(node => ({node, ru:node.textContent}));
  const tabs = [...document.querySelectorAll("[data-choice]")];
  const panel = document.querySelector("#case-panel");
  const select = document.querySelector("#case-select");
  const languagePicker = document.querySelector("mehr-language");
  const menu = document.querySelector(".menu");
  const links = document.querySelector("#mobile-links");
  const compact = window.matchMedia("(max-width: 760px)");
  const audio = document.querySelector("#sample-audio");
  const toggle = document.querySelector("#sample-toggle");
  const sampleState = document.querySelector("#sample-state");
  const sampleTime = document.querySelector("#sample-time");
  const waveform = document.querySelector("#sample-wave");
  const playbackError = document.querySelector("#sample-error");
  const sample = {
    ru: {duration:4, levels:[13,13,13,13,13,13,13,57,84,91,64,63,88,46,63,29,26,63,100,79,27,44,56,51,48,62,13]},
    uz: {duration:3.37, levels:[13,61,72,70,86,100,72,96,93,98,81,87,93,17,88,72,56,70,15,55,65,63,28,56,32,13,13]}
  };
  let bars = [];
  let selected = 0;
  let language = "ru";
  try { language = localStorage.lang || language; } catch {}
  language = (new URLSearchParams(location.search).get("lang") || language) === "uz" ? "uz" : "ru";

  function renderCase(index) {
    selected = index;
    for (const [i, tab] of tabs.entries()) {
      tab.setAttribute("aria-selected", String(i === index));
      tab.tabIndex = i === index ? 0 : -1;
    }
    select.value = String(index);
    if (compact.matches) {
      panel.setAttribute("role", "region");
      panel.removeAttribute("aria-labelledby");
      panel.setAttribute("aria-label", tabs[index].textContent);
    } else {
      panel.setAttribute("role", "tabpanel");
      panel.removeAttribute("aria-label");
      panel.setAttribute("aria-labelledby", tabs[index].id);
    }
    const values = cases[index][language === "uz" ? 1 : 0];
    ["recipient", "question", "answer", "action"].forEach((field, i) => {
      panel.querySelector('[data-field="' + field + '"]').textContent = values[i];
    });
  }

  function timeLabel(value) {
    const seconds = Math.max(0, Math.ceil(value));
    return Math.floor(seconds / 60) + ":" + String(seconds % 60).padStart(2, "0");
  }

  function paintPlayer() {
    const uz = language === "uz";
    const playing = !audio.paused && !audio.ended;
    const elapsed = audio.ended ? 0 : audio.currentTime;
    const duration = Number.isFinite(audio.duration) ? audio.duration : sample[language].duration;
    const progressed = elapsed > 0 && elapsed < duration;
    const label = playing ? (uz ? "Pauza" : "Пауза") :
      progressed ? (uz ? "Davom ettirish" : "Продолжить") : (uz ? "Tinglash" : "Послушать");
    sampleState.textContent = label;
    toggle.dataset.playing = String(playing);
    toggle.setAttribute("aria-label", label + (uz ? " · Uyga chiqqandan keyingi savol" : " · Вопрос после выписки"));
    sampleTime.textContent = timeLabel(duration - elapsed);
    bars.forEach((bar, i) => bar.classList.toggle("played", i < Math.floor(elapsed / duration * bars.length)));
  }

  function selectRecording() {
    const file = "/brand/followup-" + language + ".mp3";
    if (audio.getAttribute("src") !== file) {
      audio.pause();
      audio.setAttribute("src", file);
      audio.load();
    }
    playbackError.hidden = true;
    bars = sample[language].levels.map(level => {
      const bar = document.createElement("i");
      bar.style.setProperty("--level", level + "%");
      return bar;
    });
    waveform.replaceChildren(...bars);
    audio.setAttribute("aria-label", language === "uz" ? "Uyga chiqqandan keyingi savol" : "Вопрос после выписки");
    paintPlayer();
  }

  async function toggleRecording() {
    if (!audio.paused && !audio.ended) {
      audio.pause();
      return;
    }
    const recording = audio.getAttribute("src");
    playbackError.hidden = true;
    try {
      if (audio.error) audio.load();
      if (audio.ended) audio.currentTime = 0;
      await audio.play();
    } catch (error) {
      if (error.name !== "AbortError" && recording === audio.getAttribute("src")) {
        playbackError.hidden = false;
        paintPlayer();
      }
    }
  }

  function renderLanguage() {
    const uz = language === "uz";
    document.documentElement.lang = language;
    for (const {node, ru} of labels) node.textContent = uz ? node.dataset.uz : ru;
    document.title = uz ? "Mehr AI — qabullar orasida bemor kuzatuvi" : "Mehr AI — наблюдение за пациентами между приёмами";
    document.querySelector('meta[name="description"]').content = uz
      ? "O‘zbekiston klinikalari uchun ovozli kuzatuv. Mehr AI qabullar orasida bemorlarga qo‘ng‘iroq qiladi va javoblarini shifokorga yetkazadi."
      : "Голосовое наблюдение для клиник Узбекистана. Mehr AI звонит пациентам между приёмами, собирает ответы и передаёт врачу просьбы о помощи.";
    if (languagePicker.value !== language) {
      languagePicker.setAttribute("value", language);
      languagePicker.paint();
    }
    document.querySelector(".primary").setAttribute("aria-label", uz ? "Asosiy menyu" : "Основное меню");
    document.querySelector("#case-tabs").setAttribute("aria-label", uz ? "Kuzatuv dasturi" : "Программа наблюдения");
    document.querySelector(".hero-scene img").alt = uz ? "Keksa kishi uyida telefon qo‘ng‘irog‘iga javob bermoqda" : "Пожилой мужчина дома отвечает на телефонный звонок";
    document.querySelector(".doctor-photo img").alt = uz ? "Oilaviy shifokor poliklinikada telefonda suhbatlashmoqda" : "Семейный врач в поликлинике разговаривает по телефону";
    menu.setAttribute("aria-label", uz ? "Menyu" : "Меню");
    links.setAttribute("aria-label", uz ? "Menyu" : "Меню");
    renderCase(selected);
    selectRecording();
    try { localStorage.lang = language; } catch {}
  }

  function setMenu(open) {
    links.hidden = !open;
    menu.setAttribute("aria-expanded", String(open));
  }

  menu.addEventListener("click", () => setMenu(links.hidden));
  links.addEventListener("click", e => { if (e.target.closest("a")) setMenu(false); });
  document.addEventListener("pointerdown", e => {
    if (!links.hidden && !links.contains(e.target) && !menu.contains(e.target)) setMenu(false);
  });
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && !links.hidden) { setMenu(false); menu.focus(); }
  });
  compact.addEventListener("change", () => { if (!compact.matches) setMenu(false); renderCase(selected); });
  languagePicker.addEventListener("mehr-language-change", e => { language = e.detail; renderLanguage(); });
  select.addEventListener("change", () => renderCase(Number(select.value)));
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => renderCase(index));
    tab.addEventListener("keydown", e => {
      const n = tabs.length;
      const next = {ArrowRight:(index+1)%n, ArrowDown:(index+1)%n, ArrowLeft:(index+n-1)%n, ArrowUp:(index+n-1)%n, Home:0, End:n-1}[e.key];
      if (next === undefined) return;
      e.preventDefault(); renderCase(next); tabs[next].focus();
    });
  });
  for (const event of ["play", "pause", "ended", "timeupdate", "loadedmetadata"]) audio.addEventListener(event, paintPlayer);
  audio.addEventListener("error", () => { playbackError.hidden = false; });
  for (const link of document.querySelectorAll(".hero-link, #read-sample")) {
    link.addEventListener("click", () => renderCase(0));
  }
  window.addEventListener("pagehide", () => audio.pause());
  toggle.addEventListener("click", toggleRecording);
  toggle.setAttribute("aria-controls", "sample-audio");
  renderLanguage();
  toggle.hidden = false;
  audio.controls = false;
})();
