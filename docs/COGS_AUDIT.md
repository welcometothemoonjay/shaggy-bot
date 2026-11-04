# COGS_AUDIT

Data: 2026-11-03
Agente: OpenCode 2

## Inventário
| Cog | Slash | Prefixo | Grupos | Estado | Observações |
|---|---|---|---|---|---|
| GameSFA | + | - | sfa | FUNCIONAL COM RESSALVAS | Carrega OK |
| XpAndCoins | + | - | - | FUNCIONAL | Essencial economia/XP |
| badges | + | - | - | FUNCIONAL COM RESSALVAS | Carrega OK |
| cassino | + | + | - | FUNCIONAL COM RESSALVAS | Carrega OK |
| games | + | + | - | FUNCIONAL COM RESSALVAS | Carrega OK |
| ia | + | - | - | FUNCIONAL COM RESSALVAS | Carrega OK |
| lore | + | - | - | FUNCIONAL COM RESSALVAS | Carrega OK |
| missoes | + | - | - | FUNCIONAL COM RESSALVAS | Carrega OK |
| mystic | + | - | - | FUNCIONAL COM RESSALVAS | Carrega OK |
| noticias_ia | + | + | - | FUNCIONAL COM RESSALVAS | Carrega OK |
| pet | + | - | - | FUNCIONAL COM RESSALVAS | Carrega OK |
| ranking | + | - | - | FUNCIONAL COM RESSALVAS | Carrega OK |
| rpg | + | - | - | PARCIAL | RPG Textual orquestrado por módulos |
| ruptura | + | + | - | FUNCIONAL COM RESSALVAS | Independente |
| ruptura_extras | + | - | - | FUNCIONAL COM RESSALVAS | Extensões |
| ruptura_pvp | + | + | - | FUNCIONAL COM RESSALVAS | PvP |
| social | + | + | - | FUNCIONAL COM RESSALVAS | Prefixos adicionados |
| ultility | + (reduzido) | + | membro/cargo/dev | FUNCIONAL COM RESSALVAS | Defensivo por limite de comandos |

## Métricas
- Cogs auditados: 18
- Comandos slash carregados: **100**
- Compilação: OK
- Imports: OK


## FASE 3 - Integração
- Economia via XpAndCoins: OK
- RPG usa rpg_* tables: OK
- Ruptura usa tabelas próprias + integra com XpAndCoins: OK
- Inventário compartilhado (ruptura_inventario): OK
