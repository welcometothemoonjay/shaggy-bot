# AGENT_QUEUE - Fila de Tarefas

| ID | Prioridade | Sistema | Tarefa | Arquivos Relacionados | Dependências | Status | Critérios de Conclusão | Agente Responsável | Última Atualização |
|---|---|---|---|---|---|---|---|---|---|
| SHG-001 | P0 | Utilitys/Emojis | Revisar `cogs/ultility.py` e criar/aprimorar gerenciador central de emojis com fallbacks Unicode e verificação | `cogs/ultility.py`, `cogs/rpg.py`, `cogs/ruptura*.py` | - | READY | Gerenciador central importável, sem IDs hardcoded espalhados, fallbacks funcionais | - | 2026-11-02 |
| SHG-002 | P1 | RPG Textual | Padronizar interfaces do RPG Textual para usar gerenciador central de emojis | `cogs/rpg.py`, `rpg_system/views.py` | SHG-001 | READY | Embeds/menus do RPG textual usando gerenciador central | - | 2026-11-02 |
| SHG-003 | P1 | Ruptura Temporal | Padronizar interfaces da Ruptura Temporal para usar gerenciador central (mantendo identidade própria) | `cogs/ruptura.py`, `cogs/ruptura_extras.py`, `cogs/ruptura_pvp.py` | SHG-001 | READY | Uso via gerenciador central sem quebrar independência | - | 2026-11-02 |
| SHG-004 | P1 | Documentação | Reescrever `README.md` com estado real verificado | `README.md` | - | READY | README fiel ao código, sem funcionalidades planejadas anunciadas como implementadas | - | 2026-11-02 |
| SHG-005 | P1 | Documentação | Completar docs/ com systems, development, reports baseados no código | `docs/*` | - | READY | Documentação técnica baseada em implementação real | - | 2026-11-02 |
| SHG-006 | P2 | Auditoria | Verificar carregamento de cogs e possíveis conflitos de comandos | `main.py`, `cogs/*.py` | - | READY | Sem comandos com nomes conflitantes; carregamento validado | - | 2026-11-02 |
