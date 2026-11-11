# Leitura das seções autorizadas da disciplina — Companion v0.5.3 (experimental)

**09/11/2026, v0.5.3 — nada é salvo antes do seu clique.** O botão agora tem duas fases:
1. **Ler.** Cada seção autorizada é lida em ordem, pelo mesmo fluxo de "Sincronizar disciplina" (inclusive o
   fechamento da janela "Preferência dos dados" pelo X). Nada é enviado ao aplicativo. As leituras ficam só na
   memória do popup, e fechar o popup ou cancelar descarta tudo.
2. **Salvar no Campus AI (um clique).** As seções lidas são salvas na ordem fixa, cada uma com a confirmação (ACK)
   do aplicativo. O botão fica desativado durante e depois do envio, então cliques repetidos não reenviam nada.
   O resultado mostra cada seção como **salva**, **falhou** (com o motivo) ou **nada a enviar** (módulos já
   salvos por outra seção). Se qualquer seção falhar, na leitura ou no salvamento, o resultado é **parcial**, nunca
   "tudo salvo".

Os itens 4 a 6 abaixo continuam valendo, mas agora acontecem **depois** do clique, na fase de salvamento.

**09/11/2026, v0.5.1 (correção do dono dos módulos):** na v0.5.0 um módulo era marcado como "já lido" por uma
seção antes de ela ser salva. Se esse salvamento falhasse, a seção seguinte deixava o módulo de fora, e ele
ficava sem gravação naquela sincronização. Agora o dono só é registrado depois do `saved: true` do aplicativo.
Uma seção recusada, sem confirmação ou com erro não reivindica nada. Detalhes no item 5.

Estado em 06/11/2026: implementado e testado só com páginas **fictícias**, em Node e em Chromium isolado. Na AEDB
real **nada mudou**: só **Atividades Avaliativas** está autorizada, e a sincronização v0.4.0 ("Sincronizar
disciplina") continua sendo o modo estável. Trilhas de Aprendizagem **não foi acessada**.

## Como funciona ("Sincronizar seções autorizadas (experimental)")

1. A aba precisa ser a página inicial da disciplina 7653.
2. `tiles_catalog.js` descreve os cartões: rótulo, `data-section`, `data-true-sectionid`, tipo de link, se é
   clicável, visível e abre na mesma aba. **Sem clique e sem conteúdo** de seção, atividade, participante ou nota.
3. `catalog.js` classifica cada cartão. A decisão mais restritiva vence:

   | Cartão | Tipo | Decisão |
   | --- | --- | --- |
   | Atividades Avaliativas | seção acadêmica | **lida** (autorizada) |
   | Trilhas de Aprendizagem | seção acadêmica | **não autorizada — não é aberta** |
   | Informações da Disciplina | informativo | não lida |
   | Feedback das Aulas, Fale com o Professor | comunicação/avaliação | **bloqueado, nunca aberto** |
   | link externo, rótulo perigoso, cartão duplicado, não clicável, oculto ou em nova aba | — | bloqueado |
   | rótulo desconhecido | — | não aberto |

4. Para cada seção a ler, em ordem fixa (Atividades Avaliativas e depois Trilhas), roda **o mesmo fluxo da
   v0.4.0**, sem mudança: verificar, um clique verificado se o painel estiver fechado, esperar estabilizar, ler,
   validar e salvar com ACK. Cada seção é **uma leitura separada** no SQLite, com o seu `section_uid`.
5. **Repetição entre seções:** se um módulo já foi **salvo** (com confirmação do aplicativo) por uma seção anterior
   desta sincronização, ele é omitido da seção seguinte, e a omissão fica registrada na cobertura daquela seção.
   O dono é a primeira seção da ordem fixa **cujo salvamento foi confirmado**. Se essa seção falhar (recusa, sem
   ACK, desconexão, erro), ela não reivindica nada, e a seção seguinte envia o módulo normalmente. Uma seção cujos
   módulos já foram todos salvos por outra não é enviada.
   No aplicativo, cada módulo é **uma única linha** (`uid`). Se ele passar de uma seção para outra numa
   sincronização posterior, a linha é atualizada e a mudança `secao` é registrada; não surge uma segunda linha e a
   seção antiga não o marca como ausente.
6. **Falha de uma seção:** ela não é gravada, e o que o Campus AI já tinha dela continua como estava. As outras
   seções seguem.
7. **Resumo da disciplina:** o popup mostra uma linha por seção, a cobertura agregada (sempre **parcial**:
   cartões não acadêmicos não são lidos, e prazos e entregas não aparecem) e as listas de não autorizadas,
   bloqueadas e não lidas.

No Campus AI Windows, com mais de uma seção gravada, o quadro Companion passa a dizer "N seções com leitura" e
mostra uma linha por seção (módulos, nº e horário da leitura, linha de base ou novidades). A tabela principal
indica "Disciplina › Seção" em cada módulo. Com uma seção só, o texto é idêntico ao de antes.

## Defesas contra ampliar o escopo sem querer

- **A autorização é uma constante única:** `AUTHORIZED_SECTIONS` em `companion/src/preview.js`, hoje
  `['atividades avaliativas']`. Um teste fixa esse valor, então mudar exige alterar também o teste, de forma
  consciente e revisável.
- O popup **não pode** passar outra lista: um teste estático proíbe `authorizedSections` no `popup.js`. Só os
  testes usam esse parâmetro, para a demonstração com duas seções fictícias.
- Defesa em profundidade: mesmo chamado diretamente com "Trilhas de Aprendizagem", o fluxo de seção recusa
  **antes de tocar na aba** se a seção não estiver autorizada.
- Continua existindo **um único `.click()`** na extensão, em `open_panel.js`, com as mesmas travas. O
  `tiles_catalog.js` só lê.

## Testes desta etapa (dados sintéticos)

- **Node:** `catalog.test.mjs` (classificação dos 5 cartões, ordem fixa, bloqueios, duplicados) e
  `course_sync.test.mjs` (só Atividades Avaliativas em produção; duas seções salvas separadamente; uma seção
  falhando; módulo repetido; recusas antes de qualquer clique; cancelar entre seções; não autorizada nunca aberta).
- **Chromium isolado** (`tests/test_companion_course_sync.py`): demonstração com duas seções fictícias
  (Atividades Avaliativas, 7 módulos; Trilhas, 2 módulos). Cenários:
  - produção (só uma seção);
  - as duas seções;
  - **Trilhas falhando**: Atividades Avaliativas é salva e Trilhas não;
  - módulo repetido;
  - **v0.5.1:** salvamento de Atividades Avaliativas recusado com um módulo repetido: Trilhas envia e salva o módulo;
  - link externo;
  - início fora da página inicial.
- **v0.5.1, dono dos módulos** (`course_sync.test.mjs`, "ownership 1–6", com um aplicativo falso que tem as
  garantias do host: uma linha por `uid`, leitura tudo-ou-nada):
  1. A salva e B repete o módulo: A continua dona, sem duplicar;
  2. A falha e B repete o módulo: B salva;
  3. A falha e ninguém mais tem o módulo: o que o aplicativo tinha é preservado;
  4. A falha e B salva; na sincronização seguinte A salva: uma linha, um dono;
  5. vários módulos repetidos: cada um enviado por uma única seção;
  6. falha recusada, lançada ou ambígua (`saved` diferente de `true`) não deixa dono órfão.

  No SQLite real (temporário), `test_companion_store.py` cobre a troca de seção do cenário 4.

  Em todos: nunca se clica nos cartões 1, 4 e 5, nunca em controles de conclusão, envio ou download, e nada
  navega.
- Os 20 cenários da v0.4.0 continuam passando, sem alteração.

## O que falta autorizar (ação sua)

Para ler **Trilhas de Aprendizagem** na AEDB real, é preciso uma autorização específica, como:

> Autorizo o Campus AI Companion a abrir, ler e salvar a seção **Trilhas de Aprendizagem** da Modelagem UML
> (curso 7653), lendo somente `data-cmid`, `data-modtype`, `data-title` e o endereço dos módulos, sem abrir
> materiais, atividades ou links.

Com ela, eu faria:
1. adicionar `'trilhas de aprendizagem'` a `AUTHORIZED_SECTIONS` e atualizar o teste que fixa esse valor;
2. rodar a suíte e gerar a extensão de integração numa pasta nova (sem substituir a que está carregada);
3. você carregaria a nova versão.

Nada no host, no registro ou no banco precisa mudar.

## Como validar Trilhas no Chrome real (depois da autorização)

1. **Estrutura primeiro, sem gravar:** abra o cartão Trilhas manualmente e use **Ler esta página**. Com
   Trilhas autorizada, o popup mostra os módulos, a classificação e eventuais problemas (tipos desconhecidos,
   itens ocultos). Se a marcação for diferente da prevista, o popup mostra o diagnóstico estrutural, sem
   conteúdo, e nada é salvo.
2. **Sincronização completa:** recarregue a página inicial com os painéis fechados e use **Sincronizar seções
   autorizadas**. Esperado:
   - os 5 cartões listados, com Feedback e Fale com o Professor bloqueados e Informações não lida;
   - Atividades Avaliativas salva (7 sem mudança);
   - Trilhas salva como **primeira leitura**, linha de base, sem gerar "novidades";
   - no Campus AI: "2 seções com leitura".
3. **Riscos a observar:**
   - o painel de Trilhas pode ter marcação diferente (subseções, tipos novos como `page`, `url`, `h5pactivity`);
   - trocar de painel pode exigir que o anterior feche;
   - o `click()` programático pode se comportar diferente naquele cartão.

   Qualquer desses casos termina em "o painel não apareceu", recusa ou diagnóstico, sem gravar nada.

## Instalação da v0.5.4

As pastas anteriores **não foram alteradas**: `dist\companion-sync-0.4.0` e `dist\companion-0.5.0` a
`dist\companion-0.5.3`. A v0.5.4 está em `<pasta-do-projeto>\dist\companion-0.5.4`, com o mesmo
ID (`oglmhecabakelhiaiandpdonpblldhnn`, aceito pelo host já registrado) e as mesmas permissões. Para usá-la:
1. em `chrome://extensions`, remova a versão carregada;
2. use **Carregar sem compactação** com a pasta acima;
3. confira a versão 0.5.4 e o mesmo ID.

**Na 0.5.4:** prazos e entregas são lidos na página de cada tarefa e questionário (ver
`docs/PRAZOS_E_ENTREGAS.md`).

O que muda:
- **Desde a 0.5.2:** "Sincronizar disciplina" fecha a janela "Preferência dos dados" pelo X e **não salva sozinho**:
  use **Salvar no Campus AI**. Ver `docs/SINCRONIZACAO_UM_CLIQUE.md`.
- **Na 0.5.3:** "Sincronizar seções autorizadas" também só lê; um clique em **Salvar no Campus AI** salva todas as
  seções lidas.

Nada no host, no registro ou no banco muda. Para voltar, remova a v0.5.2 e carregue uma das pastas anteriores.
