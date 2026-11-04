# TASK_QUEUE

Atualizado em 2026-11-03 após a evolução do RPG Textual.

## P0 — Crítico

- [x] Resolver o limite de slash commands (100 no carregamento verificado)
- [x] Garantir carregamento de todos os cogs sem falhas ou duplicatas
- [x] Corrigir transações aninhadas no SQLite
- [x] Tornar compras atômicas (nunca cobrar sem entregar)
- [x] Exigir picareta válida para minerar
- [x] Persistir localização e descobertas da exploração
- [x] Corrigir energia persistente e chave diária legada
- [x] Implementar recarga automática de 100% a cada 24h
- [x] Implementar combate simples com 5 inimigos e XP por golpe
- [x] Corrigir persistência de casa

## P1 — Alto

- [x] Compra/venda pelo nome, com normalização e ambiguidade
- [x] Autocomplete de itens, picaretas, profissões e regiões
- [x] Catálogo completo de 9 profissões, com requisitos e benefícios
- [x] Receitas reais para Artesão e Ferreiro
- [x] Picaretas Madeira→Infernal com chances exatas de Abysmus
- [x] Mineração com região, tier, Minerador e XP
- [x] Conquistas persistentes com recompensa idempotente
- [x] Verificação de conquistas após ações relevantes
- [x] Exploração com continuidade, eventos e descobertas
- [x] Narração OpenRouter com cache, timeout, retry e fallback
- [x] Descrições/utilitários/efeitos reais no catálogo
- [x] Próximos objetivos na ficha do jogador
- [x] Combate com mãos/itens, estado persistente, vitória, derrota e conquistas
- [x] Testes de mercado, mineração, profissões, conquistas, exploração, IA, metas, energia e combate

## P2 — Médio

- [ ] Expor compra/melhoria de casa sem criar novo slash command
- [ ] Validar uma chamada real ao OpenRouter com chave controlada
- [ ] Definir política de durabilidade antes de ativar o campo
- [ ] Testar autocomplete e embeds em uma guild real
- [ ] Auditar integrações do RPG com XpAndCoins e demais cogs
- [ ] Revisar textos de missões diárias herdadas
- [ ] Balancear recompensas de combate com dados reais de jogadores

## P3 — Baixo

- [ ] Novas receitas de Artesão/Ferreiro (desde que consumam recursos reais)
- [ ] Mais eventos regionais sem criar recompensas desbalanceadas
- [ ] Ajustar emojis e padronização visual dos embeds
- [ ] Documentar histórico de balanceamento econômico

## Fora de escopo / não fazer agora

- [ ] Expandir o combate para loot, habilidades ou classes antes de revisar o balanceamento
- [ ] Criar classes, raças ou sistemas gigantescos novos
- [ ] Adicionar cooldowns maiores ou retenção artificial
- [ ] Modificar o Ruptura Temporal

## Próxima ação recomendada

Expor a compra de casa em um comando existente (por exemplo, uma opção
opcional em `/descansar` ou `/personagem`) e validar o fluxo em guild real,
sem ultrapassar o limite de 100 slash commands.
