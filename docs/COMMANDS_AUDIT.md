# Commands Audit - Shaggy Bot

Data: 2026-11-02

## Contagem inicial (verificada)
- `@app_commands.command`: ~105 ocorrências em cogs/
- `app_commands.Group`: utilitys (membro, cargo, dev), GameSFA (sfa)
- `@commands.command` (prefixo): 7 ocorrências
- Comandos híbridos/prefixo existem em vários lugares

## Observação
Discord global slash limit é 100. Com ~105 comandos slash diretos + subcomandos/grupos, é fácil ultrapassar ou aproximar do limite causando `CommandLimitReached`.

## Estratégia proposta
1. Agrupar comandos não-críticos em grupos slash (ex: utilitários sociais/info) quando fizer sentido
2. Converter comandos secundários para prefixo `s!` mantendo funcionalidade e permissões
3. Não tocar em comandos essenciais de economia, RPG, Ruptura Temporal
4. Melhorar logs em main.py e tratamento de erro no carregamento
5. Avaliar sync - evitar syncs redundantes


## Contagem atual
- Comandos slash diretos (@app_commands.command): 105
- Grupos: membro/cargo/dev (ultility), sfa (GameSFA)
- Comandos prefixo: ~7

**Ação necessária:** Reduzir comandos globais abaixo de 100. Converter comandos secundários para prefixo ou agrupar.


## Ações tomadas
- Adicionados comandos prefixo em cogs/social.py (ola, abracar, beijar, elogiar)
- main.py com logs aprimorados
- Gerenciador central de emojis adicionado em ultility.py

## Recomendação
Para ficar abaixo de 100, converter mais comandos secundários para prefixo ou agrupar em grupos. Com subcomandos, o total pode ser maior - considerar mover comandos informativos/social menos usados para prefixo.


## Fix aplicado
- main.py agora pula sync global apenas se **mais de 100** comandos ou em caso de CommandLimitReached, continua carregamento sem falhar
- Com **exatamente 100** comandos, o sync global é executado
- Adicionados comandos prefixo em ultility.py (avatar, usuario, servidor, ping)

## Estado após evolução do RPG (2026-11-03)
- Total verificado: **100 comandos slash**, 0 duplicados
- `/combate` ocupou a última vaga disponível
- O limite do Discord é 100; qualquer novo slash command exige remover ou agrupar outro
