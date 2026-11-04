import time, random
from .database import get_db
from .energy import Energy
from .inventory import Inventario
from .constants import MINING_COOLDOWN_SEGUNDOS, MINING_ENERGIA_CUSTO
class Mining:
    def __init__(self, guild_id: int, user_id: int):
        self.guild_id = guild_id
        self.user_id = user_id
        self.db = get_db()
        self.energy = Energy(guild_id, user_id)
        self.inventory = Inventario(guild_id, user_id)
    def pode_minar(self) -> bool:
        if not self.energy.tem(MINING_ENERGIA_CUSTO): return False
        with self.db.transacao() as db:
            row = db.execute("SELECT expira_em FROM rpg_cooldowns WHERE guild_id = ? AND user_id = ? AND chave = 'mining'", (self.guild_id, self.user_id)).fetchone()
            if not row: return True
            return time.time() >= row[0]
    def minerar(self):
        if not self.pode_minar(): return {"sucesso": False, "motivo": "Cooldown ou energia insuficiente"}
        if not self.energy.consumir(MINING_ENERGIA_CUSTO): return {"sucesso": False, "motivo": "Energia insuficiente"}
        chances = [("pedra",40,3),("carvao",25,2),("ferro",20,1),("gema",10,1),("cristal",5,1)]
        roll = random.randint(1,100); acumulado=0; drop_item="pedra"; drop_qtd=1
        for item,chance,qtd in chances:
            acumulado+=chance
            if roll<=acumulado:
                drop_item=item; drop_qtd=random.randint(1,qtd); break
        self.inventory.adicionar(drop_item, drop_qtd)
        agora=time.time(); expira=agora+MINING_COOLDOWN_SEGUNDOS
        with self.db.transacao() as db:
            db.execute("INSERT INTO rpg_cooldowns (guild_id, user_id, chave, expira_em) VALUES (?, ?, 'mining', ?) ON CONFLICT(guild_id, user_id, chave) DO UPDATE SET expira_em = excluded.expira_em", (self.guild_id,self.user_id,expira))
            db.execute("INSERT INTO rpg_acoes (guild_id, user_id, tipo, detalhe, criado_em) VALUES (?, ?, 'minerar', ?, ?)", (self.guild_id,self.user_id,f"{drop_item}x{drop_qtd}",agora))
        return {"sucesso": True, "item": drop_item, "quantidade": drop_qtd}
