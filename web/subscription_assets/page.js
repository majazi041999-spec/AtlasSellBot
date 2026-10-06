(() => {
  const tabs = [...document.querySelectorAll('[data-platform]')];
  function selectPlatform(platform) {
    tabs.forEach(tab => {
      const selected = tab.dataset.platform === platform;
      tab.setAttribute('aria-selected', String(selected));
      tab.tabIndex = selected ? 0 : -1;
    });
    document.getElementById('app-list').setAttribute('aria-labelledby', 'tab-' + platform);
    document.querySelectorAll('[data-platforms]').forEach(app => {
      app.hidden = !app.dataset.platforms.split(' ').includes(platform);
    });
  }
  const apple = /iPhone|iPad|iPod/.test(navigator.userAgent) || (/Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints > 1);
  selectPlatform(apple ? 'ios' : 'android');
  tabs.forEach(tab => {
    tab.addEventListener('click', () => selectPlatform(tab.dataset.platform));
    tab.addEventListener('keydown', event => {
      if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) {
        event.preventDefault();
        const target = event.key === 'Home' ? tabs[0] : event.key === 'End' ? tabs[1] : tabs.find(item => item !== tab);
        selectPlatform(target.dataset.platform); target.focus();
      }
    });
  });
  let toastTimer;
  function notify(message) {
    const toast = document.getElementById('toast');
    clearTimeout(toastTimer); toast.textContent = message; toast.hidden = false;
    toastTimer = setTimeout(() => { toast.hidden = true; }, 2800);
  }
  function fallbackCopy(text) {
    const field = document.createElement('textarea');
    field.value = text; field.readOnly = true;
    field.style.cssText = 'position:fixed;top:0;left:0;opacity:0;font-size:16px';
    document.body.appendChild(field);
    field.focus(); field.select(); field.setSelectionRange(0, text.length);
    let copied = false;
    try { copied = document.execCommand('copy'); } catch (_) {}
    field.remove(); return copied;
  }
  async function copyText(button, text) {
    const label = button.textContent;
    button.disabled = true;
    let copied = false;
    try {
      if (window.isSecureContext && navigator.clipboard) {
        try { await navigator.clipboard.writeText(text); copied = true; } catch (_) {}
      }
      if (!copied) copied = fallbackCopy(text);
      if (copied) {
        button.textContent = 'کپی شد ✓'; notify('لینک کپی شد؛ حالا داخل برنامه اضافه کن.');
        setTimeout(() => { button.textContent = label; }, 1800);
      } else {
        const dialog = document.getElementById('manual-copy');
        const field = dialog.querySelector('textarea'); field.value = text;
        if (dialog.showModal) dialog.showModal(); else dialog.setAttribute('open', '');
        field.focus(); field.select(); field.setSelectionRange(0, text.length);
      }
    } finally { button.disabled = false; if (copied) button.focus(); }
  }
  document.getElementById('copy-sub').addEventListener('click', event => copyText(event.currentTarget, document.getElementById('suburl').value));
  document.getElementById('suburl').addEventListener('click', event => event.currentTarget.select());
  document.querySelectorAll('button[data-link]').forEach(button => button.addEventListener('click', () => copyText(button, button.dataset.link)));
  document.querySelectorAll('.app-link').forEach(link => link.addEventListener('click', () => {
    document.getElementById('import-hint').textContent = 'اگر برنامه باز نشد، صفحه را در Chrome یا Safari باز کن؛ یا از «کپی اشتراک» استفاده کن. بعد از افزودن، اشتراک را داخل برنامه به‌روزرسانی کن.';
  }));
  window.addEventListener('pageshow', event => { if (event.persisted) window.location.reload(); });
})();
