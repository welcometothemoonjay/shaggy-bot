import time
from .database import get_db
class Marriage:
    def __init__(self,guild_id,user_id):
        self.guild_id=guild_id; self.user_id=user_id; self.db=get_db()
    def obter_relacionamento_ativo(self):
        with self.db.transacao() as db:
            row=db.execute("SELECT * FROM rpg_relacionamentos WHERE guild_id=? AND estado='ativo' AND (user_a=? OR user_b=?)", (self.guild_id,self.user_id,self.user_id)).fetchone()
            if not row: return None
            cols=[d[0] for d in db.execute("PRAGMA table_info(rpg_relacionamentos)").fetchall()]
            return dict(zip(cols,row))
    def propor(self,alvo_id,tipo="namoro"):
        if self.user_id==alvo_id: return {"sucesso":False,"motivo":"Inválido"}
        if self.obter_relacionamento_ativo(): return {"sucesso":False,"motivo":"Já possui relacionamento ativo"}
        with self.db.transacao() as db:
            row=db.execute("SELECT id FROM rpg_relacionamentos WHERE guild_id=? AND estado='pendente' AND ((user_a=? AND user_b=?) OR (user_a=? AND user_b=?))", (self.guild_id,self.user_id,alvo_id,self.user_id,alvo_id)).fetchone()
            if row: return {"sucesso":False,"motivo":"Já existe proposta pendente"}
            agora=time.time()
            db.execute("INSERT INTO rpg_relacionamentos (guild_id,user_a,user_b,tipo,estado,solicitante,criado_em,atualizado_em) VALUES (?,?,?,?,?, ?, ?, ?)", (self.guild_id,self.user_id,alvo_id,tipo,'pendente',self.user_id,agora,agora))
            return {"sucesso":True}
    def aceitar(self,relacao_id):
        agora=time.time()
        with self.db.transacao() as db:
            row=db.execute("SELECT * FROM rpg_relacionamentos WHERE id=? AND guild_id=? AND estado='pendente'", (relacao_id,self.guild_id)).fetchone()
            if not row: return {"sucesso":False,"motivo":"Proposta não encontrada"}
            user_a,row3=row[2],row[3]
            if self.user_id not in (user_a,row3): return {"sucesso":False,"motivo":"Sem permissão"}
            if row[6]==self.user_id: return {"sucesso":False,"motivo":"Aguarde a resposta"}
            db.execute("UPDATE rpg_relacionamentos SET estado='ativo',atualizado_em=? WHERE id=?", (agora,relacao_id))
            db.execute("INSERT OR REPLACE INTO rpg_relacao_membros (guild_id,user_id,relacao_id) VALUES (?,?,?)", (self.guild_id,user_a,relacao_id))
            db.execute("INSERT OR REPLACE INTO rpg_relacao_membros (guild_id,user_id,relacao_id) VALUES (?,?,?)", (self.guild_id,row3,relacao_id))
            return {"sucesso":True}
    def divorciar(self):
        rel=self.obter_relacionamento_ativo()
        if not rel: return {"sucesso":False,"motivo":"Sem relacionamento ativo"}
        agora=time.time()
        with self.db.transacao() as db:
            db.execute("UPDATE rpg_relacionamentos SET estado='finalizado',finalizado_em=?,atualizado_em=? WHERE id=?", (agora,agora,rel['id']))
            db.execute("DELETE FROM rpg_relacao_membros WHERE relacao_id=?", (rel['id'],))
            return {"sucesso":True}
