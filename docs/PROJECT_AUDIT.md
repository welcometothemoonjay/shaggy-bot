# Auditoria Técnica — Shaggy Bot

**Data:** 26 de outubro de 2026
**Commit de referência:** `27c2c90` (`Paths 1.1v(Bug & resolve)`), que contém BUG-01;
as alterações de BUG-05 ainda não estão commitadas
**Ambiente:** Linux, Python 3.14, `discord.py` 2.7.1, `openai` 3.37.0, SQLite local
**Escopo:** arquitetura, Cogs, persistência, integrações, Ruptura Temporal, testes e
documentação. A auditoria original **não** alterou balanceamento, esquema do banco ou
código de produção. As atualizações posteriores implementaram apenas BUG-01 (integração
PvE/PvP) e BUG-05 (liberação de estado em falha de interação), sem mudar dados ou
balanceamento.

> **Atualização de 26/10/2026:** o problema P-02 foi corrigido com uma guarda
> compartilhada entre PvE e PvP. A validação da concorrência confirmou que a reserva de
> estado é atômica no event loop. Na mesma rodada, o problema P-11 (vazamento de
> `ocupados` em falha de interação no PvP) foi corrigido. A suíte passou de 66 para 74
> testes; a Expansão 3 depois a levou a 89. Os demais achados continuam como estavam na
> auditoria original.

---

## 1. Resumo executivo

O projeto está funcional e tem uma base acima da média para um bot de Discord: economia
centralizada, transações SQLite explícitas nos fluxos de dinheiro, boa separação entre
regras e interface na Ruptura, validadores de catálogo e uma suíte automatizada real
(89 testes) para o sistema mais complexo.

Os principais achados são de **integração e ciclo de vida**, não de “jogo quebrado”:

1. `main.py` executa `bot.run(TOKEN)` **fora** do bloco `if __name__ == "__main__"`.
   Isso torna o módulo impossível de importar com segurança e ignora o guard de token.
2. **Resolvido em BUG-01:** a proteção contra sobreposição de estados era assimétrica; o
   PvP consultava as runs de PvE, mas a Ruptura PvE não consultava os duelos PvP. Agora
   ambos usam `estado_jogador_ocupado()`.
3. `RupturaTemporal.cog_unload()` descarta runs ativas sem finalização, recompensa ou
   devolução de itens consumidos. O timeout normal finaliza corretamente; o descarregamento
   não.
4. O modelo de pets é global por `user_id`, sem `guild_id`; o ranking consulta o top 100
   global e só depois filtra membros do servidor, o que pode produzir rankings locais
   incompletos.
5. `XpAndCoins.processar_mensagem()` executa SQLite síncrono no event loop a cada mensagem
   que passa pelo cooldown.
6. A documentação do cassino afirma que o RTP é “calculado por enumeração nos testes”, mas
   **não existe suíte de cassino** no repositório. Os valores foram conferidos nesta
   auditoria por execução direta, não por teste automatizado.

Nenhum segredo foi encontrado em código ou documentação. Não foram encontrados usos de
`eval`, `exec`, `subprocess` ou `pickle`. As duas interpolações SQL dinâmicas de
`ruptura_extras.py` usam uma lista fixa de ordenações, não entrada do usuário.

**Conclusão:** o projeto pode continuar evoluindo com segurança se as correções de
integração/ciclo de vida e a cobertura de testes forem tratadas antes de novas expansões
grandes de conteúdo.

---

## 2. Método e evidências

Foram executadas apenas operações de leitura, compilação e testes na auditoria original.
A implementação posterior de BUG-01 e BUG-05 alterou código de produção e ampliou a
suíte; as validações dessas alterações estão registradas no fim desta seção e na seção 11.

| Verificação | Comando | Resultado |
| --- | --- | --- |
| Compilação | `.venv/bin/python -m py_compile main.py cogs/*.py test_ruptura.py` | OK |
| Importação dos Cogs | importação programática dos 17 módulos | 17/17 OK |
| Suíte principal | `.venv/bin/python -m unittest test_ruptura -v` | 89 testes, OK |
| Descoberta | `.venv/bin/python -m unittest discover -v` | 89 testes, OK |
| Corrida PvE/PvP | duas `iniciar_run()` com `asyncio.gather` | 1 run criada, 1 bloqueada |
| Catálogo | `validar_catalogos()` | sem erro |
| Árvores | `validar_arvores()` | `[]` |
| Eventos | `validar_eventos()` | `[]` |
| RTP | execução de `rtp_roleta`, `rtp_moeda`, `rtp_dados`, `rtp_slots`, travessia | valores abaixo |
| Bancos | conexões `mode=ro` em `data/*.db` | tabelas e contagens levantadas |
| Segurança estática | busca por `eval`, `exec`, `subprocess`, `pickle`, SQL com f-string | sem achados críticos |
| Git | `git status`, `git log` | árvore limpa antes da auditoria; HEAD `9cb5c19` |

Não foi lido o conteúdo de valores do `.env`; apenas os nomes das variáveis foram
inspecionados para conferir a configuração documentada.

---

## 3. Estrutura e arquitetura

### 3.1 Tamanho real

| Arquivo | Linhas |
| --- | ---: |
| `cogs/ruptura.py` | 9.551 |
| `cogs/noticias_ia.py` | 3.101 |
| `cogs/cassino.py` | 2.405 |
| `cogs/badges.py` | 2.313 |
| `cogs/ultility.py` | 2.203 |
| `cogs/pet.py` | 1.525 |
| `cogs/ruptura_pvp.py` | 1.353 |
| `cogs/games.py` | 1.173 |
| `test_ruptura.py` | 2.021 |
| `cogs/XpAndCoins.py` | 1.088 |
| `cogs/ruptura_extras.py` | 1.055 |
| `cogs/mystic.py` | 1.038 |
| `cogs/GameSFA.py` | 962 |
| `cogs/lore.py` | 863 |
| `cogs/ia.py` | 851 |
| `cogs/missoes.py` | 663 |
| `cogs/ranking.py` | 245 |
| `cogs/social.py` | 222 |
| `main.py` | 136 |

Total aproximado: **32.768 linhas** em 20 arquivos Python (incluindo `cogs/__init__.py`,
vazio).

### 3.2 Carregamento

`main.py`:

- Cria `Shaggy(commands.Bot)` com prefixo `s!`, `Intents.default()` e
  `message_content=True`.
- Em `setup_hook()`, percorre `sorted(cogs/*.py)`, ignora nomes iniciados por `_` e chama
  `load_extension` para cada arquivo.
- Se um Cog falhar, registra a exceção e **relança**, encerrando a inicialização.
- Sincroniza a árvore globalmente e, no `on_ready`, copia os comandos globais para cada
  guild e sincroniza localmente.
- `on_message` chama `XpAndCoins.processar_mensagem()` e depois `process_commands()`,
  mantendo prefixo e slash no mesmo bot.

### 3.3 Dependências entre Cogs

```text
XpAndCoins (economia central)
├── badges          → transação, saldo, débito, ledger e fila de cargos
├── cassino         → transação, saldo, débito, prêmio e recuperação de partidas
├── missoes         → transação, XP, Abysmus e tabelas próprias
├── ranking         → consulta de XP/níveis
├── games           → recompensas de minijogos
├── ia              → recompensa por conversa
├── ruptura         → award_rewards() → conceder_recompensas()
├── ruptura_pvp     → award_rewards() quando configurado
└── ruptura_extras  → ranking próprio em SQLite + PonteIA

IA (OpenRouter)
├── lore            → /lore perguntar
├── noticias_ia     → notícias, resumos, explicações e GitHub
└── ruptura_extras  → crônica, conselho e profecia

RupturaTemporal
├── ruptura_pvp     → classes, RunState, EnemyState, itens, build
└── ruptura_extras  → evento "on_ruptura_run_finalizada"
```

O acoplamento é feito por `bot.get_cog("Nome")` e por imports diretos de
`cogs.ruptura` em `ruptura_pvp.py` e `ruptura_extras.py`. Não há interface formal,
protocolo ou registro tipado de serviços.

### 3.4 Persistência

Há **13 chamadas diretas a `sqlite3.connect`** distribuídas em 7 arquivos:

| Arquivo | Conexões diretas | Uso |
| --- | ---: | --- |
| `cogs/ruptura.py` | 4 | inventário e repositórios de build/mercado |
| `cogs/ruptura_pvp.py` | 3 | placar de duelos |
| `cogs/ultility.py` | 2 | avisos de moderação |
| `cogs/XpAndCoins.py` | 1 | conexão central e transações da economia |
| `cogs/ruptura_extras.py` | 1 | ranking de runs |
| `cogs/pet.py` | 1 | banco próprio |
| `cogs/noticias_ia.py` | 1 | banco próprio |

Além dessas, `badges`, `cassino` e `missoes` acessam SQLite **através** da API de
`XpAndCoins` (`transacao()`), sem abrir conexão própria.

Apenas `pet.py` define `PRAGMA busy_timeout = 15000`. Não há `journal_mode=WAL` nem
política global de `busy_timeout`. O `timeout` das conexões varia entre 5 e 15 segundos.

---

## 4. Catálogo atual da Ruptura

Contagens obtidas por importação do módulo, não por estimativa:

| Elemento | Quantidade |
| --- | ---: |
| Classes | 10 |
| Especializações | 30 |
| Nós de árvore | 150 |
| Relíquias | 12 |
| Itens | 27 |
| — passivos | 9 |
| — consumíveis | 8 |
| — artefatos | 5 |
| — estratégicos | 5 |
| Criaturas | 91 |
| — normais | 39 |
| — Chefes | 26 |
| — mini-Chefes | 24 |
| — Deuses | 2 |
| Eventos | 12 |
| Habilidades de criatura | 68 |

Duas expansões somam 56 criaturas: 20 normais (18 por era + 2 sazonais) e 36
mini-Chefes/Chefes (18 de cada categoria, 6 por era). A Expansão 3 adicionou 36
criaturas e 36 habilidades exclusivas, distribuídas em `Da'kor` (níveis 3, 5 e 10),
`Era a Vapor` (6, 10, 15 e 20) e `Futuro Distorcido` (9, 15, 20 e 25). Nenhuma tabela,
fórmula, relíquia, item ou evento mudou. Os validadores de catálogo, árvore e evento não
acusaram problemas.

---

## 5. Avaliação individual dos Cogs

A avaliação detalhada e comparativa está em [`COGS_REVIEW.md`](COGS_REVIEW.md). Resumo:

| Cog | Papel | Persistência | Estado | Recomendação |
| --- | --- | --- | --- | --- |
| `XpAndCoins` | Economia central | `user_stats` | Maduro, transacional | **Manter**; proteger como dependência crítica |
| `ruptura` | Motor do roguelite | inventário, build, mercado | Funcional, muito grande | **Manter e refatorar** em módulos internos |
| `ruptura_pvp` | Duelos | `ruptura_pvp` | Funcional, herda `EnemyState` | **Manter**; corrigir integração de estado |
| `ruptura_extras` | Ranking/perfil/IA | `ruptura_runs`, `ruptura_abates` | Funcional | **Manter e separar** repositório de IA |
| `badges` | Insígnias e cargos | 4 tabelas + fila | Maduro | **Manter**; dividir store/UI |
| `cassino` | Cassino | 3 tabelas | Funcional | **Manter**; criar testes e dividir motor/UI |
| `missoes` | Missões diárias | 3 tabelas | Funcional | **Manter**; ampliar testes |
| `pet` | Pets | `pet_collection` | Funcional, escopo global | **Manter e refatorar** escopo por guild |
| `ranking` | Ranking de XP | via XpAndCoins | Simples e correto | **Manter** |
| `games` | Minijogos | via XpAndCoins | Simples | **Manter**; testar recompensas |
| `mystic` | Misticismo | nenhuma | Conteúdo efêmero | **Manter** |
| `social` | Comandos sociais | nenhuma | Conteúdo efêmero | **Manter** |
| `lore` | Lore e /perguntar | nenhuma | Funcional | **Manter** |
| `noticias_ia` | Notícias + ferramentas | `noticias_cache` | Dois Cogs no mesmo arquivo | **Manter e dividir** |
| `ia` | Conversa com IA | memória em processo | Funcional | **Manter** |
| `GameSFA` | Duelo de cartas | nenhuma | Funcional, isolado | **Manter**; padronizar logging |
| `ultility` | Utilidades/moderação | `util_warnings` | Funcional | **Manter**; dividir grupos |

**Notas individuais**

- **`XpAndCoins`** — núcleo estável e transacional; principal risco é o SQLite síncrono no
  caminho de XP e a ausência de reconciliação de recompensas.
- **`ruptura`** — sistema mais rico e mais crítico; funciona, mas concentra motor, dados e
  UI em 9.551 linhas e descarta runs no unload.
- **`ruptura_pvp`** — reutiliza bem o motor; falha na reciprocidade da guarda de estado com
  o PvE.
- **`ruptura_extras`** — ranking e IA funcionam; falta separar repositório, integração e
  apresentação.
- **`badges`** — fluxo de compra e fila de cargos é maduro; precisa de testes e de divisão
  store/UI.
- **`cassino`** — transações e recuperação são boas; a documentação promete testes
  inexistentes e o arquivo é grande.
- **`missoes`** — coeso e determinístico; os listeners merecem teste de custo e progresso.
- **`pet`** — conteúdo rico, mas o modelo global por `user_id` distorce ranking e contexto
  entre guilds.
- **`ranking`** — simples, coeso e correto; baixo risco.
- **`games`** — minijogos diretos; faltam testes de recompensa e cooldown.
- **`mystic`** — conteúdo efêmero e sem persistência; risco baixo.
- **`social`** — pequeno e sem estado; risco baixo.
- **`lore`** — conteúdo autoral com IA opcional; risco baixo.
- **`noticias_ia`** — cache e resiliência de rede são bons; dois Cogs e 3.101 linhas pedem
  divisão.
- **`ia`** — fila, limites e memória são adequados; falta teste de degradação.
- **`GameSFA`** — isolado e funcional; logging fora do padrão.
- **`ultility`** — grupos bem definidos; tamanho justifica divisão futura.

---

## 6. Problemas comprovados

> “Comprovado” significa que o comportamento foi confirmado por leitura do código, teste
> ou execução. Hipóteses e riscos sem reprodução estão na seção 8.

### P-01 — `bot.run()` fora do guard de `__main__` (alta)

**Evidência:** `main.py:129-136`. O bloco `if __name__ == "__main__":` valida o token, mas
a chamada `bot.run(TOKEN)` está no nível do módulo, fora do `if`.

**Efeito:** importar `main.py` (por teste, ferramenta ou outro módulo) inicia o bot ou
falha com token ausente. O guard de token também não impede a chamada.

**Correção recomendada:** mover `bot.run(TOKEN)` para dentro do `if`, mantendo a validação
antes da chamada. É uma mudança pequena, mas exige autorização por tocar `main.py`.

**Critério de aceitação:** `import main` não inicia o bot; executar `python main.py` sem
token falha com mensagem clara e sem tentar conectar.

### P-02 — Guarda de concorrência assimétrica entre PvE e PvP (média) — **resolvido**

**Evidência histórica:** `cogs/ruptura.py:7399` verificava apenas `self.runs_ativas`.
`cogs/ruptura_pvp.py:1118` verificava `ruptura.runs_ativas`, e `:1147` adiciona o desafiante
a `self.ocupados`. O PvE não consultava `RupturaDuelo.ocupados`.

**Efeito:** um jogador que estava convidando, escolhendo classe ou duelando podia executar
`s!ruptura` e abrir uma run simultânea. O inverso já era bloqueado.

**Correção aplicada em 26/10/2026 (BUG-01):** `cogs/ruptura.py:7327` define
`estado_jogador_ocupado()`, que consulta runs PvE e ocupações PvP. A função é usada em
`s!ruptura` (`:7423`), em `iniciar_run()` (`:7507`) e em
`RupturaDuelo.motivo_indisponivel()` (`cogs/ruptura_pvp.py:1110`). A checagem em
`iniciar_run()` fecha a janela entre abrir a escolha de classe e confirmar a run.

**Critério de aceitação:** nenhum jogador consegue iniciar PvE enquanto estiver em
convite/duelo, e nenhum duelo começa enquanto houver run ativa. Coberto por
`TestGuardaPvEPvP` em `test_ruptura.py`.

### P-03 — Descarregamento descarta runs sem finalização (média)

**Evidência:** `cogs/ruptura.py:7346-7352`. `cog_unload()` registra um aviso e chama
`runs_ativas.clear()`.

**Efeito:** em reload/desligamento do Cog, runs ativas perdem o estado, não recebem o bônus
final, não registram ranking e não devolvem itens consumidos no início da run. O timeout
normal (`:6995-7009`) finaliza corretamente; o descarregamento não.

**Correção recomendada:** finalizar cada run no unload (com cuidado para não depender do
Discord estar disponível) ou persistir um estado mínimo para retomada/estorno.

**Critério de aceitação:** um reload do Cog não deixa runs “fantasma” nem consome itens
sem registro; o comportamento é documentado.

### P-04 — Pets sem escopo por guild e ranking global (média)

**Evidência:** `cogs/pet.py:429` cria `pet_collection` com chave primária
`(user_id, pet_id)`, sem `guild_id`. `cogs/pet.py:663` consulta
`ORDER BY nivel DESC, xp DESC LIMIT ?` sem filtro de guild e só depois o comando
`/pet ranking` filtra membros do servidor.

**Efeito:** o mesmo usuário tem um único conjunto de pets em todos os servidores. O top
100 global pode não conter os melhores pets do servidor, produzindo rankings locais
incompletos. Também há risco de mistura de contexto entre comunidades.

**Correção recomendada:** decidir explicitamente entre escopo global (documentado) ou
escopo por guild; se for por guild, adicionar `guild_id` com migração compatível e ajustar
as consultas. **Não executar migração sem autorização.**

**Critério de aceitação:** ranking e ficha usam o escopo definido; usuários de outros
servidores não aparecem indevidamente.

### P-05 — SQLite síncrono no event loop por mensagem (média)

**Evidência:** `cogs/XpAndCoins.py:632-654`. `processar_mensagem()` abre
`self.transacao()` e executa leitura/gravação síncronas diretamente na coroutine chamada
pelo `on_message` do `main.py`.

**Efeito:** em concorrência alta ou contenção de lock, o event loop pode ficar bloqueado
por até o `timeout` da conexão (10 s). O atalho de cache reduz a frequência, mas não
elimina o custo.

**Correção recomendada:** manter o cálculo e a decisão na coroutine, mas executar a
transação em `asyncio.to_thread`, como já é feito em outros fluxos do próprio Cog.

**Critério de aceitação:** o caminho de XP por mensagem não bloqueia o loop; teste de
concorrência preserva o cooldown e não duplica XP.

### P-06 — Documentação do cassino promete testes que não existem (baixa)

**Evidência:** `cogs/cassino.py:33` afirma “RTP — calculado por enumeração nos testes”.
A busca por arquivos de teste encontrou apenas `test_ruptura.py`; não há testes de cassino.

**Efeito:** risco de regressão silenciosa em RTP e persistência do cassino, além de
expectativa incorreta sobre a cobertura.

**Correção recomendada:** criar testes de RTP e de transações do cassino ou ajustar o
comentário para refletir a realidade. Os valores atuais foram conferidos manualmente nesta
auditoria.

**Critério de aceitação:** a documentação não afirma cobertura inexistente; os valores de
RTP têm teste automatizado ou fonte explícita.

### P-07 — Dados e tabelas legadas sem uso (baixa)

**Evidência:**

- `data/cassino.db` não tem referências no código (busca em `*.py` e `*.md`).
- `data/noticias.db` contém `noticias` e `rss_fontes`; o código usa `noticias_cache`
  (`cogs/noticias_ia.py:486-523`).
- `data/shaggy.db` contém `virtual_pets`, usada apenas pela migração de `cogs/pet.py`.

**Efeito:** confusão operacional, backups maiores e risco de alguém editar a tabela errada.
Não é um bug funcional.

**Correção recomendada:** documentar como legado e planejar remoção **após backup e
autorização**. Não apagar nada nesta auditoria.

### P-08 — README desatualizado (baixa; corrigido nesta auditoria)

**Evidência histórica:** o README anterior citava `utilitys.py` (arquivo real:
`cogs/ultility.py`) e `DISCORD_TOKEN` (variável real: `token_shaggy`).

**Efeito:** instruções de instalação podiam falhar.

**Status:** corrigido no README atualizado. Registrar como resolvido, não como pendência.

### P-09 — Variável de ambiente sem uso (baixa)

**Evidência:** o `.env` local contém `gpt_api_token`; a busca no código não encontrou
referências.

**Efeito:** higiene de configuração; pode induzir a crer que uma integração existe.

**Correção recomendada:** remover do `.env` local ou documentar como reservada. Não foi
lido nem exposto o valor.

### P-10 — Recompensas podem falhar silenciosamente (média)

**Evidência:** `cogs/ruptura.py:2857-2898` (`award_rewards`) registra a exceção e retorna
`False`. `registrar_vitoria()` (`:7536`) e `finalizar_run()` (`:7693`) continuam o fluxo
mesmo quando a persistência falha; o embed final avisa apenas no bônus de conclusão.

**Efeito:** o jogador pode perder XP/Abysmus de abates sem uma compensação automática.

**Correção recomendada:** enfileirar recompensas pendentes ou registrar um ledger de
falhas para reprocessamento; no mínimo, informar claramente o jogador em todos os casos.

**Critério de aceitação:** falha de economia não é silenciosa e existe caminho de
reconciliação.

### P-11 — Vazamento de `ocupados` em falha de interação no PvP (alta) — **resolvido**

**Evidência histórica:** `ConviteDuelo.aceitar` adicionava o desafiado a
`RupturaDuelo.ocupados` e chamava `stop()` antes de `interaction.response.edit_message`.
Se a edição falhasse, a exceção escapava e os dois jogadores permaneciam ocupados.
`EscolhaClasse.escolher` marcava `iniciando = True` e chamava `stop()` antes de
`interaction.response.defer()`; uma falha no defer impedia o `on_timeout` de liberar os
jogadores. Reproduzido com falha simulada: `ocupados` ficava `{7, 8}` nos dois casos.

**Efeito:** bloqueio permanente de PvE e PvP para os dois jogadores, sem comando de
recuperação, até reiniciar o bot.

**Correção aplicada em 26/10/2026 (BUG-05):** `cogs/ruptura_pvp.py` libera os dois
jogadores quando a tela de escolha não pode ser aberta e quando a confirmação falha antes
de `iniciar_duelo()`; a falha ao obter `original_response()` apenas é registrada, pois a
tela já está ativa e tem timeout. Coberto por `TestLiberacaoEstadoPvP` em
`test_ruptura.py`.

**Critério de aceitação:** `ocupados` volta a ficar vazio após falha simulada; o duelo não
é iniciado quando a confirmação falha.

---

## 7. Dívida técnica

### D-01 — Monólito `ruptura.py`

9.551 linhas concentram catálogo, efeitos, combate, eventos, itens, mercado, build,
persistência e UI. A separação lógica existe por seções, mas não física. Isso aumenta o
custo de revisão, o tempo de importação e o risco de conflitos.

**Direção:** extrair módulos internos sem transformar tudo em Cogs:
`ruptura_catalogo.py`, `ruptura_combate.py`, `ruptura_itens.py`, `ruptura_build.py` e
`ruptura_ui.py`, mantendo `ruptura.py` como fachada e preservando imports públicos.

### D-02 — Persistência fragmentada

Há 13 conexões SQLite diretas em 7 arquivos, com timeouts diferentes e sem camada comum.
As transações da economia são boas, mas cada Cog reimplementa detalhes.

**Direção:** repositório compartilhado para conexão, `busy_timeout`, `row_factory` e
transações; migrar aos poucos, começando por leitura.

### D-03 — Sem WAL nem política global de lock

Apenas `pet.py` define `busy_timeout`. O bot tem vários escritores concorrentes no mesmo
arquivo.

**Direção:** avaliar `journal_mode=WAL` e `busy_timeout` global em uma migração
controlada, com teste de concorrência.

### D-04 — Sem migrações versionadas

Cada Cog usa `CREATE TABLE IF NOT EXISTS` e, em alguns casos, `ALTER TABLE` defensivo
(`pet.py`). Não há versão de esquema nem rollback.

**Direção:** adotar uma tabela de versão e scripts idempotentes antes de novas colunas.

### D-05 — Cobertura de testes concentrada

`test_ruptura.py` cobre bem a Ruptura, mas não há testes para cassino, economia, insígnias,
pets, missões, notícias, IA, moderação, PvP ou GameSFA.

**Direção:** começar pelas regras puras (RTP, cálculo de XP, validações) e pelos fluxos
transacionais com banco temporário.

### D-06 — Acoplamento por string

`bot.get_cog("XpAndCoins")`, `bot.get_cog("IA")` e `bot.get_cog("RupturaTemporal")` são
resolvidos em tempo de execução. Se um Cog for renomeado ou não carregar, o erro aparece
tarde.

**Direção:** constantes compartilhadas e verificação de integração no `cog_load` (algumas
já existem) ou um registro tipado de serviços.

### D-07 — Estado em memória

Runs, duelos e partidas de cassino vivem em memória. O cassino tem recuperação de partidas
abertas; a Ruptura só finaliza no timeout. Um restart abrupto perde runs.

**Direção:** persistir um snapshot mínimo ou aceitar e documentar explicitamente a perda,
com estorno de itens.

### D-08 — Logging inconsistente

`GameSFA.py:48` chama `logging.basicConfig` no import e `:55-58` usa `print`. Os demais
Cogs usam `logging`. Isso duplica configuração e polui o terminal.

**Direção:** remover `basicConfig` do Cog e usar apenas o logger.

### D-09 — Arquivos grandes fora da Ruptura

`noticias_ia.py` (3.101 linhas, dois Cogs), `cassino.py` (2.405), `badges.py` (2.313) e
`ultility.py` (2.203) também concentram muitas responsabilidades.

**Direção:** dividir por camada (motor, persistência, UI) sem alterar comandos públicos.

### D-10 — Comentários e documentação divergentes

Além do caso do cassino (P-06), há trechos que descrevem patches antigos ou comportamento
que já mudou. A documentação deve ser tratada como código.

**Direção:** revisar docstrings ao tocar cada módulo; manter o README e `docs/` como fonte
de verdade.

---

## 8. Riscos de manutenção e integridade

> Riscos abaixo são avaliações; nem todos foram reproduzidos.

| ID | Risco | Probabilidade | Impacto | Mitigação |
| --- | --- | --- | --- | --- |
| R-01 | Corrida entre PvE e PvP (P-02) | Baixa | Médio | Guarda compartilhada aplicada em BUG-01; coberta por testes |
| R-02 | Perda de runs no unload (P-03) | Média | Médio | Finalização/estorno no unload |
| R-03 | Bloqueio do event loop por SQLite (P-05) | Média | Médio | `to_thread` no caminho de XP |
| R-04 | Lock de banco sob carga | Média | Alto | WAL + `busy_timeout` + repositório |
| R-05 | Recompensa perdida sem aviso (P-10) | Baixa/Média | Alto | Fila/ledger de reconciliação |
| R-06 | Ranking de pets incorreto (P-04) | Alta | Baixo/Médio | Definir escopo e corrigir consulta |
| R-07 | Regressão no cassino sem testes | Média | Médio | Testes de RTP e transação |
| R-08 | Falha de Cog derruba o boot | Baixa | Alto | Fail-fast é intencional; monitorar e ter rollback |
| R-09 | Dados legados induzem erro operacional (P-07) | Média | Baixo | Documentar e remover com backup |
| R-10 | Dependência de IA/RSS indisponível | Média | Baixo/Médio | Já há tratamento; manter mensagens claras |
| R-11 | Permissões/hierarquia de cargos no Discord | Média | Médio | Fila persistente já existe; testar em servidor real |
| R-12 | Vazamento de segredos em commits | Baixa | Alto | `.gitignore` cobre `.env`; revisar antes de push |
| R-13 | `ocupados` preso após falha de interação (P-11) | Baixa | Alto | Liberação em falha e testes aplicados em BUG-05 |

### Integridade dos dados

- A economia usa `BEGIN IMMEDIATE` e uma única transação para débito/crédito, o que é
  positivo.
- O cassino grava partida, saldo e estatísticas na mesma transação; partidas abertas são
  estornadas no restart (`cogs/cassino.py:1008-1021` e `:2170-2184`).
- As insígnias usam ledger e fila persistente de cargos, com tentativas e erro registrado.
- A Ruptura usa transações específicas para mercado/inventário e testes de concorrência.
- O ponto mais frágil é a **falha de recompensa após o fato** (P-10), não a operação
  normal.

---

## 9. Ruptura Temporal: avaliação e melhorias

### Pontos fortes

- Catálogo declarativo e validado (classes, especs, nós, itens, criaturas, eventos).
- Combate com decisões táticas reais: Foco, guarda, técnicas, ativas, status, crítico,
  relíquias e eventos.
- Chefes com telegrafia, interrupção e adaptação isolada por criatura/run/jogador.
- Mercador e forja integrados à economia com compra atômica.
- PvP reutiliza o motor sem consumir itens por padrão.
- Testes cobrem catálogo, itens, inventário, mercado, combate tático, PvP, guarda de
  estado PvE/PvP, liberação de estado em falha de interação e embeds.

### Pontos fracos

- Monólito e UI acoplada ao motor no mesmo arquivo.
- Estado apenas em memória e descarte no unload.
- Assimetria de guarda com PvP **corrigida em BUG-01**.
- Recompensas não reconciliadas em caso de falha.
- Ausência de testes de progressão longa, balanceamento e repetibilidade.
- Conteúdo cresceu mais rápido que a infraestrutura de testes.

### Melhorias prioritárias

1. **Corrigir P-01 e P-03** antes de adicionar conteúdo. P-02 foi concluído em BUG-01.
2. **Criar testes de economia da Ruptura** (recompensa por abate, bônus final, falha de
   persistência, item consumido e run abandonada).
3. **Separar o motor da UI** e reduzir `ruptura.py` a uma fachada.
4. **Persistir ou finalizar runs** de forma explícita no ciclo de vida.
5. **Medir progressão** com simulações reproduzíveis antes de mexer em balanceamento.

As propostas completas, com impacto, complexidade, dependências, riscos, prioridade e
critério de aceitação, estão em [`RUPTURA_ROADMAP.md`](RUPTURA_ROADMAP.md).

---

## 10. Recomendações sobre Cogs

### Manter

`XpAndCoins`, `ruptura`, `ruptura_pvp`, `ruptura_extras`, `badges`, `cassino`, `missoes`,
`pet`, `ranking`, `games`, `mystic`, `social`, `lore`, `noticias_ia`, `ia`, `GameSFA`,
`ultility`.

Nenhum Cog deve ser removido nesta fase: todos têm comandos registrados e funções
observáveis.

### Refatorar

| Cog | Refatoração sugerida | Risco |
| --- | --- | --- |
| `ruptura` | Extrair catálogo, combate, itens, build e UI para módulos internos | Alto (muitos imports) |
| `ruptura_extras` | Separar `RankingRepo`, `PonteIA` e apresentação | Médio |
| `noticias_ia` | Separar `Noticias` e `Ferramentas` em arquivos distintos | Médio |
| `pet` | Definir escopo por guild + repositório | Alto (dados) |
| `badges` | Separar store/ledger de UI | Médio |
| `cassino` | Separar motor de jogos, tesouraria e UI | Médio |
| `ultility` | Separar moderação, cargos e status | Baixo/Médio |

### Substituir

Não há substituição urgente de Cog. A substituição recomendada é **arquitetural**:
substituir o acesso SQLite ad hoc por um repositório compartilhado e o `get_cog` por
constantes/registro tipado, de forma incremental.

### Adicionar

Não recomendo um novo Cog de conteúdo antes de:

- cobrir os fluxos críticos com testes;
- resolver P-01 e P-03 (P-02 concluído em BUG-01);
- definir a política de migração do banco.

Um módulo interno (`ruptura_combate.py`, `ruptura_itens.py`) não é um novo Cog e pode
ajudar a reduzir o monólito sem aumentar a superfície de comandos.

### Remover/desativar

- `data/cassino.db` é legado e não referenciado; pode ser arquivado após backup.
- Tabelas `noticias` e `rss_fontes` são legadas; manter até confirmação de que nenhum
  processo externo as usa.
- `virtual_pets` só é usada na migração; remover apenas após validar que a migração já
  rodou em todos os ambientes.

---

## 11. Testes executados e resultados

### Suíte automatizada

```text
$ .venv/bin/python -m unittest test_ruptura -v
Ran 89 tests in 0.866s
OK
```

Classes de teste em `test_ruptura.py`:

- `TestCatalogo` — validadores, expansão, curva, categorias.
- `TestEventos` — janelas sazonais, eventos base, escolhas e efeitos.
- `TestItens` — quantidade por tipo, validação, equipáveis, consumíveis e estratégicos.
- `TestInventario` — persistência SQLite temporária e consumo.
- `TestMercadoAtomico` — concorrência, rollback, saldo e entrega.
- `TestMercador` — abertura, artefatos, compras e limites.
- `TestProgressaoMercador` — progressão até o mercador.
- `TestCombateTatico` — telegrafia, interrupção, adaptação, isolamento e expiração.
- `TestPvP` — filtro de itens e compatibilidade.
- `TestGuardaPvEPvP` — exclusividade de estado entre PvE e PvP nos dois sentidos.
- `TestLiberacaoEstadoPvP` — liberação de `ocupados` em falhas de interação e reserva
  atômica de duas runs concorrentes.
- `TestEmbeds` — conteúdo e limites de embed.
- `TestHabilidadesExpansao3` — as 36 habilidades novas, telegrafia/interrupção,
  esgotamento de recursos e contrajogo.
- `TestIntegracaoExpansao3` — pool de encontros, cadência inalterada, início/fim de run e
  reutilização das fórmulas de recompensa.

Nenhum teste usa o banco real: os testes de persistência patcham `DB_PATH` para um
diretório temporário.

### Validações estáticas e de importação

- `py_compile` de `main.py`, todos os `cogs/*.py` e `test_ruptura.py`: OK.
- Importação dos 17 módulos de `cogs/`: OK.
- `validar_catalogos()`: sem erro.
- `validar_arvores()`: `[]`.
- `validar_eventos()`: `[]`.

### RTP do cassino (execução direta)

| Jogo/modalidade | RTP |
| --- | ---: |
| Roleta (todos os tipos) | 97,2973% |
| Moeda | 98,00% |
| Dados alto/baixo | 94,4444% |
| Dados face 6 | 91,6667% |
| Dados soma 2 / 12 | 97,2222% |
| Dados soma 7 | 83,3333% |
| Caça-níquel | 93,4625% |
| Travessia (teto) | 96,00% |

Esses valores foram obtidos executando as funções do módulo, não por simulação
estatística nem por teste automatizado.

### Bancos inspecionados (somente leitura)

- `data/shaggy.db`: 22 tabelas de aplicação + `sqlite_sequence`.
- `data/noticias.db`: `noticias_cache` ativa; `noticias` e `rss_fontes` legadas.
- `data/cassino.db`: `cassino_historico` e `cassino_stats` legadas, sem uso no código.

Nenhum esquema foi alterado e nenhuma migração foi executada.

---

## 12. Limitações da auditoria

- **Não houve teste com Discord real.** Permissões, hierarquia de cargos, rate limits,
  interações de botões/selects/modais, entrega de cargos e comportamento em múltiplos
  servidores não foram validados ao vivo.
- **Não houve teste de carga.** A avaliação de bloqueio do event loop e contenção SQLite
  é baseada em inspeção, não em benchmark.
- **Não há medição de cobertura.** Não foi executado `coverage.py`; a afirmação de
  cobertura é qualitativa e baseada nos testes existentes.
- **RTP foi conferido por execução das funções**, não por simulação de milhões de
  partidas. Isso valida a matemática declarada, não o comportamento sob `random` real em
  produção.
- **Balanceamento não foi auditado a fundo.** Não foram alteradas chances, recompensas,
  escalas ou atributos. A curva de dificuldade só foi verificada pelo teste existente.
- **Line numbers** referem-se ao commit `9cb5c19`; mudanças futuras podem deslocá-los.
- **O `.env` não foi lido em conteúdo.** Apenas nomes de variáveis foram verificados.
- **Não foi possível confirmar** se algum processo externo usa as tabelas legadas de
  `noticias.db`/`cassino.db`.
- **Não foi avaliada** a qualidade do conteúdo de IA (prompts, respostas, custos) além da
  integração e do tratamento de falhas.

---

## 13. Conclusão

O Shaggy Bot não precisa de uma reescrita. Precisa de **higiene de ciclo de vida,
simetria de integração e testes nos sistemas que movimentam dinheiro**. A Ruptura é o
sistema mais maduro e o que mais se beneficia de refatoração estrutural, não de mais
conteúdo.

Ordem recomendada:

1. Corrigir P-01 e P-03 (mudanças pequenas, alto retorno). P-02 foi concluído em BUG-01.
2. Criar testes de economia/cassino e de falha de persistência.
3. Definir escopo de pets e política de migração.
4. Dividir os módulos maiores sem alterar comandos públicos.
5. Só então expandir classes, Chefes, itens e eventos.

A auditoria original não alterou código de produção, esquema, `.env` ou `main.py`. A
atualização posterior implementou apenas BUG-01 em `cogs/ruptura.py`, `cogs/ruptura_pvp.py`
e `test_ruptura.py`, sem tocar em banco, `.env`, `main.py` ou balanceamento.
