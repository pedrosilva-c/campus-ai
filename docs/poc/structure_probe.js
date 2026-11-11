// Campus AI — POC structure probe (read-only). Function expression: evaluate as `(<this file>)(options)`.
//   options.mode = 'structure'  -> structure only: tags, class tokens, counts, route patterns.
//                                  No page text (except which KNOWN card label matched), no hrefs, no ids
//                                  other than a yes/no "this page carries course id X".
//   options.mode = 'av'         -> AV1/AV2 activity titles, module types, module ids and visible date texts.
//                                  Refused unless options.consent === true (academic content).
// Never clicks, scrolls, navigates, submits, reads cookies/storage or executes anything from the page.
(options => {
  'use strict';
  const opts = options || {};
  const fold = (s) => String(s || '').normalize('NFKD').replace(/[̀-ͯ]/g, '')
    .toLowerCase().replace(/\s+/g, ' ').trim();
  const KNOWN = ['informacoes da disciplina', 'trilhas de aprendizagem', 'atividades avaliativas',
    'feedback das aulas', 'fale com o professor', 'avisos', 'curriculo lattes'];
  const tokens = (el) => [...el.classList].filter((c) => /^[a-z][a-z0-9_-]{0,40}$/i.test(c)).slice(0, 8);
  const route = (href) => {
    try {
      const u = new URL(href, location.href);
      if (u.protocol !== 'https:' || u.hostname !== 'ead.aedb.br') return { sameSite: false, pattern: '' };
      const keys = [...new Set(u.searchParams.keys())].sort();
      return { sameSite: true, pattern: u.pathname.replace(/[0-9]+/g, 'N') + (keys.length ? '?' + keys.join('&') : '') };
    } catch { return { sameSite: false, pattern: '' }; }
  };
  const MOD = /\/ava\/mod\/([a-z0-9]+)\/view\.php\?(?:.*&)?id=([0-9]+)/;
  const DATE_SEL = '[data-region="activity-dates"] div, .activity-dates div, .due, .duedate, time';
  const SECTION_SEL = 'li.section, [data-for="section"], .course-section, [id^="section-"]';

  if (opts.mode === 'structure') {
    const cards = [];
    const heads = document.querySelectorAll('h1,h2,h3,h4,h5,h6,.card-title,strong,a,button,[role="button"]');
    for (const h of heads) {
      const key = fold(h.textContent);
      if (!KNOWN.includes(key) || cards.some((c) => c.label === key)) continue;
      const box = h.closest('a, .card, [class*="card"], li, article, section, div') || h;
      const link = box.matches('a[href]') ? box : box.querySelector('a[href]');
      const r = link ? route(link.getAttribute('href')) : { sameSite: false, pattern: '' };
      cards.push({
        label: key, headingTag: h.tagName.toLowerCase(), boxTag: box.tagName.toLowerCase(), boxClasses: tokens(box),
        role: box.getAttribute('role') || '', hasLink: Boolean(link), linkSameSite: r.sameSite, linkRoute: r.pattern,
        linkIsFragment: Boolean(link && String(link.getAttribute('href')).startsWith('#')),
        hasOnclick: Boolean(box.closest('[onclick]') || box.querySelector('[onclick]')),
        hasDataHref: Boolean(box.closest('[data-href]') || box.querySelector('[data-href]')),
        linkTarget: link ? (link.getAttribute('target') || '') : '',
      });
    }
    const modTypes = {};
    for (const a of document.querySelectorAll('a[href*="/mod/"]')) {
      const m = String(a.href).match(MOD);
      if (m) modTypes[m[1]] = (modTypes[m[1]] || 0) + 1;
    }
    const sections = [...document.querySelectorAll(SECTION_SEL)];
    const idMatch = opts.courseId && (document.body.classList.contains('course-' + opts.courseId));
    return {
      probe: 'campus-ai-structure/1', mode: 'structure', pageRoute: route(location.href).pattern,
      pageCarriesCourseId: Boolean(idMatch),
      loginForm: Boolean(document.querySelector('form#login, input[type="password"]')),
      bodyClasses: tokens(document.body).filter((c) => !/^course-\d/.test(c) && !/^(context|cmid)-/.test(c)),
      cards,
      sections: {
        total: sections.length,
        strong: sections.filter((s) => s.matches('li.section, [data-for="section"], .course-section')).length,
        collapsedExpanders: document.querySelectorAll('[aria-expanded="false"][aria-controls], [data-toggle="collapse"].collapsed, [data-bs-toggle="collapse"].collapsed').length,
        sampleClasses: sections.slice(0, 3).map(tokens),
      },
      moduleLinksByType: modTypes,
      activityItems: document.querySelectorAll('li.activity, [data-for="cmitem"]').length,
      dateNodes: document.querySelectorAll(DATE_SEL).length,
      iframes: document.querySelectorAll('iframe').length,
    };
  }

  if (opts.mode === 'av') {
    if (opts.consent !== true) return { probe: 'campus-ai-structure/1', mode: 'av', error: 'consentimento_ausente' };
    const out = [];
    const candidates = new Set();
    for (const h of document.querySelectorAll('h1,h2,h3,h4,h5,h6,.sectionname,[data-for="section_title"]')) {
      if (/^av\s*[0-9]+\b/.test(fold(h.textContent))) candidates.add(h);
    }
    for (const h of candidates) {
      const name = fold(h.textContent).slice(0, 40).toUpperCase();
      const box = h.closest(SECTION_SEL) || h.parentElement;
      const items = [];
      for (const a of box.querySelectorAll('a[href*="/mod/"]')) {
        const m = String(a.href).match(MOD);
        if (!m || items.some((i) => i.cmid === m[2])) continue;
        // closest() with a selector list returns the NEAREST match, so ask in order of preference.
        const item = a.closest('li.activity, [data-for="cmitem"]') || a.closest('li') || a.parentElement || a;
        const title = (a.querySelector('.instancename') || a).textContent.replace(/\s+/g, ' ').trim().slice(0, 200);
        const dates = [...item.querySelectorAll(DATE_SEL)].filter((d) => !d.querySelector('div'))
          .map((d) => (d.getAttribute('datetime') || d.textContent).replace(/\s+/g, ' ').trim().slice(0, 120))
          .filter(Boolean).slice(0, 3);
        items.push({ type: m[1], cmid: m[2], title, dates, hidden: item.offsetParent === null });
        if (items.length >= 50) break;
      }
      out.push({ section: name, items });
      if (out.length >= 10) break;
    }
    return { probe: 'campus-ai-structure/1', mode: 'av', sections: out };
  }
  return { probe: 'campus-ai-structure/1', error: 'modo_desconhecido' };
})
