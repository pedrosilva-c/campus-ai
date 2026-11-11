# Campus AI Companion — validação local (v0.5.4)

**v0.5.4:** as duas sincronizações também leem **prazos e estado de entrega** na página de cada tarefa e
questionário da seção autorizada. É só leitura, com uma requisição GET de mesma origem por atividade; nada é
clicado ou enviado. O resultado aparece numa tabela antes do botão **Salvar no Campus AI**. Ver
[`../docs/PRAZOS_E_ENTREGAS.md`](../docs/PRAZOS_E_ENTREGAS.md).

**v0.5.3:** **"Sincronizar seções autorizadas"** também não salva sozinho. Ele lê as seções autorizadas uma após a
outra, mostra um resumo por seção e espera **um** clique em **Salvar no Campus AI**. Fechar o popup antes disso
descarta as leituras. Depois do clique, as seções são salvas na ordem, e o resultado mostra quais foram salvas e
quais falharam.

**v0.5.2:** se a janela **"Preferência dos dados"** do AVA aparecer durante "Sincronizar disciplina", ela é fechada
automaticamente pelo **X**, com a autorização do aluno. "Sim" e "Cancelar" nunca são acionados, e qualquer outro
diálogo continua bloqueando a leitura. Depois a seção é revalidada, sem clicar de novo no cartão. "Sincronizar
disciplina" agora **só lê e valida**: o salvamento acontece quando você clica em **Salvar no Campus AI**.

**v0.5.1 (correção):** um módulo que aparece em duas seções só passa a "pertencer" a uma seção depois que o
aplicativo CONFIRMA o salvamento dela. Se a primeira seção falhar ao salvar, a seguinte pode salvar o módulo.
Mesmas permissões, mesmo ID e mesmo comportamento da v0.5.0 em todo o resto.

**v0.5.0 (experimental):** botão **Sincronizar seções autorizadas** — lista os cartões da disciplina e lê, um após
o outro, só as seções acadêmicas autorizadas (hoje apenas Atividades Avaliativas; Trilhas de Aprendizagem aguarda
autorização). "Sincronizar disciplina" (v0.4.0) continua como modo estável. Ver
[`../docs/LEITURA_COMPLETA_DISCIPLINA.md`](../docs/LEITURA_COMPLETA_DISCIPLINA.md).

Extensão Chrome (Manifest V3) **não publicada**, para validar no seu navegador a leitura da seção
**Atividades Avaliativas** da Modelagem UML (curso 7653). Ela mostra o resultado num popup, só na memória.
Não depende do Claude e não altera nada no Moodle. Arquitetura: [`../ARCHITECTURE_3.md`](../ARCHITECTURE_3.md).

**v0.4.0 — Sincronizar disciplina (um clique):** na página inicial da Modelagem UML, o botão **Sincronizar
disciplina** confere domínio, curso 7653 e formato Tiles, **clica uma única vez no cartão Atividades
Avaliativas** (depois de validar o vínculo dele com a seção), espera o painel carregar por completo, lê os
módulos com o mesmo coletor da v0.2, valida e envia ao aplicativo Campus AI. Só diz "salvo" quando o aplicativo
confirma a gravação. Os botões **Ler esta página** e **Salvar no Campus AI** continuam como modo manual.
Detalhes, limites e roteiro do teste na AEDB: [`../docs/SINCRONIZACAO_UM_CLIQUE.md`](../docs/SINCRONIZACAO_UM_CLIQUE.md).
Nenhuma permissão nova (`activeTab` + `scripting`; `nativeMessaging` só na versão de integração).

**Salvar:** nesta pasta (pré-visualização, sem `nativeMessaging`) o salvamento responde que a integração local
não está disponível; a versão de integração é gerada com `python -m campus_ai.companion_build <pasta>`. Veja
[`../docs/INTEGRACAO_COMPANION.md`](../docs/INTEGRACAO_COMPANION.md).

## Permissões solicitadas e por quê

| Permissão | Por que | O que **não** permite |
| --- | --- | --- |
| `activeTab` | Dá acesso **temporário e só à aba atual**, **depois** que você clica no ícone da extensão. Acaba ao navegar ou fechar a aba | Nenhum acesso permanente a `ead.aedb.br`; nenhuma leitura de outras abas |
| `scripting` | Injeta `src/dom_tiles.js` na aba autorizada pelo `activeTab` para ler atributos | Sozinha não dá acesso a nenhum site |

O Chrome **não exibe aviso de permissão** na instalação para essas duas. O que **não** existe no manifesto:
`host_permissions`, `content_scripts` (nada roda ao abrir uma página), `background`/service worker,
`nativeMessaging`, `storage`, `cookies`, `tabs`, `webRequest`, `downloads`, recursos acessíveis pela web.

Defesa extra: a CSP do popup (`connect-src 'none'`) impede que qualquer código da extensão faça
requisições de rede, e o popup monta a tabela só com `textContent` (nunca interpreta HTML da página).

## O que é lido (e o que não é)

Antes de ler qualquer item, confirma: endereço (`https://ead.aedb.br`, página `section.php`), disciplina
**7653**, formato **Moodle Tiles** e seção **Atividades Avaliativas**. Se algo falhar, nada é lido. Só
então lê, de cada módulo não rotulado: `data-cmid`, `data-modtype`, `data-title` e o endereço do módulo.
**Não lê:** texto de rótulos, enunciados, anexos, calendário, notas, mensagens, outras seções ou
disciplinas, cookies, armazenamento. **Não faz:** cliques, rolagem, navegação, envio, download.

## Como carregar

1. Chrome → `chrome://extensions` → ligue **Modo do desenvolvedor** (canto superior direito).
2. **Carregar sem compactação** → escolha a pasta `...\campus-ai-mvp\companion` (a que contém `manifest.json`).
3. (Opcional) Ícone de quebra-cabeça → fixar **Campus AI Companion**.
4. Em **Detalhes** da extensão, deixe **Acesso ao site** em **Ao clicar na extensão** (padrão).

A extensão tem uma chave pública no manifesto para ter id estável
(`oglmhecabakelhiaiandpdonpblldhnn`); a chave privada foi descartada. Remova o campo `key` antes de qualquer
publicação.

## Como testar na AEDB

0. Depois de atualizar os arquivos: `chrome://extensions` → botão **Recarregar** da extensão (deve mostrar
   versão 0.2.0) e recarregue também a aba da AEDB.
1. Abra o AVA, entre manualmente, abra a Modelagem UML e clique no cartão **Atividades Avaliativas**.
   (A extensão não navega sozinha.) A seção pode abrir de dois jeitos, ambos suportados:
   - **painel na própria página da disciplina** — o endereço continua `course/view.php?id=7653`;
   - **página própria da seção** — `course/section.php?id=…`.
2. Com a seção visível, clique no ícone **Campus AI Companion** → **Ler esta página**.
3. Esperado: as 5 verificações "Confirmado"; "Modo" indicando painel ou página da seção; **7 módulos**
   (5 `assign` → Tarefa, 1 `resource_pdf` → Arquivo, 1 `groupselect` → Escolha de grupo); 3 rótulos
   ignorados; "Confere" na comparação com a referência; "Nenhum" problema; cobertura **parcial**.
   Compare títulos e tipos com a tela.
4. Se a quantidade ou os tipos forem diferentes, a tela mostra a diferença por tipo e se algum item foi
   descartado (duplicado, sem título, sem id, tipo desconhecido). A extensão não adivinha a causa.

No modo painel, o painel só é aceito se estiver **ligado ao cartão por atributos** (`data-section` /
`data-true-sectionid` do cartão) e **visível**; nunca porque contém o texto "Atividades Avaliativas".
Conteúdo oculto (`hidden`, `aria-hidden`, `inert`, recolhido, `display:none`), cartões, índice lateral e
módulos de outras seções no fundo são ignorados. Com dois painéis possíveis, um diálogo alheio aberto ou
um cartão ambíguo, a leitura é **bloqueada**. A identidade é conferida antes e de novo depois da leitura.

**Se a leitura for recusada**, o popup mostra o motivo e um **diagnóstico estrutural** (contagens, nomes de
tags, classes e atributos — nenhum texto, título ou id). Ele existe para ajustar o leitor ao DOM real: a
marcação exata do painel da AEDB ainda não foi observada. Se o motivo for "painel_fechado" ou
"painel_sem_vinculo" com a seção visível na tela, copie (ou fotografe) só a tabela de diagnóstico.

Outras recusas esperadas: login, outra seção, outra disciplina, página de atividade, outro domínio — em
todas, nenhum item é lido.

**Se o popup disser "não tem acesso a esta aba"** mesmo clicando no ícone com a aba da AEDB ativa: o
`activeTab` não foi concedido nessa situação. Não contorne; me avise (a alternativa seria declarar
`host_permissions` só para `ead.aedb.br`, que é um acesso permanente e precisa da sua decisão).

## Como desativar e remover

- **Desativar:** `chrome://extensions` → desligue o interruptor da extensão.
- **Remover:** **Remover** → confirmar. Como não há armazenamento, nada sobra no perfil do Chrome.
- Fechar o popup já descarta o resultado.

## Estrutura da pasta

| Caminho | Papel |
| --- | --- |
| `manifest.json`, `src/` | **Tudo o que o Chrome carrega** |
| `src/dom_tiles.js` | Lê atributos da página (injetado só após o seu clique) |
| `src/tiles_adapter.js`, `src/preview.js` | Classificação e verificações (funções puras / API injetada) |
| `src/popup.html/css/js`, `src/render.js` | Popup e tabela |
| `native/` | Protocolo do futuro host Native Messaging (F4). **Não é referenciado pelo manifesto, não é carregado e nenhum host está registrado no Windows** |
| `test/` | Testes Node (`node --test test/*.test.mjs`); também rodam pela suíte Python |

O Chrome ignora os arquivos que o manifesto não referencia (`native/`, `test/`, `package.json`).
