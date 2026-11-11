# Resultado estrutural real — Modelagem UML (curso 7653)

Data: 05/11/2026. Executado pelo Claude Code via Claude in Chrome ("Browser 1", Windows, local), numa aba
nova criada para a sessão e fechada no fim. Sessão AEDB já autenticada pelo aluno (nenhum login,
credencial ou cookie tocado). Só JavaScript próprio, somente leitura: nenhum clique, download, envio,
rolagem ou alteração. Navegação: `course/view.php?id=7653` → destino do tile "Atividades Avaliativas"
aberto **pelo endereço** → de volta a `view.php?id=7653`.

**Registrado aqui:** apenas estrutura (tags, classes, nomes de atributos, padrões de rota com números
ocultos, contagens, formato das datas com dígitos/letras mascarados). **Não registrado:** títulos,
datas reais, nomes, ids de seção, URLs completas, HTML, cookies. Nenhum conteúdo de atividade foi lido.

## 1. Página inicial (`/ava/course/view.php?id`)

- Identidade: `body.course-7653` presente; aba "Curso: … Modelagem UML | AVA"; sem formulário de senha.
- `body`: **`format-tiles`** (plugin de formato "Tiles"), `path-course-view`, `lang-pt_br`.
- **Tiles:** 12 `li.tile`, dos quais **5 reais** (`tile tile-clickable tilestyle-1 phototile`) e 7
  espaçadores. Os 5 correspondem a Informações da Disciplina, Trilhas de Aprendizagem, Atividades
  Avaliativas, Feedback das Aulas e Fale com o Professor.
  - Atributos do `li`: `id`, `data-section` (número), `data-true-sectionid` (id da seção no banco).
  - Controle: `<a class="tile-link" href="/ava/course/section.php?id=<sectionid>" data-section aria-label>`,
    sem `onclick` inline e sem `target`. `href.id == data-true-sectionid` nos 5 tiles.
- **Nenhuma atividade é renderizada na página inicial:** `li.activity` = 0, nós de data = 0.
- **Índice do curso (gaveta lateral, núcleo do Moodle 4.x):** 6 `.courseindex-section`
  (`data-for`, `data-id`=id da seção, `data-number`), 45 `a.courseindex-link`. Ele já lista **todas as
  seções e atividades** com rota de módulo; rótulos (`mod_label`) aparecem como
  `section.php?id=<mesma seção>#…`.
- Tipos de módulo vistos no índice: `resource` 15, `url` 9, `feedback` 9, `attendance` 6, `assign` 6,
  `groupselect` 2, `forum` 1, `msteams` 1.

## 2. Destino do tile "Atividades Avaliativas" (`/ava/course/section.php?id`)

- Identidade confirmada na chegada: `body.course-7653`, `path-course-view-section`,
  `pagelayout-course`, título "Bloco: Atividades Avaliativas | … Modelagem UML | AVA".
- **10 `li.activity`**: `label` 3, `assign` 5, `resource` 1, `groupselect` 1. Marcação padrão Moodle 4.x:
  `li.activity.activity-wrapper.modtype_<tipo>` com `data-cmid` (numérico em todos), `data-modtype`,
  **`data-title`** (em todos), `data-id`, `data-completion`, `data-completion-state`.
- **Relação com AV1/AV2:** AV1 e AV2 **não são seções**. São itens dentro desta única seção, identificados
  pelo nome: um `resource` e um `assign` com padrão "AV1"; um `groupselect` com padrão "AV2". Os 3
  `label` funcionam como separadores entre blocos. Ordem no índice: rótulo, 3 × assign, resource(AV1),
  assign(AV1), rótulo, groupselect(AV2), assign, rótulo.
- **Prazos:** **nenhuma data é exibida na página da seção** (`[data-region="activity-dates"]` = 0,
  `<time>` = 0, nenhum texto com formato de data nos `assign`). O curso parece não mostrar datas de
  atividade.
- Controles perigosos presentes: **3 botões de conclusão manual** (rótulos com `completion-manual`).
  `data-completion-state` é progresso de conclusão, **não** estado de entrega.
- 8 expansores recolhidos: todos do índice/gavetas, não de seções de conteúdo.
- Blocos laterais: `calendar_upcoming`, `calendar_month`, `completion_progress`, `dedication`,
  `accessibility`, `bibliolink`, `jacadlink`, 2 × `html`.
- `calendar_upcoming`: elementos `.event[data-region][data-eventtype-course]` (eventos **do curso**,
  criados pelo professor); **0 links para módulos**, portanto sem vínculo direto com `cmid`. Formato da
  data mascarado: `a, 9 a, 99:99`, `a-a, 99 a, 99:99 » 99:99` (dia da semana, dia, mês, hora; **sem ano**).
- Rotas de calendário presentes: `/ava/calendar/view.php?course&view`, `?course&time&view`,
  `/ava/calendar/managesubscriptions.php?course`. A página de exportação iCal não foi aberta.

## 3. Comparação com os adaptadores e fixtures atuais

| Suposição atual | Realidade observada | Consequência |
| --- | --- | --- |
| Cartões são `.section.card` / blocos de tema (`cards_course.html`) | `format-tiles`: `li.tile` + `a.tile-link` | `NAV_JS` encontra o tile (`[class*="tile"]`), mas o destino falha (próxima linha) |
| Destino de cartão = `course/view.php?id=<curso>[&section=N]` (`pilot_nav.classify_destination`) | `course/section.php?id=<sectionid>` | Hoje vira **"rota desconhecida"** → pergunta/parcial. O id é da seção, não do curso: a validação de "mesma disciplina" precisa acontecer **na chegada** (`body.course-<id>`), não pela URL |
| AV1/AV2 são `li.section` recolhidas com expansor (`nav_avaliativas.html`, `EXPAND_JS`) | AV1/AV2 são nomes de atividades numa única seção, separadas por rótulos | A procura por seções "AV1/AV2" e a expansão não encontram nada; só o padrão no nome |
| Prazos em `[data-region=activity-dates]` | Ausentes na página; só eventos de curso no bloco `calendar_upcoming`, sem ano e sem vínculo com módulo | O piloto devolve todas as atividades com prazo "Não informado" |
| Tipos de módulo do contrato/piloto | Também `attendance`, `groupselect`, `msteams`, `label` | Itens descartados como "sem tipo reconhecido" |
| `pilot.py` ignora `#courseindex` como "chrome" | O índice é a fonte mais completa e estável de estrutura | Oportunidade: inventário sem navegação |
| `moodle_browser` lê `data-cmid` | `data-cmid` presente em todos os itens | Confirma uma escolha antiga |

Nenhuma fixture atual reproduz `format-tiles`, `section.php`, `data-title` ou o índice com módulos.
`aedb_theme_course.html` tem a gaveta do índice, mas sem essa estrutura.

## 4. Viabilidade de um coletor local confiável (Companion)

**Títulos, tipos, ids e agrupamento AV1/AV2: sim, com alta confiança.** A estrutura é Moodle 4.x de núcleo
mais o formato Tiles, com atributos estáveis e semânticos (`data-cmid`, `data-modtype`, `data-title`,
`data-true-sectionid`, `courseindex` com `data-for`/`data-id`). Nada depende de classes do tema nem de
texto. O índice do curso na página inicial dá o inventário completo sem navegar. A página
`section.php` confirma e acrescenta conclusão e ordem.

**Prazos: não a partir dessas páginas.** Não há datas de atividade renderizadas. Fontes candidatas, em
ordem de confiabilidade: (1) **exportação iCal** do Moodle (estruturada, com ano, `UID` e vínculo com o
evento); (2) a visão de calendário do curso (`calendar/view.php?view=upcoming&course=…`), lida como
página; (3) o bloco `calendar_upcoming` (texto sem ano, eventos de curso, sem vínculo); (4) páginas
`mod/assign/view.php` (hoje bloqueadas pela política; exigiriam autorização própria).

**Estado de entrega:** não aparece nessas páginas. Continua `desconhecido`, nunca inferido.

## 5. Ajustes necessários (não feitos nesta etapa)

1. Aceitar `/ava/course/section.php?id=<n>` como destino de leitura **condicionado** à verificação de
   `body.course-<id>` na chegada (Companion: incluir esse padrão em `matches` e em `REPORTABLE_PAGES`).
2. Extrator baseado em `li.activity[data-cmid][data-modtype][data-title]` e no índice do curso;
   agrupar AV1/AV2 pelo padrão no título e pelos rótulos separadores, com confiança `media`.
3. Acrescentar `attendance`, `groupselect`, `msteams` e `label` (separador, não material) ao vocabulário.
4. Prazos via iCal (F5 antecipada) ou pela visão de calendário do curso, com autorização própria.
5. Fixtures novas devem reproduzir **esta** marcação, com texto sintético.

**Status (mesmo dia):** os itens 1–3 e 5 foram implementados e testados só com fixtures sintéticas
(`companion/src/tiles_adapter.js`, `dom_tiles.js`, `tests/fixtures/companion/tiles_section.html`). O
item 4 (prazos) segue pendente. Nada disso foi validado contra a AEDB real (ver §7).

## 6. Leitura consentida dos itens da seção (opção A) — 05/11/2026

Autorização do aluno: **somente** `data-title`, `data-modtype` e `data-cmid` dos itens que não são
rótulos da seção Atividades Avaliativas. Os rótulos foram descartados **antes** de qualquer acesso a seus
atributos; nenhum texto de elemento, enunciado, anexo, página interna, calendário ou nota foi lido.
Títulos e ids reais **não** são gravados no repositório (foram mostrados ao aluno só na conversa, para
conferência visual).

| Achado | Resultado |
| --- | --- |
| Itens que não são rótulo | 7 (3 rótulos ignorados) — confere com o índice do curso observado antes |
| Tipos (`data-modtype`) | `assign` ×5, `resource_pdf` ×1, `groupselect` ×1 |
| **Subtipo no modtype** | O arquivo vem como `resource_pdf`, mas o módulo na rota continua `resource`. O mapeamento precisa aceitar `resource_<subtipo>` |
| `data-cmid` | 7 de 7 numéricos e **distintos** na página |
| `data-title` | presente nos 7 |
| Marca explícita de avaliação no título | 3 de 7: AV1 ×2 (o arquivo e uma tarefa), AV2 ×1 (a escolha de grupo) |
| Sem marca | 4 de 7: 3 tarefas no primeiro bloco e 1 tarefa no segundo |
| Blocos (separados por rótulos) | bloco 1: 3 tarefas + arquivo AV1 + tarefa AV1; bloco 2: escolha de grupo AV2 + 1 tarefa |

**Identificadores e deduplicação.** O `data-cmid` é o `course_modules.id` do Moodle. O uid
`moodle:course:<id>:module:<cmid>` é exatamente o esquema que `moodle.py` e `moodle_browser.py` já
produzem, então o histórico SQLite e os nomes de nota continuam compatíveis. **Estabilidade ao longo do
tempo não está provada** (uma única leitura): o `cmid` muda se a disciplina for restaurada/copiada ou o
módulo for recriado. Validar com uma segunda leitura em outro dia (§7).

**Agrupamento AV.** Só 3 dos 7 títulos dizem AV1/AV2. Os demais são atribuídos pela **posição** (bloco
entre rótulos que contém exatamente uma marca AV) e ficam marcados `assessment_basis='posicao'`, confiança
`media`. Isso é uma inferência: sem ler o texto dos rótulos (não autorizado) não dá para saber se o
primeiro bloco inteiro é de fato AV1.

**Não verificado nesta leitura:** o `href` dos links dentro de `li.activity` (só o índice lateral foi
visto antes; o adaptador aceita `href` ausente e então deixa a URL vazia); o texto exibido do item
versus `data-title`; prazos; estado de entrega.

## 7. Procedimento de validação real (próximo passo, depende do aluno)

1. Conferir, na tela da seção, os 7 itens (título e tipo) contra a tabela mostrada na conversa.
2. Carregar a extensão **sem empacotar** e usar o popup de pré-visualização: passo a passo, permissões e
   remoção em [`companion/README.md`](../../companion/README.md). Não há Native Messaging: o resultado
   aparece só no popup, na memória.
3. (Substituído: o popup mostra os módulos, a classificação, duplicações/dados ausentes e a comparação com
   esta referência, sem registrar nada.)
4. Repetir a leitura em outro dia e comparar `cmid`s (estabilidade) e títulos.
5. Só então decidir o registro HKCU do host e a caixa de entrada (F4).
