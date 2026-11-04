import time, random
from .database import get_db
from .energy import Energy
from .economy import Economy
from .constants import THEFT_COOLDOWN_SEGUNDOS, THEFT_SUCESSO_BASE
class Theft:
    def __init__(self,bot,guild_id,user_id):
        self.bot=bot; self.guild_id=guild_id; self.user_id=user_id; self.db=get_db(); self.energy=Energy(guild_id,user_id); self.economy=Economy(bot)
    def pode_roubar(self):
        with self.db.transacao() as db:
            row=db.execute("SELECT expira_em FROM rpg_cooldowns WHERE guild_id=? AND user_id=? AND chave='theft'", (self.guild_id,self.user_id)).fetchone()
            if not row: return True
            return time.time()>=row[0]
    def roubar(self,alvo_id):
        if self.user_id==alvo_id: return {"sucesso":False,"motivo":"Não pode roubar a si mesmo"}
        if not self.pode_roubar(): return {"sucesso":False,"motivo":"Em cooldown"}
        if not self.energy.tem(15): return {"sucesso":False,"motivo":"Energia insuficiente"}
        self.energy.consumir(15)
        if random.random()>THEFT_SUCESSO_BASE+random.uniform(-0.1,0.1): 
            agora=time.time()
            with self.db.transacao() as db:
                db.execute("INSERT INTO rpg_cooldowns (guild_id,user_id,chave,expira_em) VALUES (?,?, 'theft',?) ON CONFLICT(guild_id,user_id,chave) DO UPDATE SET expira_em=excluded.expira_em", (self.guild_id,self.user_id,agora+THEFT_COOLDOWN_SEGUNDOS))
            return {"sucesso":False,"motivo":"Falhou na tentativa"}
        saldo_alvo=self.economy.obter_saldo(self.guild_id,alvo_id)
        if saldo_alvo<10: return {"sucesso":False,"motivo":"Alvo não tem o suficiente"}
        quantia=random.randint(5,min(50,saldo_alvo//10))
        ok1,_=self.economy.remover(self.guild_id,alvo_id,quantia,"roubo")
        if not ok1: return {"sucesso":False,"motivo":"Erro ao roubar"}
        self.economy.adicionar(self.guild_id,self.user_id,quantia,"roubo")
        agora=time.time()
        with self.db.transacao() as db:
            db.execute("INSERT INTO rpg_cooldowns (guild_id,user_id,chave,expira_em) VALUES (?,?, 'theft',?) ON CONFLICT(guild_id,user_id,chave) DO UPDATE SET expira_em=excluded.expira_em", (self.guild_id,self.user_id,agora+THEFT_COOLDOWN_SEGUNDOS))
        return {"sucesso":True,"quantia":quantia}
