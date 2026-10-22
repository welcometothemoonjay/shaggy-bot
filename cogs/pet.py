"""
Shaggy Bot — Pets Virtuais
==========================

Pets:
- Cthulhu de Bolso
- Pinguim Mago
- Gato Cósmico

Comandos (prefixo ilustrativo: !):
    !pet
    !pet adotar
    !pet trocar
    !pet embora
    !pet santuario
    !pet status
    !pet alimentar
    !pet brincar
    !pet renomear NOME
    !pet ajuda

Compatibilidade:
- discord.py 2.x
- SQLite
- Migração da tabela virtual_pets do protótipo anterior
"""

from __future__ import annotations

import random
import sqlite3
import time
from pathlib import Path

import discord
from discord.ext import commands


# ============================================================
# CAMINHOS E CONFIGURAÇÕES
# ============================================================

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
IMAGE_DIR = ROOT / "assets" / "pets"
DB_PATH = DATA_DIR / "shaggy.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_DIR.mkdir(parents=True, exist_ok=True)

FOME_MAX = 100
FELICIDADE_MAX = 100

PERDA_FOME_HORA = 3
PERDA_FELICIDADE_HORA = 2

XP_ALIMENTAR = 3
XP_BRINCAR = 10
XP_POR_NIVEL = 100

COOLDOWN_ALIMENTAR = 30 * 60
COOLDOWN_BRINCAR = 15 * 60


PETS = {
    "cthulhu": {
        "nome": "Cthulhu de Bolso",
        "emoji": "🐙",
        "imagem": "cthulhu.png",
        "personalidade": "Misterioso e caótico",
        "descricao": (
            "Uma pequena entidade cósmica que adora comida "
            "e sussurra segredos impossíveis."
        ),
    },
    "pinguim": {
        "nome": "Pinguim Mago",
        "emoji": "🐧",
        "imagem": "pinguim_mago.png",
        "personalidade": "Estudioso e desastrado",
        "descricao": (
            "Um mago de penas que estuda feitiços antigos "
            "e às vezes conjura peixes por acidente."
        ),
    },
    "gato": {
        "nome": "Gato Cósmico",
        "emoji": "🐈",
        "imagem": "gato_cosmico.png",
        "personalidade": "Curioso e imprevisível",
        "descricao": (
            "Um felino de outra galáxia que parece conhecer "
            "segredos escondidos no universo."
        ),
    },
}


# ============================================================
# BANCO DE DADOS
# ============================================================


def conectar_db() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout = 15000")
    return con


def inicializar_banco() -> None:
    """Cria a coleção e migra os pets do protótipo anterior."""
    with conectar_db() as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS pet_collection (
                user_id INTEGER NOT NULL,
                pet_id TEXT NOT NULL,
                nome TEXT NOT NULL,
                nivel INTEGER NOT NULL DEFAULT 1,
                xp INTEGER NOT NULL DEFAULT 0,
                fome INTEGER NOT NULL DEFAULT 100,
                felicidade INTEGER NOT NULL DEFAULT 100,
                criado_em REAL NOT NULL,
                atualizado_em REAL NOT NULL,
                ultima_alimentacao REAL NOT NULL,
                ultima_brincadeira REAL NOT NULL,
                ativo INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, pet_id)
            )
        """
        )

        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_pet_collection_active
            ON pet_collection(user_id, ativo)
        """
        )

        # Migra os dados do cog antigo sem apagá-los.
        tabela_existe = con.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'virtual_pets'
        """
        ).fetchone()

        if tabela_existe:
            colunas = {
                r["name"]
                for r in con.execute("PRAGMA table_info(virtual_pets)").fetchall()
            }

            obrigatorias = {
                "user_id",
                "pet_id",
                "nome",
                "nivel",
                "xp",
                "fome",
                "felicidade",
                "criado_em",
                "atualizado_em",
                "ultima_alimentacao",
                "ultima_brincadeira",
            }

            if obrigatorias.issubset(colunas):
                con.execute(
                    """
                    INSERT OR IGNORE INTO pet_collection (
                        user_id, pet_id, nome, nivel, xp,
                        fome, felicidade, criado_em, atualizado_em,
                        ultima_alimentacao, ultima_brincadeira, ativo
                    )
                    SELECT
                        user_id, pet_id, nome, nivel, xp,
                        fome, felicidade, criado_em, atualizado_em,
                        ultima_alimentacao, ultima_brincadeira, 1
                    FROM virtual_pets
                    WHERE pet_id IN ('cthulhu', 'pinguim', 'gato')
                """
                )

        # Evita que uma migração ou edição anterior deixe vários ativos.
        # Mantém um pet ativo por jogador, sem excluir os demais.
        usuarios = con.execute(
            """
            SELECT DISTINCT user_id
            FROM pet_collection
            WHERE ativo = 1
        """
        ).fetchall()

        for usuario in usuarios:
            uid = usuario["user_id"]
            ativos = con.execute(
                """
                SELECT pet_id
                FROM pet_collection
                WHERE user_id = ? AND ativo = 1
                ORDER BY criado_em ASC, pet_id ASC
            """,
                (uid,),
            ).fetchall()

            for pet in ativos[1:]:
                con.execute(
                    """
                    UPDATE pet_collection
                    SET ativo = 0
                    WHERE user_id = ? AND pet_id = ?
                """,
                    (uid, pet["pet_id"]),
                )


def buscar_pet_ativo(user_id: int):
    atualizar_atributos(user_id)
    with conectar_db() as con:
        return con.execute(
            """
            SELECT * FROM pet_collection
            WHERE user_id = ? AND ativo = 1
            LIMIT 1
        """,
            (user_id,),
        ).fetchone()


def listar_pets(user_id: int):
    atualizar_atributos(user_id)
    with conectar_db() as con:
        return con.execute(
            """
            SELECT * FROM pet_collection
            WHERE user_id = ?
            ORDER BY ativo DESC, criado_em ASC
        """,
            (user_id,),
        ).fetchall()


def atualizar_atributos(user_id: int) -> None:
    """Aplica a perda de atributos a todos os pets do jogador."""
    agora = time.time()

    with conectar_db() as con:
        rows = con.execute(
            """
            SELECT pet_id, atualizado_em, fome, felicidade
            FROM pet_collection
            WHERE user_id = ?
        """,
            (user_id,),
        ).fetchall()

        for row in rows:
            horas = max(
                0,
                int((agora - float(row["atualizado_em"])) // 3600),
            )

            if horas <= 0:
                continue

            fome = max(
                0,
                int(row["fome"]) - horas * PERDA_FOME_HORA,
            )
            felicidade = max(
                0,
                int(row["felicidade"]) - horas * PERDA_FELICIDADE_HORA,
            )

            con.execute(
                """
                UPDATE pet_collection
                SET fome = ?, felicidade = ?, atualizado_em = ?
                WHERE user_id = ? AND pet_id = ?
            """,
                (
                    fome,
                    felicidade,
                    agora,
                    user_id,
                    row["pet_id"],
                ),
            )


def selecionar_pet(user_id: int, pet_id: str) -> tuple[bool, str]:
    """Ativa um pet existente ou registra a primeira adoção."""
    if pet_id not in PETS:
        return False, "Esse mascote não existe."

    agora = time.time()
    dados = PETS[pet_id]

    try:
        with conectar_db() as con:
            con.execute("BEGIN IMMEDIATE")

            existente = con.execute(
                """
                SELECT pet_id FROM pet_collection
                WHERE user_id = ? AND pet_id = ?
            """,
                (user_id, pet_id),
            ).fetchone()

            if existente:
                con.execute(
                    """
                    UPDATE pet_collection
                    SET ativo = 0
                    WHERE user_id = ?
                """,
                    (user_id,),
                )

                con.execute(
                    """
                    UPDATE pet_collection
                    SET ativo = 1, atualizado_em = ?
                    WHERE user_id = ? AND pet_id = ?
                """,
                    (agora, user_id, pet_id),
                )

                return True, "Você voltou a ficar com esse companheiro!"

            con.execute(
                """
                UPDATE pet_collection
                SET ativo = 0
                WHERE user_id = ?
            """,
                (user_id,),
            )

            con.execute(
                """
                INSERT INTO pet_collection (
                    user_id, pet_id, nome, nivel, xp,
                    fome, felicidade, criado_em, atualizado_em,
                    ultima_alimentacao, ultima_brincadeira, ativo
                )
                VALUES (?, ?, ?, 1, 0, 100, 100, ?, ?, ?, ?, 1)
            """,
                (
                    user_id,
                    pet_id,
                    dados["nome"],
                    agora,
                    agora,
                    agora,
                    agora,
                ),
            )

        return True, "Seu novo companheiro chegou!"
    except sqlite3.Error:
        return False, "Não consegui salvar a troca. Tente novamente."


def mandar_pet_embora(user_id: int) -> bool:
    """Desativa o pet atual, preservando-o no santuário."""
    try:
        with conectar_db() as con:
            con.execute("BEGIN IMMEDIATE")
            cursor = con.execute(
                """
                UPDATE pet_collection
                SET ativo = 0
                WHERE user_id = ? AND ativo = 1
            """,
                (user_id,),
            )
            return cursor.rowcount > 0
    except sqlite3.Error:
        return False


def adicionar_xp(user_id: int, pet_id: str, quantidade: int) -> int:
    """Adiciona XP ao pet específico e calcula os níveis ganhos."""
    with conectar_db() as con:
        row = con.execute(
            """
            SELECT nivel, xp FROM pet_collection
            WHERE user_id = ? AND pet_id = ? AND ativo = 1
        """,
            (user_id, pet_id),
        ).fetchone()

        if row is None:
            return 0

        nivel = int(row["nivel"])
        xp = int(row["xp"]) + max(0, quantidade)
        ganhos = 0

        while xp >= XP_POR_NIVEL * nivel:
            xp -= XP_POR_NIVEL * nivel
            nivel += 1
            ganhos += 1

        con.execute(
            """
            UPDATE pet_collection
            SET nivel = ?, xp = ?, atualizado_em = ?
            WHERE user_id = ? AND pet_id = ? AND ativo = 1
        """,
            (nivel, xp, time.time(), user_id, pet_id),
        )

        return ganhos


def cuidar_pet(
    user_id: int,
    pet_id: str,
    atributo: str,
    quantidade: int,
    coluna_tempo: str,
) -> bool:
    """Atualiza atributos de cuidado do pet ativo."""
    permitidos = {
        "fome": "ultima_alimentacao",
        "felicidade": "ultima_brincadeira",
    }

    if permitidos.get(atributo) != coluna_tempo:
        raise ValueError("Operação de cuidado inválida.")

    agora = time.time()

    with conectar_db() as con:
        cursor = con.execute(
            f"""
            UPDATE pet_collection
            SET {atributo} = MIN(100, MAX(0, {atributo} + ?)),
                {coluna_tempo} = ?,
                atualizado_em = ?
            WHERE user_id = ? AND pet_id = ? AND ativo = 1
        """,
            (quantidade, agora, agora, user_id, pet_id),
        )

        return cursor.rowcount > 0


# ============================================================
# FICHAS E IMAGENS
# ============================================================


def criar_embed(row: sqlite3.Row) -> discord.Embed:
    pet = PETS[row["pet_id"]]
    fome = int(row["fome"])
    felicidade = int(row["felicidade"])
    nivel = int(row["nivel"])
    xp = int(row["xp"])

    embed = discord.Embed(
        title=f'{pet["emoji"]} {row["nome"]}',
        description=pet["descricao"],
        color=discord.Color.purple(),
    )

    embed.add_field(name="⭐ Nível", value=str(nivel), inline=True)
    embed.add_field(
        name="✨ XP",
        value=f"{xp}/{XP_POR_NIVEL * nivel}",
        inline=True,
    )
    embed.add_field(
        name="🎭 Personalidade",
        value=pet["personalidade"],
        inline=False,
    )

    embed.add_field(
        name="🍖 Fome",
        value=f"{'🟩' * (fome // 10)}{'⬛' * (10 - fome // 10)} {fome}/100",
        inline=False,
    )
    embed.add_field(
        name="💖 Felicidade",
        value=(
            f"{'🟪' * (felicidade // 10)}"
            f"{'⬛' * (10 - felicidade // 10)} {felicidade}/100"
        ),
        inline=False,
    )

    if fome <= 20:
        embed.add_field(
            name="⚠️ Fome",
            value="Seu mascote precisa comer!",
            inline=False,
        )

    if felicidade <= 20:
        embed.add_field(
            name="⚠️ Felicidade",
            value="Seu mascote precisa de atenção!",
            inline=False,
        )

    embed.set_footer(text="Shaggy Bot • Santuário de Mascotes")
    return embed


async def enviar_ficha(destino, row: sqlite3.Row) -> None:
    pet = PETS[row["pet_id"]]
    embed = criar_embed(row)
    caminho = IMAGE_DIR / pet["imagem"]

    arquivo = None
    if caminho.is_file():
        arquivo = discord.File(caminho, filename=pet["imagem"])
        embed.set_image(url=f"attachment://{pet['imagem']}")

    kwargs = {"embed": embed}
    if arquivo:
        kwargs["file"] = arquivo

    if isinstance(destino, discord.Interaction):
        if destino.response.is_done():
            await destino.followup.send(**kwargs)
        else:
            await destino.response.send_message(**kwargs)
    else:
        await destino.send(**kwargs)


# ============================================================
# SELEÇÃO INTERATIVA
# ============================================================


class SelecaoPetView(discord.ui.View):
    def __init__(
        self,
        cog: "PetCog",
        user_id: int,
        modo: str,
    ):
        super().__init__(timeout=90)
        self.cog = cog
        self.user_id = user_id
        self.modo = modo

        pets_existentes = {row["pet_id"]: row for row in listar_pets(user_id)}

        for pet_id, pet in PETS.items():
            existente = pets_existentes.get(pet_id)

            if modo == "adotar" and existente:
                continue

            if modo == "trocar" and existente and existente["ativo"]:
                continue

            if modo == "trocar" and not existente:
                continue

            if modo == "adotar" and buscar_pet_ativo(user_id):
                continue

            if modo == "trocar":
                label = f'Trocar para {pet["nome"]}'
            elif existente:
                label = f'Retomar {pet["nome"]}'
            else:
                label = f'Adotar {pet["nome"]}'

            botao = discord.ui.Button(
                label=label[:80],
                emoji=pet["emoji"],
                style=discord.ButtonStyle.primary,
                custom_id=f"pet_{modo}_{pet_id}_{user_id}",
            )
            botao.callback = self.criar_callback(pet_id)
            self.add_item(botao)

        cancelar = discord.ui.Button(
            label="Cancelar",
            emoji="❌",
            style=discord.ButtonStyle.secondary,
        )
        cancelar.callback = self.cancelar
        self.add_item(cancelar)

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Essa escolha não pertence a você.",
                ephemeral=True,
            )
            return False
        return True

    def criar_callback(self, pet_id: str):
        async def callback(interaction: discord.Interaction):
            ok, mensagem = selecionar_pet(self.user_id, pet_id)

            if not ok:
                await interaction.response.send_message(mensagem, ephemeral=True)
                return

            for item in self.children:
                item.disabled = True
            self.stop()

            row = buscar_pet_ativo(self.user_id)

            await interaction.response.edit_message(
                content=f"🌌 {mensagem}",
                embed=None,
                view=self,
                attachments=[],
            )

            if row:
                await enviar_ficha(interaction, row)

        return callback

    async def cancelar(self, interaction: discord.Interaction):
        for item in self.children:
            item.disabled = True
        self.stop()

        await interaction.response.edit_message(
            content="Seleção cancelada.",
            embed=None,
            view=self,
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


class ConfirmarDespedidaView(discord.ui.View):
    def __init__(self, user_id: int):
        super().__init__(timeout=30)
        self.user_id = user_id

    async def interaction_check(
        self,
        interaction: discord.Interaction,
    ) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message(
                "Somente quem iniciou a despedida pode confirmar.",
                ephemeral=True,
            )
            return False
        return True

    @discord.ui.button(
        label="Despedir",
        emoji="👋",
        style=discord.ButtonStyle.danger,
    )
    async def confirmar(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        sucesso = mandar_pet_embora(self.user_id)

        for item in self.children:
            item.disabled = True
        self.stop()

        mensagem = (
            "🌌 Seu mascote partiu para outra realidade. "
            "Ele continuará no santuário, com seu progresso preservado. "
            "Use `!pet adotar` para escolher outro."
            if sucesso
            else "Não encontrei um pet ativo para despedir."
        )

        await interaction.response.edit_message(
            content=mensagem,
            embed=None,
            view=self,
        )

    @discord.ui.button(
        label="Cancelar",
        emoji="❤️",
        style=discord.ButtonStyle.success,
    )
    async def cancelar(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        for item in self.children:
            item.disabled = True
        self.stop()

        await interaction.response.edit_message(
            content="❤️ Você decidiu continuar com seu companheiro.",
            embed=None,
            view=self,
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ============================================================
# COG PRINCIPAL
# ============================================================


class PetCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        inicializar_banco()

    @commands.group(
        name="pet",
        invoke_without_command=True,
        help="Consulte seu mascote ou comece uma adoção.",
    )
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def pet(self, ctx: commands.Context):
        row = buscar_pet_ativo(ctx.author.id)

        if row:
            await enviar_ficha(ctx, row)
            return

        await self.mostrar_adocao(ctx, modo="adotar")

    async def mostrar_adocao(
        self,
        ctx: commands.Context,
        modo: str,
    ):
        pets = listar_pets(ctx.author.id)
        ativos = [p for p in pets if p["ativo"]]

        if modo == "adotar" and ativos:
            await ctx.send(
                "🐾 Você já tem um pet ativo. Use `!pet trocar` "
                "para escolher outro ou `!pet embora` para se despedir."
            )
            return

        if modo == "trocar" and not ativos:
            await ctx.send("Você não tem pet ativo. Use `!pet adotar`.")
            return

        view = SelecaoPetView(self, ctx.author.id, modo)

        if not view.children:
            await ctx.send(
                "Não há opções disponíveis para essa ação. "
                "Consulte `!pet santuario`."
            )
            return

        titulo = (
            "🌠 Escolha seu companheiro" if modo == "adotar" else "🌀 Troca de mascote"
        )

        embed = discord.Embed(
            title=titulo,
            description=(
                "Escolha um mascote. Os que você já possui "
                "podem ser retomados sem perder o progresso."
            ),
            color=discord.Color.purple(),
        )

        for pet in PETS.values():
            embed.add_field(
                name=f'{pet["emoji"]} {pet["nome"]}',
                value=pet["descricao"],
                inline=False,
            )

        await ctx.send(embed=embed, view=view)

    @pet.command(name="adotar", aliases=["novo"])
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def pet_adotar(self, ctx: commands.Context):
        await self.mostrar_adocao(ctx, "adotar")

    @pet.command(name="trocar", aliases=["switch"])
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def pet_trocar(self, ctx: commands.Context):
        await self.mostrar_adocao(ctx, "trocar")

    @pet.command(name="embora", aliases=["despedir", "mandar_embora"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def pet_embora(self, ctx: commands.Context):
        row = buscar_pet_ativo(ctx.author.id)

        if not row:
            await ctx.send("Você não tem um mascote ativo para despedir.")
            return

        pet = PETS[row["pet_id"]]

        embed = discord.Embed(
            title="🌌 Uma despedida?",
            description=(
                f"Você deseja se despedir de **{row['nome']}**?\n\n"
                f"{pet['emoji']} Seu companheiro ficará guardado "
                "no santuário, com seu nível e progresso preservados."
            ),
            color=discord.Color.orange(),
        )

        await ctx.send(
            embed=embed,
            view=ConfirmarDespedidaView(ctx.author.id),
        )

    @pet.command(name="santuario", aliases=["colecao", "coleção"])
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def pet_santuario(self, ctx: commands.Context):
        pets = listar_pets(ctx.author.id)

        embed = discord.Embed(
            title="🏛️ Santuário de Mascotes",
            description=(
                "Seus companheiros permanecem aqui, " "mesmo quando não estão ativos."
            ),
            color=discord.Color.purple(),
        )

        if not pets:
            embed.description = (
                "Seu santuário está vazio. Use `!pet adotar` "
                "para conhecer seu primeiro companheiro."
            )
        else:
            for row in pets:
                pet = PETS[row["pet_id"]]
                estado = "🟢 Ativo" if row["ativo"] else "🌙 Guardado"
                embed.add_field(
                    name=f'{pet["emoji"]} {row["nome"]} — {estado}',
                    value=(
                        f"Nível {row['nivel']} • "
                        f"XP {row['xp']} • "
                        f"Fome {row['fome']}/100 • "
                        f"Felicidade {row['felicidade']}/100"
                    ),
                    inline=False,
                )

        await ctx.send(embed=embed)

    @pet.command(name="status")
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def pet_status(self, ctx: commands.Context):
        row = buscar_pet_ativo(ctx.author.id)

        if not row:
            await ctx.send("Você não tem pet ativo. Use `!pet adotar`.")
            return

        await enviar_ficha(ctx, row)

    @pet.command(name="alimentar", aliases=["comida", "feed"])
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def pet_alimentar(self, ctx: commands.Context):
        row = buscar_pet_ativo(ctx.author.id)

        if not row:
            await ctx.send("Você não tem pet ativo. Use `!pet adotar`.")
            return

        restante = COOLDOWN_ALIMENTAR - (time.time() - float(row["ultima_alimentacao"]))

        if restante > 0:
            await ctx.send(
                f"🍖 Seu pet ainda está satisfeito. "
                f"Tente novamente em {max(1, int(restante // 60) + 1)} min."
            )
            return

        if int(row["fome"]) >= FOME_MAX:
            await ctx.send("🍖 Seu pet está de barriga cheia!")
            return

        if not cuidar_pet(
            ctx.author.id,
            row["pet_id"],
            "fome",
            35,
            "ultima_alimentacao",
        ):
            await ctx.send("Não consegui atualizar seu pet. Tente novamente.")
            return

        ganhos = adicionar_xp(ctx.author.id, row["pet_id"], XP_ALIMENTAR)
        novo = buscar_pet_ativo(ctx.author.id)

        await ctx.send(f'🍖 **{novo["nome"]}** recebeu uma refeição deliciosa!')
        if ganhos:
            await ctx.send(f"✨ Seu mascote subiu {ganhos} nível(is)!")
        await enviar_ficha(ctx, novo)

    @pet.command(name="brincar", aliases=["play"])
    @commands.cooldown(1, 3, commands.BucketType.user)
    async def pet_brincar(self, ctx: commands.Context):
        row = buscar_pet_ativo(ctx.author.id)

        if not row:
            await ctx.send("Você não tem pet ativo. Use `!pet adotar`.")
            return

        restante = COOLDOWN_BRINCAR - (time.time() - float(row["ultima_brincadeira"]))

        if restante > 0:
            await ctx.send(
                f"🎮 Seu pet precisa descansar. "
                f"Tente novamente em {max(1, int(restante // 60) + 1)} min."
            )
            return

        if int(row["fome"]) <= 0:
            await ctx.send(
                "🍖 Seu pet está com muita fome para brincar. " "Alimente-o primeiro."
            )
            return

        if not cuidar_pet(
            ctx.author.id,
            row["pet_id"],
            "felicidade",
            25,
            "ultima_brincadeira",
        ):
            await ctx.send("Não consegui atualizar seu pet. Tente novamente.")
            return

        ganhos = adicionar_xp(ctx.author.id, row["pet_id"], XP_BRINCAR)
        novo = buscar_pet_ativo(ctx.author.id)

        frases = [
            f'🎮 **{novo["nome"]}** correu em círculos de felicidade!',
            f'✨ **{novo["nome"]}** inventou uma brincadeira estranha!',
            f'🐾 **{novo["nome"]}** decidiu que você é o brinquedo!',
        ]
        await ctx.send(random.choice(frases))

        if ganhos:
            await ctx.send(f"🌟 Seu mascote subiu {ganhos} nível(is)!")

        await enviar_ficha(ctx, novo)

    @pet.command(name="renomear", aliases=["nome"])
    @commands.cooldown(1, 5, commands.BucketType.user)
    async def pet_renomear(
        self,
        ctx: commands.Context,
        *,
        nome: str,
    ):
        row = buscar_pet_ativo(ctx.author.id)

        if not row:
            await ctx.send("Você não tem pet ativo. Use `!pet adotar`.")
            return

        nome = nome.strip()
        if not nome or len(nome) > 32:
            await ctx.send("O nome precisa ter entre 1 e 32 caracteres.")
            return

        with conectar_db() as con:
            con.execute(
                """
                UPDATE pet_collection
                SET nome = ?, atualizado_em = ?
                WHERE user_id = ? AND pet_id = ? AND ativo = 1
            """,
                (nome, time.time(), ctx.author.id, row["pet_id"]),
            )

        novo = buscar_pet_ativo(ctx.author.id)
        await ctx.send(f"🏷️ Seu pet agora se chama **{nome}**!")
        await enviar_ficha(ctx, novo)

    @pet.command(name="ajuda")
    async def pet_ajuda(self, ctx: commands.Context):
        embed = discord.Embed(
            title="🐾 Guia dos Mascotes",
            description="Adote, cuide e troque de companheiro.",
            color=discord.Color.purple(),
        )
        embed.add_field(
            name="Comandos",
            value=(
                "`!pet` — ver o pet ativo\n"
                "`!pet adotar` — adotar ou retomar um mascote\n"
                "`!pet trocar` — trocar para outro pet guardado\n"
                "`!pet embora` — despedir-se do pet ativo\n"
                "`!pet santuario` — ver todos os seus mascotes\n"
                "`!pet status` — consultar atributos\n"
                "`!pet alimentar` — recuperar fome\n"
                "`!pet brincar` — aumentar felicidade e XP\n"
                "`!pet renomear NOME` — mudar o nome\n"
                "`!pet ajuda` — mostrar esta ajuda"
            ),
            inline=False,
        )
        await ctx.send(embed=embed)

    @pet.error
    async def pet_error(
        self,
        ctx: commands.Context,
        error: commands.CommandError,
    ):
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                f"⏳ Espere {error.retry_after:.1f} segundos antes de tentar novamente."
            )
            return

        raise error


async def setup(bot: commands.Bot):
    inicializar_banco()
    await bot.add_cog(PetCog(bot))
