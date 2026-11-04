import time
from .database import get_db
from .constants import PROFISSOES_DISPONIVEIS
class Professions:
    def __init__(self, guild_id: int, user_id: int):
        self.guild_id = guild_id
        self.user_id = user_id
        self.db = get_db()
    def obter_todas(self):
        with self.db.transacao() as db:
            cursor = db.execute("SELECT * FROM rpg_profissoes WHERE guild_id = ? AND user_id = ?", (self.guild_id,self.user_id))
            cols=[d[0] for d in db.execute("PRAGMA table_info(rpg_profissoes)").fetchall()]
            return [dict(zip(cols,row)) for row in cursor.fetchall()]
    def obter(self,chave):
        with self.db.transacao() as db:
            row=db.execute("SELECT * FROM rpg_profissoes WHERE guild_id=? AND user_id=? AND chave=?", (self.guild_id,self.user_id,chave)).fetchone()
            if not row: return None
            cols=[d[0] for d in db.execute("PRAGMA table_info(rpg_profissoes)").fetchall()]
            return dict(zip(cols,row))
    def aprender(self,chave):
        if chave not in PROFISSOES_DISPONIVEIS: return False
        agora=time.time()
        with self.db.transacao() as db:
            try:
                db.execute("INSERT INTO rpg_profissoes (guild_id,user_id,chave,nivel,xp,atualizado_em) VALUES (?,?,?,?,1,0,?)", (self.guild_id,self.user_id,chave,agora))
                db.execute("INSERT INTO rpg_acoes (guild_id,user_id,tipo,detalhe,criado_em) VALUES (?,?,?,?,?)", (self.guild_id,self.user_id,'aprender_profissao',chave,agora))
                return True
            except Exception:
                return False
    def trabalhar(self,chave):
        prof=self.obter(chave)
        if not prof: return {"sucesso":False,"motivo":"Profissão não aprendida"}
        agora=time.time()
        with self.db.transacao() as db:
            row=db.execute("SELECT expira_em FROM rpg_cooldowns WHERE guild_id=? AND user_id=? AND chave=?", (self.guild_id,self.user_id,f"trabalhar_{chave}")).fetchone()
            if row and time.time()<row[0]: return {"sucesso":False,"motivo":"Em cooldown","restante":int(row[0]-time.time())}
            xp_ganho=10+prof['nivel']*2; novo_xp=prof['xp']+xp_ganho; novo_nivel=prof['nivel']
            if novo_xp>=prof['nivel']*50: novo_nivel=prof['nivel']+1; novo_xp=novo_xp%(prof['nivel']*50)
            db.execute("UPDATE rpg_profissoes SET nivel=?,xp=?,atualizado_em=? WHERE guild_id=? AND user_id=? AND chave=?", (novo_nivel,novo_xp,agora,self.guild_id,self.user_id,chave))
            db.execute("INSERT INTO rpg_cooldowns (guild_id,user_id,chave,expira_em) VALUES (?,?,?,?) ON CONFLICT(guild_id,user_id,chave) DO UPDATE SET expira_em=excluded.expira_em", (self.guild_id,self.user_id,f"trabalhar_{chave}",agora+300))
            db.execute("INSERT INTO rpg_acoes (guild_id,user_id,tipo,detalhe,criado_em) VALUES (?,?,?,?,?)", (self.guild_id,self.user_id,'trabalhar',chave,agora))
            return {"sucesso":True,"xp_ganho":xp_ganho,"nivel":novo_nivel,"subiu":novo_nivel>prof['nivel']}
