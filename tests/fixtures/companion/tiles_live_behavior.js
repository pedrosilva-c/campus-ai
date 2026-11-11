// FICTITIOUS stand-in for the Moodle Tiles plugin's click behaviour, injected by the tests into tiles_home.html.
// The real plugin's code was never observed; what was observed on the real AEDB is only the RESULT: clicking
// the tile shows the section in place and the address does not change. Variants (window.__variant) model what
// could go wrong. Every tile click is recorded in window.__clicks as "tile:<data-section>".
(() => {
  const variant = window.__variant || 'ok';
  // Opening a section closes the one that was open (one section shown at a time).
  const open = (number) => {
    document.querySelectorAll('.moveablesection.aberta').forEach((section) => section.classList.remove('aberta'));
    document.getElementById('section-' + number).classList.add('aberta');
  };
  // v0.5.2: the "Preferência dos dados" window (fixture hypothesis). pref_* variants: 'pref' shows it with the AV
  // panel; 'pref_closes_panel': its X also closes the panel; 'pref_sticky': its X does nothing; 'pref_reappears':
  // it comes back 300 ms after each X. Any of its three buttons is recorded; Sim/Cancelar must never appear.
  const pref = () => document.getElementById('preferencia-dados');
  window.__showPref = () => { pref().classList.add('show'); pref().setAttribute('aria-hidden', 'false'); };
  const hidePref = () => { pref().classList.remove('show'); pref().setAttribute('aria-hidden', 'true'); };
  document.addEventListener('click', (event) => {
    const button = event.target.closest && event.target.closest('[data-pref]');
    if (!button) return;
    window.__clicks.push('pref:' + button.getAttribute('data-pref'));
    if (variant === 'pref_sticky') return;
    hidePref();
    if (variant === 'pref_closes_panel') document.querySelectorAll('.moveablesection.aberta').forEach((s) => s.classList.remove('aberta'));
    if (variant === 'pref_reappears') setTimeout(window.__showPref, 300);
  }, true);

  document.addEventListener('click', (event) => {
    const link = event.target.closest && event.target.closest('a.tile-link');
    if (!link) return;
    event.preventDefault();
    window.__clicks.push('tile:' + link.getAttribute('data-section'));
    const number = link.getAttribute('data-section');
    if (variant === 'never' || variant === 'never_' + number) return;
    if (number !== '3') {                    // any other tile simply opens its own section
      setTimeout(() => open(number), 120);
      return;
    }
    if (variant === 'wrong_panel') { setTimeout(() => open('2'), 120); return; }
    if (variant === 'dialog_only') {         // a dialog appears but the panel does not open
      setTimeout(() => document.getElementById('dialogo-alheio').classList.add('show'), 120);
      return;
    }
    setTimeout(() => {
      open('3');
      if (variant.startsWith('pref')) window.__showPref();                    // the window comes up with the panel
      if (variant === 'dialog') document.getElementById('dialogo-alheio').classList.add('show');   // opens WITH a dialog
      if (variant === 'two_panels') {
        const copy = document.getElementById('section-3').cloneNode(true);
        copy.removeAttribute('id');
        document.getElementById('sections').append(copy);
      }
      if (variant === 'slow') {              // items arrive in batches, like a panel that loads its content
        const late = ['90003', '90004', '90005', '90006', '90007']
          .map((cmid) => document.querySelector('#section-3 li.activity[data-cmid="' + cmid + '"]'));
        late.forEach((item) => { item.hidden = true; });
        [[late.slice(0, 2), 250], [late.slice(2, 3), 500], [late.slice(3), 750]]
          .forEach(([batch, delay]) => setTimeout(() => batch.forEach((item) => { item.hidden = false; }), delay));
      }
    }, 120);
  }, true);
})();
