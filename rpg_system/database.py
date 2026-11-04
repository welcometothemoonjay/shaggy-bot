import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "shaggy.db"


def caminho_banco() -> Path:
    """Caminho efetivo do banco.

    A variável SHAGGY_DB_PATH permite que testes usem um banco temporário
    sem tocar nos dados reais dos jogadores.
    """
    custom = os.getenv("SHAGGY_DB_PATH", "").strip()
    if custom:
        return Path(custom).expanduser()
    return DB_PATH


class RPGDatabase:
    def __init__(self, db_path: Path | str | None = None):
        self.db_path = Path(db_path) if db_path else caminho_banco()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def conectar(self):
        # isolation_level=None deixa o controle de transação explícito.
        db = sqlite3.connect(self.db_path, timeout=15, isolation_level=None)
        db.execute("PRAGMA busy_timeout = 15000")
        db.row_factory = sqlite3.Row
        return db

    @contextmanager
    def transacao(self):
        db = self.conectar()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


def get_db() -> RPGDatabase:
    return RPGDatabase(caminho_banco())
