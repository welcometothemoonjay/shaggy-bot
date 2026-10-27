# Changelog — Shaggy Bot

Todas as mudanças relevantes do projeto serão registradas neste arquivo.

## [26/10/2026] — Ruptura Temporal: Expansão 3 (mini-Chefes e Chefes por era)

### ✨ Adicionado

- **36 criaturas novas**: **18 mini-Chefes** e **18 Chefes**, sendo **6 mini-Chefes e 6
  Chefes por era** (`Da'kor`, `Era a Vapor` e `Futuro Distorcido`). Nenhuma criatura
  normal, era, item, relíquia, evento, moeda ou tabela foi criada.
- **36 habilidades exclusivas**, uma por criatura, todas ligadas ao combate por
  `HabilidadeInimiga`, `modificar_ataque`, `reduzir_dano_recebido`, `apos_golpe`,
  `ao_turno` ou `escolher_acao`.
- **`Da'kor`** — mini-Chefes (nível 3): Vigia da Ponte Quebrada, Afiador de Ossos, Coro de
  Afogados, A Costureira de Sombras, Máscara do Primeiro Rosto e Contador de Ossos.
  Chefes (níveis 5 e 10): O Barqueiro de Ossos, A Mãe das Máscaras, O Coletor de Dívidas,
  O Pastor de Máscaras, A Viúva do Farol e O Arquivista de Nomes.
- **`Era a Vapor`** — mini-Chefes (nível 6): A Caldeira Que Respira, Ladrão de Segundos,
  Sentinela da Válvula Mestra, Fundidor de Placas, Aranha de Válvulas e Maquinista de
  Cinzas. Chefes (níveis 10, 15 e 20): O Engenheiro-Chefe, A Fornalha Viva, O Titereiro de
  Válvulas, A Dama de Latão, O Relojoeiro do Fim e A Catedral de Carvão.
- **`Futuro Distorcido`** — mini-Chefes (nível 9): Tecelã de Miragens, Devorador de
  Minutos, Arauto das Palavras Gastas, Sombra do Instante Perdido, Ponteiro Parado e Fome
  do Amanhã. Chefes (níveis 15, 20 e 25): O Espelho do Último Dia, A Fenda que Escuta, O
  Colecionador de Futuros, A Criança que Não Foi, O Devorador de Conclusões e A Última
  Testemunha.

### ⚔️ Mecânicas

- **Mini-Chefes** usam efeitos curtos e legíveis: pedágio em Foco, golpe carregado que
  expõe a criatura, cura com dreno, fios que absorvem até romper, cópia de gesto,
  contagem de golpes, limpeza de status, bloqueio do próximo ataque, defesa que vira
  ataque, placas de proteção, respingo escaldante, dreno de Foco, miragem dissipada por
  Técnica, dreno de tempo, palavras acumuladas, ausência que reduz dano, bloqueio com
  devolução de Foco e fome acumulada.
- **Chefes** usam uma ação própria na cadência/condição e delegam o restante para
  `escolher_acao_chefe()`: travessia com sangramento, alternância pedra/fome, cobrança
  por bens equipados, espinhos, marca do farol, redução do ataque do jogador, linha de
  montagem, combustão que consome barreira, fios cruzados, faces de latão, atraso do
  próximo movimento, oferenda de itens, reflexo do último dano, sussurro que expõe a
  criatura, colheita de Técnicas, ausência planejada, execução abaixo de 40% de vida e
  espelhamento de ações.
- **Contrajogo garantido:** toda ação telegrafada usa `prepara=True` e
  `interrompivel=True`, sendo cancelada por **Guardar** ou **atordoamento**. Dano direto
  de habilidade respeita a barreira e nunca leva a vida do jogador abaixo de 1; quando o
  recurso de uma habilidade (Foco, item ou barreira) está ausente, ela apenas perde o
  efeito extra, sem erro de combate.

### 🛡️ Compatibilidade

- Cadência de encontros inalterada: mini-Chefe em níveis múltiplos de 3 (exceto múltiplos
  de 5), Chefe em múltiplos de 5, Deuses intactos.
- Nenhuma mudança em `main.py`, `cogs/XpAndCoins.py`, esquema SQLite, `.env`, relíquias,
  itens, forja, mercador, progressão ou regras de fim de run.
- Recompensas continuam usando as fórmulas existentes (`xp` da criatura × multiplicador
  de categoria, sem Abysmus de abate); as 36 criaturas entram nos pools que o motor já
  consulta.

### 🧪 Validação

- `test_ruptura.py` ampliado de **74 para 89 testes**.
- `.venv/bin/python -m unittest test_ruptura -q` — **89 testes, OK** (~0,87 s).
- `.venv/bin/python -m unittest discover -q` — **89 testes, OK** (~0,91 s).
- `.venv/bin/python -m py_compile main.py cogs/*.py test_ruptura.py` — OK.
- `validar_catalogos()` — sem erros.
- `git diff --check` — sem problemas.

### 📁 Arquivos

- `cogs/ruptura.py` — 36 habilidades, 36 `EnemySpec` e ajuste de `LuzDoFarol`.
- `test_ruptura.py` — catálogo, habilidades, integração, cadência, recompensas e
  contrajogo.
- `README.md`, `CHANGELOG.md`, `docs/PROJECT_AUDIT.md`, `docs/COGS_REVIEW.md` e
  `docs/RUPTURA_ROADMAP.md` — contagens, nomes, mecânicas e resultados reais.

---

## [26/10/2026] — Ruptura Temporal: liberação de estado PvP em falhas de interação

### 🐛 Corrigido

- **Jogadores presos em `RupturaDuelo.ocupados` (BUG-05):** falhas ao abrir a tela de
  escolha de classe ou ao confirmar a escolha deixavam os dois jogadores bloqueados para
  PvE e PvP até reiniciar o bot.
- **Aceite do convite:** se `interaction.response.edit_message` falhar, o desafiado e o
  desafiante são liberados e o duelo não começa.
- **Confirmação da escolha:** se `interaction.response.defer` falhar depois de `stop()`,
  os dois jogadores são liberados; o timeout não conseguiria mais fazer isso.

### 🔧 Melhorias

- **Falha ao obter `original_response()`** apenas é registrada, pois a tela já está ativa
  e possui timeout próprio — liberar nesse ponto permitiria um duelo sobreposto.
- **`TestLiberacaoEstadoPvP`** cobre as duas falhas simuladas e a reserva atômica de duas
  `iniciar_run()` concorrentes.
- **`test_ruptura.py` ampliado para 74 testes.**

### 🛡️ Compatibilidade

- Nenhuma mudança em `data/shaggy.db`, `.env`, `main.py`, `cogs/XpAndCoins.py`, regras,
  recompensas, balanceamento ou comandos.
- Fluxos normais de convite, aceite, escolha, duelo e encerramento preservados.

### 🧪 Validação

- `.venv/bin/python -m unittest test_ruptura -v` (74 testes)
- `.venv/bin/python -m unittest discover -v` (74 testes)
- `.venv/bin/python -m py_compile cogs/ruptura.py cogs/ruptura_pvp.py test_ruptura.py`
- `git diff --check`

---

## [26/10/2026] — Ruptura Temporal: guarda única de estado PvE/PvP

### 🐛 Corrigido

- **Bypass de estado entre PvE e PvP (BUG-01):** a Ruptura PvE agora consulta os duelos
  PvP antes de iniciar uma run. Antes, o PvP verificava runs PvE, mas a reciprocidade não
  existia.
- **Janela de escolha de classe:** a checagem também ocorre em `iniciar_run()`, evitando
  que uma run seja criada depois de o jogador entrar em um duelo com a tela de classe
  aberta.
- **Mensagens explícitas:** o jogador recebe um aviso claro ao tentar iniciar PvE durante
  um convite/duelo e ao tentar duelar durante uma run PvE.

### 🔧 Melhorias

- **`estado_jogador_ocupado()`** centraliza a leitura de `runs_ativas` e `ocupados`.
- **`RupturaDuelo.motivo_indisponivel()`** passou a usar a mesma guarda compartilhada.
- **`test_ruptura.py` ampliado para 70 testes na etapa do BUG-01**, com cobertura dos
  dois sentidos da exclusividade PvE/PvP e da janela de `iniciar_run()`.

### 🛡️ Compatibilidade

- Nenhuma mudança em `data/shaggy.db`, no `.env`, no `main.py` ou no `cogs/XpAndCoins.py`.
- Nenhuma alteração em chances, dano, recompensas, escalas ou atributos.
- Comandos, aliases, tabelas e fluxos existentes foram preservados.

### 🧪 Validação

- `.venv/bin/python -m unittest test_ruptura -v` (70 testes na etapa; 74 após o BUG-05)
- `.venv/bin/python -m py_compile cogs/ruptura.py cogs/ruptura_pvp.py test_ruptura.py`
- `git diff --check`

---

## [26/10/2026] — Ruptura Temporal: combate tático, mercador e chefes adaptativos

### ✨ Adicionado

- **Ações táticas de chefe**: Golpe Pesado telegrafado (+55% se não interrompido), Postura Defensiva (reduz o próximo golpe pela metade) e Contra-Golpe (+30%).
- **Interrupção tática**: Guardar ou atordoar cancela uma ação telegrafada antes da resolução, sem dano.
- **Intenção telegrafada** no embed de combate, com aviso de como interromper a ação.
- **Mercador do Intervalo** antes de chefe/deus (nunca antes de mini-chefe), com consumíveis, estratégicos, artefatos e forja.
- **Forja vinculada à run**: até 2 aprimoramentos, com teto de +2 ataque, +2 defesa ou +20 vida máxima e custo crescente em Abysmus.
- **Chefes adaptativos**: após 3 observações com pelo menos 60% do mesmo padrão, o chefe responde uma única vez com a ação correspondente.
- **`test_ruptura.py` ampliado para 66 testes**, cobrindo combate tático, expiração, mercador, compras atômicas, concorrência e isolamento de memória.

### 🔧 Melhorias

- **`HabilidadeInimiga.escolher_acao()`** permite decisões táticas sem alterar as habilidades existentes; criaturas comuns continuam com o golpe básico.
- **`criar_inimigo()` e `preparar_combate()`** reaproveitam a categoria já sorteada, evitando duplo sorteio de deus entre o mercador e o encontro.
- **`s!market comprar`** passou a usar `MercadoRepo`: débito e entrega do item ocorrem na mesma transação, com trava por membro.
- **Helpers `guardar_item_tx()`/`consumir_item_tx()`** permitem compras atômicas dentro da transação oficial de Abysmus.

### 🛡️ Compatibilidade

- Nenhuma mudança em `data/shaggy.db`, no `.env`, no `main.py` ou no `cogs/XpAndCoins.py`.
- Nenhuma alteração nas chances de encontro, escalas de criatura, recompensas ou atributos das classes.
- Chefes, deuses e mini-chefes mantêm imunidades e limites existentes; o PvP continua usando apenas passivos e artefatos.
- A memória tática fica em `EnemyState`, sem tabela nova, e é isolada por criatura, run e jogador.

### 🧪 Validação

- `python -m py_compile cogs/ruptura.py cogs/ruptura_pvp.py test_ruptura.py`
- `python -m unittest test_ruptura -v` (66 testes)
- `validar_catalogos()` e `validar_arvores()` sem erros.

---

## [26/10/2026] — Ruptura Temporal: expansão de bestiário, itens e eventos

### ✨ Adicionado

- **20 criaturas novas** no bestiário de Ruptura Temporal:
  - **18 normais**, sendo **6 por era** (Da'kor, Era a Vapor e Futuro Distorcido);
  - **2 sazonais exclusivas**: Cavaleiro da Última Colheita (Colheita de Ecos) e Noiva de Cinzas (Semana dos Mortos).
- **20 habilidades exclusivas de criatura**, uma para cada criatura nova, com mecânicas próprias (pressão crescente, roubo de Foco, marca paradoxal, reflexo de vidro etc.).
- **Mercado ampliado para 27 itens**, agora com quatro tipos:
  - **9 passivos** de build já existentes/reorganizados;
  - **5 artefatos** equipados no início da run: Olho de Vidro, Manto de Névoa, Coração de Cristal, Sinete do Carrasco e Relógio Quebrado;
  - **8 consumíveis** de combate: Poção de Vida, Poção de Foco, Bomba de Fuligem, Óleo Pegajoso, Veneno do Véu, Escudo de Campanha, Kit de Emergência e Lâmina de Aluguel;
  - **5 itens estratégicos** com 1 uso por run: Bomba de Fumaça, Distorção Temporal, Pacto de Sangue, Isca de Carne e Selo de Silêncio.
- **Mochila de combate** com botão próprio na run; consumíveis e estratégicos gastam a ação do turno e são descontados do inventário.
- **4 eventos sazonais novos**: Equinócio de Cinzas, Solstício Rachado, Colheita de Ecos e Semana dos Mortos, com janelas de data independentes.
- **3 eventos dinâmicos com escolhas**: Mercador do Intervalo, Fenda de Dois Caminhos e Voz na Névoa. Cada escolha aplica um efeito imediato e definitivo.
- **Tela de escolha de evento** com botões e embed próprio.
- **`test_ruptura.py`**: 31 testes automatizados cobrindo catálogo, curva de dificuldade, janelas sazonais, escolhas, itens, mochila, inventário SQLite temporário e filtro de itens do PvP.

### 🔧 Melhorias

- **`ItemSpec` expandido** com `tipo`, `uso`, `aplicar`, `efeito_factory`, `limite_run` e `gasta_turno`, mantendo compatibilidade com os itens antigos.
- **Inventário e mercado** agora agrupam e exibem passivos, artefatos, consumíveis e estratégicos separadamente.
- **`RunState`** ganhou snapshot de mochila, artefatos equipados, bônus temporário de ataque e controle de escolhas/eventos dinâmicos.
- **Eventos sazonais** usam janelas genéricas de mês/dia, incluindo janelas que viram o ano.
- **Eventos dinâmicos** só entram no sorteio se nenhum evento normal saiu e a run está no nível 4+, preservando a probabilidade dos eventos base.
- **PvP** filtra novos tipos de item e equipa apenas passivos e artefatos.

### 🛡️ Compatibilidade

- Nenhuma mudança em `data/shaggy.db`, no `.env`, no `main.py` ou no `cogs/XpAndCoins.py`.
- Nenhuma alteração nas chances de encontro, categorias, curvas de escala ou recompensas existentes.
- As novas criaturas são todas `normal` e calibradas dentro da curva das criaturas antigas de cada era.
- Itens antigos continuam válidos e os eventos de Halloween/Natal mantêm suas janelas.

### 🧪 Validação

- `python -m py_compile cogs/ruptura.py cogs/ruptura_pvp.py`
- `python -m unittest test_ruptura -v` (31 testes)
- `validar_catalogos()` e `validar_arvores()` sem erros.

---

## [24/10/2026] — Ruptura Temporal V1

### ✨ Adicionado

- **IA conversacional:** adicionado um sistema de inteligência artificial para permitir conversas com o Shaggy Bot.
- **Cog de notícias (`noticias_ia.py`):** criado um sistema de coleta de notícias relevantes em três categorias:
  - **IA:** novidades e avanços em inteligência artificial.
  - **Bots e desenvolvimento:** notícias sobre bots, programação e ferramentas para desenvolvedores.
  - **RPG:** novidades relacionadas a RPG e jogos de interpretação.
- **Resumos com IA:** geração de resumos em português para facilitar o acompanhamento de até 10 matérias relevantes por categoria.
- **Sistema de builds de Ruptura Temporal:** adicionada uma estrutura de especialização com **3 caminhos de build e 5 nós para cada classe**, ampliando as possibilidades de evolução e personalização dos personagens.

### 🔧 Melhorias

- **Engine de Ruptura Temporal:** aprimoramentos na engine para evoluir a estrutura interna e a experiência de jogo.
- **Progressão de personagens:** expansão das possibilidades de construção de builds, permitindo especializações distintas para cada classe.
- **XpAndCoins:** correções e melhorias nas funções do sistema de XP e moedas.
- **`conceder_recompensas()`:** ajustes para melhorar a concessão de recompensas e a integração com outros Cogs.

### 🚀 Evolução de versão

- **Ruptura Temporal — Beta → V1:** marco de evolução do jogo, com melhorias na engine e a introdução do sistema de builds por classe.

### 🛠️ Manutenção

- Continuidade da organização modular do Shaggy Bot, preparando os sistemas para futuras expansões e novos conteúdos.

---

*Registro de desenvolvimento referente a 24 de outubro de 2026.*
