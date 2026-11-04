# Arquitetura

## Carregamento
`main.py` inicializa `Shaggy(commands.Bot)`. Em `setup_hook()` carrega todos os arquivos `.py` em `cogs/` exceto os que começam com `_`, com `load_extension("cogs.<nome>")`. Após carregar, sincroniza globalmente com `bot.tree.sync()`. Em `on_ready()`, copia comandos globais para cada guild e sincroniza localmente para aparecer imediatamente.

## Cogs
Módulos Discord.py em `cogs/`. Cada cog registra comandos slash/app_commands e views.

## Domínio RPG Textual
- `rpg_system/`: regras de negócio puras/modulares (sem dependência forte de Discord)
- `rpg_system/energy.py`: energia persistente com recarga de 100% a cada 24h
- `rpg_system/combat.py`: combate por turnos, 5 inimigos e estado em `rpg_combates`
- `rpg/`: camada de delegação seguindo estrutura esperada
- `cogs/rpg.py`: orquestrador Discord

## Economia
`XpAndCoins` é central. Outros sistemas usam `bot.get_cog("XpAndCoins")` e suas APIs/transações.

## Banco
SQLite em `data/shaggy.db`. Padrão transacional com `BEGIN IMMEDIATE` em vários locais. Tabelas organizadas por domínio.

## Ruptura Temporal
Independente, em `cogs/ruptura*.py`.
