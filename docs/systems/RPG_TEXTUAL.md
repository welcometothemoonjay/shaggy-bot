# RPG Textual

## Objetivo
Sistema RPG persistente integrado ao bot, orquestrado por cog com módulos especializados.

## Implementação
- Cog orquestrador: `cogs/rpg.py`
- Pacote domínio: `rpg/` (delegação)
- Pacote especializado: `rpg_system/` (`constants`, `database`, `models`, `items`, `inventory`, `economy`, `progression`, `energy`, `mining`, `professions`, `theft`, `houses`, `marriage`, `missions`, `activities`, `market`, `achievements`, `views`)

## Integração
- Usa tabelas `rpg_*` em `data/shaggy.db`
- Usa `ruptura_inventario` para itens
- Integra com cog `XpAndCoins` para Abysmus/XP

## Comandos (slash)
`/rpg`, `/personagem`, `/mochila`, `/mineracao`, `/trabalhar`, `/explorar`, `/descansar`, `/rpgmissoes`, `/profissoes`, `/mercador`, `/comprar`, `/vender`, `/relacionamento`, `/propor`, `/divorcio`, `/conquistas`, `/energia`, `/aprender_profissao`, `/roubar`, `/casa`, `/comprar_casa`, `/melhorar_casa`

## Dependências
`XpAndCoins` carregado para economia/XP.

## Estado
Implementado e carregável. Funcionalidades persistentes via SQLite.
