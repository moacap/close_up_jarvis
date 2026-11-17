<div align="center">
  <img alt="OpenJarvis" src="assets/OpenJarvis_Horizontal_Logo.png" width="400">

  <p><i>IA pessoal, em dispositivos pessoais.</i></p>

  <p>
    <a href="https://arxiv.org/abs/2605.17172"><img src="https://img.shields.io/badge/arXiv-2605.17172-b31b1b.svg" alt="arXiv"></a>
    <a href="https://openjarvis.stanford.edu/"><img src="https://img.shields.io/badge/project-OpenJarvis-blue" alt="Project"></a>
    <a href="https://open-jarvis.github.io/OpenJarvis/"><img src="https://img.shields.io/badge/docs-mkdocs-blue" alt="Docs"></a>
    <img src="https://img.shields.io/badge/python-%3E%3D3.10-blue" alt="Python">
    <img src="https://img.shields.io/badge/license-Apache%202.0-green" alt="License">
    <a href="https://discord.gg/CMVBmDQ5Fj"><img src="https://img.shields.io/badge/discord-join-7289da?logo=discord&logoColor=white" alt="Discord"></a>
    <a href="https://x.com/OpenJarvisAI"><img src="https://img.shields.io/badge/X-@OpenJarvisAI-black?logo=x&logoColor=white" alt="X / Twitter"></a>
  </p>
</div>

---

<div align="center">
  <img alt="OpenJarvis demo reel" src="assets/openjarvis_demo_reel.webp" width="75%">
</div>

---

> **[Documentação](https://open-jarvis.github.io/OpenJarvis/)**
>
> **[Site do projeto](https://openjarvis.stanford.edu/)**
>
> **[Paper](https://arxiv.org/abs/2605.17172)**
>
> **[Leaderboard](https://open-jarvis.github.io/OpenJarvis/leaderboard/)**
>
> **[Roadmap](https://open-jarvis.github.io/OpenJarvis/development/roadmap/)**

## Por que o OpenJarvis?

Agentes de IA pessoal estão em explosão de popularidade, mas quase todos ainda roteiam a inteligência através de APIs na nuvem. Sua IA "pessoal" continua dependendo do servidor de outra pessoa. Ao mesmo tempo, nossa pesquisa [Intelligence Per Watt](https://www.intelligence-per-watt.ai/) mostrou que modelos de linguagem locais já lidam com 88,7% das consultas de chat e raciocínio de turno único, com a eficiência de inteligência melhorando 5,3× de 2023 a 2025. Os modelos e o hardware estão cada vez mais prontos. O que tem faltado é o stack de software para tornar a IA pessoal local-first viável na prática.

O OpenJarvis é esse stack. É um framework para IA pessoal local-first, construído em torno de três ideias centrais: primitivas compartilhadas para construir agentes on-device; avaliações que tratam energia, FLOPs, latência e custo em dólares como restrições de primeira classe junto com a acurácia; e um loop de aprendizado que melhora os modelos usando dados de traço locais. O objetivo é simples: tornar possível construir agentes de IA pessoal que rodem localmente por padrão, recorrendo à nuvem apenas quando realmente necessário. O OpenJarvis pretende ser tanto uma plataforma de pesquisa quanto uma base de produção para IA local, no espírito do PyTorch.

## Instalação

Escolha sua plataforma e rode um único comando. Cada instalador cuida do [uv](https://docs.astral.sh/uv/), do venv Python, do Ollama e de um modelo inicial — cerca de 3 minutos em banda larga.

| Plataforma | Comando único |
|---|---|
| **macOS · Linux · WSL2** | `curl -fsSL https://open-jarvis.github.io/OpenJarvis/install.sh \| bash` |
| **Windows nativo** | `irm https://open-jarvis.github.io/OpenJarvis/install.ps1 \| iex` |
| **Interface de Desktop** | Baixe o `.exe` / `.dmg` / `.deb` / `.rpm` / `.AppImage` na [última release](https://github.com/open-jarvis/OpenJarvis/releases/latest) |

Depois, `jarvis` para começar. A extensão Rust e os modelos maiores continuam sendo baixados em segundo plano; `jarvis doctor` mostra o status.

Notas específicas de plataforma (configuração do WSL2, serviço de tarefa agendada no Windows nativo, pré-requisitos do desktop, instalação manual / para contribuidores): veja os [docs de instalação](https://open-jarvis.github.io/OpenJarvis/getting-started/install/).

## Começo rápido

```bash
jarvis                          # começar a conversar (padrão: chat-simple)
jarvis gui                      # iniciar a interface gráfica no navegador
jarvis init --preset <nome> --force  # substituir a config por um preset inicial
```

`jarvis gui` inicia o servidor de API local e o frontend, depois abre a interface
de chat gráfica no seu navegador padrão. Requer Node.js 22+ e está disponível a
partir de um checkout do código-fonte; instaladores de desktop empacotados estão
disponíveis na [última release](https://github.com/open-jarvis/OpenJarvis/releases/latest).

> Prefixe `jarvis ...` com `uv run`, ou ative antes com `source .venv/bin/activate`.

| Preset | O que faz |
|---|---|
| `morning-digest-mac` / `morning-digest-linux` / `morning-digest-minimal` | Resumo diário falado a partir de email, calendário, saúde, notícias |
| `deep-research` | Pesquisa multi-hop em documentos indexados, com citações |
| `code-assistant` | Agente com execução de código, I/O de arquivos e acesso ao shell |
| `scheduled-monitor` | Agente com estado em uma agenda, com memória |
| `chat-simple` | Conversa leve, sem ferramentas |

Exemplo:

```bash
jarvis init --preset morning-digest-mac --force
jarvis connect gdrive          # um único OAuth cobre Gmail / Calendar / Tasks
jarvis digest --fresh          # gerar e tocar seu primeiro resumo
```

Aprofundamentos por preset: [morning digest](https://open-jarvis.github.io/OpenJarvis/user-guide/morning-digest/) · [deep research](https://open-jarvis.github.io/OpenJarvis/user-guide/deep-research/) · [code assistant](https://open-jarvis.github.io/OpenJarvis/user-guide/code-assistant/) · [scheduled monitor](https://open-jarvis.github.io/OpenJarvis/user-guide/scheduled-monitor/) · [chat simple](https://open-jarvis.github.io/OpenJarvis/user-guide/chat-simple/) · ou o [guia completo de início rápido](https://open-jarvis.github.io/OpenJarvis/getting-started/quickstart/).

### Skills (habilidades)

Skills ensinam os agentes a usar melhor as ferramentas e aprimorar seu raciocínio. Cada skill é uma ferramenta — os agentes a descobrem em um catálogo e a invocam sob demanda.

```bash
# Instalar skills de fontes públicas
jarvis skill install hermes:arxiv
jarvis skill sync hermes --category research

# Usar skills com qualquer agente
jarvis ask "Use a skill code-explainer para explicar esse código Python: for i in range(5): print(i*2)"

# Otimizar skills a partir do seu histórico de traços
jarvis optimize skills --policy dspy

# Avaliar o impacto
jarvis bench skills --max-samples 5 --seeds 42
```

Importe do [Hermes Agent](https://github.com/NousResearch/hermes-agent) (~150 skills), [OpenClaw](https://github.com/openclaw/skills) (~13.700 skills da comunidade), ou de qualquer repositório do GitHub. As skills seguem o padrão aberto [agentskills.io](https://agentskills.io/specification).

Veja o [Guia do Usuário de Skills](https://open-jarvis.github.io/OpenJarvis/user-guide/skills/) e o [Tutorial de Skills](https://open-jarvis.github.io/OpenJarvis/tutorials/skills-workflow/) para detalhes.

### Agentes embutidos

O OpenJarvis vem com oito agentes embutidos em três modos de execução (sob demanda, agendado, contínuo):

| Agente | Tipo | O que faz |
|-------|------|-------------|
| `morning_digest` | Agendado | Resumo diário de email, calendário, saúde, notícias — com áudio TTS |
| `deep_research` | Sob demanda | Pesquisa multi-hop com citações na web e em documentos locais |
| `monitor_operative` | Contínuo | Monitoramento de longo horizonte, com memória, compressão e recuperação |
| `orchestrator` | Sob demanda | Raciocínio multi-turno com seleção automática de ferramentas |
| `native_react` | Sob demanda | Agente em loop ReAct (Pensamento-Ação-Observação) |
| `operative` | Contínuo | Agente autônomo persistente com gerenciamento de estado |
| `native_openhands` | Sob demanda | CodeAct — gera e executa código Python |
| `simple` | Sob demanda | Chat de turno único, sem ferramentas |

Veja o [Guia do Usuário](https://open-jarvis.github.io/OpenJarvis/user-guide/morning-digest/) e os [Tutoriais](https://open-jarvis.github.io/OpenJarvis/tutorials/) para instruções de configuração detalhadas.

Documentação completa — incluindo deploy com Docker, engines na nuvem, configuração de ambiente de desenvolvimento e tutoriais — em **[open-jarvis.github.io/OpenJarvis](https://open-jarvis.github.io/OpenJarvis/)**.

## Comunidade

- **GitHub:** [github.com/open-jarvis/OpenJarvis](https://github.com/open-jarvis/OpenJarvis)
- **Discord:** [discord.gg/CMVBmDQ5Fj](https://discord.gg/CMVBmDQ5Fj)
- **X / Twitter:** [@OpenJarvisAI](https://x.com/OpenJarvisAI)
- **Docs:** [open-jarvis.github.io/OpenJarvis](https://open-jarvis.github.io/OpenJarvis/)

## Contribuindo

Contribuições são bem-vindas! Veja o [Guia de Contribuição](CONTRIBUTING.md) para incentivos, tipos de contribuição e o processo de PR.

Início rápido para contribuidores:

```bash
git clone https://github.com/open-jarvis/OpenJarvis.git
cd OpenJarvis
uv sync --extra dev
uv run pre-commit install
uv run pytest tests/ -v
```

Navegue pelo [Roadmap](https://open-jarvis.github.io/OpenJarvis/development/roadmap/) para ver áreas onde a ajuda é necessária. Comente **"take"** em qualquer issue para ser atribuído automaticamente.

## Sobre

O OpenJarvis faz parte do [Intelligence Per Watt](https://www.intelligence-per-watt.ai/), uma iniciativa de pesquisa que estuda a eficiência de inteligência de sistemas de IA. O projeto é desenvolvido na [Hazy Research](https://hazyresearch.stanford.edu/) e no [Scaling Intelligence Lab](https://scalingintelligence.stanford.edu/) da [Stanford SAIL](https://ai.stanford.edu/).

## Patrocinadores

<p>
  <a href="https://www.laude.org/">Laude Institute</a> &bull;
  <a href="https://datascience.stanford.edu/marlowe">Stanford Marlowe</a> &bull;
  <a href="https://cloud.google.com/">Google Cloud Platform</a> &bull;
  <a href="https://lambda.ai/">Lambda Labs</a> &bull;
  <a href="https://ollama.com/">Ollama</a> &bull;
  <a href="https://research.ibm.com/">IBM Research</a> &bull;
  <a href="https://hai.stanford.edu/">Stanford HAI</a>
</p>

## Citação
```bibtex
@misc{saadfalcon2026openjarvispersonalaipersonal,
      title={OpenJarvis: Personal AI, On Personal Devices}, 
      author={Jon Saad-Falcon and Avanika Narayan and Robby Manihani and Tanvir Bhathal and Herumb Shandilya and Hakki Orhun Akengin and Gabriel Bo and Andrew Park and Matthew Hart and Caia Costello and Chuan Li and Christopher Ré and Azalia Mirhoseini},
      year={2026},
      eprint={2605.17172},
      archivePrefix={arXiv},
      primaryClass={cs.LG},
      url={https://arxiv.org/abs/2605.17172}, 
}
```

## Licença

[Apache 2.0](LICENSE)
