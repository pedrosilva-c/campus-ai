# Campus AI — implementação Jarvis, 14/10/2026

## Entrega e estado de validação

As Fases 1 e 2 foram implementadas e verificadas com Qt offscreen, mutex Windows,
registro simulado e driver Playwright falso. As partes locais das Fases 3–7 também
foram implementadas; a integração acadêmica real continua pendente de validação
autorizada. O usuário informou que a sessão v2 reconhece o login enquanto o
navegador permanece aberto; esta entrega não repetiu esse acesso.

Nenhuma credencial real foi usada, nenhum perfil/sessão real foi aberto ou alterado,
nenhum pacote foi instalado e nenhuma chamada AEDB, Gmail ou IA foi executada.
Não foram criados commits. A pasta disponível não tem metadados Git reconhecidos.

## Funcionalidades

- **Residente:** QSystemTrayIcon com Abrir Campus AI, Analisar agora, Lembrar mais
  tarde (15 minutos), Ignorar e Encerrar Campus AI. Fechar a janela oculta a GUI.
  Encerrar aguarda workers e fecha Chromium sem apagar o perfil. Sem bandeja
  disponível, a janela permanece acessível e fechá-la encerra o aplicativo.
- **Login Windows:** opt-in em Configurações. Usa HKCU Run, sem administrador e
  sem executar shell. Scripts anteriores foram atualizados para o mesmo mecanismo;
  o atalho legado do Campus AI é removido quando essa configuração é aplicada.
  O comando registrado usa pythonw e caminhos absolutos, com `--startup`.
  Não foi habilitado na conta real durante o desenvolvimento.
- **Instância única:** GUI, `--scan` e diagnósticos compartilham um mutex no Windows
  por diretório de dados e sessão Windows. Segunda execução encerra sem abrir
  Chromium; abra a interface pelo ícone já existente. Não há ativação remota da
  janela por IPC nesta versão. Em outros sistemas, usa QLockFile.
- **Sessão v2:** conectar, verificar, mostrar e analisar passam pelo mesmo worker.
  Playwright e seu contexto nunca trocam de thread. O worker processa eventos locais
  durante a ociosidade, informa fechamento do navegador e permite conexão manual
  posterior. Fechar uma aba reaproveita outra aba aberta do mesmo contexto.
  Cancelamento/encerramento não apagam cookies; Desconectar mantém a confirmação
  explícita já existente para apagar exclusivamente o perfil dedicado.
- **Análises:** GUI reutiliza a sessão existente. Uma análise não abre Chromium
  automaticamente: sem contexto, Moodle fica parcial e Gmail ainda pode funcionar.
  Conectar e Abrir navegador continuam ações manuais. CLI `--scan` mantém seu fluxo
  explícito anterior e não pode disputar o perfil com a GUI.
- **Piloto:** navegador limitado a uma disciplina, inclusive paginação. ID opcional
  em Configurações; vazio seleciona a primeira disciplina identificada no painel.
  A existência de outras disciplinas torna o resultado parcial. Não há botão de
  expansão para todas antes de validar os seletores reais.
- **Agendamento:** desativado por padrão, entre 15 e 1440 minutos. Confirmação
  explícita antes de salvar autorização; alterações das configurações com agenda
  ativa pedem confirmação novamente. Não executa imediatamente ao habilitar.
  Pula ciclos enquanto ocupado ou com Configurações abertas. Não recupera ciclos
  perdidos com o computador desligado e não faz login automático.
- **Alertas:** journal SQLite adicional, com inserção atômica e chaves estáveis para
  novidades/alterações, material, comunicado, prazo nas próximas 48 horas, sessão
  expirada e avisos de parcialidade. A aba Alertas recentes mostra os últimos 30.
  Toasts agrupam até três eventos; os demais ficam no histórico. As notificações
  são geradas após análises, não por acesso autônomo extra às fontes.
- **Obsidian:** notas novas por disciplina e tipo (Materiais, Atividades,
  Comunicados, Mensagens). Caminhos antigos são reutilizados. Conteúdo inclui
  origem/professor quando fornecido, datas identificadas, prazo, link, estado,
  trecho de resumo e lista de passos de estudo. Nenhum dado ausente é inferido.
  Hashes continuam protegendo edições manuais; nesses casos a atualização é
  recusada e há aviso, sem mesclar nem apagar notas.
- **IA:** contrato de provedor independente para futuros adaptadores Ollama, API e
  Codex, com consentimento associado ao provedor e ao hash do conteúdo/pergunta.
  Não há adaptador de rede ou execução CLI automático. Resultados são rotulados
  como apoio sujeito a revisão. Interface de voz apenas declara captura voluntária
  futura; nenhum microfone é inicializado.
- **Painel:** disciplinas identificadas, tabela ordenada por prazo, histórico de
  alertas, última análise, status Moodle e resumo das integrações. Perguntar ao
  Campus AI oferece consulta local determinística sobre disciplinas e atividades;
  não é um modelo generativo e não salva perguntas/respostas.

## Limitações que permanecem

1. Seletores Moodle, prazos e conteúdo de fóruns ainda usam fixtures. O leitor
   identifica o que aparece na página da disciplina; não baixa anexos nem percorre
   tópicos de fórum para interpretar todas as mensagens. Não comprova integração
   real nem entrega/correção de trabalhos.
2. Pela regra conservadora existente, uma leitura parcial preserva notas Moodle
   previamente reconhecidas e o painel Markdown. Novos itens podem gerar notas;
   atualizações de itens anteriores aguardam uma leitura completa. Isso também
   vale quando o piloto omite outras disciplinas. Não se deve tratar esse piloto
   como monitoramento completo de alterações em todas as matérias.
3. Notificações usam o mecanismo nativo oferecido pelo Qt. Windows pode suprimir
   sua apresentação. As três ações ficam no menu da bandeja e no diálogo aberto
   ao clicar na notificação de início; não são botões dentro do toast do Windows.
   Deduplicação significa registrar o evento uma vez, não confirmar que foi visto.
4. Datas sem fuso explícito usam o fuso local apenas no cálculo de alerta; datas
   inválidas não disparam alertas. Confirme os prazos no AVA.
5. Encerramento aguarda chamadas em andamento respeitarem seus timeouts. Não mata
   processos à força. Não prolonga a validade da sessão autenticada.
6. Não houve teste do login do Windows, Explorer/bandeja real, Chromium real ou
   sessão autenticada nesta tarefa. Renderização offscreen verifica apenas layout.
7. Provedores IA, limites de custos e captura voluntária de voz são extensões
   futuras. ChatGPT Plus não implica crédito gratuito de API.

## Arquivos alterados/criados

| Área | Arquivos |
| --- | --- |
| Residente e início | `campus_ai/ui.py`, `campus_ai/cli.py`, `campus_ai/instance.py`, `campus_ai/startup.py` |
| Sessão e sincronização | `campus_ai/browser_runtime.py`, `campus_ai/browser_worker.py`, `campus_ai/moodle_browser.py`, `campus_ai/engine.py` |
| Agenda, alertas e notas | `campus_ai/config.py`, `campus_ai/state.py`, `campus_ai/notifications.py`, `campus_ai/obsidian.py`, `campus_ai/gmail.py` |
| IA e voz futuras | `campus_ai/intelligence.py` |
| Scripts Windows | `scripts/habilitar_inicio_windows.ps1`, `scripts/desabilitar_inicio_windows.ps1` |
| Testes | `tests/test_resident.py`, `tests/test_browser_runtime.py`, `tests/test_browser_worker.py`, `tests/test_startup.py`, `tests/test_jarvis.py` |
| Documentação | `README.md`, `AGENTS.md`, `JARVIS_IMPLEMENTATION.md` |

## Validação e próximos passos

Suíte: `python -m unittest discover -s tests -v`, usando a `.venv` e TEMP/TMP/TMPDIR
em `.tmp-campus-ai`. Foram descobertos 83 testes: 81 passaram e os 2 testes opt-in
de navegador foram ignorados. O aviso conhecido de localização do Python 3.13
não impediu a execução. A renderização Qt foi inspecionada com dados fictícios;
prévia em `.tmp-campus-ai/jarvis-dashboard.png` e `jarvis-settings.png`.

1. Validar residente, registro opt-in, notificação e saída no Windows normal,
   primeiro em demonstração. Habilitar início automático somente por escolha do aluno.
2. Sob autorização específica para acesso real, conectar manualmente e validar
   uma disciplina. Confirmar política AEDB, estado da sessão, seletores, prazos e
   resultados parciais antes de expandir o monitoramento.
3. Configurar e autorizar Gmail Desktop OAuth separadamente.
4. Antes de ligar um provedor IA, revisar adaptador, destino de dados, limites de
   custo e consentimento por conteúdo. Não executar Codex CLI em segundo plano.
