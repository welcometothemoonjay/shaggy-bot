import os
import logging
from pathlib import Path

import discord
from discord import app_commands
from dotenv import load_dotenv
from discord.ext import commands

# =========================
# CONFIGURAÇÃO
# =========================

BASE_DIR = Path(__file__).resolve().parent

load_dotenv(BASE_DIR / ".env")
TOKEN = os.getenv("token_shaggy")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


# =========================
# CLASSE PRINCIPAL
# =========================

class Shaggy(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(
            command_prefix="s!",
            intents=intents,
        )
        # Evita sincronizar os mesmos comandos em cada evento on_ready.
        self._guilds_synced = set()

    async def setup_hook(self):
        pasta = BASE_DIR / "cogs"

        if not pasta.is_dir():
            raise RuntimeError(
                f"Pasta de Cogs não encontrada: {pasta}"
            )

        # Carrega automaticamente todos os módulos da pasta cogs.
        carregados = []
        falhas = []
        for arquivo in sorted(pasta.glob("*.py")):
            # Ignora __init__.py e outros arquivos especiais.
            if arquivo.name.startswith("_"):
                continue

            extensao = f"cogs.{arquivo.stem}"

            try:
                await self.load_extension(extensao)
                carregados.append(extensao)
                logging.info(
                    "[SHAGGY] Módulo carregado: %s",
                    extensao,
                )
            except discord.app_commands.errors.CommandLimitReached:
                falhas.append((extensao, "CommandLimitReached"))
                logging.error("[SHAGGY] LIMITE DE COMANDOS AO CARREGAR %s. Continuando sem falhar todo o bot.", extensao)
                continue
            except Exception as e:
                falhas.append((extensao, e))
                logging.exception(
                    "[SHAGGY] Falha ao carregar: %s",
                    extensao,
                )
                # Não interromper carregamento por falhas não-críticas
                continue

        logging.info("[SHAGGY] Cogs carregados: %d | Falhas: %d", len(carregados), len(falhas))

        # Sincroniza os comandos slash com o Discord.
        try:
            # Verifica quantidade aproximada
            cmds = list(self.tree.get_commands())
            if len(cmds) > 100:
                logging.error("[SHAGGY] LIMITE GLOBAL DE 100 SLASH COMMANDS EXCEDIDO (%d comandos). Pulando sync global; comandos funcionarão por servidor.", len(cmds))
                try:
                    # Tenta limpar sync global
                    await self.tree.sync()
                except Exception:
                    pass
            else:
                sincronizados = await self.tree.sync()
                logging.info(
                    "[SHAGGY] %s comandos sincronizados globalmente.",
                    len(sincronizados),
                )
        except discord.app_commands.errors.CommandLimitReached:
            logging.error("[SHAGGY] LIMITE GLOBAL DE 100 SLASH COMMANDS ATINGIDO. Pulando sync global.")
            try:
                await self.tree.sync()
            except Exception:
                pass
        except Exception:
            logging.exception("[SHAGGY] Falha ao sincronizar comandos globais.")
            pass


# =========================
# INICIALIZAÇÃO DO BOT
# =========================

bot = Shaggy()


@bot.event
async def on_ready():
    logging.info("[SHAGGY] Online como %s 👻", bot.user)

    # A sincronização global pode demorar para aparecer no autocomplete.
    # Copiar os comandos globais para cada servidor e sincronizar localmente
    # faz os comandos aparecerem imediatamente nos servidores em que o bot está.
    for guild in bot.guilds:
        if guild.id in bot._guilds_synced:
            continue

        try:
            bot.tree.copy_global_to(guild=guild)
            synced = await bot.tree.sync(guild=guild)
            bot._guilds_synced.add(guild.id)
            logging.info(
                "[SHAGGY] %s comandos sincronizados no servidor %s (%s).",
                len(synced),
                guild.name,
                guild.id,
            )
        except Exception:
            logging.exception(
                "[SHAGGY] Falha ao sincronizar comandos no servidor %s (%s).",
                guild.name,
                guild.id,
            )


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot:
        return

    cog = bot.get_cog("XpAndCoins")

    if cog is not None:
        await cog.processar_mensagem(message)

    # Mantém os comandos de prefixo funcionando.
    await bot.process_commands(message)



if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError(
            "Token não encontrado. Confira o arquivo .env "
            "e a variável token_shaggy."
        )

    bot.run(TOKEN)
