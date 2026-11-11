# Prazos e entregas das atividades — Companion v0.5.4

Estado em 09/11/2026: implementado e testado só com páginas **fictícias**, em Node e em Chromium isolado. A marcação
real das páginas de tarefa e questionário da AEDB **nunca foi observada**. As fixtures seguem o modelo padrão do
Moodle 4 e são uma hipótese. Só o teste no seu Chrome comprova o funcionamento real.

## O que acontece

As duas sincronizações ("Sincronizar disciplina" e "Sincronizar seções autorizadas") ganharam a etapa
**"Consultar prazos e entregas nas páginas das atividades"**, depois da leitura validada da seção:

1. Para cada **tarefa** (`assign`) e **questionário** (`quiz`) da seção lida, com no máximo 20 por seção, uma de cada
   vez e com 0,4 s de intervalo, `companion/src/details.js` faz **uma** requisição `GET` de mesma origem à página da
   atividade, `/ava/mod/<assign|quiz>/view.php?id=<cmid>`. É a mesma página que você abriria clicando nela.
2. A requisição sai da aba da disciplina que você abriu e reaproveita a sessão do Chrome. Nenhum cookie, token ou
   senha é lido. Redirecionamentos **não são seguidos**: um login ou outra página vira "a página redirecionou".
3. A resposta é analisada com `DOMParser`, que não executa scripts e não carrega nada. A página só é aceita se o
   `<body>` disser `course-7653`, `cmid-<cmid>` e `path-mod-<tipo>`.
4. **Lido:** a região de datas da atividade (rótulo + data visível) e, na tarefa, as **classes CSS** que o Moodle
   põe nas células de status (`submissionstatus*`, `submissiongraded`/`submissionnotgraded`), que não dependem do
   idioma. No questionário, lê-se a tabela de tentativas: estado de cada linha e presença do link de revisão.
5. **Nunca lido:** notas, comentários, feedback, arquivos, outros usuários e formulários. **Nunca feito:** clicar,
   enviar, iniciar ou finalizar tentativa, alterar qualquer coisa.
6. Nada é salvo nessa etapa. O resultado aparece no popup e só vai ao Campus AI quando você clica em **Salvar no
   Campus AI**, como na v0.5.3. A porta Native Messaging continua fechada até esse clique.

**Efeito no Moodle, igual a abrir à mão:** o Moodle registra que a página da atividade foi visualizada. Se o
professor configurou a conclusão "o aluno deve visualizar a atividade", ela passa a constar como visualizada,
exatamente como se você tivesse aberto a página. Envios, tentativas, notas e grupos não mudam.

Materiais (`resource_pdf`), escolha de grupo (`groupselect`) e outros tipos **não são consultados**. Escolha de
grupo nunca é tratada como tarefa pendente.

## Situação de cada atividade

| O que a página mostrou | Situação |
| --- | --- |
| Tarefa sem envio, rascunho ou reaberta, com prazo futuro ou sem prazo | **Pendente** |
| Tarefa sem envio, rascunho ou reaberta, com prazo vencido | **Atrasada** |
| Tarefa enviada e "não avaliada" | **Enviada — aguardando avaliação** |
| Tarefa enviada, avaliação não informada | **Enviada** |
| Tarefa avaliada | **Concluída** |
| Questionário com tentativa em andamento | **Tentativa em andamento — verificar** (atrasada se já fechou) |
| Questionário com tentativa finalizada | **Concluída** |
| Questionário sem tentativa | **Pendente** ou **Atrasada** (se já fechou) |
| Página não lida, falhou, não reconhecida ou estado ausente | **Não verificado** |

- **Prazo:** "sem prazo definido" só quando a região de datas foi reconhecida e não tem data de entrega (ou de
  fechamento, no questionário). Uma data que não pôde ser lida aparece como "não interpretado" com o texto visível.
  O que não foi verificado continua "não verificado", nunca zero e nunca "sem prazo".
- **Fuso:** as datas são as que o Moodle mostra, em America/Sao_Paulo (UTC-03:00; sem horário de verão desde
  2019). Uma data sem hora vale até 23:59.
- **Regra única:** `companion/src/deadlines.js` (popup) e `campus_ai/deadlines.py` (aplicativo) são conferidos pelos
  mesmos casos em `tests/fixtures/companion/situations.json`.

## No Campus AI Windows

- A tabela principal ganhou as colunas **Prazo**, **Tempo restante**, **Situação** e **Verificado em**, com as
  mais urgentes primeiro: atrasadas, pendentes pelo prazo mais próximo, tentativa em andamento, não verificadas,
  aguardando avaliação, enviadas, concluídas e materiais.
- Cores: **atrasada** em vermelho, **vence em até 72 h** em âmbar, **concluída/enviada** em verde. O texto também
  diz a situação; a cor nunca é a única pista.
- **"Pendências indicadas"** conta só pendentes e atrasadas comprovadas pela página numa verificação das últimas
  24 h. Uma verificação mais antiga aparece na tabela, com aviso, mas não entra na conta.
- Se uma consulta nova falhar, os valores da última verificação bem-sucedida são mantidos, e a dica da linha diz que
  a consulta mais recente falhou.

## Banco de dados (migração 2, incremental)

- `companion_details`: uma linha por módulo, atualizada no lugar e nunca duplicada. Guarda as datas (horário de
  parede + `timezone`), os estados, `verified_at`/`verified_run` (última leitura bem-sucedida) e `last_check_*`
  (última tentativa, mesmo falha).
- `companion_detail_history`: uma linha por observação **diferente** da anterior (histórico preservado, sem
  repetição).
- Nada existente é alterado ou removido. A migração roda na mesma transação de sempre, e o host faz um **backup
  verificado** do `live.db` em `%LOCALAPPDATA%\CampusAI-Companion\backup\` antes de migrar um banco existente. Sem
  backup, não há migração.
- **Quando acontece:** no primeiro "Salvar no Campus AI" depois desta atualização, porque o host registrado roda o
  código desta pasta. Os testes nunca migraram o banco real, que continua na versão 1.

## O que não é identificado

- Notas e comentários do professor (de propósito: não autorizados).
- Tarefas em grupo, extensões de prazo individuais e prazos de outras disciplinas ou seções (Trilhas continua não
  autorizada).
- Atividades de outros tipos (fórum, lição, H5P...). Ficam "não verificado" ou fora da contagem.
- Se o tema da AEDB mostrar datas ou status com outra marcação, a atividade fica "não verificado" e nada é inventado.

## Testes desta etapa (todos sintéticos)

- **Node:** casos compartilhados de situação; falha que nunca declara estado; estado do prazo; campo de entrega do
  contrato; etapa "detalhar" (só tarefas e questionários, em ordem, depois da leitura; falha parcial; parada em
  redirecionamento ou perda de acesso; cancelamento; desligada por padrão); modo por seções com módulo repetido.
- **Python:** contrato (aceita detalhes; snapshots antigos continuam válidos; rejeita estado declarado sem leitura,
  fuso errado e campos extras); migração v1→v2 com dados preservados e backup antes; sem backup, sem migração;
  histórico sem duplicação; falha que preserva o conhecido; reversão em erro; visão (ordem por urgência,
  pendências, desconhecido nunca vira zero, verificação antiga não conta, banco v1 continua legível).
- **Chromium (módulos reais):**
  - tarefa não enviada, enviada, rascunho, avaliada, aguardando avaliação, prazo futuro, expirado, sem prazo e
    prazo ilegível;
  - páginas: 404, de outra atividade, estrutura desconhecida, falha de rede, erro 500, redirecionamento para login
    (não seguido e interrompe as seguintes) e login devolvido na resposta;
  - questionário em andamento e finalizado;
  - só `GET` às atividades autorizadas; nenhum clique; nada privado (sesskey, comentário, nota) na saída; nada
    enviado antes do clique; o resultado passa pelo contrato, pelo banco temporário e pela visão.
