"""
seed.py - Popula o banco de dados do VesteBem com dados iniciais/de exemplo.

Uso:
    python seed.py           -> cria as tabelas e insere os dados (sem apagar o que já existe)
    python seed.py --reset   -> APAGA tudo e recria do zero

IMPORTANTE: os endereços, telefones e coordenadas das instituições abaixo são
EXEMPLOS. Ajuste para os dados reais da cidade do projeto antes de apresentar.
"""
import random
import sys
from datetime import datetime, timedelta

from main import app, atualizar_esquema, criar_admin_padrao, criar_login_instituicao
from models import Categoria, Doacao, Instituicao, ItemDoacao, Premio, Usuario, db

# Ajuste para a cidade do projeto
CIDADE = "Sua Cidade"
ESTADO = "MG"
LAT_CENTRO, LON_CENTRO = -19.9167, -43.9345  # coordenadas de exemplo (troque pelas da cidade)

CATEGORIAS = [
    ("Camisas", 5), ("Calças", 8), ("Sapatos", 10), ("Agasalhos", 12),
    ("Vestidos", 8), ("Roupas infantis", 5), ("Roupas de cama", 10), ("Acessórios", 3),
]

# "login" = usuário que a instituição usa para confirmar as doações (senha: 123)
INSTITUICOES = [
    {"nome": "APAE", "login": "apae", "endereco": "Endereço de exemplo, 100 - Centro", "telefone": "(00) 0000-0000",
     "latitude": LAT_CENTRO + 0.010, "longitude": LON_CENTRO - 0.008},
    {"nome": "Instituto São José", "login": "saojose", "endereco": "Endereço de exemplo, 200 - Centro", "telefone": "(00) 0000-0000",
     "latitude": LAT_CENTRO - 0.012, "longitude": LON_CENTRO + 0.006},
    {"nome": "Ponto de Coleta - UEMG", "login": "coleta_uemg", "endereco": "Campus UEMG (exemplo)", "telefone": "",
     "latitude": LAT_CENTRO + 0.004, "longitude": LON_CENTRO + 0.015},
]

PREMIOS = [
    ("Cupom de sorteio ACIAC", "1 cupom para os sorteios da ACIAC", 20, "Semente"),
    ("5 cupons de sorteio ACIAC", "Pacote com 5 cupons para sorteios", 90, "Semente"),
    ("10% de desconto no comércio parceiro", "Válido em lojas parceiras participantes", 120, "Ramo"),
    ("20% de desconto no comércio parceiro", "Válido em lojas parceiras participantes", 250, "Ramo"),
    ("Desconto no carnê do IPTU", "Percentual de desconto no IPTU (conforme convênio)", 300, "Árvore"),
]

MOTIVOS_RECUSA = [
    "Peças rasgadas ou sem condições de uso",
    "Doação não foi entregue no local",
    "Quantidade entregue diferente da cadastrada",
]

USUARIOS_EXEMPLO = [
    # (usuario, senha, cidade, estado)
    ("maria", "123", CIDADE, ESTADO),
    ("joao", "123", CIDADE, ESTADO),
    ("ana", "123", CIDADE, ESTADO),
    ("pedro", "123", CIDADE, ESTADO),
    ("lucas", "123", CIDADE, ESTADO),
]


def popular():
    criar_admin_padrao()

    if not Categoria.query.first():
        db.session.add_all(Categoria(nome=n, pontos_por_peca=p) for n, p in CATEGORIAS)
        print(f"  + {len(CATEGORIAS)} categorias")

    if not Instituicao.query.first():
        for dados in INSTITUICOES:
            dados = {k: v for k, v in dados.items() if k != "login"}
            db.session.add(Instituicao(cidade=CIDADE, estado=ESTADO, **dados))
        print(f"  + {len(INSTITUICOES)} instituições")
    db.session.commit()

    # Login de cada instituição (também funciona em bancos criados antes desta versão)
    for dados in INSTITUICOES:
        inst = Instituicao.query.filter_by(nome=dados["nome"]).first()
        if inst and not inst.responsaveis and not Usuario.query.filter_by(usuario=dados["login"]).first():
            criar_login_instituicao(inst, dados["login"], "123")
            print(f"  + login da instituição: {dados['login']} / 123")

    if not Premio.query.first():
        db.session.add_all(Premio(nome=n, descricao=d, custo_pontos=c, nivel_minimo=nv)
                           for n, d, c, nv in PREMIOS)
        print(f"  + {len(PREMIOS)} prêmios")

    db.session.commit()

    # Usuários de exemplo com doações (algumas confirmadas, outras pendentes)
    if not Usuario.query.filter_by(is_admin=False, instituicao_id=None).first():
        random.seed(42)
        categorias = Categoria.query.all()
        instituicoes = Instituicao.query.all()
        for nome, senha, cidade, estado in USUARIOS_EXEMPLO:
            u = Usuario(usuario=nome, cidade=cidade, estado=estado)
            u.definir_senha(senha)
            db.session.add(u)

            for _ in range(random.randint(1, 6)):
                data = datetime.utcnow() - timedelta(days=random.randint(0, 60))
                d = Doacao(usuario=u, instituicao=random.choice(instituicoes), criada_em=data)
                for cat in random.sample(categorias, random.randint(1, 3)):
                    d.itens.append(ItemDoacao(categoria=cat, quantidade=random.randint(1, 6)))
                d.pontos = d.calcular_pontos()
                sorteio = random.random()
                if sorteio < 0.65:  # 65% confirmadas
                    d.status = Doacao.CONFIRMADA
                    d.confirmada_em = data + timedelta(days=1)
                    u.pontos_total += d.pontos
                    u.saldo_pontos += d.pontos
                elif sorteio < 0.75:  # 10% recusadas
                    d.status = Doacao.RECUSADA
                    d.motivo_recusa = random.choice(MOTIVOS_RECUSA)
                db.session.add(d)
        db.session.commit()
        print(f"  + {len(USUARIOS_EXEMPLO)} usuários de exemplo com doações (senha: 123)")


if __name__ == "__main__":
    with app.app_context():
        if "--reset" in sys.argv:
            db.drop_all()
            print("Banco apagado.")
        db.create_all()
        atualizar_esquema()
        print("Populando o banco...")
        popular()
        print("Pronto! Logins de teste (senha 123): admin | apae, saojose, coleta_uemg | maria, joao, ana, pedro, lucas")
