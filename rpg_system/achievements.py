import time
from .database import get_db
class Achievements:
    def __init__(self,guild_id,user_id):
        self.guild_id=guild_id; self.user_id=user_id; self.db=get_db()
    CONQUISTAS = {
        "primeiro_passo":{"nome":"Primeiro Passo","descricao":"Crie seu personagem","recompensa_xp":50},
        "minerador_iniciante":{"nome":"Minerador Iniciante","descricao":"Minere 10 vezes","recompensa_xp":100},
        "explorador":{"nome":"Explorador","descricao":"Explore 20 vezes","recompensa_xp":150},
    }
    def obter_todas(self):
        with self.db.transacao() as db:
            cursor=db.execute("SELECT chave,desbloqueada_em FROM rpg_conquistas WHERE guild_id=? AND user_id=?", (self.guild_id,self.user_id))
            desbloqueadas={row[0]:row[1] for row in cursor.fetchall()}
        res=[]
        for chave,info in self.CONQUISTAS.items():
            res.append({"chave":chave,"nome":info["nome"],"descricao":info["descricao"],"recompensa_xp":info["recompensa_xp"],"desbloqueada":chave in desbloqueadas})
        return res
