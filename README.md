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
