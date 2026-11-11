# Campus AI 3.0 — arquitetura, auditoria e plano de migração

Data: 05/11/2026. Autor: Claude Code (Opus 5.5), a pedido do aluno. Nenhum acesso à AEDB real, Gmail,
conta Google ou perfil Chromium real foi feito nesta entrega. Nenhum commit (a pasta não é repositório Git).

**Legenda de estado:** ✅ implementado e testado localmente · 🧪 só fixtures/simulação · ⛔ bloqueado ·
📄 só documentado (não implementado).

---

## 1. Auditoria do projeto atual

### 1.1 Inventário de componentes

| Componente | Arquivos | Estado | Observação |
| --- | --- | --- | --- |
| Interface, bandeja, configurações | `ui.py` (912 linhas), `pilot_ui.py` | ✅ offscreen 🧪 | Nunca testada no Explorer/bandeja real |
| Instância única, início opt-in | `instance.py`, `startup.py`, `scripts/*inicio*.ps1` | ✅ | HKCU Run, não ativado na conta real |
| Dono único do Playwright | `browser_runtime.py`, `browser_worker.py` | ✅ com driver falso | Fundamento correto; manter |
| Piloto de uma disciplina | `pilot.py` (1145), `pilot_flow.py`, `pilot_nav.py` (607) | 🧪 | Segurança forte, mas seletores nunca vistos no DOM real; falhas relatadas pelo aluno |
| Leitor antigo por navegador | `moodle_browser.py` (`scan`) | 🧪 | **Duplica** o piloto com outro parser (HTMLParser em Python) |
| Moodle REST por token | `moodle.py` | 🧪 | Não se sabe se a AEDB emite token de web service para alunos |
| Gmail somente leitura | `gmail.py` | 🧪 | OAuth Desktop não aprovado/configurado na conta institucional |
| Orquestração | `engine.py` | ✅ | Regra de leitura parcial preserva notas; modelo de dados pobre |
| Histórico SQLite | `state.py` | ✅ | Só fingerprints + contagens; não guarda proveniência/cobertura |
| Obsidian | `obsidian.py` | ✅ | Idempotente com marcador de hash; recusa sobrescrever nota editada |
| Alertas | `notifications.py` | ✅ | Deduplicação atômica por chave |
| IA | `intelligence.py` | 📄 contrato | Consentimento por provedor + hash do conteúdo; sem adaptador |
| Segredos, perfil | `security.py`, `browser_profile.py`, `scripts/preparar_perfil_moodle_windows.ps1` | ✅ | ACL do perfil real não confirmada nesta entrega |
| Lista autorizada | `authorized_courses.py` | ✅ | Só Modelagem UML (7653); laço multi-disciplina proibido |

Linha de base de testes antes desta entrega: 300 (255 aprovados, 45 opt-in ignorados).

### 1.2 Duplicações

1. **Dois leitores de Moodle por navegador:** `moodle_browser.MoodleBrowserClient.scan` (HTML via
   `page.content()` + `HTMLParser`) e o piloto (`pilot.SNAPSHOT_JS`/`EXPAND_JS`/`NAV_JS`). Usam heurísticas
   diferentes para tipo, prazo e status. `engine.run_scan` ainda chama o antigo com `max_courses=1`.
2. **Validação de URL AEDB em seis lugares:** `pilot.course_url`, `pilot.reference_url`,
   `pilot_nav.classify_destination`, `pilot_flow._same_course/_is_aedb`, `moodle_browser._url` e agora
   `companion_protocol.classify_page`/`contract._url`. Candidato a um único módulo `aedb_urls.py`.
3. **Listas de tipos de módulo** em `pilot.py`, `moodle_browser.py`, `moodle.py` e `contract.py`
   (a de `contract.py` é vigiada por teste contra a do piloto).
4. **Três modelos de dados:** `PilotRow`/`Coverage`, `AcademicItem` e o novo contrato. A ponte
   `contract.from_pilot_result` / `contract.to_academic_items` permite migrar sem big bang.

### 1.3 Riscos

| Risco | Impacto | Mitigação proposta |
| --- | --- | --- |
| Seletores do piloto nunca validados no DOM real da AEDB (tema de cartões personalizado) | Leituras vazias/parciais recorrentes | POC de descoberta (§3) → fixtures estruturais fiéis → ajustar extrator |
| `AcademicItem.status` mistura "publicada" com "pendente"; `local_answer` lista toda atividade não `submitted` | Aluno pode achar que tudo está pendente ou que nada está | Contrato separa `submission` (dito pela fonte) de `pending_state` (derivado, exige confirmação recente) |
| Nenhuma marca de tempo/proveniência por registro | Dado velho aparece como atual; fonte com erro parece "sem pendências" | `provenance.observed_at`, `effective_verification` → `desatualizado`, `source_proves_absence` |
| `moodle_browser.scan` infere `pending` de texto livre ("pendente") | Falso positivo/negativo | Retirar após o novo extrator; só aceitar estado explícito |
| Claude in Chrome atua no Chrome principal do aluno, com todas as sessões | Escopo amplo e envio de conteúdo à Anthropic | Permissão de site somente `ead.aedb.br`, consentimento explícito por conteúdo, sondagem estrutural primeiro (§3) |
| Registro do host Native Messaging escreve em HKCU | Configuração persistente | Só com autorização; manifest com `allowed_origins` exato; host falha fechado |
| Conteúdo de páginas/e-mails pode conter instruções (prompt injection) | IA ou agente executa ação indevida | Dados são dados: protocolo sem comandos, IA só com fontes citadas e sem ferramentas de ação |
| `pilot.py` com 1145 linhas e JS embutido | Manutenção difícil | Extrair programas JS para arquivos e reutilizar no Companion depois da POC |

### 1.4 Código descartável (não removido nesta entrega)

- `moodle_browser.scan`/`_read_course`/`Document` e o caminho `engine.run_scan → scan(max_courses=1)`:
  substituídos pelo piloto e, depois, pelo Companion. Manter `connect`/`check_session` enquanto o
  Playwright for usado. Remover só depois da coleta 3.0 validada.
- `campus_ai_local.egg-info/` e `.impeccable/`: artefatos gerados, fora do produto.

### 1.5 Funcionalidades ainda não validadas (dependem de acesso real)

DOM real da AEDB (cartões, AV1/AV2, prazos), sessão Playwright real, token Moodle REST, exportação iCal,
OAuth Gmail institucional, bandeja/notificações/início no Windows real, Claude in Chrome nesta conta,
extensão Companion carregada no Chrome, host Native Messaging registrado.

---

## 2. Claude Code + Claude in Chrome — viabilidade

Verificado nesta sessão (05/11/2026):

- Claude Code **2.1.318** instalado; o servidor MCP `claude-in-chrome` está configurado na sessão (as
  ferramentas `mcp__claude-in-chrome__*` estão disponíveis).
- Google Chrome **156.0.8078.80** instalado.
- `list_connected_browsers` retornou **lista vazia**: nenhuma instância da extensão Claude in Chrome
  está conectada a esta conta agora. ⛔ **Nenhuma leitura real foi feita**, e nenhuma permissão de site
  foi solicitada ou alterada. Não foram chamadas ferramentas que listam abas (evita expor títulos de
  abas abertas sem necessidade).

Para destravar (ação do aluno): instalar/abrir a extensão Claude in Chrome no Chrome, entrar com a mesma
conta do Claude, conectar (`/chrome` no Claude Code) e, nas configurações de sites da extensão, permitir
**somente** `ead.aedb.br`. Depois, enviar a autorização do roteiro em
[`docs/POC_CLAUDE_CHROME.md`](docs/POC_CLAUDE_CHROME.md).

**Decisão de arquitetura:** Claude in Chrome é **ferramenta de descoberta e desenvolvimento**, não
coletor de produção. Motivos: cada leitura envia conteúdo autenticado a um provedor externo (exige
consentimento por conteúdo), o resultado não é determinístico, depende do Chrome principal com todas as
sessões do aluno e tem custo por uso. Ele serve para descobrir a estrutura real (cartões, rotas,
marcação de AV1/AV2 e prazos) e produzir fixtures e padrões; a coleta repetitiva fica com código
determinístico (Companion ou piloto Playwright).

---

## 3. Arquitetura proposta

```
             ┌───────────── descoberta (dev, sob consentimento) ─────────────┐
             │ Claude in Chrome + docs/poc/structure_probe.js → padrões,     │
             │ fixtures estruturais, regras de rota. Nunca em produção.      │
             └───────────────────────────────────────────────────────────────┘
  FONTES (adaptadores determinísticos)                NÚCLEO (Python local)              SAÍDAS
  ┌──────────────────────────────┐   Snapshot   ┌─────────────────────────────┐   ┌────────────────┐
  │ Companion MV3 (Chrome do     │──Native────▶ │ companion_protocol (valida  │   │ Jarvis: painel,│
  │ aluno, clique do aluno)      │  Messaging   │ origem, sessão, tamanho)    │   │ alertas, status│
  ├──────────────────────────────┤              │            │                │   ├────────────────┤
  │ Piloto Playwright (perfil    │─from_pilot──▶│ contract.parse_snapshot     │──▶│ Obsidian:      │
  │ dedicado, 1 disciplina)      │   _result    │ (campus-ai.academic/1)      │   │ fonte | IA |   │
  ├──────────────────────────────┤              │            │                │   │ decisões       │
  │ iCal Moodle (URL = segredo)  │──📄────────▶ │ Store v2 SQLite (uid,       │   ├────────────────┤
  │ Moodle REST (se houver token)│──🧪────────▶ │ verificação, observed_at,   │──▶│ IA (local ou   │
  │ Gmail readonly (comunicados) │──🧪────────▶ │ cobertura por fonte) 📄     │   │ autorizada) 📄 │
  └──────────────────────────────┘              │ semântica: pending_state,   │   └────────────────┘
                                                │ desatualizado, ausência     │
                                                └─────────────────────────────┘
```

### 3.1 Contrato único de dados — `campus_ai/contract.py` ✅

Esquema `campus-ai.academic/1`. Entidades: `Course`, `Section`, `Material`, `Activity` (com `Deadline`
e `submission`), `CalendarEvent`, `Announcement`, `SourceStatus` (última tentativa/sucesso por fonte),
`CoverageInfo`, `Snapshot`. Cada registro carrega `provenance` (fonte, método, `observed_at` com fuso,
padrão de rota sem valores), `verification` e `confidence`.

- **Dois eixos separados.** `verification` por registro: `confirmado`, `parcial`, `nao_verificado`,
  `desatualizado`, `erro_integracao`. `coverage` por snapshot: `completa`, `parcial`, `nao_validada`,
  `falhou`. Zero itens nunca é `completa` (rejeitado pelo validador).
- **Publicada ≠ pendente.** `submission` vem da fonte (`desconhecido` por padrão; `nao_enviado`,
  `enviado`, `avaliado` só se a fonte disser). `pending_state()` só devolve `pendente` com
  `nao_enviado` + `confirmado` + observação recente; caso contrário `desconhecido`.
- **Fonte indisponível ≠ ausência.** `source_proves_absence()` só é verdadeiro com fonte `confirmado`
  e cobertura `completa`.
- **Desatualizado.** `effective_verification()` rebaixa para `desatualizado` após `DEFAULT_MAX_AGE`
  (24 h, ajustável).
- **Identificadores estáveis.** Os mesmos dos conectores atuais (`moodle:course:<id>:module:<cmid>`),
  para não quebrar deduplicação SQLite nem nomes de notas. Sem cmid, `...:item:<hash>` com confiança
  `baixa`. Seções: `...:section:s-<hash do nome>`.
- **Validação estrita** (o contrato também recebe dados da extensão): campos desconhecidos, valores fora
  do vocabulário, URLs fora de `https://ead.aedb.br/ava/` ou com parâmetros além de `id`/`section`
  (bloqueia `sesskey`, `authtoken`), caracteres de controle, referências pendentes e limites de tamanho
  são rejeitados. Mensagens de erro nunca repetem valores.
- **Prazos.** `deadline_from_text()` converte o texto visível pt-BR do Moodle; nunca inventa data:
  o que não for interpretado fica em `raw` com `at` vazio. Sem fuso explícito, `timezone_explicit=false`.
- **Ponte.** `from_pilot_result()` converte o resultado atual do piloto; `to_academic_items()` alimenta
  o motor/Obsidian atuais só com campos estáveis em `meta` (senão cada leitura mudaria o fingerprint e
  realertaria "alterada").

### 3.2 Campus AI Companion (extensão MV3) — `companion/` 🧪 rascunho

Implementado como rascunho testável, **não carregado no Chrome**:

- `manifest.json`: única permissão `nativeMessaging`; **nenhuma** `host_permissions`; content script só
  em `https://ead.aedb.br/ava/course/view.php*`, sem `all_frames`, mundo isolado;
  `externally_connectable: {ids: []}` (nenhuma página ou outra extensão conversa com ela); CSP
  `script-src 'self'; object-src 'none'`; sem recursos acessíveis pela web; sem `update_url`.
- Coleta só por **clique do aluno** no botão da extensão (`chrome.action.onClicked`). O content script
  responde a um único pedido `collect`; a extração está **ausente de propósito** até a POC definir os
  seletores reais (o botão mostra "POC" e nada é enviado).
- `classify.js` (classificação de páginas) e `protocol.js` (mensagens) têm espelho Python e um
  fixture compartilhado (`tests/fixtures/companion/page_cases.json`), testado nas duas linguagens.
- Testes estáticos proíbem no código da extensão: `eval`, `new Function`, `innerHTML`, `fetch`, XHR,
  WebSocket, cookies, `chrome.storage`, `chrome.scripting`, consulta/criação de abas, `.click()`,
  `.submit()`, URLs externas.

### 3.3 Native Messaging — `campus_ai/companion_protocol.py` ✅ (host não registrado)

- Quadro: 4 bytes little-endian + JSON UTF-8. Entrada limitada a **512 KiB** (o Chrome aceitaria
  64 MiB); corpo acima do limite nem é lido e o host encerra. Saída limitada a 16 KiB (limite do Chrome
  é 1 MB).
- **Origem:** o Chrome passa `chrome-extension://<id>/` como primeiro argumento; o host confere contra
  uma lista configurada e **falha fechado** enquanto a lista estiver vazia. O manifest do host terá
  `allowed_origins` com o mesmo id.
- **Canal:** `hello` → `welcome` com token aleatório de sessão; `page_report` exige o token
  (comparação em tempo constante); `request_id` repetido é rejeitado (anti-replay).
- **Esquema:** envelope com campos exatos; tipos permitidos apenas `hello` e `page_report`; JSON com
  chave duplicada, `NaN`, aninhamento > 12 ou não-objeto é rejeitado; snapshot validado pelo contrato,
  atribuído a `companion` e restrito às disciplinas autorizadas; página reportável só `curso_inicio` /
  `curso_secao`.
- **Respostas** trazem só código e contagens; nunca ecoam conteúdo. Após 5 rejeições o host encerra.
- **Não há mensagem que peça ação** (abrir, baixar, gravar, enviar, executar).

Pendências 📄: (1) entrada `python -m campus_ai.companion_host` + `.bat`/`.exe`; (2) manifest do host em
`%LOCALAPPDATA%\CampusAI\companion\br.campus_ai.companion.json`; (3) chave
`HKCU\Software\Google\Chrome\NativeMessagingHosts\br.campus_ai.companion` — **exige autorização**;
(4) id estável da extensão (campo `key` no manifest ao carregar sem empacotar); (5) entrega ao app em
execução: o host é um processo separado lançado pelo Chrome. Proposta: caixa de entrada
`%LOCALAPPDATA%\CampusAI\inbox\` com gravação atômica e ACL restrita, revalidada pela GUI ao importar
(mais simples e auditável que um named pipe).

### 3.4 Calendário (iCal) 📄

Moodle padrão oferece *Calendário → Exportar calendário*, que gera
`/calendar/export_execute.php?userid=…&authtoken=…`. Quem possui a URL lê o calendário: **é credencial**.
Plano: (a) a POC só verifica, sem clicar em "Obter URL", se a página de exportação existe na AEDB;
(b) o aluno gera a URL manualmente e cola em Configurações; ela vai para o `keyring`, nunca para
`config.json`, log, nota ou contrato (o validador de URL do contrato já rejeita `authtoken`);
(c) importador com host exato, HTTPS, tamanho máximo, parser tolerante a `VEVENT` e deduplicação por
`UID` (`ical:event:<hash>`) e por `activity_uid` quando o evento aponta para um módulo; (d) eventos iCal
corroboram prazos, mas não provam entrega.

### 3.5 Gmail 📄

Manter `gmail.py` (`gmail.readonly`, escopo restrito pelo Google; `gmail.metadata` não permite busca
por `q`). Contas Workspace institucionais podem bloquear apps OAuth externos: confirmar com a AEDB.
Gmail produz apenas `Announcement` (`channel=gmail`) e **nunca** cria ou fecha atividade. Nenhuma
leitura/envio real sem consentimento específico.

### 3.6 Obsidian 📄

Preservar o escritor atual (marcador de hash, recusa em sobrescrever nota editada). Evolução:
nota por registro com região **Dados da fonte** (regenerável); arquivo separado `… (IA).md` com
provedor, data e fontes citadas; arquivo **Minhas decisões** nunca tocado; `Histórico.md` por disciplina
gerado a partir das diferenças entre snapshots; painel com estado de cobertura e "desatualizado".

### 3.7 IA acadêmica 📄

`intelligence.StudyProvider` + `Consent` (provedor + hash do conteúdo) já existem. Adaptadores:
primeiro local (Ollama), depois externos só com consentimento por conteúdo. Respostas citam `uid` dos
registros usados e assinalam incerteza. Coleta, prazos e deduplicação continuam determinísticos.
A IA não recebe ferramentas de ação e nunca envia trabalhos.

### 3.8 Jarvis 📄

Centro de controle alimentado por `SourceStatus` (última tentativa/sucesso por fonte), prazos via
`pending_state`, alertas já deduplicados, tabela de histórico de erros, modo offline mostrando o último
snapshot como `desatualizado`, e recuperação: snapshot só substitui o anterior se validar.

---

## 4. Plano de migração incremental

| Fase | Entrega | Depende de |
| --- | --- | --- |
| **F0 (esta)** | Auditoria; contrato v1 + ponte; protocolo Native Messaging; rascunho MV3; sonda da POC; roteiro; skill de descoberta | — |
| **F1** | POC Claude in Chrome em Modelagem UML (7653): relatório estrutural + resultado comparado com o navegador | Extensão conectada + autorização de conteúdo |
| **F2** | Fixtures estruturais fiéis (texto sintético); extrator determinístico; escolher Companion **ou** piloto pela evidência; coleta local completa da 7653 | F1. **Parcial (05/11/2026):** adaptador `format-tiles` + fixtures feitos, sem validação real; prazos e página inicial pendentes |
| **F3** | Store v2 SQLite (registros do contrato + `source_runs`); `engine` consome snapshots; GUI mostra verificação/cobertura | F2 |
| **F4** | Host Native Messaging registrado + caixa de entrada (se Companion vencer) | Autorização HKCU |
| **F5** | iCal (se existir) e Gmail como fontes do contrato | Autorizações próprias |
| **F6** | Obsidian v2 (fonte/IA/decisões, histórico) | F3 |
| **F7** | IA local, depois externa autorizada; Jarvis centro de controle | F3 |
| **F8** | Retirar `moodle_browser.scan` e unificar validação de URL | F2 validada |

Critério de saída de cada fase: suíte verde, nenhuma regressão de segurança dos testes existentes, e
afirmação explícita do que foi validado com dado real.

---

## 5. Dependências, riscos e próximos passos

- **Aluno:** conectar Claude in Chrome (permissão só para `ead.aedb.br`) e enviar a autorização do
  roteiro; confirmar política da AEDB sobre automação/extensões; decidir se aceita o registro HKCU do
  host quando chegar a F4.
- **Técnico:** Node.js 24 (já instalado) para testes JS; nada novo instalado.
- **Riscos abertos:** o tema da AEDB pode carregar AV1/AV2 por JavaScript ou em outra página; o cartão
  pode abrir um módulo `page`/`book` (hoje "não suportado"); a AEDB pode desativar exportação iCal; o
  OAuth institucional pode ser bloqueado.

## 6. O que foi entregue nesta execução

| Arquivo | Tipo |
| --- | --- |
| `ARCHITECTURE_3.md` | este documento |
| `campus_ai/contract.py`, `tests/test_contract.py`, `tests/fixtures/contract/snapshot_ficticio.json` | contrato v1 ✅ |
| `campus_ai/companion_protocol.py`, `tests/test_companion_protocol.py` | host Native Messaging ✅ (não registrado) |
| `companion/` (`manifest.json`, `src/*.js`, `test/*.mjs`, `package.json`), `tests/test_companion_extension.py`, `tests/fixtures/companion/page_cases.json` | rascunho MV3 🧪 |
| `docs/POC_CLAUDE_CHROME.md`, `docs/poc/structure_probe.js`, `tests/test_poc_probe.py` | preparação da POC |
| `skills/campus-ai-browser-discovery/SKILL.md` | skill local |
| `AGENTS.md`, `README.md`, `skills/campus-ai-academic-sync/SKILL.md` | atualizações curtas |

Nenhum arquivo de código existente foi alterado. Backup dos documentos editados:
`.tmp-campus-ai/arch3-before-20261105/`.

## 7. Segunda entrega (F1 + início da F2) — 05/11/2026

**Observado na AEDB real** (Claude in Chrome, somente leitura; detalhes em
`docs/poc/RESULTADO_ESTRUTURAL_7653.md`): disciplina em `format-tiles`; cartão = `a.tile-link` →
`/ava/course/section.php?id=<id da seção>`; AV1/AV2 são atividades nomeadas, não seções; 7 itens com
`data-cmid`/`data-modtype`/`data-title`; subtipo `resource_pdf`; nenhuma data na página.

**Implementado (só com fixtures sintéticas):**

| Peça | Arquivo | Papel |
| --- | --- | --- |
| Leitura do DOM | `companion/src/dom_tiles.js` | Projeção mínima: classes do `body`, `?id`, título da aba e, por `li.activity`, `data-modtype`/`data-cmid`/`data-title` + endereços de módulo. Rótulos: só a posição |
| Adaptador | `companion/src/tiles_adapter.js` | Função pura: projeção → `Snapshot` `campus-ai.academic/1`; recusa sem identidade/formato/id de seção; cobertura sempre `parcial` (ou `nao_validada` com zero itens) |
| Protocolo | `curso_bloco` em `companion_protocol.py`/`protocol.js`/`classify.js` | Página de seção do Tiles; a identidade da disciplina vem do `body.course-<id>`, não da URL |
| Contrato | `contract.py` | Tipos `attendance`/`groupselect`/`msteams`; campos opcionais `assessment` e `assessment_basis` (aditivos: snapshots antigos continuam válidos) |
| Ponte | `contract.to_academic_items` | Só `assign`/`quiz` viram "atividade"; escolha de grupo, presença etc. não aparecem como pendências |

**Decisões:** (1) um adaptador único em JS, validado em Python pelo contrato (sem lógica duplicada);
(2) grupos AV vêm do título (`titulo`) ou, se o bloco entre rótulos tiver exatamente uma marca AV, da
posição (`posicao`, confiança `media`); (3) nenhum campo derivado entra no `meta` do `AcademicItem`, para
o fingerprint não oscilar; (4) a página inicial do curso continua "pendente" (o índice lateral dá o
inventário, mas sua marcação ainda não foi validada o bastante).

**Limites honestos:** a coleta exige que o aluno abra a página da seção e clique no botão (a extensão não
tem permissão de abas para navegar sozinha — de propósito); não há prazos nem estado de entrega; o host
Native Messaging **não está registrado**; compatibilidade com o DOM real é presumida a partir de uma
leitura estrutural e uma leitura de atributos.

**Atualização (mesmo dia) — pré-visualização local, v0.1.0.** A extensão passou a ser um popup:
`activeTab` + `scripting`, sem content script, background, `host_permissions` nem `nativeMessaging`; o
Native Messaging (`protocol.js`, `background.js`) foi isolado em `companion/native/`, fora do manifesto, para
a F4. Nada é salvo ou enviado (CSP `connect-src 'none'`, sem `storage`). `src/preview.js` confirma
endereço → disciplina → Tiles → seção **antes** de ler qualquer item. Ver `companion/README.md`.
