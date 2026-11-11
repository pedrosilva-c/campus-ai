# Campus AI — assistente acadêmico para Windows

**Arquitetura 3.0 (05/11/2026):** auditoria, contrato único de dados, extensão Companion (rascunho) e
plano de migração em [`ARCHITECTURE_3.md`](../../ARCHITECTURE_3.md). A prova de conceito com Claude in Chrome
está preparada em [`docs/POC_CLAUDE_CHROME.md`](../POC_CLAUDE_CHROME.md), mas **não foi executada**:
nenhum Chrome estava conectado e nada da AEDB foi lido.

**Piloto real assistido — análise com um clique (05/11/2026):** use
`.\.venv\Scripts\python.exe -m campus_ai --pilot` no PowerShell normal. Na aba
**Teste piloto — Uma disciplina**, escolha a disciplina autorizada (hoje somente
*Modelagem UML*, id 7653) e clique em **Analisar disciplina**. O Campus
AI abre o navegador dedicado **direto nessa disciplina** (nunca `about:blank`),
reutiliza a sessão salva do perfil e, se o Moodle pedir login, aguarda você entrar
manualmente na janela e continua sozinho. Depois confirma a disciplina, lê somente
títulos, seções, materiais, atividades e prazos visíveis e mostra a tabela. O
resultado é temporário: sem Gmail, Obsidian, histórico definitivo, downloads, envios
ou IA. **Cancelar** abandona a operação sem fechar o navegador nem perder a sessão.
Veja [instruções, testes, limites e reversão](PILOT_IMPLEMENTATION.md).
Este piloto é diferente do antigo fluxo de sincronização limitada descrito abaixo:
não use **Iniciar análise** para a validação assistida. Nenhuma leitura real foi
executada pelo ambiente de desenvolvimento.

**Navegação por cartões (05/11/2026):** o Moodle da AEDB usa uma página inicial de cartões
(Informações da Disciplina, Trilhas de Aprendizagem, Atividades Avaliativas, Feedback das Aulas,
Fale com o Professor). **Analisar disciplina** (o único botão principal) abre a disciplina, entra
sozinho no cartão **Atividades Avaliativas**, lê AV1, AV2, materiais, atividades e prazos visíveis e
volta à disciplina, sem cliques manuais. O destino do cartão é validado **antes** de navegar
(mesma disciplina, rota de leitura, nenhuma página de atividade, envio, arquivo ou conta); cartões
perigosos nunca são acionados e um cartão cujo comportamento não dá para verificar só é acionado
se você confirmar (a leitura fica parcial). A caixa **Somente inspecionar a estrutura** mostra o que
o aplicativo faria com cada cartão sem navegar nem ler nada: use-a na primeira vez na AEDB real.
Trilhas de Aprendizagem ainda não é lida e é informada como não examinada (leitura parcial).

**Estrutura e cobertura honestas (05/11/2026):** a análise distingue seções acadêmicas de cartões
e regiões de layout do tema, rola a página (só rolagem, sem cliques) para carregar conteúdo tardio e
nunca trata uma seção sem conteúdo nem expansor reconhecido como "aberta": ela fica **de estado
desconhecido**. O resultado tem quatro situações: **cobertura completa**, **parcial**, **não
validada** (a estrutura acadêmica não pôde ser confirmada, por exemplo nenhum material ou
atividade extraído sem prova de que a disciplina esteja vazia) e **erro**. Links que levam a outras
páginas de seção não são seguidos: a leitura vira parcial e o aplicativo informa isso. O estado
mostra um diagnóstico estrutural só com contagens e nomes de tags.

**Seções recolhidas (05/11/2026):** a análise agora abre sozinha as seções recolhidas
da disciplina autorizada (por exemplo AV1 e AV2) antes de ler. Ela só aciona o controle
de abrir/fechar a seção, depois de verificá-lo; não abre atividades, não conclui, não
envia, não baixa. Se um expansor for ambíguo, inseguro ou inexistente, a seção fica
intacta e o resultado é **cobertura parcial**, com o motivo de cada seção. O estado final
informa seções identificadas, expandidas, já abertas e não acessíveis, e quantos materiais
e atividades foram extraídos. O Moodle pode lembrar as seções abertas como preferência da
sua tela (o mesmo que acontece quando você as abre à mão).

**Atualização Jarvis — 14/10/2026:** agente residente na bandeja, instância única,
análise na sessão v2, agenda opt-in, histórico de alertas e consulta local implementados.
Veja [relatório, arquivos alterados e limites](JARVIS_IMPLEMENTATION.md).
Fechar a janela mantém o agente; use **Encerrar Campus AI** na bandeja para sair.
Em **Configurações**, habilite voluntariamente início com Windows e, separadamente,
análises periódicas. O navegador está limitado a uma disciplina piloto. Nenhuma
conta real foi acessada nesta implementação; as descrições abaixo incluem histórico
de etapas anteriores. A consulta **Perguntar ao Campus AI** é local, sem IA externa.

**Versão de demonstração 0.1.0.** Prepara a leitura do Moodle da AEDB por API autorizada, do Gmail institucional por OAuth somente leitura e a escrita local no Obsidian. Não requer VPS. Não é um aplicativo oficial da AEDB.

> **Estado real:** o app e os testes de núcleo foram executados num ambiente Python de desenvolvimento. **Ainda não testamos o fluxo gráfico em um computador Windows nem autenticamos na AEDB ou no Google da faculdade.** A API Moodle pode estar indisponível ao aluno; nesse caso não se tenta contornar o controle da instituição.

## Funcionalidades implementadas

- Interface PySide6 com botão **Iniciar análise**, lista de materiais, indicação de novidades, prazo e alertas.
- Modo fictício para validar visual e Obsidian sem contas.
- Moodle REST (`core_webservice_get_site_info`, `core_enrol_get_users_courses`, `core_course_get_contents`, `mod_assign_get_assignments`, `mod_assign_get_submission_status`) quando autorizados.
- Alternativa Moodle por navegador visível e login manual, implementada com páginas simuladas. Playwright e Chromium estão na `.venv`; ainda falta validação assistida autorizada no AVA da AEDB.
- Gmail API OAuth para Desktop com escopo `gmail.readonly`. Lista até 30 mensagens recentes, com assunto, remetente, data e prévia. **Não baixa nem interpreta anexos ainda.**
- Histórico local SQLite para evitar notificações duplicadas.
- Classificação local simples de comunicados por assunto ou rótulo `IMPORTANT`; o histórico impede repetir o alerta para o mesmo ID de mensagem. Um registro de cada sincronização guarda apenas contagens e horário no SQLite.
- Escrita Markdown sob `<VAULT>/Campus AI/` e painel `Painel Acadêmico.md`.
- Notas pessoais e notas geradas editadas manualmente são preservadas; uma atividade renomeada mantém o mesmo arquivo quando permanece na mesma disciplina.
- Atalho de inicialização opcional do Windows, com pergunta antes de cada análise.
- Fluxo separado/manual de estudo por Codex CLI, com confirmação antes de enviar notas a IA. **Não gera resumos por IA automaticamente a cada postagem no MVP.**

## Instalação no Windows 10/11

1. Instale Python 3.11 ou 3.12 em https://www.python.org/downloads/ (com **py launcher**). Instale o Obsidian e crie/abra um vault.
2. Extraia o ZIP do projeto para uma pasta que você mantenha, por exemplo `C:\Projetos\campus-ai-mvp`.
3. Abra **PowerShell** nesta pasta e execute:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\instalar_windows.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\abrir_windows.ps1
```

4. No aplicativo abra **Configurações**, selecione a pasta raiz do vault do Obsidian e mantenha modo **Demonstração**.
5. Clique em **Iniciar análise**. Confira `Obsidian -> Campus AI -> Painel Acadêmico`.
6. Clique novamente: o contador de novidades deve ser zero, enquanto o painel continua atualizado.

Para iniciar perguntando se deve analisar ao entrar no Windows:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\habilitar_inicio_windows.ps1
```

Para desligar inicialização:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\desabilitar_inicio_windows.ps1
```

**Importante:** esse atalho aponta para a `.venv` na pasta escolhida; movê-la pode quebrar a inicialização. O EXE para Windows é gerado **no seu Windows** com:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\gerar_exe_windows.ps1
```

O ZIP entregue contém código-fonte, **não um EXE Windows já compilado**.

## Gmail: conectar com segurança

1. Acesse Google Cloud Console com uma conta capaz de criar projeto OAuth (a faculdade pode exigir aprovação do administrador). Ative a **Gmail API**.
2. Configure a tela de consentimento, público-alvo e os escopos apropriados; se projeto externo em teste, adicione a conta como usuário de teste.
3. Crie credenciais OAuth 2.0 do tipo **Desktop app** e baixe `credentials.json` **fora do repositório**.
4. No Campus AI → Configurações, selecione o JSON e clique **Conectar Gmail pelo navegador**; aprove a permissão somente leitura.
5. Configure modo **Real** e salve. Tokens de acesso e atualização ficam no cofre de credenciais do sistema, não no JSON de configurações.

Guia oficial: https://developers.google.com/workspace/gmail/api/quickstart/python

A faculdade pode restringir OAuth de apps externos. Sem permissão, a integração Gmail permanecerá desligada. Para revogar o acesso no Google, remova também a autorização nas configurações de segurança da sua Conta Google.

## Moodle AEDB: somente API autorizada

- Endereço sugerido: `https://ead.aedb.br/ava`
- O Moodle precisa permitir webservices REST e disponibilizar ao aluno um **token do serviço autorizado**. O login institucional por si só não habilita o token.
- O conector atual usa os *web services clássicos* do Moodle. Um token da REST API nova do Moodle 5.3 não é intercambiável com esse token; as funções exatas devem ser confirmadas na documentação da instalação AEDB.
- Insira exclusivamente um token autorizado em **Configurações > Token Moodle > Salvar token**. Não cole sua senha da faculdade nem compartilhe token em conversa.
- Se alguma função da API estiver bloqueada, o app registra o conector como parcial. **Não faz login automatizado nem contorna CAPTCHA/MFA.**
- Prazos e situação de entrega precisam ser confirmados no AVA. Algumas atividades podem não retornar data, status ou anexos por API.
- Em uma resposta parcial, notas Moodle existentes e o painel anterior são preservados; materiais novos identificados ainda podem ganhar notas. O aviso aparece no resultado da análise. A data `added` do módulo, quando a API a fornece, é registrada como dado da fonte, sem presumir que seja a data efetiva de publicação.

### Diagnóstico de web services, somente após autorização

Com um token **de web service clássico** autorizado pela AEDB já guardado no cofre do Windows, execute voluntariamente:

```powershell
.\.venv\Scripts\python.exe -m campus_ai --check-moodle
```

O comando faz uma chamada HTTPS a `core_webservice_get_site_info` na URL Moodle configurada e mostra quais das funções de leitura foram anunciadas ao token. Sem token, não faz conexão. Não imprime token, ID do aluno nem mensagens brutas do servidor. A lista anunciada é um diagnóstico inicial; somente uma análise autorizada pode confirmar cada função. **O comando não foi executado com credenciais reais.**

Antes dessa validação real, confirmar com a AEDB: se web services clássicos REST estão habilitados para alunos; se o token foi emitido para uso neste aplicativo; e se o serviço permite `core_webservice_get_site_info`, `core_enrol_get_users_courses`, `core_course_get_contents`, `mod_assign_get_assignments` e `mod_assign_get_submission_status`. A [documentação Moodle distingue tokens de web service dos tokens da REST API nova](https://docs.moodle.org/503/en/REST_API_tokens).

## Moodle AEDB: alternativa por navegador (prévia simulada)

Nas Configurações, o modo **Real** permite escolher **Navegador com login manual**. O painel Moodle oferece **Conectar conta AEDB**, **Verificar sessão**, **Iniciar análise**, **Abrir navegador**, **Desconectar sessão** e a data/status da última tentativa Moodle. A análise só começa quando você clica no botão. O conector usa um perfil persistente exclusivo em `%LOCALAPPDATA%\CampusAI\browser_profile`; não usa o perfil principal do Chrome, não preenche senha/MFA e não exporta cookies. O perfil contém dados de sessão sensíveis: mantenha a conta Windows protegida e não copie ou publique essa pasta. Desconectar apaga apenas esse perfil após confirmação.

**Estado atual:** Playwright 1.63.0 e Chromium estão instalados na `.venv`, mas nenhuma página ou conta real da AEDB foi acessada. O seletor de disciplinas, seções e atividades foi validado apenas com HTML simulado; pode precisar de ajustes quando a estrutura real for observada em teste assistido. O conector guarda links para materiais, sem baixar anexos; não faz entregas nem modifica dados no Moodle. Prazos e estados de entrega só aparecem se visíveis na página lida. Páginas não reconhecidas, sessão expirada ou navegação interrompida geram análise parcial e preservam notas anteriores. Bloqueio explícito de automação interrompe a leitura. A autorização de acesso e a política da AEDB precisam ser confirmadas antes de uma sessão real.

Para o primeiro acesso ao portal, ainda é necessária autorização específica para o teste assistido com login manual feito por você. O Campus AI não deve receber sua senha. A [documentação oficial do Playwright](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context) descreve o perfil persistente; a [orientação de autenticação](https://playwright.dev/python/docs/auth) alerta que o estado da sessão é sensível.

**Tentativa anterior no MXC:** `pip install playwright` falhou porque o sandbox não conseguiu resolver `pypi.org`. O aluno instalou depois pelo PowerShell normal, usando a mesma `.venv`. O extra opcional `browser` em `pyproject.toml` declara `playwright>=1.63,<2`. A [distribuição oficial no PyPI](https://pypi.org/project/playwright/) declara suporte a Python 3.13.

**Instalação manual posterior no Windows:** Playwright **1.63.0** foi instalado na `.venv` com Python **3.13.14**. `PLAYWRIGHT_BROWSERS_PATH=0` localiza Chromium revisão **1243** em `.venv\Lib\site-packages\playwright\driver\package\.local-browsers\chromium-1243` (e o shell headless correspondente). O aplicativo configura essa variável ao abrir o navegador; ela deve estar definida também ao instalar ou listar navegadores pela CLI. Para repetir a instalação em PowerShell normal, na pasta do projeto:

```powershell
$env:PLAYWRIGHT_BROWSERS_PATH = '0'
.\.venv\Scripts\python.exe -m pip install 'playwright>=1.63,<2'
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m playwright install --list
```

O teste local `tests/test_playwright_local.py` tenta abrir somente `about:blank` em um perfil temporário, com janela visível. Execute com `CAMPUS_AI_BROWSER_SMOKE=1`; sem essa variável ele é ignorado na suíte normal. No MXC, a importação do Playwright e da interface passou, mas a abertura excedeu 20 segundos **antes de iniciar o driver**. O traceback de diagnóstico parou em `asyncio`/`socketpair` do Windows no sandbox; portanto, o Chromium não chegou a ser iniciado ali. O aluno informou que o Chromium foi testado no PowerShell normal. Nenhum acesso à AEDB é feito por esse teste.

```powershell
$tempPath = Join-Path (Get-Location).Path '.tmp-campus-ai'
New-Item -ItemType Directory -Path $tempPath -Force | Out-Null
$env:TEMP = $tempPath; $env:TMP = $tempPath; $env:TMPDIR = $tempPath
$env:CAMPUS_AI_BROWSER_SMOKE = '1'
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_playwright_local.py -v
```

### Preparar a pasta CampusAI e o perfil persistente

O navegador usa %LOCALAPPDATA%\CampusAI\browser_profile. Antes do primeiro login, a pasta superior e o perfil precisam ter herança de ACL desligada e controle total somente para a conta Windows atual, SYSTEM e Administradores. O aplicativo verifica ambas as ACLs antes de abrir o Playwright. Isso não autoriza acesso à AEDB.

O script scripts/preparar_perfil_moodle_windows.ps1 só aceita as entradas conhecidas do Campus AI diretamente sob CampusAI: browser_profile, config.json e os bancos demo.db/live.db com arquivos auxiliares SQLite. Se aparecer outra entrada ou um redirecionamento, ele para antes de alterar qualquer ACL. O script não altera outras pastas do Windows.

-Prepare exige -BackupPath absoluto, fora de CampusAI, e recusa substituir um backup existente. Ele salva a ACL original da pasta superior e do perfil em SDDL, restringe a ACL do próprio arquivo de backup, confere sua leitura e só então altera as duas ACLs alvo. O backup é protegido pelo DPAPI da conta Windows atual: restaure-o com a mesma conta, na mesma instalação do Windows, e guarde-o fora do repositório. -Restore restaura as duas ACLs desse arquivo; isso pode reabrir o acesso herdado anterior. Use PowerShell normal e revise o script antes da execução.

```powershell
$backup = Join-Path $env:USERPROFILE 'CampusAI-acl-original.bin'
powershell.exe -NoProfile -NonInteractive -File .\scripts\preparar_perfil_moodle_windows.ps1 -Prepare -BackupPath $backup
powershell.exe -NoProfile -NonInteractive -File .\scripts\preparar_perfil_moodle_windows.ps1 -VerifyOnly
.\.venv\Scripts\python.exe -m campus_ai --check-browser-local

# Para restaurar as ACLs originais, se necessário:
powershell.exe -NoProfile -NonInteractive -File .\scripts\preparar_perfil_moodle_windows.ps1 -Restore -BackupPath $backup
```

O teste --check-browser-local abre somente about:blank em um Chromium visível com o perfil persistente. Nenhuma ACL real nem conta AEDB foi alterada ou acessada durante esta revisão do código. No MXC, a execução do .ps1 e o início do driver Playwright podem ser bloqueados; a validação com o perfil real fica para PowerShell normal, após aprovação específica.

Após o teste local passar e **somente com autorização separada para acessar a AEDB**, abra a GUI, escolha modo Real e acesso Moodle por navegador, selecione o vault e clique **Conectar conta AEDB**. O navegador ficará visível para você digitar suas credenciais diretamente no portal. Confirme o estado com **Verificar sessão** antes de usar **Iniciar análise**. Não envie capturas da página de login, cookies ou arquivos do perfil.

## Gerar notas de estudo com o Codex CLI — Astra / Sol

O CLI do Codex é ferramenta de desenvolvimento e também pode, se **você autorizar**, produzir notas de estudo. É separado da API paga. Requer Codex CLI instalado, autenticado e com modelo disponível na sua conta. A disponibilidade de Astra/Sol e a franquia variam por plano e versão.

Primeiro sincronize notas no Obsidian. Então execute manualmente:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\gerar_estudo_codex.ps1 -Nota "C:\Caminho\Vault\Campus AI\Disciplinas\Banco-de-Dados\Minha-aula.md"
```

O script verifica que a nota está em `Campus AI/`, explica que enviará seu conteúdo a um modelo em nuvem, pede que você digite `SIM`, executa o **Codex em modo somente leitura dentro de uma pasta temporária isolada** e guarda a resposta em `Campus AI/Estudos IA/`. O script não coleta senhas nem acessa o banco do Campus AI.

Opcionalmente passe `-Modelo "identificador-exato-no-seu-codex"` para escolher um modelo disponível. **Não suponha que o nome de exibição de um modelo seja um ID CLI válido.**

Para desenvolver o app no Codex, abra a pasta do projeto e use as orientações do arquivo `AGENTS.md` (arquivo interno de desenvolvimento, não publicado). Sugestão: Sol para implementação e testes; Astra para revisão de arquitetura, segurança e integração com Moodle.

## Dados, ética e limites

- **Segredos:** os tokens de autenticação são guardados pelo `keyring` do sistema. O arquivo OAuth `credentials.json` permanece onde você o escolheu; mantenha-o privado. Não há coleta de senha da faculdade.
- **Dados locais:** configuração sem tokens e banco SQLite em `%LOCALAPPDATA%\CampusAI\`; Markdown em seu vault. Arquivos da faculdade podem conter dados pessoais; evite sincronizar o vault em serviços públicos.
- **IA:** chamada Codex somente manual e confirmada. Leia a política da faculdade para compartilhar materiais e revise resultados antes de usar; a IA pode errar.
- **Leitura apenas:** não entrega atividades, não muda notas, não envia e-mails, não faz upload para Moodle.
- **Limitações:** PDF/anexos, análise semântica de e-mails, tarefas de quiz, progresso completo e revisões automáticas por IA ainda não estão implementados. O app não roda em segundo plano quando o computador está desligado.

## Testes rápidos

```powershell
$tempPath = Join-Path (Get-Location).Path '.tmp-campus-ai'
New-Item -ItemType Directory -Path $tempPath -Force | Out-Null
$env:TEMP = $tempPath; $env:TMP = $tempPath; $env:TMPDIR = $tempPath
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

No sandbox MXC, os diretórios temporários padrão podem bloquear escrita. A pasta `.tmp-campus-ai/` está no `.gitignore`. O Python 3.13.14 instalado pode imprimir `Failed to find real location of ...\Python313\python.exe` mesmo ao executar com código de saída zero; o aviso ocorre também ao chamar o executável base, não apenas a `.venv`. Não foi necessário recriar o ambiente.

Os testes de Moodle e Gmail usam respostas simuladas. Ainda faltam a autorização institucional para o serviço REST Moodle e a aprovação/configuração de um cliente OAuth Desktop do Google para a conta institucional. `gmail.readonly` permite ler mensagens e configurações da caixa e é classificado pelo Google como escopo restrito; o app consulta somente mensagens dentro do filtro configurado. Tokens ficam no cofre de credenciais do Windows via `keyring`; o JSON do cliente OAuth deve permanecer fora do projeto. Nenhuma conta real foi testada.

A skill local `campus-ai-academic-sync` (arquivo interno de desenvolvimento, não publicado) reúne as regras específicas de sincronização. Ela não instala pacotes nem executa scripts.

Referências oficiais: [serviços externos Moodle](https://docs.moodle.org/dev/Web_services), [tokens da REST API nova do Moodle](https://docs.moodle.org/503/en/REST_API_tokens), [escopos da Gmail API](https://developers.google.com/workspace/gmail/api/auth/scopes) e [listagem de mensagens Gmail](https://developers.google.com/workspace/gmail/api/reference/rest/v1/users.messages/list).

Documentação oficial sobre modelos do Codex: https://help.openai.com/pt-br/articles/20001516-managing-usage-with-gpt-6-astra-in-work-and-codex
