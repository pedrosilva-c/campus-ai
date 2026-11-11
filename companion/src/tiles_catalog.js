// Campus AI Companion — read-only description of the tiles of a format-tiles course home.
// Injected by the scripting API only after the student clicked a sync button (activeTab). It never clicks,
// navigates, scrolls or reads anything but tile LABELS and attributes: no section content, no activity, no
// participant or grade data. The link address is only classified (same-site section link or not), never followed.
(() => {
  'use strict';
  if (Object.hasOwn(globalThis, 'CampusAiTilesCatalog')) return;   // injected twice in the same page: keep one copy

  const ID = /^[1-9][0-9]{0,9}$/;
  const NUMBER = /^[0-9]{1,6}$/;
  const MAX_TILES = 30;
  const clean = (text) => String(text ?? '').replace(/[\u0000-\u001f\u007f]/g, ' ').replace(/\s+/g, ' ').trim();

  function rendered(el) {
    const view = el.ownerDocument.defaultView;
    for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
      if (node.hidden || node.getAttribute('aria-hidden') === 'true' || node.hasAttribute('inert')) return false;
      const style = view.getComputedStyle(node);
      if (style.display === 'none' || style.visibility === 'hidden') return false;
    }
    return el.getClientRects().length > 0;
  }

  function linkKind(link, loc, sectionId) {
    let url;
    try {
      url = new URL(link.getAttribute('href') || '', loc.href);
    } catch {
      return 'invalido';
    }
    if (url.protocol !== 'https:' || url.hostname !== 'ead.aedb.br' || url.port || url.username || url.password) return 'externo';
    const keys = [...url.searchParams.keys()];
    const ids = url.searchParams.getAll('id');
    if (url.pathname === '/ava/course/section.php' && keys.length === 1 && ids.length === 1 && ids[0] === sectionId) return 'secao';
    return 'outro';
  }

  function describe(doc, loc) {
    const classes = [...doc.body.classList];
    const course = classes.map((name) => /^course-([1-9][0-9]{0,9})$/.exec(name)).find(Boolean);
    const tiles = [];
    for (const tile of doc.querySelectorAll('li.tile')) {
      const links = tile.querySelectorAll('a.tile-link');
      if (!links.length) continue;                    // spacers
      if (tiles.length >= MAX_TILES) break;
      const link = links[0];
      const number = tile.getAttribute('data-section') || '';
      const sectionId = tile.getAttribute('data-true-sectionid') || '';
      tiles.push({
        position: tiles.length + 1,
        label: clean(link.getAttribute('aria-label') || tile.textContent).slice(0, 120),
        number: NUMBER.test(number) ? number : '',
        sectionId: ID.test(sectionId) ? sectionId : '',
        links: links.length,
        linkKind: linkKind(link, loc, sectionId),
        sameTab: (link.getAttribute('target') || '_self') === '_self' && !link.hasAttribute('download'),
        clickable: tile.classList.contains('tile-clickable'),
        visible: rendered(link),
      });
    }
    return {
      catalog: 'campus-ai-tiles-catalog/1', courseId: course ? course[1] : '', formatTiles: classes.includes('format-tiles'),
      path: loc.pathname, tiles,
    };
  }

  Object.defineProperty(globalThis, 'CampusAiTilesCatalog', { value: Object.freeze({ describe }), configurable: false });
})();
