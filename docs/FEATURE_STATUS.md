# FEATURE_STATUS

Data da auditoria: 2026-11-03.

## RPG Textual

| Sistema | Estado | Evidência / observações |
|---|---|---|
| Personagem e XP | FUNCIONAL | Curva `40×N+40`; nível 1 em 0 XP; persistido em `rpg_personagem` |
| Profissões | FUNCIONAL | 9 profissões, catálogo, requisitos, XP, benefícios e receitas; 49 testes passam |
| Mercado por nome | FUNCIONAL | Normalização sem caixa/acentos, ambiguidade, compra atômica e ledger |
| Compra/venda atômica | FUNCIONAL | Testes de rollback, saldo insuficiente e compra ambígua sem cobrança |
| Picaretas (10 tiers) | FUNCIONAL | Madeira→Infernal; chances exatas; tabela validada por teste |
| Mineração | FUNCIONAL | Exige picareta, região, energia e cooldown; recompensas atômicas |
| Picareta inicial | FUNCIONAL | Entregue uma única vez via flag `picareta_inicial` |
| Equipamento de picareta | FUNCIONAL | `/equipar`; prioridade para equipada, fallback para melhor possuída |
| Conquistas | FUNCIONAL | 35 definidas; todas as categorias ativas, incluindo as 3 de combate |
| Combate | FUNCIONAL | 5 inimigos, turnos persistentes, mãos/itens, XP por golpe, vitória/derrota |
| Exploração | FUNCIONAL | Local/região persistentes, eventos, descobertas, energia e cooldown |
| Narração OpenRouter | FUNCIONAL COM RESSALVAS | Testada com mocks; sem chave válida não houve chamada real |
| Fallback sem OpenRouter | FUNCIONAL | Teste sem chave retorna descrição local e exploração continua |
| Cache de narrativas | FUNCIONAL | `rpg_narrativas`; TTL padrão 21.600 s; teste de cache passa |
| Descrições de itens | FUNCIONAL | Catálogo persistido em código; descrição, utilidade e efeito reais |
| Próximos objetivos | FUNCIONAL | Derivados do banco em `goals.py`; exibidos em `/rpg` e `/personagem` |
| Energia | FUNCIONAL | Persistente em `rpg_flags`; recarga de 100% a cada 24h; `/descansar` restaura e reinicia o ciclo |
| Casas | PARCIAL | Tabela e leitura funcionam; compra não está exposta após remover `/casa` |
| Durabilidade | NÃO IMPLEMENTADA | Campo reservado, sem consumo |
| Missões diárias | FUNCIONAL COM RESSALVAS | Comando carrega; lógica herdada, não coberta pelos testes novos |
| Relacionamento | FUNCIONAL COM RESSALVAS | Comandos carregam; não faz parte do escopo desta evolução |

## Outros sistemas do bot

| Sistema | Estado | Observações |
|---|---|---|
| XpAndCoins | FUNCIONAL | Economia central em `user_stats` |
| Ruptura Temporal | FUNCIONAL COM RESSALVAS | Independente; não foi modificado por esta evolução |
| Badges | FUNCIONAL COM RESSALVAS | Carrega no bot |
| Cassino/Jogos | FUNCIONAL COM RESSALVAS | Carrega; não testado funcionalmente nesta missão |
| Pets | FUNCIONAL COM RESSALVAS | Carrega; não testado funcionalmente nesta missão |
| Missões/Ranking | FUNCIONAL COM RESSALVAS | Carrega; não testado funcionalmente nesta missão |
| Social/IA/Lore/Místico | FUNCIONAL COM RESSALVAS | Carrega; não testado funcionalmente nesta missão |
| Utilitys | FUNCIONAL COM RESSALVAS | Carrega; não testado funcionalmente nesta missão |

## Validação executada

- `.venv/bin/python -m py_compile rpg_system/*.py rpg_system/ai/*.py cogs/rpg.py` — OK.
- `.venv/bin/python -m unittest discover -s tests -v` — **49 testes, OK**.
- Carregamento de todos os cogs com `main.Shaggy` — **100 comandos slash**,
  **0 duplicados**, **0 falhas**.
- Backup do banco real em `backups/shaggy.db.bak.20261103_143906`; os testes
  usam banco temporário via `SHAGGY_DB_PATH` e não tocam dados reais.

## Não testado nesta missão

- Chamada real ao OpenRouter com chave de produção.
- Interações Discord reais (cliques, autocomplete e respostas em guild).
- Fluxos de outros cogs fora do RPG Textual.
- Concorrência com múltiplos processos simultâneos (a atomicidade foi
  exercitada por transações e testes, não por carga real).
