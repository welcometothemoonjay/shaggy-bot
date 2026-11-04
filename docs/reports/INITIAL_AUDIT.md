# Auditoria Inicial - Shaggy Bot

Data: 2026-11-02
Agente: OpenCode (Big Pickle)

## Resumo
Projeto Discord.py 2.7.1 com múltiplos cogs carregados automaticamente por `main.py`. Usa SQLite em `data/shaggy.db`. Possui dois RPGs: RPG Textual (implementado agora em `cogs/rpg.py` com módulos `rpg_system/` e `rpg/`) e Ruptura Temporal (`cogs/ruptura.py`, `ruptura_extras.py`, `ruptura_pvp.py`). Economia centralizada via cog `XpAndCoins` (user_stats, Abysmus). 

## Estado verificado
- main.py carrega todos *.py em cogs/ exceto _*, sincroniza comandos globalmente e copia para guilds.
- XpAndCoins gerencia XP/níveis/Abysmus com transações, ledger e comandos admin.
- rupture_* integra com XpAndCoins via APIs.
- Tabelas rpg_* já existiam em `data/shaggy.db` - agora há cog `cogs/rpg.py` + pacotes `rpg_system/` e `rpg/` para orquestrar RPG textual.
- `ultility.py` existe (nomes como ultility). Precisa revisão para centralizar emojis.

## Observações
- Não há pytest configurado visivelmente; README menciona testes com unittest.
- Alguns arquivos .pyc e __pycache__ presentes.
- Git mostra alterações não commitadas (M/D/??).
