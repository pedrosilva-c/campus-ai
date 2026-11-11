// Campus AI Companion — deadlines and delivery state of ONE activity of the authorized section (v0.5.4).
// Injected by the scripting API into the course tab the student opened, ONLY after a click on a sync button.
//
// It makes ONE same-origin GET request to the activity's own page, /ava/mod/<assign|quiz>/view.php?id=<cmid>,
// exactly the page the student would open by hand. The address is built here from a validated number and a
// fixed kind; it is never taken from the page. The browser sends its own session with the request: no cookie,
// token or key is read by this code. Redirects are NOT followed (a login or another page is reported, never
// opened). The answer is parsed with DOMParser, which runs no script and loads nothing; the live page is not
// touched. Before anything is read from the fetched page, its <body> must say course-<id>, cmid-<cmid> and
// path-mod-<kind>.
//
// Read: the activity dates region (labels and the visible date text) and, for an assignment, the CSS classes
// Moodle puts on the submission status and grading status cells (submissionstatus*, submissiongraded /
// submissionnotgraded); for a quiz, the attempts summary table (state cells and the presence of review links).
// Never read: grades, feedback, comments, files, other users, any form. Nothing is clicked, submitted or started:
// no quiz attempt is opened (the page is only fetched and parsed). Opening the page does make Moodle record a
// "view" of the activity, the same as opening it by hand.
(() => {
  'use strict';
  if (Object.hasOwn(globalThis, 'CampusAiDetails')) return;   // injected twice in the same page: keep one copy

  const ID = /^[1-9][0-9]{0,9}$/;
  const KINDS = new Set(['assign', 'quiz']);
  const MAX_CHARS = 3 * 1024 * 1024;
  const TIMEOUT_MS = 15000;
  const MAX_RAW = 160;
  const MONTHS = { jan: 1, janeiro: 1, january: 1, fev: 2, fevereiro: 2, feb: 2, february: 2, mar: 3, marco: 3, march: 3,
    abr: 4, abril: 4, apr: 4, april: 4, mai: 5, maio: 5, may: 5, jun: 6, junho: 6, june: 6, jul: 7, julho: 7, july: 7,
    ago: 8, agosto: 8, aug: 8, august: 8, set: 9, setembro: 9, sep: 9, sept: 9, september: 9, out: 10, outubro: 10,
    oct: 10, october: 10, nov: 11, novembro: 11, november: 11, dez: 12, dezembro: 12, dec: 12, december: 12 };
  // Order matters: "data limite" before "data de entrega"; "fecha" is the quiz closing date.
  const LABELS = [
    ['limite', /^(data limite|limite|cut-?off)/],
    ['abertura', /^(abre|aberto|aberta|abertura|disponivel a partir|permitir envios a partir|opened|opens|allow submissions from)/],
    ['entrega', /^(vencimento|data de entrega|entrega|prazo|due)/],
    ['fechamento', /^(fecha|fechado|fechada|fechamento|encerra|encerrado|encerramento|closes|closed)/],
  ];

  const fold = (text) => String(text ?? '').normalize('NFKD').replace(/[̀-ͯ]/g, '').toLowerCase()
    .replace(/\s+/g, ' ').trim();
  const bounded = (text) => String(text ?? '').replace(/\s+/g, ' ').trim().slice(0, MAX_RAW);
  const pad = (n) => String(n).padStart(2, '0');

  // "quarta-feira, 31 dez. 2098, 23:59" / "31 de dezembro de 2098 às 23:59" / "Wednesday, 31 December 2098, 11:59 PM"
  // -> '2098-12-31T23:59' (wall time shown by Moodle, the student's time zone). '' when it cannot be read.
  function parseDate(text) {
    const folded = fold(text);
    const m = /(\d{1,2})\s+(?:de\s+)?([a-z]+)\.?\s+(?:de\s+)?(\d{4})(?:\s*,?\s*(?:as\s*)?(\d{1,2}):(\d{2})\s*(am|pm)?)?/.exec(folded);
    if (!m || !MONTHS[m[2]]) return '';
    const [year, month, day] = [Number(m[3]), MONTHS[m[2]], Number(m[1])];
    const check = new Date(Date.UTC(year, month - 1, day));
    if (check.getUTCFullYear() !== year || check.getUTCMonth() !== month - 1 || check.getUTCDate() !== day) return '';
    let at = `${year}-${pad(month)}-${pad(day)}`;
    if (m[4] !== undefined) {
      let hour = Number(m[4]);
      const minute = Number(m[5]);
      if (m[6] === 'pm' && hour < 12) hour += 12;
      if (m[6] === 'am' && hour === 12) hour = 0;
      if (hour > 23 || minute > 59) return '';
      at += `T${pad(hour)}:${pad(minute)}`;
    }
    return at;
  }

  function kindOf(label) {
    const folded = fold(label).replace(/:$/, '').trim();
    const hit = LABELS.find(([, rx]) => rx.test(folded));
    return hit ? hit[0] : '';
  }

  // Activity dates (Moodle 4: [data-region="activity-dates"] > div > strong label + date text). Returns whether the
  // region exists (a page with the region and no due label has, explicitly, no due date) and the dates found.
  function readDates(page) {
    const regions = page.querySelectorAll('[data-region="activity-dates"], .activity-dates');
    const dates = [];
    for (const region of regions) {
      for (const line of region.querySelectorAll(':scope > div, :scope > p, :scope > li')) {
        const strong = line.querySelector('strong, b, .dimmed_text');
        const label = strong ? strong.textContent : '';
        const kind = kindOf(label);
        if (!kind || dates.some((d) => d.kind === kind)) continue;
        const raw = bounded(line.textContent.replace(label, ''));
        dates.push({ kind, at: parseDate(raw), raw });
      }
    }
    return { region: regions.length > 0, dates };
  }

  // Assignment: submission status table (CSS classes only for the states; the due date row as a fallback date).
  function readAssign(page) {
    const { region, dates } = readDates(page);
    const table = page.querySelector('.submissionstatustable, [data-region="submission-status"]');
    let submission = 'desconhecido';
    let grading = 'desconhecido';
    if (table) {
      for (const cell of table.querySelectorAll('td, div')) {
        for (const token of cell.classList) {
          if (/^submissionstatus_?submitted$/.test(token)) submission = 'enviado';
          else if (/^submissionstatus_?draft$/.test(token)) submission = 'rascunho';
          else if (/^submissionstatus_?reopened$/.test(token)) submission = 'reaberto';
          else if (/^(submissionstatus_?(new)?|nosubmission|submissionstatus_?nosubmission)$/.test(token)
            && submission === 'desconhecido') submission = 'sem_envio';
          else if (token === 'submissiongraded') grading = 'avaliado';
          else if (token === 'submissionnotgraded' && grading === 'desconhecido') grading = 'nao_avaliado';
        }
      }
      for (const row of table.querySelectorAll('tr')) {          // "Data de entrega" row, when the region lacks it
        const head = row.querySelector('th, td');
        const value = head && head.nextElementSibling;
        const kind = head && value ? kindOf(head.textContent) : '';
        if (kind && !dates.some((d) => d.kind === kind)) {
          const raw = bounded(value.textContent);
          dates.push({ kind, at: parseDate(raw), raw });
        }
      }
    }
    return { structure: Boolean(region || table), dates, submission, grading, attempt: 'nao_se_aplica' };
  }

  // Quiz: attempts summary table. A finished attempt has a review link; an unfinished one has a state cell saying
  // "em andamento"/"in progress" (fixed Moodle state words, compared folded). No table = no attempt yet, but only
  // when the page structure was recognised (dates region or quiz information block).
  function readQuiz(page) {
    const { region, dates } = readDates(page);
    const table = page.querySelector('table.quizattemptsummary');
    const info = page.querySelector('.quizinfo, [data-region="quiz-info"], .quizattempt');
    let attempt = 'desconhecido';
    if (table) {
      let finished = 0;
      let open = 0;
      for (const row of table.querySelectorAll('tbody tr')) {
        // cell by cell: row.textContent glues "1" and "Em andamento" into "1em andamento" (no word boundary)
        const text = fold([...row.querySelectorAll('td, th')].map((cell) => cell.textContent).join(' '));
        if (/\b(em andamento|em progresso|in progress)\b/.test(text)) open += 1;
        else if (row.querySelector('a[href*="/mod/quiz/review.php"]') || /\b(finalizada|finalizado|finished|enviada|enviado)\b/.test(text)) finished += 1;
      }
      attempt = open ? 'em_andamento' : finished ? 'finalizada' : 'desconhecido';
    } else if (region || info) {
      attempt = 'nenhuma';
    }
    return { structure: Boolean(region || table || info), dates, submission: 'nao_se_aplica', grading: 'nao_se_aplica', attempt };
  }

  async function read(doc, loc, options) {
    const out = (result, facts = null) => ({ result, facts });
    const cmid = String((options && options.cmid) || '');
    const kind = String((options && options.kind) || '');
    const courseId = String((options && options.courseId) || '');
    if (!ID.test(cmid) || !KINDS.has(kind) || !ID.test(courseId)) return out('parametros_invalidos');
    if (loc.protocol !== 'https:' || loc.hostname !== 'ead.aedb.br' || loc.port) return out('fora_do_dominio');
    if (!doc.body.classList.contains(`course-${courseId}`)) return out('curso_diferente');

    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    let response;
    let text = '';
    try {
      response = await fetch(`/ava/mod/${kind}/view.php?id=${cmid}`, {
        method: 'GET', credentials: 'same-origin', mode: 'same-origin', redirect: 'manual', cache: 'no-store',
        referrerPolicy: 'same-origin', signal: controller.signal,
      });
      if (response.type === 'opaqueredirect' || (response.status >= 300 && response.status < 400)) return out('redirecionado');
      if (response.status === 401 || response.status === 403 || response.status === 404) return out('inacessivel');
      if (!response.ok) return out('falha_http');
      if (!/^text\/html\b/i.test(response.headers.get('content-type') || '')) return out('nao_html');
      text = await response.text();
    } catch {
      return out(controller.signal.aborted ? 'tempo_esgotado' : 'falha_rede');
    } finally {
      clearTimeout(timer);
    }
    if (text.length > MAX_CHARS) return out('grande_demais');

    const page = new DOMParser().parseFromString(text, 'text/html');
    const classes = [...page.body.classList];
    if (page.body.id === 'page-login-index' || classes.includes('pagelayout-login')) return out('sessao_expirada');
    if (!classes.includes(`course-${courseId}`) || !classes.includes(`cmid-${cmid}`) || !classes.includes(`path-mod-${kind}`)) {
      return out('pagina_nao_reconhecida');
    }
    const facts = kind === 'assign' ? readAssign(page) : readQuiz(page);
    return facts.structure ? out('ok', facts) : out('estrutura_desconhecida');
  }

  Object.defineProperty(globalThis, 'CampusAiDetails', { value: Object.freeze({ read, parseDate }), configurable: false });
})();
