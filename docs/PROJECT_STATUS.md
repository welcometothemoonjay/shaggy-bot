# PROJECT_STATUS

Data: 2026-11-03
Agente: OpenCode 2

## Estrutura
- main.py: bot Shaggy, carregamento automático de cogs/, sync global+guild
- cogs/: 18 arquivos (incluindo rpg.py)
- rpg/: delegação
- rpg_system/: módulos especializados
- data/shaggy.db
- docs/

## Estado
Em auditoria completa conforme missão. O RPG Textual possui personagem,
profissões, mercado, mineração, exploração, energia com recarga de 24h,
combate com 5 inimigos, conquistas e casa.

## Problemas conhecidos
- Limite de 100 slash commands **atingido**: novos comandos exigem remover ou
  agrupar outro.
- Compra de casa ainda não exposta por comando.
- OpenRouter validado apenas com mocks.
