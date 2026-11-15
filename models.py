"""
models.py - Modelos do banco de dados (SQLAlchemy) do VesteBem.

Tabelas:
    usuarios        -> doadores e administradores
    categorias      -> tipos de peça (Camisas, Calças, Sapatos...) e quantos pontos valem
    instituicoes    -> instituições parceiras / pontos de coleta (APAE, Instituto São José...)
    doacoes         -> uma doação feita por um usuário para uma instituição
    itens_doacao    -> peças de cada doação (categoria + quantidade)
    premios         -> prêmios que podem ser trocados por pontos
    resgates        -> histórico de trocas de pontos por prêmios
"""
from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


# ---------------------------------------------------------------------------
# Níveis do Sistema de Benefícios
# ---------------------------------------------------------------------------
NIVEIS = [
    # (nome, pontos mínimos, pontos máximos, benefício)
    ("Semente", 0, 100, "Cupons para sorteios na ACIAC"),
    ("Ramo", 101, 300, "Descontos exclusivos no comércio local parceiro"),
    ("Árvore", 301, None, "Percentual de desconto no carnê do IPTU"),
]
# "Floresta" não depende de pontos fixos: é o Top 10 do ano (ver main.py -> ranking).


def nivel_por_pontos(pontos: int) -> dict:
    """Retorna o nível (Semente, Ramo, Árvore) correspondente a uma pontuação."""
    for nome, minimo, maximo, beneficio in NIVEIS:
        if maximo is None or pontos <= maximo:
            return {"nome": nome, "minimo": minimo, "maximo": maximo, "beneficio": beneficio}
    return {"nome": "Semente", "minimo": 0, "maximo": 100, "beneficio": NIVEIS[0][3]}


# ---------------------------------------------------------------------------
# Usuário
# ---------------------------------------------------------------------------
class Usuario(db.Model):
    __tablename__ = "usuarios"

    id = db.Column(db.Integer, primary_key=True)
    usuario = db.Column(db.String(50), unique=True, nullable=False, index=True)
    senha_hash = db.Column(db.String(255), nullable=False)
    cidade = db.Column(db.String(100), nullable=False)
    estado = db.Column(db.String(2), nullable=False)  # sigla: MG, SP...
    is_admin = db.Column(db.Boolean, default=False, nullable=False)

    # pontos_total  = tudo que o usuário já ganhou (define o nível)
    # saldo_pontos  = pontos disponíveis para trocar por prêmios (carteira virtual)
    pontos_total = db.Column(db.Integer, default=0, nullable=False)
    saldo_pontos = db.Column(db.Integer, default=0, nullable=False)

    criado_em = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    doacoes = db.relationship("Doacao", back_populates="usuario", lazy="dynamic")
    resgates = db.relationship("Resgate", back_populates="usuario", lazy="dynamic")

    def __init__(self, **kwargs):
        # Garante pontos = 0 já ao criar o objeto (o default da coluna só vale ao salvar)
        kwargs.setdefault("pontos_total", 0)
        kwargs.setdefault("saldo_pontos", 0)
        kwargs.setdefault("is_admin", False)
        super().__init__(**kwargs)

    # Senha: nunca guardamos a senha "pura", só o hash.
    def definir_senha(self, senha: str) -> None:
        self.senha_hash = generate_password_hash(senha)

    def verificar_senha(self, senha: str) -> bool:
        return check_password_hash(self.senha_hash, senha)

    @property
    def nivel(self) -> dict:
        return nivel_por_pontos(self.pontos_total)

    def __repr__(self):
        return f"<Usuario {self.usuario}>"


# ---------------------------------------------------------------------------
# Categoria de peça
# ---------------------------------------------------------------------------
class Categoria(db.Model):
    __tablename__ = "categorias"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(50), unique=True, nullable=False)
    pontos_por_peca = db.Column(db.Integer, default=5, nullable=False)

    def __repr__(self):
        return f"<Categoria {self.nome}>"


# ---------------------------------------------------------------------------
# Instituição parceira / ponto de coleta
# ---------------------------------------------------------------------------
class Instituicao(db.Model):
    __tablename__ = "instituicoes"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    endereco = db.Column(db.String(200))
    cidade = db.Column(db.String(100), nullable=False)
    estado = db.Column(db.String(2), nullable=False)
    telefone = db.Column(db.String(30))
    # Coordenadas para a busca por geolocalização
    latitude = db.Column(db.Float)
    longitude = db.Column(db.Float)
    ativa = db.Column(db.Boolean, default=True, nullable=False)

    doacoes = db.relationship("Doacao", back_populates="instituicao", lazy="dynamic")

    def __repr__(self):
        return f"<Instituicao {self.nome}>"


# ---------------------------------------------------------------------------
# Doação
# ---------------------------------------------------------------------------
class Doacao(db.Model):
    __tablename__ = "doacoes"

    PENDENTE = "pendente"
    CONFIRMADA = "confirmada"
    RECUSADA = "recusada"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    instituicao_id = db.Column(db.Integer, db.ForeignKey("instituicoes.id"), nullable=False)
    status = db.Column(db.String(20), default=PENDENTE, nullable=False)
    observacao = db.Column(db.String(255))
    pontos = db.Column(db.Integer, default=0, nullable=False)  # calculado ao cadastrar
    criada_em = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    confirmada_em = db.Column(db.DateTime)

    usuario = db.relationship("Usuario", back_populates="doacoes")
    instituicao = db.relationship("Instituicao", back_populates="doacoes")
    itens = db.relationship("ItemDoacao", back_populates="doacao", cascade="all, delete-orphan")

    @property
    def total_pecas(self) -> int:
        return sum(item.quantidade for item in self.itens)

    def calcular_pontos(self) -> int:
        return sum(item.quantidade * item.categoria.pontos_por_peca for item in self.itens)


class ItemDoacao(db.Model):
    __tablename__ = "itens_doacao"

    id = db.Column(db.Integer, primary_key=True)
    doacao_id = db.Column(db.Integer, db.ForeignKey("doacoes.id"), nullable=False)
    categoria_id = db.Column(db.Integer, db.ForeignKey("categorias.id"), nullable=False)
    quantidade = db.Column(db.Integer, default=1, nullable=False)

    doacao = db.relationship("Doacao", back_populates="itens")
    categoria = db.relationship("Categoria")


# ---------------------------------------------------------------------------
# Prêmios e resgates (troca de pontos)
# ---------------------------------------------------------------------------
class Premio(db.Model):
    __tablename__ = "premios"

    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(120), nullable=False)
    descricao = db.Column(db.String(255))
    custo_pontos = db.Column(db.Integer, nullable=False)
    nivel_minimo = db.Column(db.String(20), default="Semente", nullable=False)
    ativo = db.Column(db.Boolean, default=True, nullable=False)


class Resgate(db.Model):
    __tablename__ = "resgates"

    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey("usuarios.id"), nullable=False)
    premio_id = db.Column(db.Integer, db.ForeignKey("premios.id"), nullable=False)
    pontos_gastos = db.Column(db.Integer, nullable=False)
    criado_em = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)

    usuario = db.relationship("Usuario", back_populates="resgates")
    premio = db.relationship("Premio")
