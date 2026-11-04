# BUG_TRACKER

Data: 2026-11-03

## Corrigidos nesta evolução

| ID | Severidade | Sistema | Problema encontrado | Causa | Correção | Status |
|---|---|---|---|---|---|---|
| BUG-001 | P0 | Comandos | Limite de 100 slash commands | Crescimento de comandos por cog | `/casa` removido, `/equipar` e `/combate` adicionados; total verificado em 100 | CORRIGIDO |
| BUG-002 | P0 | Banco | `database is locked` em progressão/profissões | `BEGIN IMMEDIATE` aninhado | Helpers `*_tx` e uma única transação por ação | CORRIGIDO |
| BUG-003 | P0 | Mercado | Compra só aceitava `key` interna | Comando expunha IDs e não resolvia nomes | Resolução por nome com normalização, aliases e ambiguidade | CORRIGIDO |
| BUG-004 | P0 | Mercado | Risco de cobrar sem entregar item | Débito e entrega em etapas/transações separadas | Débito, item, ledger e histórico na mesma transação | CORRIGIDO |
| BUG-005 | P1 | Mineração | Era possível minerar sem picareta | Falta de validação de posse/equipamento | Picareta obrigatória; equipada tem prioridade, senão a melhor possuída | CORRIGIDO |
| BUG-006 | P1 | Mineração | Sem recompensa de Abysmus por tier | Mineração antiga não sorteava moedas | Chances exatas por picareta, com teto de 60 Abysmus | CORRIGIDO |
| BUG-007 | P1 | Mineração | Região e profissão não influenciavam | Cálculo antigo ignorava região/Minerador | Materiais por região/tier, bônus de Minerador e XP profissional | CORRIGIDO |
| BUG-008 | P1 | Conquistas | `verificar()` nunca era chamado | Fluxo de comandos não disparava a verificação | Verificação após criar, minerar, explorar, comprar, aprender/trabalhar e ao abrir `/conquistas` | CORRIGIDO |
| BUG-009 | P1 | Conquistas | Risco de recompensa duplicada | Verificação sem unicidade robusta | `INSERT OR IGNORE` + `rowcount` + PK por jogador/chave | CORRIGIDO |
| BUG-010 | P1 | Exploração | Local/região não persistiam | Estado calculado e descartado | `rpg_localizacao`, `rpg_descobertas`, `rpg_regioes` e `rpg_personagem.regiao` | CORRIGIDO |
| BUG-011 | P1 | Energia | Energia “sumia” ou mudava por dia | Uso de `rpg_contadores` com a data na chave | Energia em `rpg_flags`, com migração única do legado | CORRIGIDO |
| BUG-012 | P1 | Casas | Casa desaparecia no dia seguinte | Mesmo problema de chave diária em `rpg_contadores` | Tabela `rpg_casas`, uma por jogador | CORRIGIDO |
| BUG-013 | P2 | IA | Import duplicado no módulo narrativo | `from .ai.narrative` dentro do próprio pacote | Import removido; módulo usa dependências locais | CORRIGIDO |
| BUG-014 | P2 | Mundo | `ImportError: REGIOES` | Código novo usava plural e o módulo antigo expunha `REGIOS` | Alias `REGIOES = REGIOS` sem duplicar dados | CORRIGIDO |
| BUG-015 | P2 | Profissões | Benefício de nível 10 do Minerador não era aplicado | Bônus raro existia no cálculo, mas não era passado ao sorteio | Rolagem extra de material raro no sorteio | CORRIGIDO |
| BUG-016 | P2 | Profissões | Texto de produção extra não batia com a fórmula | Fórmula linear divergia dos marcos 2/5/10 | Fórmula ajustada para 10%/25%/50% | CORRIGIDO |
| BUG-017 | P2 | Profissões | Descrições de bônus de coleta prometiam valores diferentes dos reais | Texto herdado sem vínculo com a fórmula | Descrições alinhadas aos valores reais (3%/12%/27% e +2%/+8%/+18%) | CORRIGIDO |
| BUG-018 | P2 | Mercado | Venda podia gerar arbitragem | Base de venda elevada | Venda fixada em 50% do preço base + bônus de Mercador limitado | CORRIGIDO |
| BUG-019 | P1 | Energia | Energia não recuperava com o tempo | Só `/descansar` restaurava | Recarga preguiçosa de 100% a cada 24h em `rpg_flags`; descanso reinicia o ciclo | CORRIGIDO |
| BUG-020 | P2 | Combate | 3 conquistas de combate sem fonte de progresso | Combate não existia | Combate por turnos com 5 inimigos, XP por golpe e vitória/derrota persistidas | CORRIGIDO |

## Pendentes / limitações conhecidas

| ID | Severidade | Sistema | Situação | Próxima ação |
|---|---|---|---|---|
| OPEN-001 | P2 | Casas | Compra não exposta após remover `/casa` | Expor compra/melhoria em um comando existente, sem criar novo slash command |
| OPEN-002 | P2 | OpenRouter | Sem chave real no ambiente; testes usam mocks | Validar uma chamada real em ambiente controlado e revisar custos |
| OPEN-003 | P3 | Ferramentas | Durabilidade não implementada | Definir regra de consumo antes de ativar o campo |
| OPEN-004 | P2 | Bot geral | Integrações entre cogs não foram auditadas nesta missão | Auditoria independente fora do escopo do RPG |

## Observação

Os testes usam `SHAGGY_DB_PATH` com banco temporário e mocks. Nenhum jogador
real recebeu recompensa durante a validação. O backup do banco real está em
`backups/shaggy.db.bak.20261103_143906`.
