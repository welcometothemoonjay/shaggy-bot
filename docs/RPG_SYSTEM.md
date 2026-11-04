# RPG_SYSTEM — Arquitetura e mecânicas

O RPG Textual é independente do Ruptura Temporal. Toda a mecânica é decidida
e persistida em Python; o OpenRouter, quando configurado, apenas produz texto
narrativo.

## Arquitetura

| Camada | Arquivo(s) | Responsabilidade |
|---|---|---|
| Cog Discord | `cogs/rpg.py` | Valida interação, chama os sistemas e monta os embeds |
| Domínio | `rpg_system/*.py` | Regras, cálculos, persistência e transações |
| IA narrativa | `rpg_system/ai/narrative.py` | Chamada opcional ao OpenRouter, cache e fallback |
| Banco | `rpg_system/database.py`, `schema.py` | SQLite, migrações aditivas, caminho configurável |
| Apresentação | `rpg_system/views.py`, `goals.py` | Ficha, conquistas e próximos objetivos |
| Economia | `rpg_system/economy.py` | Saldo em `user_stats.coins` |
| Inventário | `rpg_system/inventory.py` | Itens em `ruptura_inventario` |
| Combate | `rpg_system/combat.py` | Inimigos, turnos, dano, XP e recompensas |
| Energia | `rpg_system/energy.py` | Recarga automática de 100% a cada 24h |

O banco fica em `data/shaggy.db` por padrão. `SHAGGY_DB_PATH` permite usar um
banco temporário em testes. As transações usam `BEGIN IMMEDIATE`,
`busy_timeout = 15000` e `row_factory = sqlite3.Row`.

## Persistência

| Tabela | Uso |
|---|---|
| `rpg_personagem` | Nível, XP, região, classe e reputação |
| `rpg_profissoes` | Nível e XP por profissão aprendida |
| `rpg_profissoes_log` | Histórico de atividades profissionais |
| `rpg_equipamentos` | Picareta equipada por jogador |
| `rpg_acoes` | Histórico de ações (usado por conquistas) |
| `rpg_cooldowns` | Cooldowns por atividade/profissão |
| `rpg_flags` | Energia persistente, instante da recarga e flags idempotentes |
| `rpg_combates` | Estado do combate ativo (um por jogador) |
| `rpg_localizacao` | Local atual do jogador |
| `rpg_descobertas` | Locais já descobertos |
| `rpg_regioes` | Regiões já visitadas |
| `rpg_mineracao_stats` | Totais de mineração e maior tier usado |
| `rpg_transacoes` | Ledger de compras e vendas |
| `rpg_conquistas` | Conquistas desbloqueadas (chave única por jogador) |
| `rpg_casas` | Casa persistente (uma por jogador) |
| `rpg_narrativas` | Cache persistente de descrições do OpenRouter |
| `ruptura_inventario` | Inventário compartilhado de itens |
| `user_stats` | Saldo de Abysmus (`coins`) |

`rpg_contadores` é legado; a energia é migrada uma vez para `rpg_flags`.

## Comandos do RPG

São 19 comandos neste cog: `/rpg`, `/personagem`, `/mochila`, `/mineracao`,
`/trabalhar`, `/profissoes`, `/aprender_profissao`, `/mercador`, `/comprar`,
`/vender`, `/equipar`, `/explorar`, `/descansar`, `/combate`, `/rpgmissoes`,
`/conquistas`, `/energia`, `/relacionamento` e `/propor`.

O bot inteiro tem **100 comandos slash** no carregamento verificado; o limite
do Discord é 100. `/combate` ocupou a última vaga disponível. `/casa` foi
removido para liberar espaço e `/equipar` foi adicionado. As informações de
casa aparecem em `/rpg` e `/personagem`, mas a compra de casa ainda não está
exposta por comando (ver limitações).

## Progressão de personagem

- Nível 1 começa com 0 XP.
- Custo para ir do nível `N` ao `N+1`: `40 × N + 40` (80, 120, 160, 200…).
- `calcular_nivel` retorna nível, XP dentro do nível e XP necessário para o
  próximo.
- Fontes de XP: mineração, exploração, trabalho profissional, conquistas,
  combate e eventos.
- XP de combate: `1 + nível mínimo do inimigo ÷ 2` por golpe, mais o XP de
  vitória do inimigo.
- XP de mineração: `5 + tier da picareta + 2 × índice da região`.
- XP de trabalho: `4 + (nível da profissão ÷ 3)`.
- XP de exploração: `10 + 4 × índice da região + 0–8`, com bônus por
  descoberta (+10), nova região (+15), evento e nível de Explorador.

A ficha mostra barra de XP, próximo nível, região/local, profissões, casa,
saldo, energia, conquistas e até três próximos objetivos.

## Mundo

Cinco regiões e onze locais, com bloqueio por nível:

| Região | Nível mínimo | Locais | Multiplicador de moedas |
|---|---:|---|---:|
| Dakor | 1 | Planícies de Dakor, Floresta Verde, Mina Abandonada | 0.85 |
| Costa de Âmbar | 2 | Praia de Âmbar, Grutas Costeiras | 1.00 |
| Picos de Gelo | 4 | Vale Nevado, Caverna de Gelo | 1.15 |
| Deserto de Cinzas | 6 | Dunas de Cinzas, Ruínas Calcinadas (especial) | 1.30 |
| Abismo Umbral | 9 | Fenda Umbral, Coração Abissal (especial) | 1.50 |

Cada local tem bioma, clima, características, história, elementos ambientais e
coletas próprias. Dakor é sempre acessível; as demais regiões precisam estar
desbloqueadas por nível e descobertas por `/explorar` para permitir mineração.

## Mineração

1. Exige personagem, região válida e liberada, energia ≥ 10 e cooldown de
   **300 segundos** livre.
2. Exige possuir uma picareta. A equipada tem prioridade; sem equipamento, a
   melhor possuída é usada automaticamente.
3. Verifica o requisito de nível da picareta.
4. Sorteia materiais do pool da região, limitado ao tier da picareta.
5. Aplica o multiplicador de materiais da picareta e os bônus do Minerador.
6. Sorteia Abysmus com a chance exata do tier.
7. Consome energia, grava cooldown, itens, saldo, XP, estatísticas e histórico
   na mesma transação.

Chances de Abysmus por picareta:

| Tier | Picareta | Chance |
|---:|---|---:|
| 1 | Madeira | 10% |
| 2 | Pedra | 15% |
| 3 | Cobre | 20% |
| 4 | Ferro | 25% |
| 5 | Aço | 30% |
| 6 | Ouro | 40% |
| 7 | Diamante | 50% |
| 8 | Arcana | 60% |
| 9 | Abissal | 75% |
| 10 | Infernal | 100% |

Quantidade de moedas: base `1 + tier ÷ 2` até `3 + tier × 2`, multiplicada por
`coins_mult` da região, bônus de Minerador e
`1 + 0.5% × nível do personagem` (limitado a +25%), com teto de **60
Abysmus** por mineração. A chance de 100% da Infernal não remove esses limites.

Rolagens de materiais: 1 (tiers 1–3), 2 (4–6), 3 (7–9), 4 (tier 10). A
quantidade final é limitada a 25 por material.

## Combate

Combate simples por turnos, persistente entre usos de `/combate` e sem
cooldown adicional. Cada ação custa **4 de energia**.

| Inimigo | Nível mínimo | PV | Ataque | XP de vitória | Abysmus | Dificuldade |
|---|---:|---:|---|---:|---|---|
| 👺 Goblin | 1 | 35 | 4–7 | 28 | 8–18 | Fácil |
| 🧰 Mímico | 2 | 55 | 5–9 | 40 | 80–140 | Média |
| 😈 Diabrete | 3 | 70 | 8–13 | 55 | 20–35 | Média |
| 🪓 Orc | 5 | 110 | 12–18 | 85 | 35–60 | Difícil |
| 🐺 Cérbero | 8 | 170 | 14–20 | 180 | 120–200 | Lendário |

O Cérbero é o único inimigo **especial** e ativa a conquista
`cacador_lendas`. Abaixo de metade da vida ele entra em fúria e causa 35% mais
dano.

Fluxo:

1. `/combate inimigo:Nome` inicia a luta e já executa o turno 1.
2. `/combate` repete o ataque com a arma armazenada; `/combate arma:Nome`
   troca de arma sem reiniciar o combate.
3. Armas: as mãos causam `4 + nível ÷ 2` até `+3`; ferramentas usam
   `poder_combate = 4 + tier × 2`; qualquer outro item é improvisado e causa
   apenas 2–5 de dano.
4. O jogador tem `60 + 10 × nível` de PV. Há 12% de crítico (1,5× de dano) e
   8% de erro do inimigo.
5. Todo golpe concede XP. A vitória concede o XP e os Abysmus do inimigo; a
   derrota encerra a luta sem remover moedas.
6. Apenas um combate ativo por jogador. O estado fica em `rpg_combates` e
   energia, dano, XP, moedas, histórico e limpeza do estado são gravados na
   mesma transação.

## Energia

- Máximo de **100**. A energia volta a 100 sozinha a cada **24 horas**.
- A verificação é preguiçosa: ocorre na primeira leitura ou consumo após o
  intervalo, sem task em background.
- O instante da última recarga fica em `rpg_flags.energia_regen_em`.
- `/descansar` restaura tudo imediatamente, mantém cooldown de **600 s** e
  reinicia o ciclo de 24h para não conceder recarga duplicada.
- Custos: mineração **10**, exploração **5**, combate **4**.

## Mercado

Ver `docs/MARKET_CATALOG.md`. Pontos centrais:

- Compra e venda pelo nome, sem diferenciar caixa/acentos.
- Nome ambíguo lista opções e não cobra nada.
- Compra atômica: débito, item, ledger e histórico na mesma transação.
- Saldo insuficiente e requisito bloqueado são recusados antes do débito.
- Desconto de Mercador: 1% por nível, teto 15%.
- Venda: 50% do preço base + bônus de Mercador de 1% por nível, teto +10%.
- O catálogo e as descrições são persistidos em código; não são gerados a
  cada abertura.

## Profissões

Ver `docs/PROFESSIONS.md`. Nove profissões, progressão independente e
requisitos por nível de personagem. O jogador pode aprender várias. A
mineração não exige Minerador; a profissão apenas concede XP e bônus.

## Conquistas

`rpg_system/achievements_v2.py` possui **35 conquistas**: 8 de exploração, 11
de mineração, 4 de profissões, 5 de economia, 4 de progressão e 3 de combate.
As 3 de combate agora são alcançáveis: vitória, 10 vitórias e vitória sobre o
Cérbero especial.

- Desbloqueio persistente em `rpg_conquistas`, com chave única por jogador.
- `INSERT OR IGNORE` + verificação de `rowcount` impede recompensa duplicada.
- Recompensas de XP e Abysmus são creditadas na mesma transação do desbloqueio.
- A verificação ocorre após criação, mineração, exploração, compra, combate,
  aprendizagem/trabalho profissional e ao abrir `/conquistas`.
- `/conquistas` aceita filtro por categoria e mostra progresso/meta.

## Exploração

- Cooldown de **120 segundos** e custo de **5 de energia**.
- Região bloqueada por nível; Dakor não exige descoberta prévia.
- Continuidade: 62% de chance de permanecer no local atual da mesma região;
  caso contrário, sorteia outro local da região.
- Persiste local atual, descobertas, região visitada e região do personagem.
- Recompensas: XP, chance de 55% de 0–`2 + 2 × índice` Abysmus, item de evento
  ou 32% de item das coletas locais, com chance de quantidade 2.
- Eventos ocorrem com 38% de chance e são definidos no código; a IA apenas os
  narra.
- A descrição vem do OpenRouter com fallback local. Ver
  `docs/OPENROUTER_SETUP.md`.

## Interface e progressão percebida

- `/rpg` cria o personagem e entrega a Picareta de Madeira uma única vez.
- `/personagem` reúne ficha, saldo, energia com recarga, profissões, casa,
  conquistas, estatísticas de combate e até quatro próximos objetivos.
- `/mochila` agrupa itens por categoria e mostra a picareta em uso.
- `/mercador item:Nome` mostra descrição, utilidade, efeito real, requisitos e
  atributos de mineração.
- Resultados de mineração, trabalho e exploração mostram recompensas, XP,
  progresso profissional e cooldowns.
- `/combate` mostra catálogo, PV, dano, crítico, recompensas e energia. Sem
  combate ativo, abre o catálogo dos cinco inimigos.
- `goals.py` deriva objetivos do estado real: próximo nível, próxima
  profissão, próxima picareta e saldo faltante, região não explorada, combate
  (ativo, primeira vitória ou 10 vitórias) e conquista com maior progresso.

## Limitações atuais

- O combate é simples: não há esquiva ativa, habilidades, classes de combate,
  loot de inimigo nem durabilidade de arma.
- Durabilidade de ferramentas não está implementada (`durabilidade = 0`).
- A compra de casa não tem comando próprio após a remoção de `/casa`; a
  tabela e a leitura continuam funcionais.
- O OpenRouter foi validado com mocks; não há chamada real comprovada sem uma
  chave válida no ambiente.
- A casa é cosmética/econômica; não concede bônus mecânicos.
