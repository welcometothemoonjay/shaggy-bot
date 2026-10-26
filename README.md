# 👻 Shaggy Bot

<p align="center">
  <strong>Um bot de Discord onde o caos encontra a aventura.</strong>
  <br>
  RPGs, minijogos, economia virtual, progressão e eventos que podem mudar tudo.
</p>

<p align="center">
  <a href="https://github.com/welcometothemoonjay">GitHub do desenvolvedor</a>
</p>

---

## 🌌 Sobre o projeto

**Shaggy Bot** é um bot para Discord desenvolvido em Python com `discord.py`. Ele reúne
RPG, minijogos, economia virtual, progressão, conteúdo dos universos de **Segredo
Floresta Adentro (SFA)** e **Maré Morta**, moderação e ferramentas com IA.

O projeto está em desenvolvimento contínuo. Os sistemas são organizados em Cogs
carregados automaticamente por `main.py`; a economia central vive em
`cogs/XpAndCoins.py` e é reutilizada pelos demais módulos.

> **Estado deste README:** atualizado junto com a auditoria técnica de outubro de 2026.
> Os detalhes de arquitetura, riscos, dívida técnica e propostas estão em
> [`docs/PROJECT_AUDIT.md`](docs/PROJECT_AUDIT.md),
> [`docs/RUPTURA_ROADMAP.md`](docs/RUPTURA_ROADMAP.md) e
> [`docs/COGS_REVIEW.md`](docs/COGS_REVIEW.md).

## ✨ Funcionalidades

### 🪙 Economia e progressão

- XP por mensagem, com cooldown, bônus por texto/anexo/interação e inspiração aleatória.
- Bônus diário com sequência de dias no fuso de Brasília (UTC−3).
- Níveis com progressão configurável e **Abysmus** como moeda especial.
- Comandos de consulta (`/xp`, `/level`, `/coins`, `/ranking`).
- Comandos administrativos para ajustar XP e saldo com validação e transação.
- A economia é a **fonte oficial** do saldo: cassino, insígnias, Ruptura e demais
  sistemas usam a API de `XpAndCoins` em vez de escrever em `user_stats` por conta própria.

### 🌀 Ruptura Temporal

Roguelite de combate por turnos em que eras diferentes se misturam. O jogador escolhe
uma classe, monta uma build, enfrenta criaturas, Chefes e Deuses e tenta sobreviver o
máximo possível.

**Como jogar**

- `s!ruptura` (ou `s!rt`) inicia uma run com uma classe e uma passiva exclusivas.
- `s!market` abre o mercado; `s!market comprar CHAVE quantidade` compra um item.
- `s!inventario` mostra passivos, artefatos, consumíveis e estratégicos guardados.
- `/build` gasta Abysmus na especialização e nos nós da classe.
- Durante o combate, use **Atacar**, **Guardar**, **Concentrar**, a **Técnica** da classe,
  as habilidades ativas da build, a **Mochila** de combate e o botão de **Evento** quando
  uma escolha estiver disponível.
- Antes de um **Chefe** ou **Deus**, um **mercador** aparece com consumíveis, estratégicos,
  artefatos e aprimoramentos de forja.
- `s!ranking_ruptura`, `s!perfil_ruptura`, `s!cronica` e `s!bestiario` consultam o
  histórico e o catálogo.
- `s!duelo @membro` inicia um PvP da Ruptura; `s!duelorank` mostra o placar do servidor.

**Conteúdo atual**

- **10 classes**, **30 especializações** e **150 nós** de árvore.
- **12 relíquias**.
- **27 itens** no mercado: **9 passivos**, **8 consumíveis**, **5 artefatos** e
  **5 estratégicos**.
- **55 criaturas**: **39 normais**, **8 Chefes**, **6 mini-Chefes** e **2 Deuses**.
  A expansão mais recente adicionou **20 criaturas** (18 normais, 6 por era, e 2 sazonais).
- **32 habilidades de criatura**, incluindo as habilidades exclusivas das criaturas novas.
- **12 eventos**: 3 base, 6 sazonais e 3 dinâmicos com escolhas.

**Combate tático**

- Chefes e Deuses podem usar **Golpe Pesado** (telegrafado, +55% de dano se não for
  interrompido), **Postura Defensiva** (reduz o próximo golpe recebido pela metade) e
  **Contra-Golpe** (+30%).
- A intenção do inimigo aparece no embed. **Guardar** ou **atordoar** interrompe uma ação
  telegrafada e cancela o dano.
- Cada Chefe observa as últimas ações do jogador. Após **3 observações** com pelo menos
  **60%** do mesmo padrão, ele se adapta **uma única vez**.
- A memória é isolada por criatura, run e jogador; criaturas comuns mantêm o golpe básico.

**Mercador e forja**

- O mercador surge **depois da vitória**, quando o próximo encontro é **Chefe** ou
  **Deus** — nunca antes de mini-Chefe.
- A vitrine traz **2 consumíveis**, **2 estratégicos**, **até 1 artefato** ainda não
  equipado e **3 ofertas de forja**.
- Consumíveis e estratégicos vão para o inventário persistente e para a mochila da run.
  Artefatos valem **somente nesta run** e são aplicados na compra.
- A forja permite **2 aprimoramentos por run**, com teto de **+2 ataque**, **+2 defesa**
  ou **+20 vida máxima**. Cada uso custa +4 Abysmus em relação ao anterior.
- Toda compra é atômica: débito de Abysmus e entrega/efeito usam a mesma transação da
  economia.

**Regras dos itens**

- Passivos e artefatos são equipados automaticamente no início da run e consumidos do
  inventário, respeitando o limite por item.
- Consumíveis e estratégicos entram na mochila de combate da run; **usar um item gasta a
  ação do turno** e o item é consumido.
- Estratégicos só podem ser usados **1 vez por run**.
- O **PvP** usa apenas passivos e artefatos; consumíveis e estratégicos ficam fora do duelo.
- Uma run PvE e um duelo PvP são **mutuamente exclusivos** para o mesmo jogador. A guarda
  é compartilhada entre os dois Cogs, inclusive durante a escolha de classe.
- As janelas sazonais não alteram a dificuldade global: fora delas, o evento simplesmente
  não entra no sorteio.

**Validação local**

```bash
.venv/bin/python -m unittest test_ruptura -v
```

A suíte cobre catálogo, combate tático, preparação/interrupção/resolução de ações,
expiração de efeitos, adaptação e isolamento de Chefes, mercador, forja, compras atômicas,
concorrência, inventário SQLite temporário, PvP, guarda de estado PvE/PvP e embeds. Os
testes usam um banco temporário e não tocam em `data/shaggy.db`.

### 🎰 Salão da Ruptura — cassino

Cassino temático integrado ao Abysmus, com NPCs, conquistas e estatísticas.

- **Roleta**, **moeda**, **dados** (alto/baixo, face 6 e somas), **blackjack**,
  **caça-níquel temporal** e **Travessia das Fendas**.
- Saldo, partida e estatísticas são gravados na mesma transação.
- Partidas interativas abertas são estornadas se o bot reiniciar.
- RTP documentado no código; os valores foram conferidos por execução direta das funções
  durante a auditoria, não por uma suíte automatizada de cassino (que não existe no
  repositório).

### 🌲 Segredo Floresta Adentro — SFA

Universo de fantasia sombria e horror cósmico que inspira parte do conteúdo.

- Livros, cosmologia, facções, glossário, lacunas e perguntas de lore (`/lore ...`).
- Duelo de cartas com `/sfa duelo`.
- Bestiário, crônicas e conteúdo gerado por IA na Ruptura.

### 🎲 Minijogos e escolhas aleatórias

- 10 minijogos em slash commands: roleta-russa, moeda, dado, pedra-papel-tesoura,
  par ou ímpar, duelos numérico e elemental, adivinhação, sorte ou caos e ideias de RPG.
- Comandos sociais e de sorte em `cogs/social.py` e `cogs/mystic.py`.
- Missões diárias com progresso por mensagens, anexos, respostas, menções, reações e uso
  de comandos.

### 🐾 Pets, insígnias e moderação

- Sistema de pets com adoção, cuidados, evolução, habilidades, ranking e migração do
  protótipo antigo.
- Loja de insígnias com cargos do Discord, histórico e fila persistente de entrega.
- Moderação de membros, cargos, canais, anúncios e ferramentas de desenvolvedor.

### 🤖 IA, notícias e utilidades

- `s!ia` conversa com o Shaggy e `s!ia_limpar` reinicia o histórico.
- `/noticia`, `/buscar_noticia`, `/resumir`, `/explique`, `/github` e `/debug` usam RSS,
  GitHub e OpenRouter quando configurados.
- `/help`, `/ping`, `/status`, `/servidor`, `/usuario`, `/avatar` e ferramentas de canal.

## 🧩 Arquitetura do projeto

### Estrutura real

```text
shaggy-bot/
├── main.py                  # Bot, carregamento automático dos Cogs e sincronização
├── requirements.txt         # Dependências de execução
├── test_ruptura.py          # Única suíte automatizada do repositório (70 testes)
├── cogs/
│   ├── XpAndCoins.py        # Economia central: XP, níveis, Abysmus, transações
│   ├── ruptura.py           # Motor da Ruptura: catálogo, combate, build, mercado, UI
│   ├── ruptura_extras.py    # Ranking, perfil, crônica, bestiário e IA da Ruptura
│   ├── ruptura_pvp.py       # Duelos PvP da Ruptura
│   ├── cassino.py           # Salão da Ruptura
│   ├── badges.py            # Insígnias, cargos, ledger e fila persistente
│   ├── missoes.py           # Missões diárias, portais e listeners
│   ├── pet.py               # Pets
│   ├── ranking.py           # Ranking de XP/níveis
│   ├── games.py             # Minijogos
│   ├── mystic.py            # Tarô, runas, astrologia e afins
│   ├── social.py            # Comandos sociais
│   ├── lore.py              # Lore de SFA e Maré Morta
│   ├── noticias_ia.py       # Notícias/RSS e ferramentas com IA
│   ├── ia.py                # Conversa com IA
│   ├── GameSFA.py           # Duelo de cartas de SFA
│   ├── ultility.py          # Ajuda, status, moderação, cargos e canais
│   └── __init__.py
├── data/                    # Bancos SQLite locais (ignorados pelo Git)
├── docs/                    # Auditoria técnica e roadmap
├── assets/
├── CHANGELOG.md
└── .env                     # Segredos locais (ignorado pelo Git)
```

### Carregamento e integração

1. `main.py` carrega `Shaggy(commands.Bot)` com prefixo `s!` e intents padrão +
   `message_content`.
2. `setup_hook()` percorre `cogs/*.py` em ordem alfabética, ignora arquivos que começam
   com `_` e carrega cada módulo com `load_extension`.
3. Os comandos slash são sincronizados globalmente e copiados para cada servidor no
   `on_ready`.
4. `on_message` encaminha mensagens para `XpAndCoins.processar_mensagem()` e depois chama
   `process_commands`, preservando os comandos de prefixo.
5. Cogs que precisam de economia ou IA obtêm a instância via `bot.get_cog(...)`; não há
   injeção de dependência formal nem contêiner de serviços.

### Camadas e responsabilidades

- **Apresentação:** Cogs, embeds, botões, selects, modais e grupos de comandos.
- **Regras:** funções puras em `ruptura.py` (catálogo, efeitos, combate, eventos, itens)
  e classes de domínio nos demais Cogs.
- **Persistência:** SQLite local, com transações explícitas em `XpAndCoins` e repositórios
  próprios na Ruptura, cassino, insígnias, pets, missões e notícias.
- **Integrações externas:** Discord, OpenRouter (SDK `openai`), feeds RSS e API do GitHub.

### Tecnologias

- **Python 3.14** no ambiente local auditado (o projeto não fixa versão mínima).
- **discord.py 2.x** — bot, comandos híbridos/slash, views e tarefas.
- **SQLite** — persistência local.
- **openai** — cliente compatível com OpenRouter.
- **aiohttp** e **feedparser** — notícias e feeds.
- **python-dotenv** — carregamento do `.env`.
- **psutil** — opcional; melhora `/status` quando instalado.
- **Git/GitHub** — versionamento.

## 🕹️ Comandos

### Economia, ranking e missões

| Comando | Tipo | Descrição |
| --- | --- | --- |
| `/xp` | Slash | Consulta XP e nível. |
| `/level` | Slash | Mostra o nível e a progressão. |
| `/coins` | Slash | Consulta o saldo de Abysmus. |
| `/ranking` | Slash | Ranking de XP do servidor. |
| `/xp_gerenciar` | Slash | Administra XP de um membro. |
| `/coin_gerenciar` | Slash | Administra o saldo de um membro. |
| `/missoes` | Slash | Missões diárias e Portais de Distorção. |

### Ruptura Temporal

| Comando | Tipo | Descrição |
| --- | --- | --- |
| `s!ruptura` / `s!rt` | Prefixo | Inicia uma run. |
| `s!inventario` / `s!inv` | Prefixo | Inventário da Ruptura. |
| `s!market` / `s!loja` | Prefixo | Mercado; use `s!market comprar CHAVE QTD`. |
| `/build` | Slash | Especialização e árvore da classe. |
| `/build_resetar` | Slash | Refaz pontos de uma classe mediante taxa. |
| `s!ranking_ruptura` | Prefixo | Ranking de runs. |
| `s!perfil_ruptura` | Prefixo | Perfil do jogador na Ruptura. |
| `s!cronica` | Prefixo | Crônica gerada por IA. |
| `s!bestiario` | Prefixo | Consulta o bestiário. |
| `s!conselho` | Prefixo | Conselho gerado por IA. |
| `s!profecia` | Prefixo | Profecia gerada por IA. |
| `s!duelo` / `s!pvp` | Prefixo | Duelo PvP. |
| `s!duelorank` | Prefixo | Placar de duelos do servidor. |

### Cassino, jogos e SFA

| Comando | Tipo | Descrição |
| --- | --- | --- |
| `/cassino` / `s!cassino` | Slash/Prefixo | Abre o Salão da Ruptura. |
| `/cassino_stats` | Slash | Estatísticas do jogador. |
| `/cassino_titulos` | Slash | Conquistas do cassino. |
| `/roleta_russa`, `/moeda`, `/dado`, `/ideia_rpg` | Slash | Minijogos. |
| `/pedra_papel_tesoura`, `/par_ou_impar`, `/duelo_numerico` | Slash | Minijogos. |
| `/duelo_elemental`, `/adivinhar_escolha`, `/sorte_ou_caos` | Slash | Minijogos. |
| `/sfa duelo` | Slash | Duelo de cartas de SFA. |

### Lore, misticismo e social

| Comandos | Tipo | Descrição |
| --- | --- | --- |
| `/lore livros`, `cosmologia`, `alinhamento`, `faccao` | Slash | Conteúdo de lore. |
| `/lore olho`, `sistema`, `ruptura`, `glossario` | Slash | Conteúdo de lore. |
| `/lore lacunas`, `perguntar` | Slash | Lacunas e perguntas (IA). |
| `/bola8`, `/tarot`, `/runas`, `/destino`, `/horoscopo` | Slash | Misticismo. |
| `/numerologia`, `/lua`, `/aura`, `/compatibilidade` | Slash | Misticismo. |
| `/sonho`, `/pressagio`, `/ritual`, `/amuleto` | Slash | Misticismo. |
| `/ola`, `/abracar`, `/beijar`, `/elogiar` | Slash | Social. |
| `/shippar`, `/escolher`, `/reagir`, `/moletom` | Slash | Social. |

### Pets, insígnias, IA e moderação

| Comando | Tipo | Descrição |
| --- | --- | --- |
| `s!pet ...` | Prefixo | `adotar`, `trocar`, `embora`, `santuario`, `status`, `alimentar`, `brincar`, `carinho`, `habilidade`, `diario`, `ver`, `ranking`, `catalogo`, `renomear`, `ajuda`. |
| `/insignias`, `/minhas_insignias`, `/insignia_detalhes` | Slash | Loja e consulta de insígnias. |
| `/insignia_comprar`, `/insignia_auditoria` | Slash | Compra e auditoria. |
| `/insignia_criar`, `/insignia_editar`, `/insignia_ativar` | Slash | Administração do catálogo. |
| `/insignia_desativar`, `/insignia_configurar_cargo` | Slash | Administração do catálogo. |
| `/insignia_conceder`, `/insignia_revogar`, `/insignia_sincronizar` | Slash | Gestão de cargos. |
| `s!ia`, `s!ia_limpar` | Prefixo | Conversa com IA e reset do histórico. |
| `/noticia`, `/buscar_noticia`, `/resumir` | Slash | Notícias e resumos. |
| `/explique`, `/github`, `/debug` | Slash | Ferramentas com IA. |
| `s!noticia` | Prefixo | Notícias por prefixo. |
| `/help`, `/ping`, `/status`, `/servidor`, `/usuario`, `/avatar` | Slash | Utilidades. |
| `/limpar`, `/slowmode`, `/trancar`, `/destrancar`, `/anunciar` | Slash | Canais. |
| `/membro ...` | Slash | `expulsar`, `banir`, `desbanir`, `silenciar`, `liberar`, `apelido`, `avisar`, `avisos`, `limpar_avisos`. |
| `/cargo ...` | Slash | `dar`, `remover`, `criar`, `editar`, `deletar`, `lista`, `info`. |
| `/dev ...` | Slash | `recarregar`, `sincronizar` (restrito). |

## 🗄️ Bancos de dados

Os bancos ficam em `data/` e são ignorados pelo Git. Não há migrações automáticas
versionadas; cada Cog garante as próprias tabelas com `CREATE TABLE IF NOT EXISTS`.

### `data/shaggy.db`

Banco central da economia e da maior parte dos sistemas:

- `user_stats` — XP, nível, Abysmus, cooldown e bônus diário.
- `badge_defs`, `badge_owned`, `badge_ledger`, `badge_role_queue` — insígnias.
- `cassino_partidas`, `cassino_stats`, `cassino_conquistas` — cassino.
- `missoes_progresso`, `missoes_bonus`, `portais` — missões.
- `pet_collection` — pets (escopo por `user_id`).
- `rt_build_state`, `rt_build_nodes`, `rt_build_credit`, `rt_build_log` — builds.
- `ruptura_inventario`, `ruptura_runs`, `ruptura_abates`, `ruptura_pvp` — Ruptura.
- `util_warnings` — avisos de moderação.
- `virtual_pets` — tabela legada, usada apenas pela migração de `pet.py`.

### `data/noticias.db`

- `noticias_cache` — cache ativo de notícias.
- `noticias` e `rss_fontes` — tabelas legadas, preservadas mas sem uso no código atual.

### `data/cassino.db`

- `cassino_historico` e `cassino_stats` — arquivo legado, **sem referências no código
  atual**. O cassino atual grava em `data/shaggy.db`.

## ⚙️ Configuração

Crie um `.env` na raiz. O `main.py` carrega o arquivo com `python-dotenv`.

| Variável | Obrigatória | Uso |
| --- | --- | --- |
| `token_shaggy` | Sim | Token do bot Discord. |
| `OPENROUTER_API_KEY` | Não | Habilita IA, notícias, crônicas e conselhos. |
| `OPENROUTER_MODEL` | Não | Modelo padrão de conversa. |
| `OPENROUTER_NEWS_MODEL` | Não | Modelo para notícias. |
| `OPENROUTER_CODE_MODEL` | Não | Modelo para código/ferramentas. |
| `OPENROUTER_VISION_MODEL` | Não | Modelo para imagens. |
| `GITHUB_TOKEN` | Não | Aumenta o limite da API do GitHub. |

> O `.env` local também contém uma variável `gpt_api_token`, que **não é referenciada
> pelo código atual**. Não reutilize esse nome sem antes conectar o código a ele.

**Segurança:** nunca publique o `.env`, tokens, chaves ou bancos de dados. O `.gitignore`
já cobre `.env`, `.venv/`, `__pycache__/` e `data/*.db`.

## 🚀 Instalação e execução

### 1. Pré-requisitos

- Python 3.10+ (o ambiente auditado usa 3.14).
- Git.
- Um aplicativo/bot no Discord com o token correspondente.

### 2. Clone e crie o ambiente

```bash
git clone https://github.com/welcometothemoonjay/shaggy-bot.git
cd shaggy-bot
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Instale as dependências

```bash
pip install -r requirements.txt
```

`requirements.txt` contém `discord.py`, `python-dotenv`, `openai`, `aiohttp` e
`feedparser`. `psutil` é opcional e melhora apenas o `/status`.

### 4. Configure o `.env`

```env
token_shaggy=SEU_TOKEN_AQUI
# Opcional:
# OPENROUTER_API_KEY=SUA_CHAVE_AQUI
```

### 5. Execute

```bash
python3 main.py
```

O bot carrega todos os arquivos de `cogs/` e sincroniza os comandos slash. Se um Cog
falhar no carregamento, o erro é registrado no terminal e o processo é encerrado.

## 🧪 Testes e validação

A única suíte automatizada do repositório é `test_ruptura.py`:

```bash
.venv/bin/python -m unittest test_ruptura -v
# ou
.venv/bin/python -m unittest discover -v
```

Resultado da auditoria e da correção BUG-01: **70 testes, todos aprovados**. A suíte não
precisa de Discord conectado e usa banco temporário.

Validações complementares executadas na auditoria:

```bash
.venv/bin/python -m py_compile main.py cogs/*.py test_ruptura.py
```

- Compilação de todos os módulos: OK.
- Importação dos 17 módulos de `cogs/`: OK.
- `validar_catalogos()`, `validar_arvores()` e `validar_eventos()`: sem erros.
- RTP do cassino conferido por execução direta das funções (não por testes automatizados).

**Limitação:** não há testes automatizados para cassino, economia, insígnias, pets,
missões, notícias, IA, moderação ou PvP. Também não é possível validar interações reais
com o Discord neste ambiente.

## 🔧 Desenvolvimento

### Convenções

1. Identifique o Cog responsável e suas dependências (`XpAndCoins`, `IA`, `RupturaTemporal`).
2. Use as APIs existentes de economia (`transacao`, `obter_saldo_tx`, `alterar_coins_tx`,
   `conceder_recompensas`) em vez de escrever em `user_stats`.
3. Execute operações SQLite síncronas fora do event loop com `asyncio.to_thread` em novos
   códigos.
4. Preserve compatibilidade de comandos, tabelas e dados existentes.
5. Adicione testes para regras puras e para fluxos de persistência com banco temporário.
6. Atualize `CHANGELOG.md` e, quando a mudança for estrutural, os documentos em `docs/`.

### Versionamento

```bash
git status
git diff
git add .
git commit -m "Descrição da mudança"
git push
```

Não commite `.env`, bancos locais ou credenciais.

## 🛣️ Direções futuras

As propostas detalhadas estão em [`docs/RUPTURA_ROADMAP.md`](docs/RUPTURA_ROADMAP.md).
Em resumo:

- [ ] Corrigir inconsistências de integração e ciclo de vida da Ruptura.
- [ ] Ampliar a cobertura de testes para os demais Cogs.
- [ ] Melhorar a qualidade e a legibilidade do combate.
- [ ] Evoluir classes, builds, Chefes adaptativos, itens e economia.
- [ ] Criar mais criaturas, eventos e formas de progressão/repetibilidade.
- [ ] Melhorar a interface e a acessibilidade dos embeds e botões.
- [ ] Refatorar os módulos maiores sem alterar o comportamento observável.

Esta lista representa possibilidades de desenvolvimento, não uma promessa de
funcionalidades já disponíveis.

## 🔐 Segurança e dados

- Não compartilhe tokens do Discord nem chaves de API.
- Não envie credenciais para o GitHub.
- Proteja os bancos de dados com informações dos jogadores.
- Faça backups antes de mudanças importantes de esquema.
- Valide entradas e operações econômicas.
- Teste alterações antes de executá-las em um servidor ativo.
- A auditoria não encontrou uso de `eval`, `exec`, `subprocess` ou `pickle`; as duas
  interpolações SQL dinâmicas em `ruptura_extras.py` usam uma lista fixa de ordenações.

## 📚 Documentação técnica

- [`docs/PROJECT_AUDIT.md`](docs/PROJECT_AUDIT.md) — auditoria completa, evidências,
  problemas comprovados, dívida técnica e limitações.
- [`docs/RUPTURA_ROADMAP.md`](docs/RUPTURA_ROADMAP.md) — propostas priorizadas para a
  Ruptura Temporal.
- [`docs/COGS_REVIEW.md`](docs/COGS_REVIEW.md) — avaliação individual e comparativa dos
  Cogs, com recomendação de manter, melhorar, refatorar, remover ou substituir.

## 👨‍💻 Desenvolvedor

**Jay Moon**

GitHub: [@welcometothemoonjay](https://github.com/welcometothemoonjay)

## 📜 Licença

Código pode ser redistribuído ou utilizado livremente.

---

<p align="center">
  <strong>Shaggy Bot — entre por diversão, fique pela aventura.</strong>
  <br>
  <em>O próximo acontecimento pode estar fora da sua linha temporal.</em>
</p>
