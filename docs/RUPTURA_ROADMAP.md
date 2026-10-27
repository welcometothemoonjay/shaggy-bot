# Roadmap — Ruptura Temporal

**Base:** auditoria de 26/10/2026, commit `9cb5c19`; status atualizado após a
Expansão 3 (alterações ainda não commitadas; HEAD `4e32aa4`).
**Objetivo:** organizar melhorias da Ruptura Temporal por problema, impacto e custo, sem
alterar balanceamento, recompensas ou esquema de dados nesta fase.

> Este documento é **propositivo**. Nada aqui foi implementado. Propostas que tocam
> balanceamento (chances, dano, recompensas, escalas, atributos) exigem autorização
> explícita antes de qualquer mudança.

## Legenda

- **Prioridade P0:** corrigir antes de nova expansão de conteúdo.
- **P1:** próximo ciclo; alto retorno e risco controlado.
- **P2:** evolução planejada; depende de P0/P1.
- **P3:** oportunidade futura; não bloqueia o presente.
- **Complexidade:** baixa, média ou alta.
- **Critério de aceitação:** condição objetiva e verificável para considerar a proposta
  concluída.

## Visão geral

| ID | Proposta | Categoria | Prioridade | Complexidade |
| --- | --- | --- | --- | --- |
| BUG-01 | Guarda única de estado PvE/PvP | Bugs | P0 | Baixa |
| BUG-02 | Finalização de runs no unload | Bugs | P0 | Média |
| BUG-03 | Reconciliação de recompensas | Bugs | P0 | Média |
| BUG-04 | Chave de run por guild | Bugs | P1 | Média |
| BUG-05 | Liberação de estado PvP em falha de interação | Bugs | P1 | Baixa |
| CMB-01 | Leitura tática do turno | Combate | P1 | Baixa |
| CMB-02 | Resumo de status e efeitos | Combate | P1 | Baixa |
| CMB-03 | Log de combate reproduzível | Combate | P2 | Média |
| CMB-04 | Variedade de intenções sem inflar dano | Combate | P2 | Média |
| CLS-01 | Presets de build | Classes/builds | P1 | Média |
| CLS-02 | Comparação de especializações | Classes/builds | P2 | Baixa |
| CLS-03 | Validação e clareza dos nós | Classes/builds | P1 | Baixa |
| BOSS-01 | Telemetria de adaptação | Chefes | P2 | Baixa |
| BOSS-02 | Dicas de contra-jogo | Chefes | P1 | Baixa |
| BOSS-03 | Fases de Chefe | Chefes | P2 | Alta |
| ITM-01 | Fluxo de uso de item | Itens/economia | P1 | Média |
| ITM-02 | Transparência do mercado | Itens/economia | P1 | Baixa |
| ITM-03 | Ledger de economia da run | Itens/economia | P1 | Média |
| CRE-01 | Cobertura e consistência do bestiário | Criaturas/eventos | P2 | Média |
| CRE-02 | Cadeias de eventos | Criaturas/eventos | P2 | Média |
| CRE-03 | Calendário sazonal visível | Criaturas/eventos | P1 | Baixa |
| PRG-01 | Progressão meta-cósmica | Progressão | P2 | Alta |
| PRG-02 | Desafios diários/semanais | Progressão | P1 | Média |
| PRG-03 | Histórico e score de run | Progressão | P1 | Baixa |
| UX-01 | Densidade do embed de combate | UX | P1 | Baixa |
| UX-02 | Layout e acessibilidade dos botões | UX | P1 | Baixa |
| UX-03 | Onboarding e tutorial | UX | P1 | Média |
| UX-04 | Resumo pós-run | UX | P1 | Baixa |
| TST-01 | Separar motor e UI | Testabilidade | P0 | Alta |
| TST-02 | RNG injetável | Testabilidade | P1 | Média |
| TST-03 | Camada de banco e concorrência | Testabilidade | P1 | Média |
| TST-04 | Suítes de economia e cassino | Testabilidade | P0 | Média |
| TST-05 | Simulador de progressão | Testabilidade | P2 | Média |

## Status de execução

- **Concluído em 26/10/2026:** BUG-01 — guarda única de estado PvE/PvP, com
  `estado_jogador_ocupado()` compartilhado e cobertura automatizada nos dois sentidos.
- **Concluído em 26/10/2026:** BUG-05 — liberação de `ocupados` quando a abertura da
  escolha de classe ou a confirmação do duelo falha, com testes de regressão.
- **Concluído em 26/10/2026:** Expansão 3 — **36 criaturas** (18 mini-Chefes e 18 Chefes,
  6 + 6 por era), com 36 habilidades exclusivas, contrajogo telegrafado e testes de
  catálogo, combate, integração e recompensa. Catálogo atual: **91 criaturas** e **68
  habilidades**.
- **Em andamento:** nenhum item.
- **Próximo recomendado:** BUG-02 — finalização de runs no unload.
- **Pendentes:** todas as demais propostas desta lista.

---

## 1. Correções de bugs

### BUG-01 — Guarda única de estado PvE/PvP

**Status:** concluído em 26/10/2026.

- **Problema/oportunidade:** o PvP verifica `runs_ativas`, mas o PvE não verifica
  `RupturaDuelo.ocupados`. Um jogador em convite/duelo pode iniciar uma run.
- **Solução:** centralizar a checagem “jogador disponível?” em uma função compartilhada
  (por exemplo, no Cog de duelo ou em um serviço neutro) e chamá-la tanto em
  `s!ruptura` quanto em `s!duelo`.
- **Impacto:** elimina estados sobrepostos e bugs difíceis de reproduzir.
- **Complexidade:** Baixa.
- **Dependências:** nenhuma; só os dois Cogs.
- **Riscos:** bloquear jogadores legítimos se a função for usada em fluxos que hoje são
  permitidos; cobrir com teste.
- **Prioridade:** P0.
- **Critério de aceitação:** teste automatizado prova que PvE e PvP são mutuamente
  exclusivos por jogador, com mensagem clara nos dois sentidos.
- **Implementação:** `cogs/ruptura.py` ganhou `estado_jogador_ocupado()`, usado por
  `s!ruptura`, por `iniciar_run()` e por `RupturaDuelo.motivo_indisponivel()`. A checagem
  também cobre a janela entre abrir a escolha de classe e confirmar a run.

### BUG-02 — Finalização de runs no unload

- **Problema/oportunidade:** `cog_unload()` limpa `runs_ativas` sem finalizar, premiar ou
  devolver itens.
- **Solução:** percorrer as runs no unload e chamar um caminho de finalização seguro
  (persistência + evento de ranking), sem depender de edição de mensagem no Discord;
  opcionalmente, persistir um snapshot mínimo para retomada.
- **Impacto:** evita perda silenciosa de progresso e itens em reload/restart.
- **Complexidade:** Média.
- **Dependências:** `finalizar_run`, `award_rewards`, decisão sobre retomada.
- **Riscos:** finalizar durante desligamento pode falhar no banco; precisa ser idempotente
  e best-effort.
- **Prioridade:** P0.
- **Critério de aceitação:** teste com Cog descarregado confirma que cada run ativa foi
  finalizada uma única vez (ou explicitamente marcada como abortada) e que o ranking não
  recebe duplicata.

### BUG-03 — Reconciliação de recompensas

- **Problema/oportunidade:** falha em `award_rewards` é registrada e o fluxo continua; o
  jogador pode perder XP/Abysmus sem compensação.
- **Solução:** registrar recompensas pendentes em uma outbox/ledger com `run_id`,
  `user_id`, `guild_id`, valores e status; reprocessar em background ou no início da
  próxima interação.
- **Impacto:** consistência econômica e confiança do jogador.
- **Complexidade:** Média.
- **Dependências:** tabela nova (requer autorização), API de `XpAndCoins`, idempotência.
- **Riscos:** duplicar recompensa se a chave de idempotência for mal definida.
- **Prioridade:** P0.
- **Critério de aceitação:** simulação de falha do XpAndCoins deixa a recompensa
  pendente; reprocessamento credita exatamente uma vez.

### BUG-04 — Chave de run por guild

- **Problema/oportunidade:** `runs_ativas` usa apenas `user_id`; uma run em um servidor
  bloqueia o jogador em outro.
- **Solução:** decidir explicitamente entre “uma run global por usuário” (documentado) ou
  chave `(guild_id, user_id)` em `runs_ativas`, PvP e build.
- **Impacto:** remove bloqueio inesperado entre comunidades; alinha o estado ao
  `RunState.guild_id`.
- **Complexidade:** Média.
- **Dependências:** `runs_ativas`, `RupturaDuelo.ocupados`, `_locks_build`,
  `_locks_mercado`.
- **Riscos:** multiplicar runs simultâneas por jogador e aumentar carga; decidir com dados.
- **Prioridade:** P1.
- **Critério de aceitação:** comportamento documentado e testado para dois guilds; nenhuma
  colisão de locks.

### BUG-05 — Liberação de estado PvP em falha de interação

**Status:** concluído em 26/10/2026.

- **Problema/oportunidade:** `ConviteDuelo.aceitar` reservava o desafiado e depois editava
  a mensagem; `EscolhaClasse.escolher` marcava `iniciando` e chamava `stop()` antes de
  `interaction.response.defer()`. Uma exceção nesses pontos deixava os dois jogadores em
  `RupturaDuelo.ocupados` para sempre, bloqueando PvE e PvP até reiniciar o bot.
- **Solução:** liberar os dois jogadores quando a tela de escolha não pode ser aberta e
  quando a confirmação da escolha falha antes de `iniciar_duelo()`; a falha de
  `original_response()` apenas é registrada, pois a tela já está ativa e tem timeout.
- **Impacto:** elimina bloqueio permanente causado por erro de rede/HTTP ou interação
  expirada, sem mexer nas regras do duelo.
- **Complexidade:** Baixa.
- **Dependências:** `ConviteDuelo`, `EscolhaClasse`, `RupturaDuelo.liberar`.
- **Riscos:** liberar cedo demais e permitir duelo duplicado; o fluxo só libera quando a
  tela/confirmação não foi efetivada.
- **Prioridade:** P1.
- **Critério de aceitação:** teste com falha simulada em `edit_message` e em `defer`
  confirma que `ocupados` volta a ficar vazio; o teste de concorrência confirma que duas
  `iniciar_run()` simultâneas criam uma única run.

---

## 2. Qualidade do combate

### CMB-01 — Leitura tática do turno

- **Problema/oportunidade:** o embed já mostra intenção, mas o jogador precisa cruzar
  várias linhas para saber o que é urgente.
- **Solução:** destacar no topo do embed a ameaça atual (“Golpe Pesado — interrompa com
  Guardar/atordoamento”), o recurso disponível e a ação recomendada, sem revelar números
  ocultos.
- **Impacto:** reduz erros de leitura e torna o combate mais legível.
- **Complexidade:** Baixa.
- **Dependências:** `criar_embed`, `AcaoInimiga`.
- **Riscos:** excesso de texto; validar limite de 1024/4096 caracteres.
- **Prioridade:** P1.
- **Critério de aceitação:** teste de embed garante a linha de ameaça e o limite de
  tamanho em todos os estados (sem inimigo, telegrafado, atordoado).

### CMB-02 — Resumo de status e efeitos

- **Problema/oportunidade:** status como veneno, sangria, marca, fraqueza e barreira
  aparecem dispersos no log.
- **Solução:** bloco compacto “Seus efeitos” / “Efeitos do inimigo” com turnos restantes e
  origem.
- **Impacto:** melhora a tomada de decisão e a sensação de controle.
- **Complexidade:** Baixa.
- **Dependências:** `RunState`, `EnemyState`, `Efeito`.
- **Riscos:** duplicar informação já presente; manter o log curto.
- **Prioridade:** P1.
- **Critério de aceitação:** cada status ativo aparece uma vez, com duração correta, e
  desaparece no turno seguinte ao fim.

### CMB-03 — Log de combate reproduzível

- **Problema/oportunidade:** o log é textual e volátil; bugs de combate são difíceis de
  reproduzir.
- **Solução:** registrar um log estruturado por turno (ação, RNG relevante, dano, efeitos)
  em memória e incluí-lo no evento final, sem persistir dados sensíveis.
- **Impacto:** acelera diagnóstico e testes de regressão.
- **Complexidade:** Média.
- **Dependências:** `executar_ataque`, `turno_inimigo`, `finalizar_run`.
- **Riscos:** volume de log e exposição de informação; limitar a N turnos.
- **Prioridade:** P2.
- **Critério de aceitação:** uma run de teste gera um log estruturado que permite
  reconstruir dano e ordem de ações.

### CMB-04 — Variedade de intenções sem inflar dano

- **Problema/oportunidade:** criaturas comuns mantêm o golpe básico; a variedade tática
  fica concentrada em Chefes.
- **Solução:** permitir que criaturas normais usem uma intenção simples de “preparar”
  (sem aumento de dano), apenas para ensinar leitura tática; a decisão de dano fica para
  autorização de balanceamento.
- **Impacto:** combate inicial mais interessante sem mudar a curva.
- **Complexidade:** Média.
- **Dependências:** `HabilidadeInimiga`, `escolher_acao_chefe`, testes de combate.
- **Riscos:** alterar dificuldade percebida; começar por uma única criatura e medir.
- **Prioridade:** P2.
- **Critério de aceitação:** criatura piloto telegrafa e pode ser interrompida; testes
  provam que o dano esperado não aumentou.

---

## 3. Classes e builds

### CLS-01 — Presets de build

- **Problema/oportunidade:** trocar de especialização/nós exige reconstruir a build
  manualmente; jogadores experientes repetem cliques.
- **Solução:** salvar até 2 presets por classe (nós + spec) e permitir aplicar, com
  validação de pontos e custo explícito.
- **Impacto:** mais experimentação e repetibilidade.
- **Complexidade:** Média.
- **Dependências:** `rt_build_*`, `BuildRepo`, UI de `/build`.
- **Riscos:** presets inválidos após mudança de árvore; versionar ou validar na aplicação.
- **Prioridade:** P1.
- **Critério de aceitação:** aplicar preset restaura exatamente os nós pagos; preset
  inválido é rejeitado sem cobrar.

### CLS-02 — Comparação de especializações

- **Problema/oportunidade:** a tela de escolha mostra descrições, mas não o impacto
  relativo.
- **Solução:** mostrar um resumo comparativo (ativas, passivas, sinergia com itens) sem
  prometer números de dano que o motor não calcula.
- **Impacto:** decisão mais informada e menos arrependimento.
- **Complexidade:** Baixa.
- **Dependências:** `ESPECS`, `TelaClasse`.
- **Riscos:** texto excessivo; manter objetivos.
- **Prioridade:** P2.
- **Critério de aceitação:** cada especialização exibe os mesmos campos comparáveis e o
  embed respeita o limite.

### CLS-03 — Validação e clareza dos nós

- **Problema/oportunidade:** 150 nós e regras de pré-requisito podem gerar dúvida sobre o
  que está disponível e por quê.
- **Solução:** exibir motivo de bloqueio (nó anterior, nível, classe, pontos) e validar
  pré-requisitos também no servidor, não só na UI.
- **Impacto:** menos compras frustradas e menos suporte.
- **Complexidade:** Baixa.
- **Dependências:** `validar_arvores`, `BuildRepo.desbloquear`.
- **Riscos:** revelar demais; manter mensagens curtas.
- **Prioridade:** P1.
- **Critério de aceitação:** tentativa de compra inválida retorna motivo específico e não
  altera créditos/saldo.

---

## 4. Chefes adaptativos

### BOSS-01 — Telemetria de adaptação

- **Problema/oportunidade:** a adaptação existe, mas não há visibilidade de quantas vezes
  dispara nem se está concentrada em um padrão.
- **Solução:** contar adaptações por criatura/classe no evento da run e expor no resumo
  final; opcionalmente, um comando de diagnóstico para desenvolvedores.
- **Impacto:** permite avaliar se a mecânica é rara demais ou previsível.
- **Complexidade:** Baixa.
- **Dependências:** `MemoriaChefe`, `EnemyState`, `finalizar_run`.
- **Riscos:** dados em memória; não persistir sem autorização.
- **Prioridade:** P2.
- **Critério de aceitação:** o resumo final mostra adaptações por criatura sem alterar o
  combate.

### BOSS-02 — Dicas de contra-jogo

- **Problema/oportunidade:** o jogador pode não entender como interromper uma ação
  telegrafada.
- **Solução:** incluir uma dica curta e contextual (“Guardar interrompe; atordoamento
  também”) somente quando a ação for telegrafada.
- **Impacto:** reduz frustração e ensina a mecânica.
- **Complexidade:** Baixa.
- **Dependências:** `criar_embed`, `AcaoInimiga`.
- **Riscos:** repetição; mostrar só nas primeiras ocorrências por run.
- **Prioridade:** P1.
- **Critério de aceitação:** a dica aparece na primeira telegrafia de cada tipo e não
  aparece quando não há ação pendente.

### BOSS-03 — Fases de Chefe

- **Problema/oportunidade:** Chefes têm comportamento tático, mas não mudam de fase ao
  longo da luta.
- **Solução:** definir 2 fases com transição telegrafada, reutilizando o motor de
  intenções; **sem alterar dano/vida sem autorização**.
- **Impacto:** lutas mais memoráveis e maior variedade percebida.
- **Complexidade:** Alta.
- **Dependências:** `EnemyState`, `HabilidadeInimiga`, balanceamento autorizado.
- **Riscos:** inflar duração ou dificuldade; exige simulação e teste.
- **Prioridade:** P2.
- **Critério de aceitação:** Chefe piloto muda de fase uma vez, com aviso claro e sem
  aumentar o dano esperado fora do orçamento aprovado.

---

## 5. Itens e economia

### ITM-01 — Fluxo de uso de item

- **Problema/oportunidade:** a mochila compartilha espaço com ações de combate e o uso
  gasta o turno; jogadores podem se perder entre “usar” e “equipar”.
- **Solução:** separar visualmente “usar agora” de “equipado na run”, mostrar quantidade e
  confirmar itens estratégicos de uso único.
- **Impacto:** menos cliques errados e menos itens desperdiçados.
- **Complexidade:** Média.
- **Dependências:** `TelaMochila`, `usar_consumivel`, `ItemSpec`.
- **Riscos:** adicionar confirmação em excesso; limitar a estratégicos.
- **Prioridade:** P1.
- **Critério de aceitação:** usar item consome exatamente 1 unidade e 1 turno; cancelar não
  consome nada.

### ITM-02 — Transparência do mercado

- **Problema/oportunidade:** a vitrine mostra ofertas, mas o jogador pode não saber por que
  uma compra está bloqueada.
- **Solução:** exibir saldo, preço, motivo do bloqueio (limite, artefato já equipado,
  forja no teto) e o efeito resumido antes da confirmação.
- **Impacto:** menos frustração e menos compras acidentais.
- **Complexidade:** Baixa.
- **Dependências:** `motivo_bloqueio_oferta`, `preco_oferta`, UI do mercador.
- **Riscos:** excesso de texto; usar campos curtos.
- **Prioridade:** P1.
- **Critério de aceitação:** toda oferta bloqueada exibe motivo específico; compra válida
  mostra preço e saldo resultante.

### ITM-03 — Ledger de economia da run

- **Problema/oportunidade:** XP/Abysmus são creditados por abate e no fim, mas não há um
  registro consultável por run.
- **Solução:** manter um ledger em memória e incluí-lo no evento `ruptura_run_finalizada`
  e no resumo final (sem nova tabela nesta fase).
- **Impacto:** auditoria do jogador e base para reconciliação (BUG-03).
- **Complexidade:** Média.
- **Dependências:** `registrar_vitoria`, `finalizar_run`, `award_rewards`.
- **Riscos:** duplicar dados; manter apenas o necessário.
- **Prioridade:** P1.
- **Critério de aceitação:** o resumo final soma exatamente o XP/Abysmus creditado e
  diferencia bônus de abate, evento e conclusão.

---

## 6. Criaturas e eventos

### CRE-01 — Cobertura e consistência do bestiário

- **Problema/oportunidade:** o catálogo cresceu para 91 criaturas; nem toda criatura tem
  habitat, era ou gancho de evento explícito.
- **Solução:** auditar metadados (era, categoria, habilidade, fraqueza, descrição) e
  padronizar o que falta; não alterar atributos.
- **Impacto:** consistência de lore e facilidade de expansão.
- **Complexidade:** Média.
- **Dependências:** `EnemySpec`, `validar_catalogos`, `s!bestiario`.
- **Riscos:** mudar nomes/chaves quebrou dados de ranking; preservar chaves existentes.
- **Prioridade:** P2.
- **Critério de aceitação:** todas as criaturas têm os campos obrigatórios e o validador
  cobre a regra.

### CRE-02 — Cadeias de eventos

- **Problema/oportunidade:** eventos são independentes; não há consequência entre
  escolhas de uma mesma run.
- **Solução:** permitir que uma escolha marque um flag e desbloqueie uma variação de evento
  posterior, mantendo os efeitos atuais.
- **Impacto:** narrativa mais coesa e replay com memória.
- **Complexidade:** Média.
- **Dependências:** `EventoSpec`, `RunState.eventos_dinamicos`.
- **Riscos:** combinações imprevistas; limitar a pares e testar.
- **Prioridade:** P2.
- **Critério de aceitação:** uma cadeia piloto aparece apenas após a escolha
  pré-requisito e aplica o efeito esperado.

### CRE-03 — Calendário sazonal visível

- **Problema/oportunidade:** janelas sazonais existem, mas o jogador não sabe quando um
  evento volta.
- **Solução:** mostrar no bestiário/evento a janela ativa e a próxima data, sem prometer
  conteúdo futuro.
- **Impacto:** orienta expectativa e aumenta participação.
- **Complexidade:** Baixa.
- **Dependências:** `evento_disponivel`, `EventoSpec`.
- **Riscos:** datas erradas; derivar da mesma função de validação.
- **Prioridade:** P1.
- **Critério de aceitação:** a data exibida coincide com `evento_disponivel` para uma
  amostra de datas (incluindo virada de ano).

---

## 7. Progressão e repetibilidade

### PRG-01 — Progressão meta-cósmica

- **Problema/oportunidade:** a progressão principal é a build por classe; não há meta
  duradoura entre runs.
- **Solução:** criar trilha cosmética/colecionável (títulos, molduras, variantes de
  relíquia) que não aumente poder de combate.
- **Impacto:** retenção sem pay-to-win e sem inflar balanceamento.
- **Complexidade:** Alta.
- **Dependências:** persistência, UI, economia, autorização de escopo.
- **Riscos:** virar segunda economia; manter estritamente cosmético.
- **Prioridade:** P2.
- **Critério de aceitação:** recompensa cosmética é desbloqueada por marcos e não altera
  atributos de combate.

### PRG-02 — Desafios diários/semanais

- **Problema/oportunidade:** runs são repetíveis, mas não há objetivo rotativo.
- **Solução:** desafios opcionais com modificadores declarados (ex.: “vença sem usar
  consumível”) e recompensa limitada, reutilizando o motor de eventos.
- **Impacto:** repetibilidade e variedade.
- **Complexidade:** Média.
- **Dependências:** `RunState`, eventos, economia, agendamento.
- **Riscos:** modificadores que quebram builds; validar e oferecer alternativa.
- **Prioridade:** P1.
- **Critério de aceitação:** desafio diário é determinístico por data, rastreável e não
  afeta runs normais.

### PRG-03 — Histórico e score de run

- **Problema/oportunidade:** o ranking guarda nível/abates, mas o jogador não vê um
  histórico legível das próprias runs.
- **Solução:** comando de histórico com data, classe, nível, abates, motivo e duração,
  usando `ruptura_runs`.
- **Impacto:** sensação de progresso e base para desafios.
- **Complexidade:** Baixa.
- **Dependências:** `RankingRepo`, `ruptura_runs`.
- **Riscos:** privacidade; mostrar apenas as runs do próprio jogador.
- **Prioridade:** P1.
- **Critério de aceitação:** histórico lista apenas runs do autor, paginado e ordenado por
  data.

---

## 8. Interface/UX

### UX-01 — Densidade do embed de combate

- **Problema/oportunidade:** o embed acumula log, status, intenção, build e itens; em
  telas pequenas fica denso.
- **Solução:** hierarquizar seções (ameaça > recursos > log), limitar o log a N linhas e
  usar fields curtos.
- **Impacto:** leitura mais rápida e menos erros.
- **Complexidade:** Baixa.
- **Dependências:** `criar_embed`.
- **Riscos:** esconder informação útil; manter o log completo no evento.
- **Prioridade:** P1.
- **Critério de aceitação:** o embed cabe no limite e mantém ameaça, vida, Foco e ações
  visíveis em todos os estados.

### UX-02 — Layout e acessibilidade dos botões

- **Problema/oportunidade:** há muitos botões/selects e estados desabilitados que podem
  não ser óbvios.
- **Solução:** agrupar por função (ação, recurso, item, evento), usar emoji consistente e
  rótulos que expliquem o custo.
- **Impacto:** menos cliques errados e melhor uso em mobile.
- **Complexidade:** Baixa.
- **Dependências:** `TelaCombate`, `TelaMochila`, `EventoEscolhaView`.
- **Riscos:** limite de 5 linhas/25 componentes; validar.
- **Prioridade:** P1.
- **Critério de aceitação:** todos os controles cabem nos limites do Discord e cada botão
  desabilitado tem motivo no embed.

### UX-03 — Onboarding e tutorial

- **Problema/oportunidade:** a Ruptura tem muitos sistemas; o primeiro contato pode ser
  overwhelming.
- **Solução:** tutorial curto opcional na primeira run, explicando Foco, guarda,
  interrupção e mochila em 3–4 passos.
- **Impacto:** melhora ativação e reduz abandono.
- **Complexidade:** Média.
- **Dependências:** UI, estado de primeira run, textos.
- **Riscos:** atrapalhar veteranos; permitir pular e lembrar a escolha.
- **Prioridade:** P1.
- **Critério de aceitação:** tutorial aparece uma vez por usuário, pode ser pulado e não
  altera o combate.

### UX-04 — Resumo pós-run

- **Problema/oportunidade:** o embed final tem resultado e bônus, mas não um “o que
  aprendi”.
- **Solução:** resumo com classe, nível, abates por categoria, melhor golpe, itens usados,
  adaptações de Chefe e link para o histórico.
- **Impacto:** fechamento satisfatório e aprendizado.
- **Complexidade:** Baixa.
- **Dependências:** `finalizar_run`, `RunState`.
- **Riscos:** texto longo; usar fields e truncar.
- **Prioridade:** P1.
- **Critério de aceitação:** resumo cabe no embed e os totais batem com o ledger da run.

---

## 9. Testabilidade e arquitetura

### TST-01 — Separar motor e UI

- **Problema/oportunidade:** `ruptura.py` tem 8.063 linhas e mistura regras, persistência
  e UI; testes exigem importar Discord.
- **Solução:** extrair módulos internos (`ruptura_catalogo`, `ruptura_combate`,
  `ruptura_itens`, `ruptura_build`, `ruptura_ui`) e manter `ruptura.py` como fachada
  compatível.
- **Impacto:** testes mais rápidos, revisões menores, menos risco de conflito.
- **Complexidade:** Alta.
- **Dependências:** imports públicos atuais, `ruptura_pvp`, `ruptura_extras`, testes.
- **Riscos:** quebrar imports e pickles; fazer em etapas com testes verdes.
- **Prioridade:** P0 (estrutural), executável em fases.
- **Critério de aceitação:** todos os imports públicos continuam funcionando; a suíte
  passa sem alteração de comportamento.

### TST-02 — RNG injetável

- **Problema/oportunidade:** decisões usam `random` global; reproduzir um combate é
  difícil.
- **Solução:** permitir injetar um `random.Random` no motor (ou semente por run) e usar
  nos testes de combate/eventos.
- **Impacto:** testes determinísticos e diagnóstico mais rápido.
- **Complexidade:** Média.
- **Dependências:** `executar_ataque`, `preparar_combate`, `sortear_evento`.
- **Riscos:** mudar assinaturas públicas; usar parâmetro opcional.
- **Prioridade:** P1.
- **Critério de aceitação:** mesma semente produz mesma sequência de dano/eventos em teste.

### TST-03 — Camada de banco e concorrência

- **Problema/oportunidade:** 13 conexões diretas, timeouts variados, sem WAL global.
- **Solução:** repositório compartilhado com `busy_timeout`, `row_factory` e transação;
  avaliar WAL em migração controlada.
- **Impacto:** menos “database is locked”, código repetido e bugs de concorrência.
- **Complexidade:** Média.
- **Dependências:** `XpAndCoins`, repositórios da Ruptura, testes.
- **Riscos:** WAL muda comportamento de backup; documentar e testar.
- **Prioridade:** P1.
- **Critério de aceitação:** teste concorrente de compras/XP passa repetidamente sem lock
  e sem saldo negativo.

### TST-04 — Suítes de economia e cassino

- **Problema/oportunidade:** não há testes de cassino, XP, insígnias ou pets; o RTP é
  documentado como testado, mas não é.
- **Solução:** criar suítes com banco temporário para APIs de economia, RTP e transações
  do cassino, além de testes de falha/rollback.
- **Impacto:** protege o dinheiro do jogo e reduz regressões.
- **Complexidade:** Média.
- **Dependências:** `XpAndCoins`, `cassino`, fixtures temporárias.
- **Riscos:** testes frágeis por RNG; usar injeção/semente.
- **Prioridade:** P0.
- **Critério de aceitação:** RTP e operações de saldo têm testes determinísticos; falha
  injetada não altera saldo.

### TST-05 — Simulador de progressão

- **Problema/oportunidade:** mudanças de balanceamento são avaliadas por sensação.
- **Solução:** simulador offline que roda N runs com políticas simples e reporta
  distribuição de nível, abates, mortes e uso de itens.
- **Impacto:** decisões de balanceamento com evidência, sem alterar o jogo em produção.
- **Complexidade:** Média.
- **Dependências:** RNG injetável, motor separado, autorização para interpretar dados.
- **Riscos:** simulador não representa jogadores reais; usar como bússola, não verdade.
- **Prioridade:** P2.
- **Critério de aceitação:** simulação reproduzível por semente gera relatório com
  métricas acordadas.

---

## Sequenciamento sugerido

1. **Ciclo 1 (P0):** BUG-01 **concluído**; restam BUG-02, BUG-03 e TST-04.
2. **Ciclo 2 (P1):** TST-01 (fase 1), CMB-01, CMB-02, ITM-01, ITM-02, UX-01, UX-03,
   PRG-02, PRG-03.
3. **Ciclo 3 (P1/P2):** BOSS-02, CLS-01, CLS-03, CRE-03, TST-02, TST-03.
4. **Ciclo 4 (P2):** BOSS-01, BOSS-03, CMB-03, CMB-04, CLS-02, ITM-03, CRE-01, CRE-02,
   PRG-01, TST-05, UX-02, UX-04.

## O que não fazer agora

- Não alterar chances, dano, recompensas, escalas ou atributos sem autorização e sem
  simulação.
- Não criar tabelas ou migrações sem decisão explícita de esquema.
- Não adicionar um Cog novo de conteúdo antes de resolver P0 e ampliar testes.
- Não reescrever a Ruptura de uma vez; fatiar com testes verdes.
