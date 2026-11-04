import time,json,random
from datetime import datetime
from .database import get_db
from .constants import FUSO_HORARIO, MISSOES_DIARIAS_LIMITE
class RPGMissions:
    def __init__(self, guild_id: int, user_id: int):
        self.guild_id = guild_id
        self.user_id = user_id
        self.db = get_db()
    def _hoje(self):
        return datetime.now(FUSO_HORARIO).date().isoformat()
    def obter_missoes_diarias(self):
        hoje=self._hoje()
        with self.db.transacao() as db:
            cursor = db.execute("SELECT * FROM rpg_missoes WHERE guild_id=? AND user_id=? AND periodo=?", (self.guild_id,self.user_id,hoje))
            cols=[d[0] for d in db.execute("PRAGMA table_info(rpg_missoes)").fetchall()]
            missoes=[dict(zip(cols,row)) for row in cursor.fetchall()]
            if len(missoes)==0:
                return self._gerar_missoes(hoje)
            return missoes
    def _gerar_missoes(self,periodo):
        modelos=[("explorar_3","Explore 3 vezes","explorar",3,30),("minerar_5","Minere 5 vezes","minerar",5,40),("trabalhar_2","Trabalhe 2 vezes","trabalhar",2,35),("conversar_10","Interaja 10 vezes","interagir",10,25)]
        selecionadas=random.sample(modelos,min(MISSOES_DIARIAS_LIMITE,len(modelos)))
        agora=time.time(); resultado=[]
        with self.db.transacao() as db:
            for key,desc,tipo,meta,xp in selecionadas:
                db.execute("INSERT INTO rpg_missoes (guild_id,user_id,missao_key,periodo,estado,etapa,progresso,dados_json,atualizado_em) VALUES (?,?,?,?, 'ativa',0,0,?,?)", (self.guild_id,self.user_id,key,periodo,json.dumps({"desc":desc,"meta":meta,"xp":xp,"tipo":tipo}),agora))
                resultado.append({"missao_key":key,"periodo":periodo,"estado":"ativa","progresso":0,"dados_json":json.dumps({"desc":desc,"meta":meta,"xp":xp,"tipo":tipo})})
        return resultado
