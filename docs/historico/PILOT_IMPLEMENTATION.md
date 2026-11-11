# Piloto AEDB — seleção manual de uma disciplina

## Navegação controlada por cartões (Atividades Avaliativas) — 05/11/2026

### Por que a estratégia anterior não bastava

O diagnóstico do usuário: o AVA da AEDB tem página inicial de cartões e o conteúdo fica **atrás**
deles. Rolar a página e procurar `.section` só enxerga o DOM inicial. A camada nova navega entre as
páginas da mesma disciplina e reaproveita a leitura existente (rolagem, expansores verificados,
cobertura honesta) em cada página alcançada.

### Fluxo (um clique em **Analisar disciplina**)

1. Abre a disciplina e confirma sessão e identidade (como antes).
2. `NAV_JS` (modo `cards`) **descreve** os cartões da região principal sem tocar em nenhum: papel
   (alvo, estudo, informativo, bloqueado, outro), tag, tipo de navegação (link, atributo, script,
   aba, âncora, JS sem destino), presença de href, host e padrão de rota.
3. Python decide o que fazer com o cartão **Atividades Avaliativas** (`plan_card`):
   - **link / `data-href` / destino em `onclick`** validados: abre **por endereço** (`goto`), sem
     clicar; o handler do cartão nunca roda;
   - **aba semântica** (`role=tab` + `aria-controls`): clica uma vez e lê na própria página;
   - **âncora** da mesma página: nenhuma navegação, lê a página;
   - **comportamento não verificável / rota desconhecida / parâmetros extras**: nada é tocado e o
     aplicativo **pergunta** (padrão Não). Sim = um clique, depois verificação do contexto e leitura
     parcial; Não = só a página inicial é lida;
   - **bloqueado** (outro curso, outro host, atividade/arquivo/conta) ou **módulo não suportado**:
     não navega; leitura parcial com o motivo.
4. Após navegar: aguarda a página assentar, confirma sessão, id do curso e que o endereço final
   ainda é página da disciplina; lê AV1/AV2/atividades/materiais/prazos (rolagem + expansão);
   emite os estados "Acessando Atividades Avaliativas", "Identificando AV1/AV2", "Extraindo
   materiais", "Verificando cobertura"; **volta** à página da disciplina e confirma o retorno.
5. Resultado: tabela (disciplina, seção, tipo, título, prazo) e diagnóstico com o texto
   `Navegação: cartões N (tipos) ...`, rota (padrão sem valores), páginas visitadas, retorno,
   cartões não examinados, informativos e bloqueados.

### Segurança

| Item | Como é tratado |
|---|---|
| Destino | `classify_destination`: https, host exato, sem porta/credenciais, rota de leitura, mesmo id |
| Feedback / Fale com o Professor / enviar / concluir / responder / excluir / editar / baixar | nunca alvo; nunca clicados |
| Atividades, arquivos, mensagens, usuário, admin, edição | rotas bloqueadas; nada é aberto |
| Downloads | `Browser.setDownloadBehavior deny` antes da primeira navegação (testado) |
| Profundidade | 1: cartões da página de destino nunca são seguidos |
| Cancelar, timeout, navegador fechado | encerram sem fechar o Chromium nem tocar no perfil |
| Sessão expirada | `PilotLoginRequired`; não tenta voltar |

### Modo de inspeção (diagnóstico real assistido)

A caixa **Somente inspecionar a estrutura dos cartões** executa só a etapa 2: nada é navegado,
clicado ou lido. A saída traz, por cartão, `[papel] tag tipo href=sim|não host+rota → decisão`, mais
a contagem de cartões. É o que deve ser enviado se a navegação não funcionar na AEDB real.
Nenhum HTML, texto privado, URL completa, cookie ou cabeçalho é registrado; o texto pode ser
copiado da própria tela e não é salvo nem enviado.

### Arquivos

- Criados: `campus_ai/pilot_nav.py`, `tests/test_pilot_nav.py`, `tests/test_pilot_dom_nav.py`
  (opt-in), `tests/fixtures/nav_home.html`, `tests/fixtures/nav_avaliativas.html`.
- Alterados: `campus_ai/pilot.py` (`PilotStop`, `navigation`/`notes` no resultado, gancho de seções,
  `check_identity`/`check_nav`), `browser_runtime.py` (`_pilot_run`, ação `pilot_continue`),
  `pilot_ui.py` (botão único, caixa de inspeção, estados, pergunta do cartão), `ui.py` (cancelamento),
  `tests/test_pilot_ui.py`, `test_pilot_expand.py`, docs e skill.
- Backup: `.tmp-campus-ai/cards-before-20261105/` (14 arquivos).

### Testes

300 descobertos: **255 aprovados + 45 opt-in ignorados**; com `CAMPUS_AI_BROWSER_SMOKE=1` (Chromium
headless local; `ead.aedb.br` respondido por `route.fulfill`; resto abortado; proxy inexistente):
**300 aprovados**. Fluxo Início → Atividades Avaliativas → AV1/AV2 → materiais → retorno, por link,
atributo, script e aba; cartão ambíguo (pergunta, Sim, Não); destinos de atividade, outro curso,
outro host, rota desconhecida e parâmetros extras; sessão expirada na página de destino; timeout
(requisição pendurada); cancelamento; downloads negados; botões perigosos que registram qualquer
clique (concluir, enviar, baixar, responder) e nunca são acionados; só GET e só as URLs esperadas.
**Os testes usam HTML fictício: não provam compatibilidade com a AEDB real.**

### Como validar no Windows

1. Feche a instância antiga pela bandeja. Execute:
   ```powershell
   Set-Location '<pasta-do-projeto>'
   .\.venv\Scripts\python.exe -m campus_ai --pilot
   ```
2. **Primeira vez:** marque *Somente inspecionar a estrutura dos cartões* e clique em **Analisar
   disciplina**. Confira se o cartão Atividades Avaliativas aparece como `[target]` e qual a
   decisão ("navegaria (link validado)", "pediria confirmação ..." etc.).
3. Desmarque e clique de novo. Acompanhe os estados; ao final confira AV1, AV2, prazos e o texto de
   cobertura. Se o aplicativo perguntar sobre o cartão, leia a pergunta antes de responder.
4. Se falhar, envie só o texto do estado (estrutura e contagens).

### Diagnóstico esperado (fictício)

`Cobertura parcial: 2 seções acadêmicas reconhecidas, 1 expandida automaticamente, 1 já aberta, 0
não acessíveis. 2 materiais e 2 atividades extraídos. ... Navegação: cartões 5 (link 4, onclick-url
1); alvo Atividades Avaliativas via link (rota /ava/course/view.php?id&section); páginas visitadas 2;
retorno à disciplina confirmado; não examinados (fora do escopo desta etapa): Trilhas de
Aprendizagem; informativos não lidos: Informações da Disciplina; bloqueados (nunca acionados):
Feedback das Aulas, Fale com o Professor.` Parcial **porque Trilhas ainda não é lida**.

### Reverter

Feche o app pela bandeja. Restaure de `.tmp-campus-ai/cards-before-20261105/` os 14 arquivos aos
mesmos caminhos (`campus_ai/pilot.py`, `pilot_ui.py`, `browser_runtime.py`, `browser_worker.py`, os
testes, `README.md`, `AGENTS.md`, `PILOT_IMPLEMENTATION.md`, a skill) e `campus_ai/ui.py` (uma linha:
`'pilot_continue'` no cancelamento; sem backup próprio, desfaça a edição), e remova os 5 arquivos
criados acima. Rode a suíte. Nada no perfil do Chromium, ACLs, SQLite, Obsidian ou Gmail foi tocado.

### Limitações

- Estrutura real dos cartões desconhecida: o destino pode ser uma página de módulo (`page`, `book`,
  `folder`), hoje **não suportada** (informada como parcial), ou uma rota própria do tema (pergunta).
- Se o clique do cartão ambíguo muda o conteúdo sem mudar o endereço, a leitura vale para a página
  atual e é marcada parcial.
- Trilhas de Aprendizagem e Informações da Disciplina não são lidas nesta etapa.
- Seções vazias legítimas ainda aparecem como "estado desconhecido" (cautela).

## Leitura vazia no Moodle real: estrutura, rolagem e cobertura — 05/11/2026

### Evidência e causa

Relato do uso real: "cobertura completa, 6 seções, 0 expandidas, 6 abertas, 0 materiais, 0
atividades, uma linha 'Seção 1'", com o navegador na área de cartões (Avisos, Currículo Lattes,
Informações da Disciplina, Trilhas de Aprendizagem, Atividades Avaliativas).
Reproduzido com HTML fictício equivalente (`tests/fixtures/cards_only.html`): o código anterior
dizia *"Cobertura completa: 7 seções identificadas, 0 expandidas, 7 já abertas ... 0 materiais"*
com linhas "Avisos", "Currículo Lattes" ... "Seção 6", "Seção 7". Causas **comprovadas no código**:

1. `sectionSelector` aceitava `.section` genérico e `[data-sectionid]` em qualquer tag: cartões do
   tema viraram "seções".
2. Estado "aberta" era o padrão (`collapsed ? 'collapsed' : 'open'`): sem região oculta e sem
   atividade oculta, tudo era "aberto", mesmo sem conteúdo nem expansor.
3. O nome caía em `'Seção ' + (i + 1)` (a linha genérica "Seção 1").
4. Nenhuma regra ligava a cobertura aos itens extraídos: zero itens podia ser "completo".
5. Sem rolagem (conteúdo renderizado só ao rolar não existia na leitura) e a leitura só reconhecia
   um formato de marcação de atividade.

**Ainda depende da AEDB real** (não verificável aqui): se AV1/AV2 são seções Moodle recolhíveis
abaixo dos cartões, conteúdo carregado por rolagem/clique, ou páginas separadas (`&section=N`);
e como o expansor é marcado. O diagnóstico novo foi desenhado para responder isso.

### O que mudou

- **Classificação** (JS fixo): candidatas → acadêmicas. Assinatura forte do Moodle, ou `.section`
  fraco com atividades reais; só o bloco mais interno vale (wrappers ficam fora). Cartões e regiões
  de layout são contados e ignorados. `<details>` fechado passou a ser expansor reconhecido.
- **Estado de bloco**: `collapsed` / `open` (precisa de conteúdo renderizado ou região
  expandida) / `unknown`. Blocos sem nome não geram linha "Seção N".
- **Rolagem** (`explore_page`): passos de 85% da viewport, espera 400 ms, até o fundo estável por
  2 leituras; máx. 30 passos e 20 s (`PilotLimits.scroll_ms`); volta ao topo; repete se algo
  foi expandido. Só a viewport se move.
- **Leitura**: marcação de atividade ampliada (`li[id^=module-]`, `modtype_*`); em seção forte sem
  invólucro reconhecido, usa os links `/mod/<tipo>/view.php?id=` visíveis. Módulos fora de seções
  (cartões) só são contados.
- **Navegação adicional**: link de página de seção (`view.php?id=<curso>&section=N`) para uma
  seção ausente ou vazia conta como dependência de outra página: não é seguido, resultado parcial.
- **Cobertura** (`_decide`): `completa`, `parcial`, `nao_validada`, `falhou`. Regras na seção do
  AGENTS.md. Zero itens só é "completa" se o índice do curso (quando existe) também lista 0 itens
  e não há links/atividades fora das seções.

### Diagnóstico esperado

Página do relatório (fictícia): `Cobertura não validada: 2 seções acadêmicas reconhecidas, 0
expandidas automaticamente, 0 já abertas, 2 de estado desconhecido, 0 não acessíveis (bloco sem
nome (seção 1): estado desconhecido: sem conteúdo visível nem expansor reconhecido; ...). 0
materiais e 0 atividades extraídos. Diagnóstico estrutural: regiões candidatas 8; expansores
seguros 0, acionados 0; elementos de atividade 0; itens extraídos 0; rolagens 2; ignorados: layout
6, cartões de navegação para outra página 2, links de módulo fora de seções 1. Motivos: nenhum
material ou atividade extraído e nada confirma que a disciplina esteja vazia.`

Curso com cartões, seções abaixo da dobra e AV2 carregada por rolagem: `Cobertura parcial: 4
seções acadêmicas reconhecidas, 1 expandida automaticamente, 1 já aberta, 1 de estado
desconhecido, 1 não acessível (AV3: nenhum controle de expansão encontrado; estrutura:
div.hdr[onclick]; ...)`. A parte "estrutura:" só traz tags/classes/presença de atributos: é o que
permite ajustar o reconhecimento da AEDB sem expor conteúdo.

### Arquivos

- Criados: `tests/test_pilot_dom_structure.py` (opt-in), `tests/fixtures/cards_course.html`,
  `tests/fixtures/cards_only.html`.
- Alterados: `campus_ai/pilot.py` (programas JS, `Coverage`, `explore_page`, `_decide`, texto),
  `campus_ai/pilot_ui.py` (estado "não validada", etapa "explorando"), `tests/test_pilot_expand.py`
  (simulador + 13 testes novos), `test_pilot.py`, `test_pilot_flow.py`, `test_pilot_ui.py`,
  `test_pilot_dom_expand.py`, docs e skill. `browser_runtime.py` não mudou.

### Testes

245 descobertos: **215 aprovados + 30 opt-in ignorados**; com `CAMPUS_AI_BROWSER_SMOKE=1`
(Chromium headless local, `ead.aedb.br` respondido por `route.fulfill`, resto abortado, proxy
inexistente): **245 aprovados**. Novos: cartões antes das seções, seções abaixo da dobra,
conteúdo após rolagem, abertas/recolhidas/desconhecidas, elementos que parecem seções, seção sem
expansor, atividades com título, material sem prazo, leitura parcial, cancelamento durante a
rolagem, timeout de rolagem, sessão expirada, navegação adicional, divergência do índice do curso
e nenhum clique em cartões.

### Reverter

Encerre o aplicativo pela bandeja. Restaure de `.tmp-campus-ai/structure-before-20261105/` os 15
arquivos aos mesmos caminhos (`campus_ai/pilot.py`, `pilot_ui.py`, `browser_runtime.py`, os testes,
`README.md`, `AGENTS.md`, `PILOT_IMPLEMENTATION.md` e a skill) e remova os três arquivos criados
acima. Rode a suíte. Estados anteriores: `expand-before-20261105/`, `simplify-before-20261105/`.
Nada no perfil do Chromium, ACLs, SQLite, Obsidian ou Gmail foi tocado.

### Limitações

- Estrutura real da AEDB desconhecida; seção vazia legítima sem expansor fica "desconhecida" (parcial).
- O índice do curso pode listar itens que a leitura não conta (parcial por cautela).
- Nada é seguido além da página autorizada; conteúdo só acessível por outra página fica parcial.
- Rolagem de contêineres internos cobre `#page`, `#region-main`, `main` e similares.

## Expansão automática de seções e cobertura — 05/11/2026

### Por que era preciso expandir à mão

O leitor só enxerga o DOM **renderizado** (propositalmente: não lê texto oculto). O conteúdo
de uma seção recolhida (`display:none`) não é renderizado, e o piloto **nunca clicava**
em nada. Além disso, a única detecção de "recolhida" era `.section .collapse:not(.show)`
(Bootstrap): num tema que recolhe de outro jeito o contador dava 0 e o resultado saía
"completo" sem cobertura real. Isso explica o "Leitura concluída" com AV1/AV2 fechadas.

### O que mudou

1. **Plano** (`EXPAND_JS`, modo `plan`, sem interação): lista as seções da região principal
   (as mais externas; fora de gavetas, índice, blocos e menus), o estado de cada uma
   (recolhida se uma região controlada/`.collapse` não é renderizada, ou se suas atividades
   existem no DOM sem serem renderizadas) e a classificação do expansor: `safe`,
   `ambiguous`, `unsafe` ou `none`.
2. **Clique** (modo `click`, uma seção por vez, chave vinda do plano): o JS recalcula tudo e
   só clica se o controle for um expansor verificado (veja AGENTS.md). Ambíguo = mais de uma
   região controlada distinta na mesma seção. Inseguro = existe candidato, mas falha em
   alguma verificação (formulário, `download`, `target`, `data-action`, href que não seja
   fragmento, rótulo como excluir/enviar/baixar/salvar/editar/concluir/marcar, região fora
   da seção ou dentro de atividade, controle invisível). Controles de menu
   (`aria-haspopup`, `.dropdown-menu`, `.section-actions`) e tudo dentro de atividades são
   ignorados.
3. **Espera** (`state`): reavalia a cada 250 ms até a seção estar aberta, sem `aria-busy`/
   spinner/`.collapsing` e com o conteúdo estável por duas leituras (cobre carregamento
   assíncrono). Prazo por seção 6 s; orçamento total 30 s (`PilotLimits.expand_ms`).
4. **Novas rodadas** (até 3): seções reveladas ou alteradas no DOM pela expansão são
   replanejadas; cada seção é tentada uma vez.
5. **Leitura final** (uma só): cada item agora traz **seção**, tipo, título, prazo
   rotulado ("Não informado" se não houver) e a referência permitida (`/mod/<tipo>/view.php?id=`
   sem parâmetros privados). Itens repetidos (mesmo módulo, ou mesma seção+tipo+título)
   são listados uma vez e contados.

### Cobertura (o que "completo" significa)

`Coverage`: seções identificadas, expandidas automaticamente (e verificadas carregadas),
já abertas, não acessíveis (com o motivo por seção), materiais, atividades, seções sem
itens, repetições removidas. **Completa** = todas as seções identificadas foram examinadas,
sem truncamento. **Parcial** = qualquer seção não acessível (ambígua, insegura, sem
controle, tempo/limite esgotado, não expandiu, não carregou a tempo), zero seções
reconhecidas, nós/tempo esgotados ou mais seções que o limite. O estado na tela é
"cobertura completa" ou "cobertura parcial", nunca "concluído". Estado de entrega não é
lido: nenhuma atividade é classificada como pendente.

### Arquivos

- Criados: `tests/test_pilot_expand.py`, `tests/test_pilot_dom_expand.py` (opt-in),
  `tests/fixtures/collapsible_course.html`, `tests/fixtures/collapsible_mixed.html`.
- Alterados: `campus_ai/pilot.py` (programas JS reestruturados, `Coverage`, `expand_sections`,
  `read(expand=, progress=)`, deduplicação, texto de cobertura, `PilotLimits.expand_ms`),
  `browser_runtime.py` (análise e leitura pós-nome passam `expand=True`), `pilot_ui.py`
  (estado "expandindo", rótulos de cobertura, coluna Seção, itens sem contar seções),
  `tests/test_pilot.py`, `test_pilot_flow.py`, `test_pilot_title.py`, `test_pilot_ui.py`,
  `test_pilot_dom_themes.py`, `test_pilot_flow_chromium.py`, docs e skill.
- Corrigido de passagem: navegador fechado no meio da leitura dizia "A disciplina mudou".
- Backup: `.tmp-campus-ai/expand-before-20261105/` (14 arquivos).

### Testes

219 descobertos: **200 aprovados + 19 opt-in ignorados**; com `CAMPUS_AI_BROWSER_SMOKE=1`
(Chromium headless local, `ead.aedb.br` respondido por `route.fulfill`, resto abortado,
proxy inexistente como barreira): **219 aprovados**. Cobertos: AV1/AV2 recolhidas, seções
já abertas, conteúdo assíncrono, seção vazia, expansor ambíguo/inseguro/ausente,
duplicados, limite de tempo e de quantidade, seção que não expande, clique recusado,
seção aninhada revelada, cancelamento, sessão expirada e navegador fechado durante a
expansão, navegação indevida, downloads negados antes do primeiro clique, e — no DOM real —
que só os expansores foram acionados (botões de concluir/enviar/baixar/menu/excluir das
fixtures registram qualquer clique e ficaram vazios), que nenhuma requisição além de GET
da própria disciplina ocorreu e que nenhum arquivo foi requisitado.

### Limitações

- Marcação real da AEDB desconhecida. Expansores sem `aria-expanded`/`aria-controls` e sem
  gatilho Bootstrap (ex.: `<details>`, `div` com `onclick`) ficam intactos e geram
  cobertura parcial; o motivo mostra a estrutura (tags/atributos) para ajustar.
- Moodle pode lembrar as seções abertas (preferência de interface); não restauramos.
- Formatos de curso paginados (uma seção por página) mostram apenas a seção da página.
- Seção "recolhida" detectada por heurística; atividades no DOM mas invisíveis por CSS
  (modelos de edição, por exemplo) contam como seção não acessível.
- Cancelar não reverte seções já abertas.

### Validar no Windows

```powershell
Set-Location '<pasta-do-projeto>'
.\.venv\Scripts\python.exe -m campus_ai --pilot
```

(encerre antes a instância antiga pela bandeja). Aba piloto, **Analisar disciplina
selecionada**, sem abrir AV1/AV2. Confira "cobertura completa/parcial", as contagens e, se
parcial, os motivos por seção. Se vier parcial, envie só o texto do estado.

## Abertura direta e análise com um clique — 05/11/2026

### Causa do `about:blank`

A ação `pilot_open` só chamava `BrowserRuntime._ensure_open()`: o Playwright cria o
contexto persistente com uma primeira aba em branco e, **por decisão do desenho de
14/10** ("sem navegação automática; o usuário digita/navega"), nenhum `goto` era feito.
Não era falha do Chromium nem do perfil. O piloto então exigia seleção manual da aba,
confirmação e um segundo clique para ler.

### Novo fluxo (um clique)

`Analisar disciplina` → worker v2 (único dono do Chromium):

1. `abrindo`: reutiliza/abre o Chromium dedicado (perfil persistente intacto), nega
   downloads por CDP **antes** de navegar e vai direto à URL autorizada
   (`pilot_flow.reach_course`; se a aba já está na disciplina, não recarrega).
2. `login`: se cair em `/ava/login/`, `/ava/auth/` ou em provedor externo, apenas
   consulta `page.url` a cada 1 s (até 3 min) enquanto você entra **manualmente**.
   Ao voltar, se o Moodle levar a outra página AEDB, navega de novo (no máximo 3
   navegações no total) à mesma URL autorizada.
3. `autenticado`: sessão reconhecida por menu do usuário/logout; formulário de senha,
   `body.notloggedin` e menu de visitante contam como não autenticado. Página ainda
   carregando não é tratada como login (espera até 30 s).
4. Identidade (`PilotReader.identify`): automática se o título visível combina com
   *Modelagem UML*, **ou** se o id do curso na própria página (classe do `body` /
   `M.cfg.courseId`) é 7653 — um cabeçalho personalizado não reconhecido deixa de
   bloquear. A URL sozinha nunca basta. Sem título nem id: **um** diálogo pede/confirma
   o nome (o nome digitado é só rótulo; a leitura continua presa à URL autorizada).
5. `analisando` → `concluído` / `parcial` / `erro`: mesma leitura limitada de antes
   (somente títulos, seções, materiais, atividades e prazos rotulados visíveis;
   prazo ausente = "Não informado"; seção recolhida = resultado parcial).

Outras abas do Chromium são ignoradas, não inspecionadas. Cancelar só abandona a
operação (cooperativo, também durante a espera de login); navegador e sessão ficam.
Timeout: abertura 20 s; mensagens indicam que a sessão foi preservada. Os limites de
nós/tempo deixaram de ser opções na tela (padrão 3000 nós, 5 s DOM, 15 s total).

**Abrir navegador dedicado** continua existindo e agora abre a disciplina autorizada
(e espera o login), sem ler conteúdo.

### Disciplinas autorizadas (preparação)

`campus_ai/authorized_courses.py` guarda `authorized_courses.json` em
`%LOCALAPPDATA%\CampusAI` (id numérico + nome, máx. 50; arquivo ausente ou corrompido
volta ao padrão de uma disciplina, nunca amplia a autorização; carregar não grava).
Nada na interface edita a lista nem varre várias disciplinas. "Analisar minha
faculdade" deverá chamar a mesma análise **sequencialmente**, com limites, e exige
nova autorização antes de existir.

### Arquivos

- Criados: `campus_ai/pilot_flow.py`, `campus_ai/authorized_courses.py`,
  `tests/test_pilot_flow.py`, `tests/test_pilot_flow_chromium.py`,
  `tests/test_authorized_courses.py`.
- Alterados: `campus_ai/pilot.py` (`identify`, `PilotLoginRequired`, identidade por
  id, `selection` no resultado), `pilot_ui.py` (reescrito), `browser_runtime.py`
  (`pilot_analyze`/`pilot_open` novos; `pilot_select` removido), `browser_worker.py`
  (sinal `progress`), `ui.py`, `tests/test_pilot.py`, `test_pilot_ui.py`,
  `test_pilot_title.py`, `test_browser_worker.py`, docs e skill.
- Backup anterior: `.tmp-campus-ai/simplify-before-20261105/` (14 arquivos).
  Reversão: encerrar o app, restaurar esses arquivos aos mesmos caminhos e remover
  os cinco criados acima.

### Testes

190 descobertos: **176 aprovados, 14 opt-in ignorados**. Com
`CAMPUS_AI_BROWSER_SMOKE=1` (Chromium headless local): **190 aprovados**.
`tests/test_pilot_flow_chromium.py` roda o fluxo real num Chromium temporário em que
`ead.aedb.br` é respondido localmente por `route.fulfill` (HTML fictício), com proxy
inexistente como barreira (uma requisição não interceptada falha ao conectar; verificado
com `example.com`). Cobre: abrir direto, login manual simulado, já autenticado,
cabeçalho não reconhecido com id correspondente, e que só a URL autorizada e a página
de login são requisitadas. O 302 do Moodle é modelado como redirecionamento por script
porque o Playwright não reintercepta um 302 respondido localmente.
Testes removidos por cobrirem ações eliminadas (`pilot_select`, abertura sem navegação,
exigência de uma só aba): substituídos pelos de `test_pilot_flow.py`.

### Executar no Windows

```powershell
Set-Location '<pasta-do-projeto>'
.\.venv\Scripts\python.exe -m campus_ai --pilot
```

Encerre antes qualquer instância antiga pela bandeja (ela roda o código anterior).
Na aba piloto: **Analisar disciplina**; entre manualmente se pedido.
Se falhar, informe apenas o texto de "Estado" (inclui diagnóstico só com contagens).

### Ainda sem validação real

Seletores/estrutura do tema AEDB; se o login da AEDB usa redirecionamento HTTP simples
ou provedor externo (SSO); se `body.course-7653`/`M.cfg` existem no tema; reutilização
da sessão persistente entre execuções; comportamento do Chromium visível em primeiro
plano; tempo de carregamento real frente aos 20 s/30 s.

## Correção do reconhecimento de título — 05/11/2026

Sintoma relatado na disciplina real (id 7653): "Título da disciplina não reconhecido",
"Seleção invalidada", "Leitura: falhou — Itens: 0". A página foi aberta pelo usuário;
o ambiente de desenvolvimento **não** acessou a AEDB nem viu o DOM real.

Causas reproduzidas com o `SNAPSHOT_JS` antigo no Chromium local (HTML fictício):

1. Título aceito somente do primeiro `<h1>` visível. Banner de tema personalizado
   (`h2`/`div` em área destacada) → título vazio.
2. A seleção percorria o documento inteiro desde `<html>` com o mesmo orçamento de
   3000 nós da leitura. Menus/gavetas/blocos antes do cabeçalho esgotavam o limite;
   `select()` ignorava `truncated` e relatava "título não reconhecido".
3. Texto visível dentro de `aria-hidden="true"` era descartado (cópia visual +
   cópia `sr-only` é comum em temas).
4. Logo do site em `<h1>` no navbar era aceito silenciosamente como disciplina.

Qual(is) dessas ocorre(m) na AEDB ainda não foi comprovado; as quatro foram tratadas.

Correção (`pilot.py`): o programa DOM fixo coleta até 40 candidatos limitados, fora de
navbar/gavetas/blocos/rodapé/menus, de fontes independentes: `h1` do cabeçalho
(`#page-header`, `.page-header-headings`...), áreas destacadas de curso
(`[class*=course-title]`, `[class*=course-banner] h2`...), trilha de navegação com link
para o **mesmo id**, outros `h1` e o título da aba (`Curso: … | Site`; ` - ` é
preservado). Python agrupa textos compatíveis (caixa, travessões, cópia duplicada,
nome curto contido no completo) e pontua por fonte. Grupos incompatíveis com apoio
semelhante → **ambíguo**: a interface pede escolha manual entre os títulos
encontrados, depois a confirmação normal. Sem candidatos, a identificação espera
700 ms e repete até 3 vezes na mesma aba (sem `goto`/`reload`), dentro do timeout total.

Validações adicionais: classe `course-<id>` do `body` e `M.cfg.courseId`, se
presentes, precisam coincidir com o id da URL (sinal auxiliar; ausência não bloqueia).
A URL não substitui a sessão: exige menu do usuário/logout, recusa `body.notloggedin`,
menu de visitante e formulário de senha visível. Falha mostra diagnóstico **só com
contagens** (h1 visíveis/total, área de curso, trilha, título da aba presente,
região principal, estado do documento) — informe esse texto para ajustar seletores.

Leitura: percorre apenas a região principal (`#region-main`, `[role=main]`...),
rejeitando subárvores de gavetas, índice do curso e blocos. Datas de atividade
aninhadas (Moodle 4.x), rótulos de prazo `Vencimento/Prazo/Data limite/Fecha/Encerra/Due`
(nunca `Aberto/Abre`), tipos em português (Tarefa, Arquivo, Questionário...),
atividades restritas sem link pelo nome visível, `.modtype_label` ignorado, texto
`accesshide/sr-only` removido dos itens. Seções recolhidas são contadas e tornam o
resultado **parcial** com instrução de expandir manualmente.

Testes: 145 descobertos; padrão **135 aprovados, 10 ignorados** (opt-in). Com
`CAMPUS_AI_BROWSER_SMOKE=1` neste Windows: **145 aprovados**, incluindo
`tests/test_pilot_dom_themes.py` (7 testes, Chromium headless, host `.invalid`
servido por `route.fulfill`, demais requisições abortadas, sem perfil persistente)
e o smoke antigo de downloads `deny`. Fixtures fictícias: `aedb_theme_course.html`,
`boost_course.html`, `ambiguous_course.html`, `empty_course.html`, `login_page.html`.
Fixtures **não provam** o DOM real da AEDB.

Backup anterior a esta correção: `.tmp-campus-ai/titlefix-before-20261105/`
(11 arquivos, estrutura preservada). Arquivos criados nesta correção, a remover numa
reversão: `tests/test_pilot_title.py`, `tests/test_pilot_dom_themes.py` e as cinco
fixtures acima.

### Próximos passos (não implementados)

1. Validação real assistida pelo usuário (abaixo). Ajustar seletores apenas a partir
   do diagnóstico estrutural, sem capturar HTML autenticado.
2. Depois de estável: comparar itens da disciplina piloto com o SQLite (IDs `cmid`),
   em memória primeiro; só então notificação Windows opt-in de novos itens/prazos.
3. Notas Obsidian por disciplina sob `Campus AI/` e resumos IA somente com
   consentimento explícito por envio; análise ao iniciar o Windows já é opt-in.

> As seções **abaixo desta linha** descrevem o piloto manual de 14/10/2026. Onde falam
> em abrir o navegador sem navegação, **Selecionar disciplina aberta**, **Ler títulos e
> prazos**, recusa de múltiplas abas ou confirmação por caixa de diálogo, o
> comportamento foi substituído pelas seções de 05/11/2026 acima.

## Estado da entrega

Implementado sem acesso à AEDB real. O usuário autorizou somente a leitura assistida
dos títulos e prazos visíveis de uma disciplina escolhida e confirmada no aplicativo.
Nenhuma leitura autenticada foi executada pelo ambiente de desenvolvimento.

O piloto é separado de **Iniciar análise** e de `engine.run_scan`. Não consulta o
painel de cursos, não escolhe a primeira disciplina, não segue links e não lê Gmail.
Os dados ficam apenas em memória na tabela piloto. Não chama History, ObsidianWriter
nem provedores IA. A inicialização normal do aplicativo ainda pode abrir seu banco
local existente para mostrar o histórico anterior; resultados piloto não entram nele.

## Executar no PowerShell normal

```powershell
Set-Location '<pasta-do-projeto>'
.\.venv\Scripts\python.exe -m campus_ai --pilot
```

Se o Campus AI já estiver rodando com esta versão, abra-o pela bandeja e escolha a
aba **Teste piloto — Uma disciplina**. Não inicie outro processo para disputar o
perfil. Uma instância antiga precisa ser encerrada voluntariamente para carregar o
código novo; isso fecha seu Chromium e pode exigir novo login manual. Não há troca
de código em um processo já aberto nem conexão a um navegador de outro processo.

1. Na aba piloto, use **Abrir navegador dedicado** se necessário. Uma sessão v2 já
   controlada pelo aplicativo é reutilizada. Não há navegação automática para `/my/`
   ou para a AEDB nesse comando; digite/navegue você mesmo no navegador.
2. Faça login manual se solicitado e abra a disciplina desejada. Mantenha somente
   essa aba no Chromium dedicado. O piloto recusa múltiplas abas, sem inspecionar
   seus títulos ou escolher uma delas por conta própria.
3. Clique em **Selecionar disciplina aberta**. O aplicativo valida exatamente
   `https://ead.aedb.br/ava/course/view.php?id=<número>`, verifica sinais de sessão,
   identifica o título visível e pede confirmação. Parâmetros privados não aparecem
   no endereço mostrado. Selecionar não extrai a lista de materiais.
4. Confira nome/endereço e confirme. Só então clique em **Ler títulos e prazos**.
5. Confira a tabela temporária: Disciplina, Tipo, Título, Prazo e Origem. Links limpos
   aparecem como dica na coluna Origem, sem ação de abrir. AEDB é indicada nas linhas
   somente após receber o resultado do leitor, sem misturar itens da demonstração.
6. Use **Cancelar leitura** para descartar o resultado corrente. O cancelamento é
   cooperativo: uma chamada CDP já iniciada pode terminar antes de ser descartada.
7. Trocar de aba após a operação limpa a seleção/tabela. A agenda permanece suspensa
   nesta execução, inclusive para eventos de timer já enfileirados. Reativá-la exige
   voltar às Configurações; não faça isso durante a validação piloto.

Se houver mudança de disciplina, sessão expirada, aba fechada, bloqueio institucional
ou falha de seleção, o aplicativo pede nova seleção/manual login conforme o caso.
Não tenta abrir páginas extras para compensar a falha. Não use **Iniciar análise**
na validação: o fluxo completo continua sendo uma funcionalidade separada, capaz de
consultar outras fontes e escrever notas.

## Escopo e limites

- Leitura de uma única página já aberta, vinculada à mesma aba e ao ID confirmado.
  Nenhuma paginação, clique, expansão de seção, submissão, conclusão ou download.
- Somente títulos de disciplina/seções/itens e prazos explicitamente rotulados
  (ex.: Vencimento, Prazo, Data de entrega, Due) são retornados. Não se usa a primeira
  data do item como prazo. Prazo ausente/ambíguo vira **Não informado**.
- Apenas DOM renderizado: elementos ocultos/recolhidos são omitidos. Elementos fora
  da região atualmente rolada, mas renderizados na página, podem ser lidos.
- Padrão UI: até 3000 nós examinados, 5 segundos para a avaliação DOM e 15 segundos
  totais por operação. Configurável na aba: 100–10000 nós, 0,5–15 segundos para DOM
  e 15–30 segundos totais. Contagem inclui nós de texto examinados; é conservadora.
- Não há navegação a receber timeout: o leitor não usa `goto`. O timeout da avaliação
  é enviado ao Chromium; há também limite de tempo dentro do programa e descarte
  após o orçamento total. Uma falha do transporte/driver que deixe a chamada CDP
  sem resposta pode atrasar cancelamento/retorno; não matamos o navegador à força.
- Estrutura desconhecida ou orçamento esgotado retorna **parcial**. **Completa**
  significa somente leitura da estrutura visível reconhecida, não cobertura de toda
  a disciplina, anexos ou estado acadêmico. Nunca se infere conclusão de atividade.
- Não há HTML integral, headers, cookies, valores de inputs ou texto de senha em
  logs. O script fixo retorna somente campos necessários e diagnósticos booleanos.
- A navegação manual e a atividade normal da página podem ser registradas pelo
  Moodle. Este fluxo não promete invisibilidade ao portal.
- O perfil, cookies e ACLs não são copiados, restaurados ou alterados manualmente.
  O Chromium continua responsável por sua própria sessão e armazenamento normal.

## Downloads

O contexto v2 já usa `accept_downloads=False`. O piloto exige adicionalmente que o
Chromium aceite `Browser.setDownloadBehavior` com `behavior: deny` antes da seleção.
Se essa configuração falhar, o piloto é recusado. Essa restrição permanece no contexto
dedicado até seu encerramento; não é alterada para permitir downloads ao sair da aba.
O piloto não dispara requests de arquivos nem clica em links de materiais.

Referências da implementação: [política de downloads CDP](https://chromedevtools.github.io/devtools-protocol/tot/Browser/#method-setDownloadBehavior)
e [avaliação DOM com timeout CDP](https://chromedevtools.github.io/devtools-protocol/tot/Runtime/#method-evaluate).

## Testes e limites da validação

112 testes descobertos: **109 aprovados, 3 ignorados**, saída zero.
Log local: `.tmp-campus-ai/pilot-tests.log`.

Os testes novos cobrem seleção/consentimento, URLs, origem, mudança de página,
disciplina vazia, prazos ausentes/presentes, estrutura desconhecida, expiração,
browser fechado, timeouts, cancelamento, bloqueio, política de downloads,
isolamento de Gmail/Obsidian/SQLite, sessão preservada e suspensão de agenda.
Os testes padrão usam projeções DOM simuladas e fixture HTML fictício. Não comprovam
os seletores ou a política de downloads no Chromium real.

Há um smoke test adicional opt-in que usa **about:blank**, HTML fictício, perfil
temporário e bloqueia requests de rede. Ele exercita o script DOM real, conteúdo
oculto, prazo e tentativa de baixar um blob fictício sob política deny. Nenhum
arquivo acadêmico é usado. Os outros dois smoke tests locais anteriores continuam
opt-in. Para executar somente o novo teste no Windows normal:

```powershell
$tempPath = Join-Path (Get-Location).Path '.tmp-campus-ai'
New-Item -ItemType Directory -Path $tempPath -Force | Out-Null
$env:TEMP = $tempPath; $env:TMP = $tempPath; $env:TMPDIR = $tempPath
$env:CAMPUS_AI_BROWSER_SMOKE = '1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_pilot_dom_smoke.py -v
Remove-Item Env:\CAMPUS_AI_BROWSER_SMOKE
```

O smoke test não foi executado no MXC. A validação real assistida continua pendente
da seleção e confirmação do usuário no aplicativo. Não envie credenciais, cookies,
HTML autenticado ou capturas integrais. Para reportar uma falha, basta o estado e o
diagnóstico genérico exibidos pelo piloto.

## Arquivos

Alterados: `campus_ai/ui.py`, `campus_ai/browser_runtime.py`,
`campus_ai/browser_worker.py`, `campus_ai/cli.py`, `README.md`, `AGENTS.md`,
`skills/campus-ai-academic-sync/SKILL.md`.

Criados: `campus_ai/pilot.py`, `campus_ai/pilot_ui.py`, `tests/test_pilot.py`,
`tests/test_pilot_ui.py`, `tests/test_pilot_dom_smoke.py`,
`tests/fixtures/pilot_course.html`, `PILOT_IMPLEMENTATION.md`.

Sem mudanças em `engine.py`, `moodle_browser.py`, `browser_profile.py`, esquema do
banco, instalação, inicialização automática ou credenciais. Nenhum commit/publicação.

## Reversão

Para apenas desativar o modo, saia da aba piloto. Nenhuma migração de dados precisa
ser desfeita. Não use Desconectar, não apague o perfil e não restaure cookies/ACLs.

Para reverter o código desta entrega, há cópias dos sete arquivos originais em
`.tmp-campus-ai/pilot-before-20261014/`, com a estrutura de diretórios preservada.
Esse backup contém somente código/documentação, não o perfil ou dados acadêmicos.
Primeiro encerre o aplicativo pela bandeja e preserve quaisquer edições feitas
depois desta entrega. Então restaure manualmente os sete arquivos dessa pasta para
os mesmos caminhos no projeto e remova somente os sete arquivos listados como
criados acima. Não remova diretórios inteiros. Rode a suíte novamente. A restauração
fecha a sessão do processo para carregar código antigo, podendo exigir novo login.

O backup está em pasta temporária ignorada pelo projeto; guarde uma cópia dele se
pretender limpar `.tmp-campus-ai` antes de decidir pela reversão.
