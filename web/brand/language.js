(() => {
  const languages = {ru: "Русский", uz: "O‘zbekcha"};
  const flag = code => '<img class="lang-flag" src="/brand/flag-' + code + '.png" alt="" width="19" height="19">';
  let menuId = 0;

  class LanguagePicker extends HTMLElement {
    connectedCallback() {
      this.menuId = "language-options-" + (++menuId);
      this.paint();
      this.addEventListener("click", this);
      this.addEventListener("keydown", this);
      this.addEventListener("focusout", this);
      document.addEventListener("pointerdown", this);
    }
    disconnectedCallback() {
      this.removeEventListener("click", this);
      this.removeEventListener("keydown", this);
      this.removeEventListener("focusout", this);
      document.removeEventListener("pointerdown", this);
    }
    get value() { return this.getAttribute("value") === "uz" ? "uz" : "ru"; }
    paint() {
      const selected = this.value;
      const label = selected === "ru" ? "Выбрать язык" : "Tilni tanlash";
      this.innerHTML = `<button class="lang-switch" type="button" aria-haspopup="menu" aria-expanded="false" aria-label="${label} · ${selected.toUpperCase()}" aria-controls="${this.menuId}">
        ${flag(selected)}<span>${selected.toUpperCase()}</span><i class="lang-caret" aria-hidden="true"></i></button>
        <div id="${this.menuId}" class="lang-options" role="menu" aria-label="${label}" hidden>${Object.entries(languages).map(([code,name])=>`<button type="button" role="menuitemradio" tabindex="-1" aria-checked="${code===selected}" data-lang="${code}">${flag(code)}<b>${code.toUpperCase()}</b><span lang="${code}">${name}</span><i aria-hidden="true">${code===selected?"✓":""}</i></button>`).join("")}</div>`;
    }
    toggle(open,focus) {
      const trigger = this.querySelector(".lang-switch");
      this.querySelector(".lang-options").hidden = !open;
      trigger.setAttribute("aria-expanded",String(open));
      if (focus) (open ? this.querySelector('[aria-checked="true"]') : trigger).focus();
    }
    choose(code) {
      if (code === this.value) { this.toggle(false,true); return; }
      this.setAttribute("value",code);
      localStorage.lang = code;
      const url = new URL(location.href);
      if (url.searchParams.has("lang")) {
        url.searchParams.set("lang",code);
        history.replaceState(history.state,"",url);
      }
      this.paint();
      this.dispatchEvent(new CustomEvent("mehr-language-change",{bubbles:true,detail:code}));
      document.querySelector("mehr-language .lang-switch")?.focus();
    }
    handleEvent(e) {
      const button = this.querySelector(".lang-switch");
      const open = button.getAttribute("aria-expanded") === "true";
      if (e.type === "pointerdown") {
        if (open && !this.contains(e.target)) this.toggle(false,false);
      } else if (e.type === "focusout") {
        if (open && e.relatedTarget && !this.contains(e.relatedTarget)) this.toggle(false,false);
      } else if (e.type === "click") {
        const choice=e.target.closest("[data-lang]");
        if (choice) this.choose(choice.dataset.lang);
        else if (e.target.closest(".lang-switch")) this.toggle(!open,true);
      } else if (e.type === "keydown") {
        if (e.key === "Escape" && open) { e.preventDefault(); this.toggle(false,true); return; }
        if (!["ArrowDown","ArrowUp","Home","End"].includes(e.key)) return;
        e.preventDefault();
        if (!open) { this.toggle(true,true); return; }
        const opts=[...this.querySelectorAll("[data-lang]")];
        const i=opts.indexOf(document.activeElement);
        opts[e.key==="Home"?0:e.key==="End"?opts.length-1:(i+(e.key==="ArrowDown"?1:-1)+opts.length)%opts.length].focus();
      }
    }
  }
  customElements.define("mehr-language",LanguagePicker);
})();