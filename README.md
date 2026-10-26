# 👻 Shaggy Bot

<p align="center">
  <strong>Um bot de Discord onde o caos encontra a aventura.</strong>
  <br>
  RPGs, minijogos, economia virtual, progressão e eventos que podem mudar tudo.
</p>

<p align="center">
  <a href="https://github.com/welcometothemoonjay">GitHub do desenvolvedor</a>
</p>

---

## 🌌 Sobre o projeto

**Shaggy Bot** é um bot para Discord desenvolvido em Python, criado para transformar servidores em espaços de diversão, exploração e experiências interativas.

O projeto combina sistemas de progressão, economia virtual, jogos de escolhas aleatórias e mecânicas inspiradas em RPGs. Seu objetivo é oferecer experiências que vão além dos comandos tradicionais, com sistemas expansíveis e espaço para novas aventuras, classes, criaturas, habilidades, itens e eventos.

O Shaggy Bot está em desenvolvimento contínuo. Novas mecânicas podem ser adicionadas e os sistemas existentes podem evoluir conforme o projeto cresce.

## ✨ Funcionalidades

### ⚔️ RPG e progressão

- Sistema de experiência (XP) e níveis.
- Economia virtual com moedas e Abysmus.
- Progressão de personagens e desenvolvimento de habilidades.
- Sistemas expansíveis de classes, criaturas, itens e equipamentos.
- Possibilidade de criar novas mecânicas sem reconstruir o projeto inteiro.

### 🌀 Ruptura Temporal

Uma experiência de RPG em que diferentes épocas, criaturas e acontecimentos podem se encontrar.

Imagine encontrar criaturas medievais, seres futuristas, artefatos desconhecidos e eventos especiais em uma mesma aventura.

A Ruptura Temporal foi concebida para permitir a expansão de conteúdo, com novas possibilidades de builds, itens, encontros e desafios.

**Como jogar**

- `s!ruptura` (ou `s!rt`) inicia uma run com uma classe e uma passiva exclusivas.
- `s!market` abre o mercado; `s!market comprar CHAVE quantidade` compra um item.
- `s!inventario` mostra passivos, artefatos, consumíveis e estratégicos guardados.
- `/build` gasta Abysmus na especialização e nos nós da classe.
- Durante o combate, use **Atacar**, **Guardar**, **Concentrar**, a **Técnica** da classe, as habilidades ativas da build, a **Mochila** de combate e o botão de **Evento** quando uma escolha estiver disponível.
- Antes de um **chefe** ou **deus**, um **mercador** aparece com consumíveis, estratégicos, artefatos e aprimoramentos de forja.

**Conteúdo atual**

- **10 classes**, **30 especializações** e **12 relíquias**.
- **55 criaturas**: 35 base, **18 novas** (6 por era) e **2 sazonais exclusivas**, cada uma com habilidade própria.
- **32 habilidades de criatura**, incluindo as **20 habilidades exclusivas** das criaturas novas.
- **27 itens** no mercado:
  - **9 passivos** de build (ataque, defesa, vida, barreira, crítico e foco);
  - **5 artefatos** com efeitos especiais durante a run;
  - **8 consumíveis** de combate (cura, Foco, dano, status e defesa);
  - **5 itens estratégicos** com **1 uso por run** (fumaça, distorção, pacto, isca e selo).
- **12 eventos**: 3 base, 2 sazonais clássicos (Halloween e Natal), **4 sazonais novos** (Equinócio de Cinzas, Solstício Rachado, Colheita de Ecos e Semana dos Mortos) e **3 dinâmicos com escolhas**.

**Combate tático**

- Chefes e deuses podem usar **Golpe Pesado** (telegrafado, +55% de dano se não for interrompido), **Postura Defensiva** (reduz o próximo golpe recebido pela metade) e **Contra-Golpe** (+30%).
- A intenção do inimigo aparece no embed. **Guardar** ou **atordoar** interrompe uma ação telegrafada e cancela o dano.
- Cada chefe observa as últimas ações do jogador dentro do combate. Após **3 observações** com pelo menos **60%** do mesmo padrão, ele se adapta **uma única vez**.
- A memória é isolada por criatura, run e jogador; nenhuma tabela nova é criada e criaturas comuns mantêm o golpe básico.

**Mercador e forja**

- O mercador surge **depois da vitória**, quando o próximo encontro é **chefe** ou **deus** — nunca antes de mini-chefe.
- A vitrine traz **2 consumíveis**, **2 estratégicos**, **até 1 artefato** ainda não equipado e **3 ofertas de forja**.
- Consumíveis e estratégicos vão para o inventário persistente e para a mochila da run. Artefatos valem **somente nesta run** e são aplicados na compra.
- A forja permite **2 aprimoramentos por run**, com teto de **+2 ataque**, **+2 defesa** ou **+20 vida máxima**. Cada uso custa +4 Abysmus em relação ao anterior.
- Toda compra é atômica: o débito de Abysmus e a entrega/efeito usam a mesma transação da economia.

**Regras dos itens**

- Passivos e artefatos são equipados automaticamente no início da run e consumidos do inventário, respeitando o limite por item.
- Consumíveis e estratégicos entram na mochila de combate da run; **usar um item gasta a ação do turno** e o item é consumido.
- Estratégicos só podem ser usados **1 vez por run**.
- O **PvP** usa apenas passivos e artefatos; consumíveis e estratégicos ficam fora do duelo.
- As janelas sazonais não alteram a dificuldade global: fora delas, o evento simplesmente não entra no sorteio.

**Validação local**

```bash
python -m unittest test_ruptura -v
```

A suíte cobre catálogo, combate tático, preparação/interrupção/resolução, expiração de efeitos, adaptação e isolamento de chefes, mercador, forja, compras atômicas, concorrência e compatibilidade com o PvP. Os testes usam um banco temporário e não tocam em `data/shaggy.db`.

### 🌲 Segredo Floresta Adentro — SFA

Um universo de fantasia sombria e horror cósmico que inspira parte das experiências de RPG do projeto.

Entre florestas misteriosas, entidades, facções, relíquias e forças desconhecidas, os jogadores podem encontrar mecânicas próprias e desafios ligados ao universo de SFA.

### 🎲 Minijogos e escolhas aleatórias

Jogos interativos em que o jogador e o bot podem realizar escolhas aleatórias, competir e descobrir resultados imprevisíveis.

O projeto também pode receber novos minijogos, desafios e experiências sociais.

### 🪙 XP, moedas e Abysmus

A economia virtual permite desenvolver sistemas de recompensas e progressão.

- Ganhos de XP por atividades compatíveis com as regras do bot.
- Evolução por níveis.
- Moedas para sistemas de economia e recompensas.
- Abysmus como moeda especial para mecânicas que utilizam esse recurso.
- Possibilidade de integração com novos sistemas de jogos.

> Os ganhos, limites e regras dependem da implementação de cada sistema.

## 🧩 Arquitetura do projeto

O Shaggy Bot utiliza Python e `discord.py`, com funcionalidades organizadas em Cogs para facilitar a manutenção e a expansão.

Exemplo de organização:

```text
shaggy-bot/
├── main.py
├── cogs/
│   ├── games.py
│   ├── mystic.py
│   ├── social.py
│   ├── utilitys.py
│   └── ...
├── data/
├── .env
├── .gitignore
└── README.md
```

### Tecnologias

- **Python** — linguagem principal.
- **discord.py** — integração com a API do Discord.
- **SQLite** — armazenamento local de dados, quando utilizado pelos sistemas.
- **Git** — controle de versão.
- **GitHub** — hospedagem do código-fonte e histórico de desenvolvimento.

## 🚀 Instalação

### 1. Pré-requisitos

Instale uma versão de Python compatível com o projeto, o Git e as dependências utilizadas pelo bot.

Confira as versões instaladas:

```bash
python3 --version
git --version
```

### 2. Clone o repositório

```bash
git clone https://github.com/welcometothemoonjay/shaggy-bot.git
cd shaggy-bot
```

### 3. Crie um ambiente virtual

No Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 4. Instale as dependências

Se o projeto possuir um arquivo `requirements.txt`:

```bash
pip install -r requirements.txt
```

Caso ainda não exista, instale as dependências definidas pelo projeto. Não presuma que todas as bibliotecas são necessárias sem conferir os imports.

### 5. Configure o token do Discord

Crie um arquivo `.env` na raiz do projeto e configure o token utilizado pelo `main.py`.

Exemplo ilustrativo:

```env
DISCORD_TOKEN=COLOQUE_SEU_TOKEN_AQUI
```

O nome da variável deve corresponder ao que o código realmente utiliza.

**Segurança:** nunca publique seu token, senhas, chaves privadas ou o arquivo `.env` no GitHub.

### 6. Execute o bot

```bash
python3 main.py
```

Se a inicialização estiver configurada corretamente, o bot deverá conectar-se ao Discord e carregar os Cogs habilitados.

## 🔧 Desenvolvimento

O Shaggy Bot é um projeto expansível. Para adicionar novas funcionalidades:

1. Identifique o sistema responsável pela mecânica.
2. Verifique as integrações com banco de dados, XP e moedas.
3. Implemente a funcionalidade seguindo os padrões dos Cogs existentes.
4. Teste os comandos e as interações.
5. Verifique se os dados continuam consistentes após reiniciar o bot.
6. Registre as alterações no Git.

### Versionamento com Git

Confira as alterações:

```bash
git status
git diff
```

Registre uma nova versão:

```bash
git add .
git commit -m "Adiciona nova funcionalidade"
git push
```

Mantenha arquivos privados e bancos de dados locais fora dos commits quando não houver uma razão segura e explícita para compartilhá-los.

## 🛣️ Direções futuras

O desenvolvimento pode incluir:

- [ ] Expansão dos sistemas de RPG.
- [ ] Novas classes, habilidades, criaturas e itens.
- [ ] Mais minijogos e experiências interativas.
- [ ] Eventos especiais e encontros raros.
- [ ] Sistemas adicionais de progressão e conquistas.
- [ ] Cassino temático com NPCs e jogos integrados à economia.
- [ ] Melhorias na interface por meio de embeds, botões e menus.
- [ ] Testes automatizados e melhorias de estabilidade.
- [ ] Possíveis integrações futuras com uma plataforma web.

Esta lista representa possibilidades de desenvolvimento, não uma promessa de funcionalidades já disponíveis.

## 🔐 Segurança e dados

- Não compartilhe tokens do Discord.
- Não envie credenciais para o GitHub.
- Proteja o banco de dados que contém informações dos jogadores.
- Faça backups antes de mudanças importantes no esquema do banco.
- Valide entradas e operações econômicas.
- Teste alterações antes de executá-las em um servidor ativo.

## 👨‍💻 Desenvolvedor

**Jay Moon**

GitHub: [@welcometothemoonjay](https://github.com/welcometothemoonjay)

## 📜 Licença

Código pode ser redistribuído ou utilizado livremente.

---

<p align="center">
  <strong>Shaggy Bot — entre por diversão, fique pela aventura.</strong>
  <br>
  <em>O próximo acontecimento pode estar fora da sua linha temporal.</em>
</p>
