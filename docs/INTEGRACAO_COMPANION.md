# Integração Companion → Campus AI Windows (F4) — preparada, NÃO ativada

Estado em 05/11/2026: todo o caminho (extensão → Native Messaging → validação → SQLite → comparação →
resumo no aplicativo) está implementado e testado **só com dados fictícios**. Nenhum host foi registrado no
Windows (a chave HKCU não existe), nenhum instalador foi executado e a AEDB não foi acessada nesta fase.

## Arquitetura de comunicação

```
Popup (clique em "Ler esta página")           ── memória do popup apenas
   └─ clique em "Salvar no Campus AI"  (src/save.js — único arquivo com porta nativa)
        connectNative('br.campus_ai.companion')
        ── hello ─────────────▶  Chrome inicia o host como o USUÁRIO ATUAL:
        ◀──────── welcome(token)    %LOCALAPPDATA%\CampusAI-Companion\campus_ai_companion_host.cmd
        ── page_report(token, snapshot) ─▶  python -m campus_ai.companion_host
                                       1. origem = chrome-extension://oglmhecabakelhiaiandpdonpblldhnn/ (antes de tudo)
                                       2. quadro ≤ 512 KiB, JSON estrito, envelope exato, sem replay
                                       3. contrato campus-ai.academic/1 + origem "companion" + curso autorizado
                                       4. SnapshotStore.save → UMA transação SQLite (live.db, tabelas companion_*)
        ◀──────── ack(saved: true, result)  somente após o COMMIT
                  ou rejected(código)      falha registrada em companion_runs (só o código)
   popup: "Salvo no Campus AI (leitura nº N)…" apenas com ack saved:true deste request_id
```

| Requisito | Onde |
| --- | --- |
| Só a extensão autorizada conecta | `allowed_origins` no manifesto do host + `caller_origin` (falha fechado) |
| Contrato estrito | `contract.parse_snapshot` + regras do host (origem companion, curso autorizado, página reportável) |
| Limite de tamanho | 512 KiB de entrada (o corpo nem é lido acima disso), 16 KiB de saída |
| Repetidas / malformadas | `request_id` repetido, chave JSON duplicada, NaN, aninhamento, campos desconhecidos → `rejected` |
| Sem comandos | só `hello` e `page_report`; não existe mensagem que peça ação ao aplicativo |
| Sem rede externa | host só lê stdin e escreve stdout/SQLite; CSP do popup `connect-src 'none'` |
| Timeout / desconexão | popup: 15 s e `onDisconnect` (sem confirmação ⇒ nada é alegado); host: uma leitura por execução e encerramento forçado após 60 s |
| Usuário atual | HKCU, `%LOCALAPPDATA%`, sem administrador, processo do próprio usuário |
| Nada de conteúdo em logs | o host não imprime nada; falhas guardam só um código fixo |

## Persistência e comparação (`campus_ai/companion_store.py`)

- Mesmo arquivo `live.db` do `History`, tabelas `companion_runs`, `companion_items`, `companion_changes`,
  `companion_meta` (versão do esquema; migração em transação; nunca rebaixa um esquema mais novo).
- Por leitura: curso autorizado, exatamente uma seção, uids `moodle:course:<id>:module:<cmid>` da mesma
  disciplina e seção, títulos não vazios. Novos, alterados (título, tipo, grupo AV, seção), sem mudança,
  **ausentes nesta leitura** (marcados, nunca apagados nem chamados de removidos) e reaparecidos. Itens de
  outras seções não são tocados. Situação de entrega guardada como veio (`desconhecido`).
- Erro em qualquer passo ⇒ ROLLBACK de toda a leitura e `rejected`; o popup não diz "salvo".
- O aplicativo Windows mostra o resumo na aba **Companion (Chrome)**, lendo o banco em modo somente
  leitura (`mode=ro`), e informa se o host está registrado (consulta só leitura ao HKCU).

## Versões da extensão

| Pasta | Permissões | Uso |
| --- | --- | --- |
| `companion/` (v0.3.0) | `activeTab`, `scripting` | Pré-visualização validada. "Salvar" responde "integração local não disponível" |
| `dist/companion-integracao/` (gerada) | + `nativeMessaging` | Integração. Mesmo id. Gerar com `.\.venv\Scripts\python.exe -m campus_ai.companion_build` |

As duas têm o mesmo id: carregue só uma de cada vez.

## Procedimento de ativação (NÃO executar sem autorização explícita)

Auditoria de 05/11/2026: simulação executada, lançador testado pelo `cmd.exe` com pipes binários e banco
temporário, extensão de integração gerada em `dist\companion-integracao`. Comandos no PowerShell normal, na
pasta do projeto:

1. Simular (não altera nada) e conferir o manifesto e o lançador exibidos:
   `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\instalar_companion_host.ps1`
2. Encerrar o Campus AI pela bandeja (evita disputa pelo `live.db` durante o backup).
3. Com autorização: `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\instalar_companion_host.ps1 -Aplicar`
   Ordem: backup verificado do `live.db` em `%LOCALAPPDATA%\CampusAI-Companion\backup\live-<data>.db` (se
   falhar, para) → lançador `.cmd` + manifesto do host → **uma** chave
   `HKCU\Software\Google\Chrome\NativeMessagingHosts\br.campus_ai.companion`.
4. `chrome://extensions` → na extensão atual (pré-visualização) clicar **Remover** → **Carregar sem
   compactação** → `<pasta-do-projeto>\dist\companion-integracao`. O Chrome passa a
   pedir a permissão "Comunicar-se com aplicativos nativos cooperativos" (é o `nativeMessaging`). Mesmo id.
5. Na AEDB: abrir Atividades Avaliativas → **Ler esta página** → conferir os 7 módulos → **Salvar no
   Campus AI**. Esperado na primeira vez: "Salvo no Campus AI (leitura nº 1): 7 novo(s)…". Abrir o Campus AI
   e conferir a aba **Companion (Chrome)**. Uma segunda leitura deve dar "7 sem mudança".

## Reversão

1. `powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\remover_companion_host.ps1` (simulação) e
   depois com `-Aplicar`: remove só a chave HKCU do host e os dois arquivos; preserva `backup\`.
2. `chrome://extensions` → remover a de integração → carregar de novo `...\campus-ai-mvp\companion`.
3. Só se quiser apagar também as leituras salvas: encerrar o Campus AI e copiar o backup por cima do banco
   (`Copy-Item "$env:LOCALAPPDATA\CampusAI-Companion\backup\live-<data>.db" "$env:LOCALAPPDATA\CampusAI\live.db"`).
   Sem isso, as tabelas `companion_*` ficam no banco sem efeito sobre o resto do aplicativo.

A pasta do host fica **fora** de `%LOCALAPPDATA%\CampusAI` porque `preparar_perfil_moodle_windows.ps1`
aborta ao encontrar entradas desconhecidas ali.

## Limites

- Não foi testado com o Chrome real conversando com um host registrado (exige a etapa 3).
- Se o popup for fechado depois de o host gravar e antes do ack chegar, a leitura fica salva sem aviso no
  popup; o aplicativo mostra a leitura na aba Companion. O inverso (dizer "salvo" sem gravação) não ocorre.
- O lançador usa a `.venv` do projeto: mover a pasta do projeto exige reinstalar o host.
