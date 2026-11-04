# AGENT_HANDOFF

## Estado atual — 2026-11-03

A evolução do RPG Textual está implementada e validada no escopo da missão.
O Ruptura Temporal não foi modificado.

- Banco real preservado; backup em
  `backups/shaggy.db.bak.20261103_143906`.
- Testes usam `SHAGGY_DB_PATH` temporário e mocks; nenhum jogador real foi
  afetado.
- Todos os cogs carregam: **19 cogs**, **100 comandos slash**, **0
  duplicados**, **0 falhas**.
- Suíte nova: **61 testes, todos passando** com
  `.venv/bin/python -m unittest discover -s tests -v`.
- `py_compile` passa em `rpg_system/*.py`, `rpg_system/ai/*.py`,
  `cogs/rpg.py`, `cogs/ultility.py` e `tests/test_rpg_evolution.py`.
- Novos recursos são comandos de prefixo `s!`, fora do limite de 100 slash
  commands.

## O que mudou

### Núcleo e banco

- `rpg_system/database.py`: `SHAGGY_DB_PATH`, `isolation_level=None`,
  `busy_timeout` e `row_factory`.
- `rpg_system/schema.py`: migrações aditivas e criação de tabelas base para
  bancos limpos de teste.
- `rpg_system/economy.py`, `inventory.py`, `progression.py`: helpers
  transacionais `*_tx`; fim das transações aninhadas.
- `rpg_system/energy.py`: energia persistente em `rpg_flags`, recarga
  automática de 100% a cada 24h e migração do legado.
- `rpg_system/houses.py`: casa em `rpg_casas`, uma por jogador, apelidos de
  tipo e melhoria com custo `200 × nível`.
- `rpg_system/combat.py`: **10 inimigos**, turnos persistentes em
  `rpg_combates`, ataque com mãos/itens, XP por golpe, vitória/derrota e
  conquistas.
- `rpg_system/admin.py`: inspeção/ranking e alterações atômicas de moedas, XP,
  energia, itens, combate e reset seletivo para moderação.

### Conteúdo e sistemas

- `rpg_system/constants.py`: curva de nível `40×N+40`, custos de
  mineração/exploração/combate, intervalo de recarga de 24h e lista de 9
  profissões.
- `rpg_system/world.py`: 5 regiões, 11 locais, eventos e alias
  `REGIOES = REGIOS`.
- `rpg_system/tools.py`: 10 picaretas e 2 machados, com chances exatas de
  Abysmus e validação matemática.
- `rpg_system/items.py`: catálogo com descrição, utilidade e efeito reais.
- `rpg_system/market_v2.py`: compra/venda por nome, resolução de ambiguidade,
  requisitos, equipamento, picareta inicial, ledger e atomicidade.
- `rpg_system/professions_v2.py`: catálogo, requisitos, benefícios, XP,
  receitas reais e bônus alinhados aos textos.
- `rpg_system/mining_v2.py`: picareta obrigatória, região, tier, chances de
  moedas, bônus de Minerador (incluindo raro no nível 10), XP e estatísticas.
- `rpg_system/achievements_v2.py`: 35 conquistas persistentes e idempotentes,
  com as 3 de combate ativas.
- `rpg_system/exploration.py`: localização persistente, descobertas, eventos,
  recompensas e narração assíncrona.
- `rpg_system/ai/narrative.py`: OpenRouter com cache persistente, timeout,
  `max_tokens`, backoff para 429/5xx, validação de resposta e fallback.
- `rpg_system/views.py` e `goals.py`: ficha, conquistas e próximos objetivos.
- `cogs/rpg.py`: 19 slash commands, autocomplete e embeds ricos; `/equipar` e
  `/combate`. Foram adicionados comandos de prefixo para jogador (`s!rpg`,
  `s!mochila`, `s!minerar`, `s!trabalhar`, `s!explorar`, `s!descansar`,
  `s!lutar`, `s!casa`, `s!objetivos`, `s!rankingrpg`, `s!conquistas`,
  `s!ajudarpg`) e para moderação (`s!rpggive`, `s!rpgtake`, `s!rpgset`,
  `s!rpgitem`, `s!rpgitemremover`, `s!rpgficha`, `s!rpglimparcombate`,
  `s!rpgreset`). `/casa` continua removido do slash.
- `cogs/ultility.py`: categoria `RPG` com emoji 🧭 no mapa do `/help` e regra
  automática para cogs com "rpg"/"aventura"/"ficha"/"personagem".

### Testes e documentação

- `tests/test_rpg_evolution.py`: 49 testes de configuração, mercado,
  mineração, profissões, conquistas, exploração, OpenRouter, objetivos, casa,
  energia de 24h e combate.
- Documentação atualizada: `RPG_SYSTEM.md`, `PROFESSIONS.md`,
  `MARKET_CATALOG.md`, `FEATURE_STATUS.md`, `BUG_TRACKER.md`,
  `TASK_QUEUE.md`, `OPENROUTER_SETUP.md` e este handoff.
- `.env.example` atualizado com todas as variáveis opcionais do OpenRouter.

## Problemas conhecidos / pendências

1. A compra de casa não está exposta por comando após a remoção de `/casa`.
   A tabela e a leitura funcionam; falta uma interface sem criar novo slash
   command.
2. O OpenRouter foi validado com mocks. Não houve chamada real porque não há
   chave válida no ambiente.
3. Durabilidade de ferramentas não foi implementada.
4. O combate é simples e ainda não possui loot, habilidades ou classes; o
   balanceamento deve ser revisado com dados reais.
5. As alterações estão no working tree e ainda não foram commitadas. O
   repositório já tinha modificações anteriores não relacionadas; não reverta
   trabalho do usuário.

## Próxima ação exata

1. Revisar `git diff` e commitar apenas os arquivos do RPG/documentação.
2. Expor compra/melhoria de casa em comando existente e testar em guild real.
3. Quando houver chave, validar uma chamada real ao OpenRouter e conferir
   custos/limites.

## Como validar novamente

```bash
.venv/bin/python -m py_compile rpg_system/*.py rpg_system/ai/*.py cogs/rpg.py
.venv/bin/python -m unittest discover -s tests -v
```

Para o carregamento completo, usar `main.Shaggy` e carregar todos os módulos
de `cogs/`, conferindo contagem de comandos, duplicatas e falhas.
