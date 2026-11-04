import time, random
from .database import get_db
from .energy import Energy
from .progression import Progression
from .economy import Economy
class Activities:
    def __init__(self, bot, guild_id: int, user_id: int):
        self.bot = bot
        self.guild_id = guild_id
        self.user_id = user_id
        self.db = get_db()
        self.energy = Energy(guild_id,user_id)
        self.progression = Progression(guild_id,user_id)
        self.economy = Economy(bot)
    def explorar(self):
        with self.db.transacao() as db:
            row = db.execute("SELECT expira_em FROM rpg_cooldowns WHERE guild_id=? AND user_id=? AND chave='explorar'", (self.guild_id,self.user_id)).fetchone()
            if row and time.time()<row[0]: return {"sucesso":False,"motivo":"Em cooldown"}
        if not self.energy.tem(5): return {"sucesso":False,"motivo":"Energia insuficiente"}
        self.energy.consumir(5)
        agora=time.time()
        xp_gain=random.randint(10,25); coins_gain=random.randint(0,5)
        self.progression.ganhar_xp(xp_gain)
        if coins_gain>0: self.economy.adicionar(self.guild_id,self.user_id,coins_gain,"explorar")
        item_ganho=None
        if random.random()<0.3:
            from .inventory import Inventario
            inv=Inventario(self.guild_id,self.user_id); item_ganho=random.choice(["pedra","madeira","erva"]); inv.adicionar(item_ganho,1)
        with self.db.transacao() as db:
            db.execute("INSERT INTO rpg_cooldowns (guild_id,user_id,chave,expira_em) VALUES (?,?, 'explorar',?) ON CONFLICT(guild_id,user_id,chave) DO UPDATE SET expira_em=excluded.expira_em", (self.guild_id,self.user_id,agora+120))
            db.execute("INSERT INTO rpg_acoes (guild_id,user_id,tipo,detalhe,criado_em) VALUES (?,?,?,?,?)", (self.guild_id,self.user_id,'explorar',f"xp{xp_gain}",agora))
        return {"sucesso":True,"xp":xp_gain,"moedas":coins_gain,"item":item_ganho}
    def descansar(self):
        agora=time.time()
        with self.db.transacao() as db:
            row = db.execute("SELECT expira_em FROM rpg_cooldowns WHERE guild_id=? AND user_id=? AND chave='descansar'", (self.guild_id,self.user_id)).fetchone()
            if row and time.time()<row[0]: return {"sucesso":False,"motivo":"Já descansou recentemente"}
        self.energy.restaurar_completo()
        with self.db.transacao() as db:
            db.execute("INSERT INTO rpg_cooldowns (guild_id,user_id,chave,expira_em) VALUES (?,?, 'descansar',?) ON CONFLICT(guild_id,user_id,chave) DO UPDATE SET expira_em=excluded.expira_em", (self.guild_id,self.user_id,agora+600))
            db.execute("INSERT INTO rpg_acoes (guild_id,user_id,tipo,detalhe,criado_em) VALUES (?,?,?,?,?)", (self.guild_id,self.user_id,'descansar','energia_completa',agora))
        return {"sucesso":True}
