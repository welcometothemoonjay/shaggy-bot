# Shaggy Bot

## 1. Sobre o projeto
Shaggy Bot é um bot Discord desenvolvido em Python com `discord.py 2.7.1`, focado em entretenimento, progressão, economia e RPGs. Utiliza SQLite (`data/shaggy.db`) para persistência.

## 2. Funcionalidades
Sistemas realmente implementados no repositório:
- **Progressão/XP**: Cog `XpAndCoins` - XP por mensagem, níveis, Abysmus, comandos admin.
- **RPG Textual**: Cog `cogs/rpg.py` com módulos especializados em `rpg_system/` e delegação em `rpg/` (personagem, inventário, mineração, profissões, exploração, combate por turnos com 5 inimigos, missões diárias, loja, economia, energia com recarga de 24h, roubo, casas, casamento/relacionamento, conquistas).
- **Ruptura Temporal**: `cogs/ruptura.py`, `ruptura_extras.py`, `ruptura_pvp.py` - sistema independente de fantasia temporal.
- **Badges/Insígnias**: `cogs/badges.py` com loja, cargos e fila persistente.
- **Missões diárias (globais)**: `cogs/missoes.py`.
- **Cassino**: `cogs/cassino.py`.
- **Pets**: `cogs/pet.py`.
- **Ranking**: `cogs/ranking.py`.
- **Jogos**: `cogs/games.py`, `cogs/GameSFA.py`.
- **Social**: `cogs/social.py`.
- **IA/Lore/Notícias**: `cogs/ia.py`, `cogs/lore.py`, `cogs/noticias_ia.py`, `cogs/mystic.py`.
- **Utilidades/Moderação**: `cogs/ultility.py` (com gerenciador central de emojis adicionado).
- **Outros**: `cogs/ruptura_extras.py`, `cogs/ruptura_pvp.py`.

## 3. RPGs disponíveis
### RPG Textual
- Orquestrado por `cogs/rpg.py`, delegando regras aos módulos em `rpg_system/` (sem dependência obrigatória de Discord).
- Usa tabelas `rpg_*` e integra com `XpAndCoins` para Abysmus/XP.

### Ruptura Temporal
- Implementado em `cogs/ruptura*.py`, **independente** do RPG Textual.
- Possui identidade temática própria e integra com `XpAndCoins` quando aplicável.

Os dois RPGs são sistemas distintos, com finalidades diferentes.

## 4. Sistemas complementares
- **XP e Coins**: Gerenciados por `XpAndCoins` (`user_stats`).
- **Abysmus**: Moeda rara centralizada via `XpAndCoins`.
- **Badges**: Sistema de insígnias com cargos e persistência.
- **Inventário**: Presente em ambos os RPGs (`ruptura_inventario`, `rpg_equipamentos`, etc.).
- **Economia**: Centralizada no `XpAndCoins` com transações.
- **Sistemas sociais**: Casamento/relacionamento (RPG Textual), comandos sociais (`social.py`).
- **Outros**: Pets, cassino, missões, ranking.

## 5. Arquitetura
- `main.py`: Classe `Shaggy(commands.Bot)`. `setup_hook()` percorre `cogs/*.py` em ordem alfabética, ignora arquivos iniciando com `_`, carrega extensões. Sincroniza comandos globalmente e copia/sincroniza por guild no `on_ready()`. `on_message()` repassa mensagens ao cog `XpAndCoins` e mantém comandos de prefixo.
- Comunicação entre cogs via `bot.get_cog()`.
- Economia centralizada via `XpAndCoins.transacao()`.
- Operações SQLite síncronas devem ser executadas fora do event loop quando em contextos assíncronos (seguindo padrão do projeto).

## 6. Estrutura de diretórios
```
shaggy-bot/
├── main.py
├── cogs/           # Cogs Discord (carregados automaticamente)
├── rpg/            # Domínio RPG Textual (delegação/padrão)
├── rpg_system/     # Módulos especializados RPG Textual
├── data/           # Bancos SQLite
├── assets/         # Assets
├── docs/           # Documentação técnica
├── .venv/          # Ambiente virtual
├── requirements.txt
└── README.md
```

## 7. Requisitos
- Python 3.10+
- discord.py >= 2.4.0 (ambiente com 2.7.1)
- python-dotenv >= 1.0.1
- Demais dependências em `requirements.txt`

## 8. Instalação
```bash
git clone <repo>
cd shaggy-bot
python -m venv .venv
source .venv/bin/activate  # Linux
pip install -r requirements.txt
```

## 9. Configuração
Crie um arquivo `.env` com:
```env
token_shaggy=SEU_TOKEN_AQUI
```
Nunca commitar tokens/credenciais.

## 10. Banco de dados
- Localização: `data/shaggy.db`
- Tabelas principais: `user_stats`, `rpg_*`, `ruptura_*`, `rt_build_*`, `badge_*`, `cassino_*`, `missoes_*`, `pet_collection`, etc.
- Migrações aditivas quando aplicável; preservar dados existentes.

## 11. Inicialização
```bash
source .venv/bin/activate
python main.py
```

## 12. Testes
Existem arquivos de teste mencionados na documentação histórica; não há pytest obrigatório configurado neste estado. Testes podem ser executados conforme necessidade:
```bash
python -m py_compile main.py cogs/*.py rpg/*.py rpg_system/*.py
```

## 13. Desenvolvimento
- Adicionar novo cog em `cogs/` (herda `commands.Cog`, possui `async def setup(bot)`)
- Seguir padrões existentes (transações via cog de economia quando aplicável)
- Usar gerenciador central de emojis em `cogs/ultility.py` (`ShaggyEmojis`/`emojis`)
- Manter Ruptura Temporal independente

## 14. Documentação
Veja pasta `docs/`: `docs/README.md`, `docs/ARCHITECTURE.md`, `docs/AGENT_HANDOFF.md`, `docs/AGENT_QUEUE.md`, `docs/BUG_TRACKER.md`, `docs/systems/`, `docs/development/`, `docs/reports/`.

## 15. Estado atual
- **Versão/Estado**: Projeto em desenvolvimento ativo. RPG Textual adaptado ao padrão do projeto com módulos especializados.
- **Verificado**: Estrutura de carregamento, integração XpAndCoins, estrutura de tabelas RPG/Ruptura.
- **Pendências importantes**: Padronização completa de emojis em todas as interfaces dos RPGs, revisão de `ultility.py` aprofundada, atualização contínua da documentação.
- **Limitações conhecidas**: Nem todas as interações Discord podem ser validadas neste ambiente; seguir padrões transacionais existentes.
