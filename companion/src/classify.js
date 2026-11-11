// Page classification. Mirror of campus_ai/companion_protocol.py `classify_page`; both are tested
// against tests/fixtures/companion/page_cases.json so they cannot drift apart silently.
// Only structure leaves this function: path with digits hidden and query KEY names, never values.

export const AEDB_HOST = 'ead.aedb.br';

const ACTIVITY = new Set(['assign', 'quiz', 'forum', 'lesson', 'choice', 'feedback', 'glossary', 'wiki',
  'workshop', 'scorm', 'h5pactivity', 'lti', 'data', 'bigbluebuttonbn', 'chat', 'survey',
  'attendance', 'groupselect', 'msteams']);
const READ = new Set(['page', 'book', 'folder']);
const FILE = new Set(['resource', 'url', 'imscp']);
const MODULE_PATH = /^\/ava\/mod\/([a-z0-9]+)\/view\.php$/;

export function routePattern(url) {
  const keys = [...new Set(url.searchParams.keys())].sort();
  return url.pathname.replace(/[0-9]+/g, 'N') + (keys.length ? '?' + keys.join('&') : '');
}

function info(kind, route = '', moodleId = '') {
  return Object.freeze({ kind, route, moodleId });
}

export function classifyPage(href) {
  let url;
  try {
    url = new URL(String(href));
  } catch {
    return info('invalida');
  }
  if (url.protocol !== 'https:' || url.hostname !== AEDB_HOST || url.port !== '' || url.username || url.password) {
    return info('externa');
  }
  const route = routePattern(url);
  if (url.pathname === '/ava/course/view.php') {
    const keys = [...url.searchParams.keys()];
    const id = url.searchParams.getAll('id');
    const section = url.searchParams.getAll('section');
    const clean = keys.every((k) => k === 'id' || k === 'section') && id.length === 1 && section.length <= 1
      && /^[1-9][0-9]{0,9}$/.test(id[0]) && (section.length === 0 || /^[0-9]{1,6}$/.test(section[0]));
    if (clean) return info(section.length ? 'curso_secao' : 'curso_inicio', route, id[0]);
    return info('outra_aedb', route);
  }
  if (url.pathname === '/ava/course/section.php') {
    const keys = [...url.searchParams.keys()];
    const id = url.searchParams.getAll('id');
    // format-tiles: ?id is a SECTION id; the course is proven by the page itself (body class), not the URL.
    if (keys.length === 1 && id.length === 1 && /^[1-9][0-9]{0,9}$/.test(id[0])) return info('curso_bloco', route);
    return info('outra_aedb', route);
  }
  const module = url.pathname.match(MODULE_PATH);
  if (module && READ.has(module[1])) return info('modulo_leitura', route);
  if (module && ACTIVITY.has(module[1])) return info('modulo_atividade', route);
  if (module && FILE.has(module[1])) return info('modulo_arquivo', route);
  if (url.pathname.startsWith('/ava/login/')) return info('login', route);
  if (url.pathname.startsWith('/ava/calendar/')) return info('calendario', route);
  return info('outra_aedb', route);
}
