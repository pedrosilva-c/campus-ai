# Jarvis — IA local (10/11/2026)

O Jarvis entende pedidos fora do repertório das regras com uma **IA local e gratuita**: Ollama 0.40.15 + `qwen3.5:4b`
(Apache 2.0), rodando só neste computador. Nenhuma API paga, nenhuma nuvem.

**Como funciona** (`campus_ai/jarvis/llm.py`):
1. As regras (`nlu.py`) tentam primeiro. São instantâneas e determinísticas.
2. Se não entenderem, ou se só bateram uma palavra ambígua ("mandar", "PDF", "abrir"), o modelo escolhe **uma**
   intenção de uma lista fechada (`llm.INTENTS`). Ele recebe só a sua frase, nunca títulos do Moodle, memórias ou
   documentos.
3. A resposta é validada (`llm.validate`):
   - só aceita intenções da lista, nunca `confirmar`;
   - nomes de atividade só passam se as palavras estiverem na sua frase;
   - frases com cara de segredo não são enviadas ao modelo.
4. A ferramenta de sempre executa e responde com os dados reais. O modelo **não** redige fatos nem calcula datas.
5. Recusas finais nunca vão ao modelo: enviar e-mail, submeter, iniciar questionário, pagar, apagar arquivos.

**Privacidade:**
- A API fica em `127.0.0.1:11434`, e o cliente só aceita endereços do próprio computador e ignora proxies.
- A nuvem está desligada (`~/.ollama/server.json` com `disable_ollama_cloud: true`, mais `OLLAMA_NO_CLOUD=1` só no
  processo que o Campus AI inicia). O log confirmou `Ollama cloud disabled: true`.
- Modelos `-cloud`/`:cloud` são recusados.
- Medido durante inferências reais: zero conexões externas dos processos do Ollama.

**Instalação** (portátil, sem administrador, sem Registro):
- Local: `%LOCALAPPDATA%\CampusAI-Ollama\v0.40.15`. O `.zip` oficial teve o SHA-256 conferido contra o GitHub e o
  `sha256sum.txt`, foi verificado pelo Defender, e os executáveis e DLLs estão assinados pela Ollama Inc. (DigiCert).
- O modelo fica em `%USERPROFILE%\.ollama\models` (3,1 GB).
- O Campus AI inicia o servidor ao abrir, se ele não estiver rodando, e o encerra ao fechar. Sem Ollama, tudo continua
  por regras. A primeira resposta após abrir pode levar de 1 a 2 minutos (carga do modelo, que é aquecido em segundo
  plano). Depois, as respostas vêm em poucos segundos.

**Limites:**
- Sem prazos verificados no `live.db` (leitura salva antes da extensão 0.5.4), o Jarvis responde "não verificado" e
  não escolhe a "mais urgente". Para prazos reais, sincronize e salve com o Companion 0.5.4.
- O enunciado das atividades não é armazenado: os documentos o marcam como NÃO DISPONÍVEL.

# Jarvis — Etapa 1: núcleo (09/11/2026)

Primeira etapa do Projeto Jarvis: conversa por texto, interpretação de comandos, ferramentas reais, memória local,
lembretes e histórico. **Voz, monitoramento automático do Moodle, PDF/planilhas/apresentações e integrações pessoais
são as próximas etapas e ainda não existem.** Nenhuma dependência foi instalada.

## Arquitetura

```
Janela (ui.py) ── aba "Jarvis" (jarvis_ui.py: conversa, Interromper, links de arquivos, lembretes → bandeja)
                     │ worker QThread (a janela não trava)
                     ▼
             jarvis/agent.py  Jarvis.handle(texto, cancelled)
                │  1. nlu.py      frase → intenção + campos (regras em português, sem modelo externo)
                │  2. tools.py    ferramenta real (dados locais, documentos, lembretes, memória)
                │  3. store.py    jarvis.db: conversa, memórias, operações, lembretes, contexto curto
                ▼
   academic.py ── companion_view (live.db em modo SOMENTE LEITURA) ── leituras salvas pelo Companion
   documents.py ── .docx (Office Open XML escrito direto) + .md, em Documentos\Campus AI\
```

- **`jarvis.db` é separado do `live.db`.** O Jarvis nunca escreve dados acadêmicos, e um teste garante isso.
- **Contexto curto:** "essa atividade" é a última atividade apontada por uma resposta. Uma lista numerada permite
  responder "2" ou "a segunda". Uma confirmação pendente (só para apagar memória) cai se o próximo pedido for outro.
- **Histórico de operações:** cada pedido vira uma operação com estado (ok, falhou, cancelado, recusado,
  aguardando confirmação). Uma operação que ficou "executando" num fechamento inesperado vira "falhou" na
  próxima abertura, nunca "ok".
- **Interromper:** o botão pede à ferramenta em execução que pare entre etapas. Nada parcial é entregue.

## O que funciona de verdade

| Pedido (exemplos) | O que acontece |
| --- | --- |
| "Jarvis, o que tenho para fazer hoje?" | Atrasadas, as que vencem hoje, os próximos 7 dias, pendentes sem prazo e tentativas em andamento, com a origem de cada dado e o aviso de cobertura parcial. Sem verificação, diz isso em vez de "nada pendente". |
| "Quais atividades vencem primeiro?" / "O que ainda não entreguei?" / "O que já entreguei?" | Listas a partir das leituras salvas. |
| "Prepare essa atividade" / "Prepare a atividade X" / "Prepare minha atividade de Modelagem UML" | Gera `Documentos\Campus AI\Atividades\<data>-preparacao-<atividade>.docx` e `.md`: dados com a origem, o que não se sabe (o enunciado não é lido), plano de trabalho com datas até o prazo, checklist e rascunho. Se houver várias atividades, pergunta qual. |
| "Organize minha semana" | Gera o plano da semana (`Documentos\Campus AI\Planos\`). |
| "Me avise amanhã às 18h sobre essa entrega" / "um dia antes do prazo" / "daqui a 2 horas" / "sexta às 9h" | Lembrete persistente. O aviso aparece na bandeja e na conversa enquanto o Campus AI estiver aberto ou em segundo plano. "Quais são meus lembretes?", "cancele o lembrete 2". |
| "Lembre que …" / "O que você sabe sobre mim?" / "Corrija a memória 2 para …" / "Apague a memória 2" | Memória local. Apagar pede confirmação. Senhas, tokens, cookies, chaves e números longos são recusados e omitidos do histórico. |
| "O que está conectado?" | Estado real das integrações e o que falta para cada uma. |
| "O que você fez?" | Últimas operações. |

**Recusados com explicação** (nunca simulados): enviar e-mail, submeter ou entregar no Moodle, iniciar ou
responder questionário, resumir matéria e pesquisar na internet (falta modelo de linguagem ou busca), abrir
projetos, PDF, planilha e apresentação (próximas etapas). Pedido não entendido: diz que não entendeu e mostra o que
sabe fazer.

## Limitações (honestas)

- **Interpretação por regras**, sem modelo de linguagem: entende os pedidos acima e variações próximas, não
  qualquer frase. Um modelo pode ser ligado depois em `intelligence.py`, com sua escolha de provedor e
  consentimento por pedido.
- **"Preparar" não resolve a atividade:** o Campus AI não lê o enunciado (só datas e estados). O material organiza
  o trabalho e indica o que falta; você cola o enunciado.
- **Os dados acadêmicos são os que o Companion salvou.** Com leituras anteriores à extensão 0.5.4, prazos e entregas
  aparecem como "não verificados".
- **O `.docx` é escrito sem biblioteca.** Foi validado como pacote e XML bem formado nos testes, mas não foi aberto
  no Microsoft Word neste ambiente.
- **Lembretes só disparam com o Campus AI em execução** (janela ou bandeja). Iniciar junto com o Windows já existe
  em Configurações (opt-in).

## Testes

`tests/test_jarvis_core.py` (sintéticos, temporários, relógio fixo):
- os exemplos do pedido chegam à ferramenta certa, e as expressões de tempo são entendidas;
- segredos nunca são guardados, e operações interrompidas por queda aparecem como falha;
- "hoje", próximos prazos e não entregues usam a leitura salva, e nunca se inventa sem dados;
- o "prepare" gera um `.docx` válido e um `.md`; com várias atividades, pergunta qual e aceita o número;
- arquivos nunca são sobrescritos; o plano da semana é gerado;
- lembretes pelo contexto, com vencimento e cancelamento;
- a memória pode ser guardada, listada, corrigida e apagada com confirmação;
- ações externas são recusadas e pedidos desconhecidos não são adivinhados;
- interromper não entrega nada, e o Jarvis nunca escreve no `live.db`;
- o painel responde em segundo plano, o histórico sobrevive a uma reabertura, links fora da pasta de entregas não
  abrem e cada lembrete aparece uma única vez.
