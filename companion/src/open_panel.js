// Campus AI Companion — opens the "Atividades Avaliativas" tile of the course home (format-tiles).
// Injected by the scripting API ONLY after the student clicked "Sincronizar disciplina" (activeTab).
//
// This is the ONLY place in the extension that interacts with the page. open() does exactly one thing: one
// click on the link of ONE verified tile, which makes the Tiles plugin show the section in place (same
// document, so the activeTab access survives). Every gate runs in this same call, right before the click
// (no time gap between checking and clicking):
//   * the page is /ava/course/view.php of the authorized course (body.course-<id>) in format-tiles;
//   * no dialog is open;
//   * exactly ONE tile matches the section label, with exactly one a.tile-link, no dangerous word in its label;
//   * the tile is linked to its section by attributes: data-section, data-true-sectionid and a link whose
//     address is https, host ead.aedb.br, /ava/course/section.php with the single parameter id equal to
//     data-true-sectionid (the address is only COMPARED: it is never opened or followed by this code);
//   * the link opens in the same tab, is not a download, is not in a form or dialog, the tile is clickable
//     and rendered.
// Anything else returns a refusal reason and nothing is clicked. Never clicks activities, completion or
// submission controls, never reads activity content, never navigates.
//
// v0.5.2 — the SECOND and last interaction, authorized by the student on 09/11/2026: closing Moodle's
// "Preferência dos dados" window by ITS X (closeDataPreference). Never "Sim", never "Cancelar", never another
// dialog, never a close button outside that window. The window is recognised by dom_tiles.js
// (dataPreferenceClose) in this same call, right before the click.
(() => {
  'use strict';
  if (Object.hasOwn(globalThis, 'CampusAiOpenPanel')) return;   // injected twice in the same page: keep one copy

  const ID = /^[1-9][0-9]{0,9}$/;
  const NUMBER = /^[0-9]{1,6}$/;
  const DIALOGS = '[role="dialog"], [role="alertdialog"], .modal, dialog[open]';   // same list as dom_tiles.js
  // Same list as the desktop pilot (campus_ai/pilot_nav.py BLOCKED_WORDS).
  const DANGEROUS = ['feedback', 'fale com', 'enviar', 'finalizar', 'concluir', 'responder', 'excluir', 'editar',
    'baixar', 'download', 'submeter', 'marcar como', 'tentativa'];

  const fold = (text) => String(text ?? '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/\s+/g, ' ').trim();

  function rendered(el) {
    const view = el.ownerDocument.defaultView;
    for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
      if (node.hidden || node.getAttribute('aria-hidden') === 'true' || node.hasAttribute('inert')) return false;
      const style = view.getComputedStyle(node);
      if (style.display === 'none' || style.visibility === 'hidden') return false;
    }
    return el.getClientRects().length > 0;
  }

  function open(doc, loc, options) {
    const refuse = (reason) => ({ clicked: false, reason });
    const label = fold(options && options.label);
    const courseId = String((options && options.courseId) || '');
    if (!label || !ID.test(courseId)) return refuse('parametros_invalidos');

    const classes = [...doc.body.classList];
    if (!classes.includes(`course-${courseId}`)) return refuse('curso_diferente');
    if (!classes.includes('format-tiles')) return refuse('formato');
    if (loc.pathname !== '/ava/course/view.php') return refuse('pagina_invalida');
    if ([...doc.querySelectorAll(DIALOGS)].some(rendered)) return refuse('dialogo_bloqueia');

    const tiles = [...doc.querySelectorAll('li.tile')].filter((tile) => tile.querySelector('a.tile-link'));
    const matched = tiles.filter((tile) => {
      const link = tile.querySelector('a.tile-link');
      return [fold(link.getAttribute('aria-label')), fold(tile.textContent)].some((name) => name.includes(label));
    });
    if (!matched.length) return refuse('tile_nao_encontrado');
    if (matched.length > 1) return refuse('tile_ambiguo');
    const tile = matched[0];
    const links = tile.querySelectorAll('a.tile-link');
    if (links.length !== 1) return refuse('tile_ambiguo');
    const link = links[0];

    const wording = `${fold(tile.textContent)} ${fold(link.getAttribute('aria-label'))}`;
    if (DANGEROUS.some((word) => wording.includes(word))) return refuse('tile_perigoso');

    const number = tile.getAttribute('data-section') || '';
    const sectionId = tile.getAttribute('data-true-sectionid') || '';
    if (!NUMBER.test(number) || !ID.test(sectionId)) return refuse('tile_sem_vinculo');
    if (link.hasAttribute('data-section') && link.getAttribute('data-section') !== number) return refuse('tile_sem_vinculo');
    let target;
    try {
      target = new URL(link.getAttribute('href') || '', loc.href);
    } catch {
      return refuse('tile_sem_vinculo');
    }
    const keys = [...target.searchParams.keys()];
    const ids = target.searchParams.getAll('id');
    if (target.protocol !== 'https:' || target.hostname !== 'ead.aedb.br' || target.port || target.username
        || target.password || target.pathname !== '/ava/course/section.php' || keys.length !== 1
        || ids.length !== 1 || ids[0] !== sectionId) {
      return refuse('tile_sem_vinculo');
    }
    if ((link.getAttribute('target') || '_self') !== '_self' || link.hasAttribute('download')
        || link.closest('form, [role="dialog"], .modal')) {
      return refuse('tile_perigoso');
    }
    if (!tile.classList.contains('tile-clickable')) return refuse('tile_nao_clicavel');
    if (!rendered(link)) return refuse('tile_oculto');

    link.click();                      // interaction 1 of 2: the verified tile link
    return { clicked: true };
  }

  // Closes the "Preferência dos dados" window by its X, and nothing else. 'dialogo_ausente' = no dialog is open
  // any more (nothing to do); any other refusal = nothing was clicked and the run stops.
  function closeDataPreference(doc, loc, options) {
    const refuse = (reason) => ({ clicked: false, reason });
    const courseId = String((options && options.courseId) || '');
    if (!ID.test(courseId)) return refuse('parametros_invalidos');

    const classes = [...doc.body.classList];
    if (!classes.includes(`course-${courseId}`)) return refuse('curso_diferente');
    if (!classes.includes('format-tiles')) return refuse('formato');
    if (loc.pathname !== '/ava/course/view.php') return refuse('pagina_invalida');
    const reader = globalThis.CampusAiDomTiles;
    if (!reader || typeof reader.dataPreferenceClose !== 'function') return refuse('dialogo_nao_identificado');

    const found = reader.dataPreferenceClose(doc);       // the window must be the ONLY rendered dialog, recognised
    if (!found || !found.button) return refuse(found && found.reason === 'dialogo_ausente' ? 'dialogo_ausente' : 'dialogo_nao_identificado');
    const button = found.button;
    const dialog = button.closest(DIALOGS);
    if (!button.isConnected || !dialog || !rendered(dialog) || !rendered(button)) return refuse('dialogo_nao_identificado');

    button.click();                    // interaction 2 of 2: the X of the authorized window
    return { clicked: true };
  }

  Object.defineProperty(globalThis, 'CampusAiOpenPanel', { value: Object.freeze({ open, closeDataPreference }),
    configurable: false });
})();
