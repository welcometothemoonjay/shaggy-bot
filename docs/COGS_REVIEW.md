# Revisão de Cogs — Shaggy Bot

**Base:** commit `27c2c90`, auditoria de 26/10/2026, com BUG-01 e BUG-05.
**Pergunta central:** cada Cog deve ser mantido, melhorado, refatorado, removido ou
substituído?

> A revisão original não alterou Cogs. Em 26/10/2026, BUG-01 alterou apenas
> `cogs/ruptura.py` e `cogs/ruptura_pvp.py` para compartilhar a guarda de estado PvE/PvP;
> BUG-05 também alterou `cogs/ruptura_pvp.py` para garantir a liberação de `ocupados` em
> falhas de interação. O restante das recomendações continua como proposta e exige
> autorização.

---

## 1. Critérios

| Critério | O que avalia |
| --- | --- |
| **Criticidade** | Quanto o bot perde se o Cog falhar ou for removido. |
| **Maturidade** | Tratamento de erros, transações, validação, testes e documentação. |
| **Coesão** | Se o arquivo tem uma responsabilidade clara. |
| **Acoplamento** | Dependência de outros Cogs, banco ou serviços externos. |
| **Custo de manutenção** | Tamanho, duplicação, complexidade e frequência de mudança. |

Escala qualitativa: **alta / média / baixa**.

---

## 2. Visão comparativa

| Cog | Linhas | Comandos principais | Persistência | Criticidade | Maturidade | Coesão | Recomendação |
| --- | ---: | --- | --- | --- | --- | --- | --- |
| `XpAndCoins` | 1.088 | `/xp`, `/level`, `/coins`, `/ranking`, admin | `user_stats` | **Alta** | **Alta** | Alta | **Manter** (proteger) |
| `ruptura` | 9.551 | `s!ruptura`, `s!market`, `s!inventario`, `/build` | inventário, build, mercado | **Alta** | Média/Alta | Baixa | **Manter + refatorar** |
| `ruptura_pvp` | 1.353 | `s!duelo`, `s!duelorank` | `ruptura_pvp` | Média | Média | Média | **Manter** (integração coberta) |
| `ruptura_extras` | 1.055 | `s!ranking_ruptura`, `s!perfil_ruptura`, IA | `ruptura_runs`, `ruptura_abates` | Média | Média | Média | **Manter + separar** |
| `badges` | 2.313 | 13 comandos de insígnias | 4 tabelas + fila | Média/Alta | Alta | Média | **Manter + dividir** |
| `cassino` | 2.405 | `/cassino`, stats, títulos | 3 tabelas | Média | Média | Média | **Manter + testar/dividir** |
| `missoes` | 663 | `/missoes` + listeners | 3 tabelas | Média | Média | Alta | **Manter** |
| `pet` | 1.525 | `s!pet ...` (15 subcomandos) | `pet_collection` | Média | Média | Média | **Manter + refatorar escopo** |
| `ranking` | 245 | `/ranking` | via XpAndCoins | Baixa/Média | Alta | Alta | **Manter** |
| `games` | 1.173 | 10 minijogos | via XpAndCoins | Baixa/Média | Média | Média | **Manter + testar** |
| `mystic` | 1.038 | 13 comandos | nenhuma | Baixa | Alta | Média | **Manter** |
| `social` | 222 | 8 comandos | nenhuma | Baixa | Alta | Alta | **Manter** |
| `lore` | 863 | 10 comandos | nenhuma | Baixa/Média | Média | Média | **Manter** |
| `noticias_ia` | 3.101 | 6 slash + prefixo | `noticias_cache` | Média | Média | Baixa | **Manter + dividir** |
| `ia` | 851 | `s!ia`, `s!ia_limpar` | memória | Média | Média/Alta | Alta | **Manter** |
| `GameSFA` | 962 | `/sfa duelo` | nenhuma | Baixa | Média | Alta | **Manter + padronizar log** |
| `ultility` | 2.203 | 11 slash + grupos | `util_warnings` | Média | Alta | Média | **Manter + dividir** |

### Leitura do quadro

- **Núcleo crítico:** `XpAndCoins` e `ruptura`. Falhas nesses dois afetam dinheiro,
  progressão e a experiência principal.
- **Núcleo de suporte:** `badges`, `cassino`, `missoes`, `pet` e `ruptura_extras` giram em
  torno da economia e do histórico.
- **Conteúdo e utilidades:** `games`, `mystic`, `social`, `lore`, `GameSFA`, `ultility`.
- **Integrações externas:** `ia`, `noticias_ia`, `lore` e `ruptura_extras` dependem de
  OpenRouter/RSS/GitHub.

---

## 3. Avaliação individual

### 3.1 `cogs/XpAndCoins.py`

**Papel:** economia central. XP por mensagem, níveis, bônus diário, Abysmus,
`transacao()`, `obter_saldo_tx()`, `alterar_coins_tx()` e `conceder_recompensas()`.

**Pontos fortes**

- Transações explícitas com `BEGIN IMMEDIATE`, commit/rollback e fechamento garantido.
- API reutilizada por praticamente todos os Cogs; evita escrita concorrente em
  `user_stats`.
- Cooldown e bônus diário resolvidos na mesma transação, reduzindo dupla concessão.
- Comandos administrativos com validação, limite e timeout.
- Fuso explícito (UTC−3) e cálculo de nível documentado.

**Pontos fracos**

- `processar_mensagem()` executa SQLite síncrono no event loop (`:632-654`), apesar de o
  restante do projeto usar `asyncio.to_thread` em vários fluxos.
- Erros de economia são registrados, mas não há reconciliação central de recompensas
  falhas.
- É um ponto único de falha: se o Cog não carregar, vários sistemas degradam.

**Recomendação: MANTER e proteger.** Não substituir. Corrigir o caminho síncrono e criar
testes de concorrência/rollback. Tratar como dependência crítica com contrato estável.

---

### 3.2 `cogs/ruptura.py`

**Papel:** motor do roguelite — catálogo, efeitos, combate, eventos, itens, mercado,
build, persistência e UI.

**Pontos fortes**

- Catálogo declarativo e validado (10 classes, 30 especs, 150 nós, 12 relíquias, 27 itens,
  91 criaturas, 12 eventos, 68 habilidades).
- Combate com Foco, guarda, técnicas, ativas, status, crítico, relíquias e eventos.
- Chefes com telegrafia, interrupção e adaptação isolada.
- Mercado/forja com compra atômica e testes de concorrência.
- Boa suíte de testes para o tamanho do sistema (89 testes no total).
- UI funcional com botões, selects, mochila e eventos.

**Pontos fracos**

- 9.551 linhas e múltiplas responsabilidades no mesmo arquivo.
- `cog_unload()` descarta runs sem finalização.
- Estado apenas em memória; restart abrupto perde runs.
- Recompensas podem falhar sem compensação.
- UI e regras importam `discord` juntas, dificultando testes puros.

**Recomendação: MANTER e REFATORAR em fases.** É o coração do projeto; não substituir.
Extrair módulos internos (catálogo, combate, itens, build, UI), preservando a fachada e os
imports usados por `ruptura_pvp.py` e `ruptura_extras.py`.

---

### 3.3 `cogs/ruptura_pvp.py`

**Papel:** duelos PvP da Ruptura, reutilizando `RunState`, `EnemyState` e o motor.

**Pontos fortes**

- Reaproveita o motor em vez de duplicar regras.
- Itens de PvP limitados a passivos/artefatos por padrão.
- Placar persistido em `ruptura_pvp`.
- Convite, escolha de classe e ciclo de duelo com `ocupados`.
- Verifica runs PvE antes de duelar.
- Libera os dois jogadores quando a abertura da escolha ou a confirmação falha (BUG-05).

**Pontos fracos**

- A reciprocidade da guarda foi corrigida em BUG-01; o PvE agora consulta `ocupados`.
- Duelo e PvE ainda mantêm coleções de estado separadas, mas a leitura é centralizada
  por `estado_jogador_ocupado()`.
- Em empate, o cálculo de XP usa `XP_DERROTA_PVP` para ambos; hoje o padrão é 0, mas a
  lógica fica latente.
- Sem suíte própria; guarda compartilhada e liberação de estado são cobertas em
  `test_ruptura.py`.

**Recomendação: MANTER; integração de estado coberta.** Não substituir.

---

### 3.4 `cogs/ruptura_extras.py`

**Papel:** ranking de runs, perfil, crônica, bestiário, conselho e profecia; integra IA.

**Pontos fortes**

- Ranking com SQL tipado e ordem fixa (sem interpolação de entrada).
- Escuta `on_ruptura_run_finalizada` e persiste runs/abates.
- `PonteIA` reaproveita o Cog `IA` em vez de criar outro cliente.
- Comandos de IA com fallback e mensagens de indisponibilidade.

**Pontos fracos**

- Repositório, ponte de IA e apresentação no mesmo arquivo.
- Depende de um nome de Cog (`IA`) e de um evento interno; falhas aparecem em runtime.
- `cog_load` e `on_ready` fazem verificação de integração, mas não bloqueiam o boot.

**Recomendação: MANTER e separar** `RankingRepo`, `PonteIA` e a camada de comando em
módulos/áreas distintas. Não substituir.

---

### 3.5 `cogs/badges.py`

**Papel:** loja de insígnias, posse, ledger, fila persistente de cargos e auditoria.

**Pontos fortes**

- Compra transacional: débito + posse + histórico + fila na mesma transação.
- Fila persistente com tentativas e último erro; reprocessada por loop.
- Ledger e auditoria; comandos administrativos completos.
- Boa separação conceitual entre catálogo, posse e entrega de cargo.

**Pontos fracos**

- 2.313 linhas e UI/regras/persistência no mesmo arquivo.
- Depende da economia por `get_cog`, com verificação tardia.
- Entrega de cargo é efeito externo; exige permissões/hierarquia corretas.
- Sem testes automatizados no repositório.

**Recomendação: MANTER e dividir** store/ledger, fila e UI. Não substituir.

---

### 3.6 `cogs/cassino.py`

**Papel:** cassino temático com roleta, moeda, dados, blackjack, slots e travessia.

**Pontos fortes**

- Usa a API da economia e mantém saldo/partida/estatísticas na mesma transação.
- Recuperação de partidas abertas no restart.
- RTP documentado e implementado por funções verificáveis.
- Conquistas, estatísticas e NPCs com boa ambientação.
- `cog_unload` estorna partidas ativas.

**Pontos fracos**

- Docstring afirma RTP “calculado por enumeração nos testes”, mas não há testes de cassino
  no repositório.
- 2.405 linhas com motor, tesouraria, UI e conteúdo.
- RTP varia bastante entre modalidades (por exemplo, soma 7 em 83,33% e soma 2/12 em
  97,22%); é uma decisão de design, mas merece documentação explícita.
- Sem testes de concorrência/rollback próprios.

**Recomendação: MANTER; criar testes e dividir** motor/tesouraria/UI. Não substituir.

---

### 3.7 `cogs/missoes.py`

**Papel:** missões diárias determinísticas, progresso por eventos e Portais de Distorção.

**Pontos fortes**

- Sorteio determinístico por semente, resistente a restart.
- Progresso em transação da economia.
- Listeners para mensagens, reações e conclusão de comandos.
- Anti-spam em memória e cache de missões.
- Comando com `defer` antes de SQLite, evitando timeout de interação.

**Pontos fracos**

- Usa tabelas próprias dentro da transação de `XpAndCoins`; acoplamento aceitável, mas
  implícito.
- Listeners fazem trabalho em todo `on_message`/`on_raw_reaction_add`; o custo depende dos
  filtros.
- Sem testes automatizados.

**Recomendação: MANTER.** É coeso e bem delimitado. Adicionar testes de sorteio e
progresso.

---

### 3.8 `cogs/pet.py`

**Papel:** pets com adoção, cuidados, evolução, habilidades, ranking e migração.

**Pontos fortes**

- Migração defensiva de `virtual_pets` e colunas novas.
- `busy_timeout` explícito e transações próprias.
- Conteúdo rico (estágios, habilidades, frases, diário).
- Comandos com cooldown e escopo de guild nos comandos.

**Pontos fracos**

- `pet_collection` não tem `guild_id`; o pet é global por usuário.
- `ranking_geral` consulta o top 100 global e só depois filtra membros do servidor,
  podendo omitir o top local.
- 1.525 linhas e UI/regras/persistência juntas.
- Sem testes automatizados.

**Recomendação: MANTER e REFATORAR o escopo** (global documentado ou por guild com
migração autorizada). Não substituir.

---

### 3.9 `cogs/ranking.py`

**Papel:** `/ranking` de XP/níveis, com paginação.

**Pontos fortes**

- Pequeno, coeso e direto.
- Usa `asyncio.to_thread` para consultar a economia.
- Paginação e posição do autor.

**Pontos fracos**

- Depende de `XpAndCoins`; se ausente, o comando falha.
- Sem testes próprios.

**Recomendação: MANTER.** Baixo risco.

---

### 3.10 `cogs/games.py`

**Papel:** 10 minijogos slash com recompensa de XP/Abysmus.

**Pontos fortes**

- Comandos simples, com cooldown e validação.
- Usa a economia central para recompensas.
- Não mantém estado persistente complexo.

**Pontos fracos**

- Sem testes de recompensa/limites.
- Regras de cada jogo duplicam validações simples.
- Dependência de economia por `get_cog`.

**Recomendação: MANTER e adicionar testes** de recompensa e cooldown. Não substituir.

---

### 3.11 `cogs/mystic.py`

**Papel:** tarô, runas, astrologia, numerologia, sonhos, presságios, rituais e amuletos.

**Pontos fortes**

- Conteúdo efêmero, sem persistência; baixo risco de integridade.
- Comandos coesos e com boa ambientação.
- Não movimenta dinheiro.

**Pontos fracos**

- Sem testes (aceitável para conteúdo aleatório, mas limites de embed poderiam ser
  testados).
- Arquivo grande para conteúdo majoritariamente textual.

**Recomendação: MANTER.** Não é prioridade de refatoração.

---

### 3.12 `cogs/social.py`

**Papel:** comandos sociais e de interação.

**Pontos fortes**

- Pequeno, coeso, sem persistência.
- Baixo risco.

**Pontos fracos**

- Sem testes; depende de menções/embeds.

**Recomendação: MANTER.** Baixo risco.

---

### 3.13 `cogs/lore.py`

**Papel:** livros, cosmologia, facções, glossário, lacunas e `/lore perguntar`.

**Pontos fortes**

- Conteúdo autoral organizado.
- `/lore perguntar` degrada se a IA não estiver disponível.
- Sem persistência.

**Pontos fracos**

- Dependência opcional da IA por `get_cog`.
- Sem testes de formatação/limites.

**Recomendação: MANTER.** Não substituir.

---

### 3.14 `cogs/noticias_ia.py`

**Papel:** dois Cogs no mesmo arquivo — `Noticias` (RSS/cache/notícias) e `Ferramentas`
(`/explique`, `/debug`, `/github`, `/resumir`, `/buscar_noticia`).

**Pontos fortes**

- Cache SQLite com índice e limpeza.
- `feedparser` em thread, timeouts de HTTP e tratamento de falhas.
- Integração opcional com GitHub/OpenRouter.
- Comandos com cooldown e mensagens de erro.

**Pontos fracos**

- 3.101 linhas, dois Cogs e várias responsabilidades no mesmo arquivo.
- Tabelas legadas (`noticias`, `rss_fontes`) preservadas.
- Dependência de rede e de chave de API; testes automatizados inexistentes.
- O cache e a coleta são difíceis de testar sem injeção de HTTP.

**Recomendação: MANTER e DIVIDIR** em `noticias` e `ferramentas` (ou módulos internos
equivalentes), sem alterar os comandos públicos. Não substituir.

---

### 3.15 `cogs/ia.py`

**Papel:** conversa com o Shaggy via OpenRouter, com fila, tentativas, cooldown e memória
por usuário/canal.

**Pontos fortes**

- Limite de conversas, truncamento de histórico e limpeza.
- Timeout, tentativas com espera e limite de chamadas simultâneas.
- Recompensa de XP integrada à economia.
- `s!ia_limpar` explícito.

**Pontos fracos**

- Memória apenas em processo; restart perde histórico (aceitável, mas documentar).
- Depende de chave/modelo externos.
- Sem testes de fila/erros.

**Recomendação: MANTER.** É coeso; adicionar testes de degradação e limites.

---

### 3.16 `cogs/GameSFA.py`

**Papel:** duelo de cartas de SFA via `/sfa duelo`.

**Pontos fortes**

- Isolado, sem persistência nem economia.
- Regras claras, views com timeout e liberação de partidas.
- Não interfere em outros sistemas.

**Pontos fracos**

- `logging.basicConfig` no import e `print` no logger local (`:48-58`).
- Sem testes.
- Não tem progressão/recompensa (pode ser intencional).

**Recomendação: MANTER e padronizar logging.** Não substituir.

---

### 3.17 `cogs/ultility.py`

**Papel:** ajuda, ping, status, informações, moderação de membros, cargos, canais,
anúncios e ferramentas de desenvolvedor.

**Pontos fortes**

- Grupos bem definidos (`/membro`, `/cargo`, `/dev`).
- Permissões explícitas e mensagens em português.
- Avisos persistidos em `util_warnings`.
- `psutil` opcional, com fallback.

**Pontos fracos**

- 2.203 linhas com muitas responsabilidades.
- Depende de permissões/hierarquia do Discord, não testáveis aqui.
- Sem testes.

**Recomendação: MANTER e, se crescer, dividir** em moderação, cargos e status. Não
substituir.

---

## 4. Recomendações transversais

### 4.1 Manter

Todos os 17 Cogs têm função observável e comandos registrados. **Nenhum deve ser removido
nesta fase.**

### 4.2 Melhorar sem refatorar

- Adicionar testes de regras puras e transações.
- Corrigir P-01, P-02 e P-03 da auditoria.
- Padronizar logging (`GameSFA`) e `to_thread` em SQLite.
- Documentar escopo de pets e dados legados.

### 4.3 Refatorar

Ordem sugerida, do maior retorno para o maior risco:

1. `ruptura` — extrair módulos internos.
2. `noticias_ia` — separar os dois Cogs.
3. `pet` — escopo por guild/repositório.
4. `badges` — store/ledger × UI.
5. `cassino` — motor × tesouraria × UI.
6. `ultility` — moderação × cargos × status.

### 4.4 Substituir

Não há Cog a substituir. A substituição recomendada é **de infraestrutura**:

- SQLite ad hoc → repositório compartilhado.
- `get_cog("Nome")` → constantes/registro tipado.
- Estado em memória → snapshot/recuperação onde fizer sentido.

### 4.5 Adicionar

Não adicionar um novo Cog de conteúdo antes de:

- resolver os P0 da auditoria;
- criar testes de economia/cassino;
- definir a política de migração.

Módulos internos da Ruptura não são Cogs novos e são bem-vindos.

### 4.6 Remover/arquivar

- `data/cassino.db` — legado sem referências; arquivar após backup.
- `noticias` e `rss_fontes` — legado; remover apenas após confirmar que nada externo usa.
- `virtual_pets` — manter até validar a migração em todos os ambientes.

---

## 5. Matriz de decisão

| Ação | Cogs | Justificativa |
| --- | --- | --- |
| **Manter sem mudança estrutural** | `ranking`, `social`, `mystic`, `games`, `lore`, `ia`, `GameSFA` | Baixo acoplamento ou conteúdo efêmero; melhorias são incrementais. |
| **Manter e melhorar** | `XpAndCoins`, `missoes`, `ruptura_pvp` | Núcleo correto; faltam testes e pequenos ajustes de integração. |
| **Manter e refatorar** | `ruptura`, `ruptura_extras`, `badges`, `cassino`, `pet`, `noticias_ia`, `ultility` | Tamanho e múltiplas responsabilidades; comportamento deve ser preservado. |
| **Substituir** | nenhum Cog | Não há ganho que justifique reescrever um módulo inteiro agora. |
| **Arquivar dados legados** | `data/cassino.db`, tabelas antigas | Não usados pelo código; exigem backup e autorização. |

---

## 6. Conclusão

A arquitetura de Cogs é adequada ao tamanho do projeto, mas alguns módulos cresceram além
do que um arquivo deveria carregar. O caminho de menor risco é:

1. **Estabilizar** (`XpAndCoins`, Ruptura, PvP) com testes e correções pontuais.
2. **Separar** os módulos grandes em camadas internas, sem mudar comandos.
3. **Documentar** escopo de dados (pets, tabelas legadas) e contratos entre Cogs.
4. **Só então** expandir conteúdo.

Nenhum Cog é “descartável”; o que existe hoje é dívida de organização, não de conceito.
