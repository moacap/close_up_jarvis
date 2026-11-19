# Documentação — Close-UP Jarvis

Guia operacional e técnico das funcionalidades configuradas no **Close-UP Jarvis** (identidade visual TargetQI / Close-UP).

---

## 1. Arquitetura e Serviços

- **Backend (API FastAPI):** executado via `uv run --extra desktop jarvis start --port 8180` (`http://localhost:8180`).
- **Frontend (React + Vite):** servido em desenvolvimento na porta `5199` (`http://localhost:5199`) com proxy para `http://127.0.0.1:8180`.
- **Extensão nativa Rust (`openjarvis_rust`):** compilada no `.venv` para habilitar o backend SQLite de memória (`GET /v1/memory/stats`).
- **Base de Conhecimento (`KnowledgeStore`):** armazena os registros indexados de todos os conectores na tabela `knowledge_chunks`, diferenciados pela coluna `source`.
- **Provedor de IA padrão:** configurado para roteamento multi/cloud com suporte a **Azure OpenAI** (`azure/gpt-5.4`, `azure/gpt-5-mini`), usado tanto no chat quanto nos agentes gerenciados.

---

## 2. Chat Principal

- **Consulta automática a Fontes Conectadas:** ao perguntar no chat sobre notícias RSS, contatos, calendário, notas ou mensagens, o servidor injeta automaticamente os registros indexados correspondentes do `KnowledgeStore` (`news_rss`, `apple_contacts`, `apple_calendar`, `apple_notes`, `imessage`), além de disponibilizar as ferramentas `knowledge_search` e `knowledge_sql`.
- **Execução de Scripts Customizados (`@script` e `--param`):**
  - Digite `@` no campo de mensagem para abrir o menu de autocompletar com os scripts disponíveis.
  - Digite `--` após o script para completar os parâmetros suportados.
- **Renderização de HTML:** respostas que retornam tabelas ou blocos HTML (`<table>`, `<div>`, etc., com ou sem bloco ```` ```html ````) são sanitizadas com `DOMPurify` e renderizadas diretamente como HTML estilizado na conversa.
- **Reexecutar Prompt:** cada mensagem enviada pelo usuário exibe o ícone de **Executar novamente** (`RotateCcw`) ao lado do balão, permitindo reenviar o mesmo comando com um clique.
- **Leitura em Voz Alta (TTS):** suporte a seleção de voz e idioma nas respostas do assistente.

---

## 3. Fontes de Dados (Conectores) e Webhooks

Na aba **Fontes de Dados** (`DataSourcesPage`), cada conector possui:
- **Ícone `(?)`:** exibe exemplos prontos de como consultar aquele conector no chat.
- **Botão `Edit` (quando aplicável):** permite atualizar URLs, tokens, tenant ou lista de feeds sem precisar desconectar.
- **Lista de Webhooks Ativos:** exibe os endpoints HTTP ativos diretamente no card do conector.

### Conectores principais

| Conector | `source` no `KnowledgeStore` | Configuração / Observações |
| --- | --- | --- |
| **Sales Farma Propagandistas** | `sales_farma` | Configurado via URL da API + Bearer token (`Edit` disponível no card). |
| **TagetIQ** | `coachingqi_visits` | Antigo *CoachingQI Visitas*; aceita sincronização por API e ingestão por webhook (`Edit` disponível no card). |
| **News / RSS** | `news_rss` | Configurado em `~/.openjarvis/connectors/news_rss.json`; edite os feeds pelo botão `Edit`. |
| **Apple Calendar / Contacts / Notes / iMessage** | `apple_calendar`, `apple_contacts`, `apple_notes`, `imessage` | Fontes locais macOS sincronizadas via `Sync Now` / `Re-sync`. |

### Webhooks e endpoints ativos

- **TagetIQ (`coachingqi_visits`):**
  - `POST /targetqi/visit-record`
  - `POST /api/v1/targetqi/visit-record`
  - `POST /v1/connectors/coachingqi_visits/ingest`
  - URL remota configurada no conector (exibida como `GET/POST`).
- **Sales Farma Propagandistas (`sales_farma`):**
  - Endpoint HTTP configurado no conector (exibido como `GET`).

---

## 4. Agentes Gerenciados (`AgentsPage`)

Os **Agentes** (como o **Close UP Assistant**, tipo `deep_research`) são assistentes persistentes que executam pesquisas multi-etapas com ferramentas (`think`, `knowledge_sql`, `knowledge_search`, `scan_chunks`) e mantêm histórico próprio.

### Abas do Agente

- **Cabeçalho:** exibe nome (editável inline clicando no ícone de lápis), status (`idle`, `running`, `error`), botão **Executar agora**, **Pausar** e excluir.
- **Interagir:** chat direto com o agente mostrando o **Rastro de atividade** (ferramentas chamadas) e o resultado final.
- **Visão Geral:** configura **Instruções do agente**, modelo, agendamento (`Manual`, intervalo ou `cron`), orçamento e métricas de tokens.
- **Fontes de Dados:** lista as fontes conectadas disponíveis para o agente.
- **Canais de Mensagens:** vincula o agente a canais externos (ex.: Sendblue/SMS, Slack).
- **Tarefas:** acompanha tarefas executadas e pendentes.
- **Memória:** exibe a memória resumida das execuções do agente.
- **Aprendizado:** permite clicar na badge **Habilitado / Desabilitado** para alternar `learning_enabled` e clicar em **Executar aprendizado** (`POST /v1/managed-agents/{id}/learning/run`), que analisa os *traces* do `TraceStore` e registra eventos `learning_cycle` em `agent_learning_log`.
- **Registros:** logs e *traces* de execução.

### Exemplos de uso no dia a dia

1. **Cruzamento de visitas e vendas:** pedir na aba **Interagir** do agente para comparar registros de `coachingqi_visits` (TagetIQ) com `sales_farma`.
2. **Briefing periódico agendado:** configurar agendamento diário na **Visão Geral** com instruções fixas para resumir visitas, agenda (`apple_calendar`) e notícias (`news_rss`).
3. **Agentes especializados:** criar agentes separados por função (ex.: auditoria TagetIQ, monitoramento Farma RSS, resumo executivo).

---

## 5. Aparência, Idioma e Créditos

- **Paleta visual TargetQI / Close-UP:** definida em `frontend/src/index.css` com destaque principal `#aa0012` (hover `#8a000f`), superfícies `#f8f8fa` / `#ffffff`, bordas `#dee0e5` e inputs/dropdowns padronizados com foco em `#aa0012`.
- **Configurações (`SettingsPage`):** seleção de tema (Claro, Escuro, Sistema), tamanho da fonte, idioma (`Português`, `English`, `Español`) e fuso horário.
- **Sobre:** *Close-UP* — *Engenheiro de Software: Moacir Alves Pereira.*

---

## 6. Comandos Úteis de Operação

```bash
# Iniciar / parar o servidor backend na porta 8180
uv run --extra desktop jarvis start --port 8180
uv run --extra desktop jarvis stop

# Verificar extensão Rust de memória
uv run python -c "from openjarvis._rust_bridge import RUST_AVAILABLE; print(RUST_AVAILABLE)"

# Verificar TypeScript do frontend
./frontend/node_modules/.bin/tsc -p frontend/tsconfig.json --noEmit
```
