# Sincronizar disciplina (um clique) — Companion v0.4.0, atualizado na v0.5.2

## v0.5.2 (09/11/2026): janela "Preferência dos dados" e salvamento pelo botão

Na AEDB real, você observou que a janela **"Preferência dos dados"** (X, "Cancelar", "Sim") bloqueava a leitura, e
autorizou o Companion a fechá-la sozinho, **só pelo X**. Hoje o fluxo é:

| # | Etapa | O que muda |
| --- | --- | --- |
| 1 | Verificar | Igual. Se a janela já estiver aberta, a verificação reconhece isso e segue para a etapa 3. |
| 2 | Abrir | Igual: **no máximo um** clique no cartão por sincronização, e nunca de novo depois de fechar a janela. |
| 3 | Fechar (novo) | Só se a janela aparecer, antes ou depois do clique no cartão. Ela precisa ser o **único** diálogo visível e ser reconhecida pelo título, pelo X no cabeçalho e pelos dois botões "Sim"/"Cancelar", sem links nem campos. Então o Companion clica **no X** e espera a janela sumir. "Sim" e "Cancelar" nunca são acionados. No máximo 2 fechamentos; se ela voltar uma terceira vez, a sincronização para. |
| 4 | Aguardar | Igual. Depois de fechar a janela, a seção é **revalidada**. Se ela não estiver visível, para com "a seção não ficou disponível", sem clicar no cartão de novo. |
| 5 | Ler | Igual. |
| 6 | Salvar | **Não é mais automático.** O resultado aparece e o salvamento acontece quando você clica em **Salvar no Campus AI**. |

Qualquer diálogo **desconhecido** (outro título, botão a mais, X fora do cabeçalho, link ou campo, ou dois diálogos
ao mesmo tempo) continua aberto e bloqueia a leitura. O diagnóstico mostra separadamente:
- se a seção está visível;
- os diálogos abertos;
- a janela "Preferência dos dados" identificada;
- os diálogos desconhecidos;
- os diálogos ocultos, que não bloqueiam.

**Limite honesto:** a marcação real dessa janela não foi observada. O reconhecimento segue o modal padrão do Moodle.
Se a janela real for diferente, o Companion **não a fecha**, mostra "diálogos desconhecidos: 1" no diagnóstico e não
lê nada. Nesse caso, o diagnóstico estrutural (sem texto) é o que permite ajustar o reconhecimento.

Estado em 06/11/2026: implementado e testado em Chromium isolado com páginas **fictícias**. **Não validado na
AEDB real**: o teste assistido (abaixo) é seu. Nenhum acesso à AEDB foi feito durante o desenvolvimento.

## O que acontece ao clicar em "Sincronizar disciplina"

| # | Etapa | O que é feito | Reaproveita |
| --- | --- | --- | --- |
| 1 | Verificar | Endereço `ead.aedb.br` (HTTPS), curso 7653 (URL **e** `body.course-7653`), formato Tiles, vínculo cartão↔seção | `runPreview` (validado na AEDB real) |
| 2 | Abrir | **Um** `click()` no link do cartão "Atividades Avaliativas", só se o painel estiver fechado | `open_panel.js` (novo) |
| 3 | Aguardar | Sonda só de identidade a cada 300 ms até o painel estar visível e com a mesma quantidade de itens por 900 ms (máx. 12 s) | `dom_tiles.js` (inalterado) |
| 4 | Ler | A mesma leitura do modo manual: identidade → itens → identidade de novo | `runPreview` |
| 5 | Salvar | Envio ao host; "salvo" só com o ACK do aplicativo (gravação já confirmada por COMMIT) | `saveSnapshot` |

Se o painel já estiver aberto, ou se a página for a própria seção (`section.php`), a etapa 2 e 3 são puladas e
**nenhum clique** é feito.

## Por que clicar e não navegar para a seção

O `activeTab` vale **até a página mudar**. O clique no cartão faz o plugin Tiles mostrar a seção no mesmo
documento (foi o que você observou: o endereço continua `course/view.php?id=7653`), então o acesso continua.
Navegar para `section.php` trocaria o documento e a extensão perderia o acesso no meio do fluxo.

## O único clique: todas as travas (`companion/src/open_panel.js`)

Verificadas na mesma chamada, imediatamente antes do clique; se qualquer uma falhar, **nada é clicado**:

- página `/ava/course/view.php`, `body.course-7653` e `format-tiles`; nenhum diálogo visível;
- **exatamente um** cartão corresponde a "Atividades Avaliativas", com **um** `a.tile-link`;
- nenhuma palavra perigosa no rótulo (`feedback`, `fale com`, `enviar`, `finalizar`, `concluir`, `responder`,
  `excluir`, `editar`, `baixar`, `download`, `submeter`, `marcar como`, `tentativa` — a mesma lista do piloto);
- vínculo por atributos: `data-section`, `data-true-sectionid` e o endereço do link (`https`, `ead.aedb.br`,
  `/ava/course/section.php`, único parâmetro `id` igual a `data-true-sectionid`). O endereço só é **comparado**;
- link na mesma aba, sem `download`, fora de formulário e de diálogo; cartão com a classe `tile-clickable` e visível.

Um teste estático garante que existe **um único** `.click()` em toda a extensão, em `open_panel.js`, depois de
todas essas travas e sem nada executado depois dele.

## O que NÃO é feito

Seguir links de tarefas ou arquivos; acionar conclusão, envio ou avaliação; baixar; abrir outras disciplinas ou
seções; rodar em segundo plano (a sincronização vive e morre com o popup); enviar a serviços externos; pedir
permissões novas. O coletor `dom_tiles.js`, o `preview.js` e o banco **não foram alterados**.

## Falhas e o que o popup diz (nunca "salvo" antes do ACK)

| Situação | Resultado |
| --- | --- |
| Página errada, outra disciplina, sem Tiles, login, outro domínio | Recusa na etapa 1, nada clicado |
| Cartão duplicado, desvinculado, perigoso, oculto, não clicável, nova aba | Recusa na etapa 2, nada clicado |
| Diálogo aberto / dois painéis / painel sem vínculo | Bloqueia, nada lido |
| Cartão clicado e o painel não aparece ou não estabiliza em 12 s | "O painel não apareceu…", nada lido; **não clica de novo** |
| O clique navegou e o `activeTab` acabou | "A página mudou… a extensão perdeu o acesso"; use o modo manual |
| Sessão expirou no meio | "Entre manualmente e tente de novo", nada salvo |
| Painel mudou entre a espera e a leitura | "A página ou o painel mudou", nada exibido |
| Host ausente / sem resposta / desconectado / sem ACK | "Lidos, mas NÃO há confirmação de que foram salvos" + botão manual **Salvar** |
| **Cancelar** | Para entre as etapas; nada salvo (um envio já feito só conta com ACK) |
| **Fechar o popup** | Interrompe a sincronização; o painel pode ficar aberto na página; nada é salvo sem ACK |

## Riscos conhecidos (por isso o teste assistido)

1. **O plugin Tiles real nunca foi observado.** Sabe-se só o resultado do seu clique (painel em linha, mesmo
   endereço). Um `click()` programático pode, em tese, ser ignorado por um tratador que exija evento "confiável";
   nesse caso o popup mostra "o painel não apareceu" (com o diagnóstico estrutural no modo manual) e nada é lido.
2. **Preferência de interface:** o Moodle pode lembrar o último cartão aberto, como se você mesmo tivesse
   clicado. Não é dado acadêmico.
3. Se o clique navegar de verdade para `section.php`, o `activeTab` acaba (ver tabela acima).
4. Um diálogo que apareça **sem** o painel abrir vira "o painel não apareceu" (o coletor validado só avalia
   diálogos depois de achar um painel). É seguro, só menos específico.

## Como instalar a v0.4.0 de integração (sem substituir nada sozinho)

A pasta que o seu Chrome tem carregada (`dist\companion-integracao`, v0.3.0) **não foi alterada**. A v0.4.0 está
em uma pasta nova:

`<pasta-do-projeto>\dist\companion-sync-0.4.0`

1. `chrome://extensions` → **Remover** a extensão atual (mesmo ID `oglmhecabakelhiaiandpdonpblldhnn`, não podem
   coexistir). O host e o banco continuam como estão.
2. **Carregar sem compactação** → a pasta acima. Confirme: versão 0.4.0, mesmo ID, permissão "Comunicar-se com
   aplicativos nativos cooperativos", "Acesso ao site": "Ao clicar na extensão".
3. Feche e abra o Campus AI (para o painel principal e a aba Companion), se estiver com versão antiga.

## Teste assistido na AEDB real (feito por você)

1. Entre manualmente no AVA e abra **a página inicial da Modelagem UML** (`course/view.php?id=7653`), com o
   painel **fechado** (recarregue a página, se preciso).
2. Clique no ícone → **Sincronizar disciplina**. Mantenha a janela aberta. Acompanhe as 5 etapas.
3. **Esperado:** "Sincronizado e salvo no Campus AI. Salvo no Campus AI (leitura nº 4…): 0 novo(s), 0 alterado(s)…
   7 sem mudança", 7 módulos na tabela do popup; em até ~2 s o painel principal do Campus AI mostra a leitura
   (a nº 4 com os dados atuais).
4. Repita com o painel **já aberto**: deve pular "Abrir" e "Aguardar" (sem clique) e dar o mesmo resultado.
5. Se algo falhar: anote **a mensagem exata** e a etapa; no modo manual, "Ler esta página" mostra o diagnóstico
   estrutural. Nada disso exige colar conteúdo da disciplina.

Observação: `companion_runs` não usa AUTOINCREMENT; a numeração segue a sequência real das leituras gravadas.

## Desfazer

Remover a extensão v0.4.0 e carregar de volta `dist\companion-integracao` (v0.3.0) ou a pasta `companion\`
(pré-visualização). Nada no host, no registro ou no banco precisa mudar.
