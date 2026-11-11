// Campus AI Companion — DOM projection for Moodle "format-tiles" pages.
// Injected by the scripting API ONLY after the student clicks the extension button (activeTab).
//
// Two ways a section is shown (both seen or inferred on the AEDB):
//   * 'secao_pagina': /ava/course/section.php?id=<section id> — the section is the page.
//   * 'painel'      : /ava/course/view.php?id=<course> with the section opened in place (the URL does not
//                     change). The panel is accepted ONLY when it is linked by attributes to the requested
//                     tile (data-section / data-true-sectionid), is rendered (not hidden, aria-hidden,
//                     inert, collapsed or display:none) and is the only such candidate. Text never links a
//                     region to a section. A dialog that does not contain the panel blocks the reading.
//
// Dialogs (v0.5.2): counted on every read. The "Preferência dos dados" window is recognised by its title, its
// header X and its two buttons "Sim"/"Cancelar" (fixed comparisons only); it still blocks the reading here: only
// open_panel.js may close it, by its X, and only when "Sincronizar disciplina" asks. This file never clicks.
//
// It only READS: body classes, the page title, tile link attributes, and per rendered li.activity of the
// chosen root its data-modtype / data-cmid / data-title and module link addresses. It never reads the text
// of labels, activities, events or panels, never clicks, scrolls, navigates, submits, or touches cookies or
// storage. The diagnostic carries counts, tag names, class tokens and attribute NAMES only.
(() => {
  'use strict';
  if (Object.hasOwn(globalThis, 'CampusAiDomTiles')) return;   // injected twice in the same page: keep one copy

  const MAX_ENTRIES = 500;
  const MAX_HREFS = 8;
  const MAX_CONTAINERS = 5;
  // Navigation, side panels and the tiles themselves are never academic content.
  const OUTSIDE = '#courseindex, .courseindex, [data-region="drawer"], .drawer, aside, .block, nav, .navbar, '
    + 'header, footer, li.tile';
  const SECTION_LIKE = 'li.section, [data-section], [data-sectionid], [data-for="section"], [role="dialog"], .modal';
  const ID = /^[1-9][0-9]{0,9}$/;
  const NUMBER = /^[0-9]{1,6}$/;
  // Every kind of dialog. Any RENDERED one that is not the panel itself blocks the reading (same list in open_panel.js).
  const DIALOGS = '[role="dialog"], [role="alertdialog"], .modal, dialog[open]';
  // The ONE dialog recognised by name (authorized by the student on 09/11/2026 to be closed by its X): Moodle's
  // "Preferência dos dados" window, with a close button in its header and the buttons "Sim" and "Cancelar".
  // Only fixed comparisons against these folded strings are made; no dialog text leaves the page.
  const DATA_PREFERENCE = Object.freeze({ title: 'preferencia dos dados', buttons: Object.freeze(['cancelar', 'sim']) });
  const CONTROLS = 'button, a, input, select, textarea, [role="button"], [role="link"], [role="checkbox"], '
    + '[role="radio"], [role="menuitem"], [contenteditable="true"]';
  const FIELDS = 'a, input, select, textarea, form, iframe, object, embed';
  const CLOSE_WORDS = ['fechar', 'close'];

  const fold = (text) => String(text ?? '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/\s+/g, ' ').trim();
  const tokens = (el) => [...el.classList].filter((c) => /^[a-z][a-z0-9_-]{0,40}$/i.test(c)).slice(0, 6);
  const attrNames = (el) => [...el.attributes].map((a) => a.name).filter((n) => n !== 'class' && n !== 'style').slice(0, 10);
  const academic = (el) => !el.closest(OUTSIDE);
  const activitiesIn = (root) => [...root.querySelectorAll('li.activity')].filter(academic);

  function rendered(el) {
    const view = el.ownerDocument.defaultView;
    for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
      if (node.hidden || node.getAttribute('aria-hidden') === 'true' || node.hasAttribute('inert')) return false;
      if (node.classList.contains('collapse') && !node.classList.contains('show')) return false;
      const style = view.getComputedStyle(node);
      if (style.display === 'none' || style.visibility === 'hidden' || style.contentVisibility === 'hidden') return false;
    }
    return el.getClientRects().length > 0;
  }

  function describe(el) {
    return { tag: el.tagName.toLowerCase(), classes: tokens(el), attrs: attrNames(el),
      activities: activitiesIn(el).length, inDialog: Boolean(el.closest('[role="dialog"], .modal')) };
  }

  // Where the visible academic activities live, for the diagnostic (structure only).
  function visibleContainers(doc) {
    const seen = new Set();
    const out = [];
    for (const item of activitiesIn(doc.body).filter(rendered)) {
      const box = item.parentElement && item.parentElement.closest(SECTION_LIKE) || item.parentElement;
      if (!box || seen.has(box)) continue;
      seen.add(box);
      out.push(describe(box));
      if (out.length >= MAX_CONTAINERS) break;
    }
    return out;
  }

  function locatePanel(doc, label, diag) {
    const wanted = fold(label);
    const tiles = [...doc.querySelectorAll('li.tile')].filter((t) => t.querySelector('a.tile-link'));
    diag.tiles = tiles.length;
    const matched = wanted ? tiles.filter((t) => {
      const link = t.querySelector('a.tile-link');
      return [fold(link.getAttribute('aria-label')), fold(t.textContent)].some((name) => name.includes(wanted));
    }) : [];
    diag.tilesMatched = matched.length;
    if (!matched.length) return { reason: 'tile_nao_encontrado' };
    if (matched.length > 1) return { reason: 'tile_ambiguo' };
    const number = matched[0].getAttribute('data-section') || '';
    const sectionId = matched[0].getAttribute('data-true-sectionid') || '';
    if (!NUMBER.test(number) || !ID.test(sectionId)) return { reason: 'tile_sem_vinculo' };

    // Attribute links only (values are validated digits, so the selectors cannot be injected).
    const selector = [`[id="section-${number}"]`, `[data-section="${number}"]`, `[data-sectionid="${sectionId}"]`,
      `[data-true-sectionid="${sectionId}"]`, `[data-for="section"][data-id="${sectionId}"]`].join(', ');
    let candidates = [...doc.querySelectorAll(selector)].filter((el) => academic(el) && activitiesIn(el).length);
    candidates = candidates.filter((c) => !candidates.some((other) => other !== c && c.contains(other)));  // innermost
    const visible = candidates.filter(rendered);
    diag.candidates = candidates.length;
    diag.visibleCandidates = visible.length;
    if (visible.length > 1) return { reason: 'paineis_multiplos' };
    if (!visible.length) {
      const otherVisible = activitiesIn(doc.body).some(rendered);
      return { reason: !candidates.length && otherVisible ? 'painel_sem_vinculo' : 'painel_fechado' };
    }
    return { panel: visible[0], number, sectionId };
  }

  const outermost = (list) => list.filter((el) => !list.some((other) => other !== el && other.contains(el)));

  // The X of the "Preferência dos dados" window: a plain button (not submit, not in a form, not disabled), whose
  // data-action is empty or "hide", marked as a close button by class or by an aria-label/title "Fechar"/"Close",
  // and showing no text other than "×"/"x". Anything else is not that X.
  function isCloseButton(control) {
    if (control.tagName !== 'BUTTON' || control.disabled || control.closest('form')) return false;
    if (!['', 'button'].includes((control.getAttribute('type') || '').toLowerCase())) return false;
    const action = control.getAttribute('data-action') || '';
    if (action !== '' && action !== 'hide') return false;
    if (!['', '×', 'x'].includes(fold(control.textContent))) return false;
    const named = [control.getAttribute('aria-label'), control.getAttribute('title')]
      .some((name) => CLOSE_WORDS.includes(fold(name)));
    return action === 'hide' || control.classList.contains('close') || control.classList.contains('btn-close') || named;
  }

  // Recognises the "Preferência dos dados" window. ALL must hold, otherwise it is an unknown dialog:
  //   * exactly one title text among .modal-title / [data-region="title"] / aria-labelledby targets inside it,
  //     equal (accents and case folded) to "Preferência dos dados";
  //   * exactly one header (.modal-header / [data-region="header"]) with exactly ONE control, the close button;
  //   * outside the header exactly TWO controls, both rendered buttons, reading "Sim" and "Cancelar";
  //   * no link, field, form or frame anywhere in it (rendered or not).
  // Returns the close button only when it is recognised; the button is only used by open_panel.js, in the same call.
  function dataPreferenceOf(dialog) {
    const titled = [...dialog.querySelectorAll('.modal-title, [data-region="title"]')];
    for (const holder of [dialog, ...dialog.querySelectorAll('[aria-labelledby]')]) {
      for (const id of String(holder.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean)) {
        const target = dialog.ownerDocument.getElementById(id);
        if (target && dialog.contains(target)) titled.push(target);
      }
    }
    const titles = new Set([...new Set(titled)].map((el) => fold(el.textContent)));
    const headers = outermost([...new Set(dialog.querySelectorAll('.modal-header, [data-region="header"]'))]);
    const controls = [...dialog.querySelectorAll(CONTROLS)];
    const inHeader = headers.length === 1 ? controls.filter((c) => headers[0].contains(c)) : [];
    const others = controls.filter((c) => !inHeader.includes(c));
    const close = inHeader.length === 1 && isCloseButton(inHeader[0]) && rendered(inHeader[0]) ? inHeader[0] : null;
    const buttons = others.length === 2 && others.every((c) => c.tagName === 'BUTTON' && rendered(c))
      && others.map((c) => fold(c.textContent)).sort().join('|') === DATA_PREFERENCE.buttons.join('|');
    const known = titles.size === 1 && titles.has(DATA_PREFERENCE.title) && headers.length === 1 && Boolean(close)
      && buttons && !dialog.querySelector(FIELDS);
    return known ? close : null;
  }

  // Dialogs that are not the panel itself (nor inside it): rendered ones split into the recognised window and
  // unknown ones; hidden ones never block. `root` may be null (no panel found): then every dialog counts.
  function surveyDialogs(doc, root) {
    const all = outermost([...doc.querySelectorAll(DIALOGS)]);
    const unrelated = all.filter((d) => !root || (!d.contains(root) && !root.contains(d)));
    const visible = unrelated.filter(rendered);
    const closers = visible.map(dataPreferenceOf);
    return {
      rendered: all.filter(rendered).length, hidden: all.length - all.filter(rendered).length,
      visible, known: closers.filter(Boolean), unknown: closers.filter((c) => !c).length,
    };
  }

  // For open_panel.js only (same page, same call as its click): the X of the window, when it is the ONLY rendered
  // dialog of the page and it is recognised. Never another button, never another dialog.
  function dataPreferenceClose(doc) {
    const dialogs = surveyDialogs(doc, null);
    if (!dialogs.visible.length) return { reason: 'dialogo_ausente' };
    if (dialogs.unknown || dialogs.visible.length !== 1 || dialogs.known.length !== 1) return { reason: 'dialogo_nao_identificado' };
    return { button: dialogs.known[0] };
  }

  function readEntries(items) {
    const entries = [];
    let truncated = false;
    for (const item of items) {
      if (entries.length >= MAX_ENTRIES) { truncated = true; break; }
      const modtype = item.getAttribute('data-modtype') || '';
      if (modtype === 'label') { entries.push({ label: true }); continue; }   // position only, never its text
      const hrefs = [];
      for (const link of item.querySelectorAll('a[href*="/mod/"]')) {
        if (hrefs.length >= MAX_HREFS) break;
        try { hrefs.push(new URL(link.getAttribute('href'), item.ownerDocument.baseURI).href); } catch { /* ignore */ }
      }
      entries.push({
        modtype: modtype.slice(0, 40),
        cmid: (item.getAttribute('data-cmid') || '').slice(0, 12),
        title: (item.getAttribute('data-title') || '').slice(0, 1000),
        hrefs,
      });
    }
    return { entries, truncated };
  }

  // withEntries=false returns only the identity of the page and of the open section (no item data), so
  // the extension can decide whether it is the authorized one BEFORE any item is read.
  function project(doc, loc, { withEntries = true, sectionLabel = '' } = {}) {
    const classes = [...doc.body.classList];
    const course = classes.map((name) => /^course-([1-9][0-9]{0,9})$/.exec(name)).find(Boolean);
    const diag = { reason: '', tiles: 0, tilesMatched: 0, candidates: 0, visibleCandidates: 0, openDialogs: 0,
      hiddenDialogs: 0, dataPreferenceDialogs: 0, unknownDialogs: 0, sectionVisible: 0,
      hiddenActivities: 0, visibleActivitiesOutside: 0, containers: [] };
    let mode = 'nenhum';
    let root = null;
    let sectionId = '';
    let sectionName = '';
    let number = '';

    if (loc.pathname === '/ava/course/section.php') {
      const ids = new URLSearchParams(loc.search).getAll('id');
      mode = 'secao_pagina';
      root = doc.body;
      sectionId = ids.length === 1 && ID.test(ids[0]) ? ids[0] : '';
    } else if (loc.pathname === '/ava/course/view.php') {
      const found = locatePanel(doc, sectionLabel, diag);
      if (found.panel) {
        mode = 'painel';
        root = found.panel;
        sectionId = found.sectionId;
        number = found.number;
        sectionName = String(sectionLabel).slice(0, 200);
      } else {
        diag.reason = found.reason;
      }
    } else {
      diag.reason = 'rota_nao_suportada';
    }

    // Dialogs are counted on EVERY read (with or without a panel), so the reason and the counts always agree.
    // A rendered dialog that is not the panel blocks: 'dialogo_preferencia' when it is only the recognised
    // "Preferência dos dados" window, 'dialogo_bloqueia' for anything else. Without a panel, a dialog explains a
    // closed or unlinked panel; structural refusals (tile_*, two panels, route) keep their own reason.
    const dialogs = surveyDialogs(doc, root);
    diag.openDialogs = dialogs.rendered;
    diag.hiddenDialogs = dialogs.hidden;
    diag.dataPreferenceDialogs = dialogs.known.length;
    diag.unknownDialogs = dialogs.unknown;
    diag.sectionVisible = root ? 1 : 0;
    if (dialogs.visible.length && (root || diag.reason === 'painel_fechado' || diag.reason === 'painel_sem_vinculo')) {
      diag.reason = dialogs.unknown ? 'dialogo_bloqueia' : 'dialogo_preferencia';   // never read behind a dialog
      mode = 'nenhum';
      root = null;
    }

    let items = [];
    if (root) {
      const all = activitiesIn(root);
      items = all.filter(rendered);
      diag.hiddenActivities = all.length - items.length;
      diag.visibleActivitiesOutside = activitiesIn(doc.body).filter((a) => !root.contains(a) && rendered(a)).length;
    } else {
      diag.containers = visibleContainers(doc);
    }
    const { entries, truncated } = withEntries && root ? readEntries(items) : { entries: [], truncated: false };
    return {
      projection: 'campus-ai-tiles/1',
      courseId: course ? course[1] : '',
      formatTiles: classes.includes('format-tiles'),
      mode,
      sectionPage: mode === 'secao_pagina' && classes.includes('path-course-view-section'),
      sectionId,
      sectionName,
      panelKey: `${mode}:${sectionId}:${number}:${items.length}`,
      docTitle: String(doc.title || '').slice(0, 300),
      diagnostic: diag,
      entries,
      truncated,
    };
  }

  Object.defineProperty(globalThis, 'CampusAiDomTiles', { value: Object.freeze({ project, dataPreferenceClose }),
    configurable: false });
})();
