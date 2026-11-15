"""
main.py - Aplicação principal do VesteBem (Flask).

Como rodar:
    pip install -r requirements.txt
    python seed.py        # (opcional) cria e popula o banco com dados de exemplo
    python main.py        # sobe o servidor em http://127.0.0.1:5000

Login de administrador padrão (APENAS PARA TESTE):
    usuário: admin   senha: 123
"""
import math
import os
from datetime import datetime
from functools import wraps

from flask import Flask, flash, g, redirect, render_template, request, session, url_for
from sqlalchemy import extract, func

from models import (
    NIVEIS,
    Categoria,
    Doacao,
    Instituicao,
    ItemDoacao,
    Premio,
    Resgate,
    Usuario,
    db,
)

ESTADOS = [
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
    "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
]
ORDEM_NIVEIS = [n[0] for n in NIVEIS]  # ["Semente", "Ramo", "Árvore"]


# ===========================================================================
# Configuração da aplicação e do banco
# ===========================================================================
app = Flask(__name__)

# Em produção defina a variável de ambiente SECRET_KEY com um valor secreto.
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "vestebem-chave-de-desenvolvimento")
# SQLite: o arquivo fica em instance/vestebem.db (criado automaticamente).
# Para trocar de banco basta mudar esta URL, ex.: "mysql+pymysql://user:senha@host/vestebem"
app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///vestebem.db")
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db.init_app(app)


def criar_admin_padrao():
    """Garante que exista o usuário admin / 123 (apenas para testes)."""
    if not Usuario.query.filter_by(usuario="admin").first():
        admin = Usuario(usuario="admin", cidade="-", estado="MG", is_admin=True)
        admin.definir_senha("123")
        db.session.add(admin)
        db.session.commit()


def inicializar_banco():
    """Cria as tabelas (se não existirem) e o admin padrão."""
    with app.app_context():
        db.create_all()
        criar_admin_padrao()


# ===========================================================================
# Autenticação
# ===========================================================================
@app.before_request
def carregar_usuario_logado():
    """Antes de cada requisição, carrega o usuário da sessão em g.usuario."""
    usuario_id = session.get("usuario_id")
    g.usuario = db.session.get(Usuario, usuario_id) if usuario_id else None


def login_obrigatorio(view):
    """Decorator: só deixa acessar a rota se estiver logado."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if g.usuario is None:
            flash("Faça login para acessar o VesteBem.", "aviso")
            return redirect(url_for("login", proximo=request.path))
        return view(*args, **kwargs)
    return wrapper


def admin_obrigatorio(view):
    """Decorator: só deixa acessar a rota se for administrador."""
    @wraps(view)
    @login_obrigatorio
    def wrapper(*args, **kwargs):
        if not g.usuario.is_admin:
            flash("Acesso restrito ao administrador.", "erro")
            return redirect(url_for("painel"))
        return view(*args, **kwargs)
    return wrapper


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.usuario:
        return redirect(url_for("painel"))

    if request.method == "POST":
        nome = request.form.get("usuario", "").strip().lower()
        senha = request.form.get("senha", "")
        usuario = Usuario.query.filter_by(usuario=nome).first()

        if usuario and usuario.verificar_senha(senha):
            session.clear()
            session["usuario_id"] = usuario.id
            flash(f"Bem-vindo(a), {usuario.usuario}!", "sucesso")
            proximo = request.args.get("proximo")
            # Só redireciona para caminhos internos (evita "open redirect")
            if proximo and proximo.startswith("/") and not proximo.startswith("//"):
                return redirect(proximo)
            return redirect(url_for("admin_doacoes" if usuario.is_admin else "painel"))

        flash("Usuário ou senha inválidos.", "erro")

    return render_template("login.html")


@app.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    if g.usuario:
        return redirect(url_for("painel"))

    dados = {}
    if request.method == "POST":
        dados = {
            "usuario": request.form.get("usuario", "").strip().lower(),
            "cidade": request.form.get("cidade", "").strip(),
            "estado": request.form.get("estado", "").strip().upper(),
        }
        senha = request.form.get("senha", "")
        confirmar = request.form.get("confirmar_senha", "")

        erros = []
        if len(dados["usuario"]) < 3 or not dados["usuario"].replace("_", "").replace(".", "").isalnum():
            erros.append("O usuário deve ter ao menos 3 caracteres (letras, números, '.' ou '_').")
        if Usuario.query.filter_by(usuario=dados["usuario"]).first():
            erros.append("Este nome de usuário já está em uso. Escolha outro.")
        if len(senha) < 3:
            erros.append("A senha deve ter ao menos 3 caracteres.")
        if senha != confirmar:
            erros.append("As senhas não conferem.")
        if not dados["cidade"]:
            erros.append("Informe a cidade.")
        if dados["estado"] not in ESTADOS:
            erros.append("Selecione um estado válido.")

        if erros:
            for erro in erros:
                flash(erro, "erro")
        else:
            novo = Usuario(usuario=dados["usuario"], cidade=dados["cidade"], estado=dados["estado"])
            novo.definir_senha(senha)
            db.session.add(novo)
            db.session.commit()
            flash("Cadastro realizado! Agora faça login.", "sucesso")
            return redirect(url_for("login"))

    return render_template("cadastro.html", estados=ESTADOS, dados=dados)


@app.route("/logout")
def logout():
    session.clear()
    flash("Você saiu da sua conta.", "sucesso")
    return redirect(url_for("login"))


# ===========================================================================
# Área do doador
# ===========================================================================
@app.route("/")
@login_obrigatorio
def index():
    return redirect(url_for("painel"))


@app.route("/painel")
@login_obrigatorio
def painel():
    u = g.usuario
    nivel = u.nivel
    # Progresso até o próximo nível (para a barra de progresso)
    if nivel["maximo"]:
        progresso = int(100 * (u.pontos_total - nivel["minimo"]) / (nivel["maximo"] - nivel["minimo"] + 1))
    else:
        progresso = 100
    ultimas = u.doacoes.order_by(Doacao.criada_em.desc()).limit(5).all()
    pendentes = u.doacoes.filter_by(status=Doacao.PENDENTE).count()
    return render_template(
        "painel.html", nivel=nivel, progresso=progresso, ultimas=ultimas,
        pendentes=pendentes, niveis=NIVEIS, floresta=usuario_no_top10(u.id),
    )


@app.route("/doar", methods=["GET", "POST"])
@login_obrigatorio
def doar():
    categorias = Categoria.query.order_by(Categoria.nome).all()
    instituicoes = Instituicao.query.filter_by(ativa=True).order_by(Instituicao.nome).all()

    if request.method == "POST":
        instituicao = db.session.get(Instituicao, request.form.get("instituicao_id", type=int))
        if not instituicao or not instituicao.ativa:
            flash("Escolha uma instituição válida.", "erro")
            return redirect(url_for("doar"))

        doacao = Doacao(usuario=g.usuario, instituicao=instituicao,
                        observacao=request.form.get("observacao", "").strip()[:255])
        # 1. Separe: o doador informa a quantidade de peças por categoria
        for cat in categorias:
            qtd = request.form.get(f"qtd_{cat.id}", type=int) or 0
            if qtd > 0:
                doacao.itens.append(ItemDoacao(categoria=cat, quantidade=min(qtd, 500)))

        if not doacao.itens:
            flash("Informe a quantidade de pelo menos uma peça.", "erro")
            return redirect(url_for("doar"))

        doacao.pontos = doacao.calcular_pontos()
        db.session.add(doacao)
        db.session.commit()
        flash(f"Doação registrada! Leve as peças até {instituicao.nome}. "
              f"Você ganhará {doacao.pontos} pontos quando a instituição confirmar o recebimento.",
              "sucesso")
        return redirect(url_for("minhas_doacoes"))

    instituicao_escolhida = request.args.get("instituicao", type=int)
    return render_template("doar.html", categorias=categorias, instituicoes=instituicoes,
                           instituicao_escolhida=instituicao_escolhida)


@app.route("/minhas-doacoes")
@login_obrigatorio
def minhas_doacoes():
    doacoes = g.usuario.doacoes.order_by(Doacao.criada_em.desc()).all()
    return render_template("minhas_doacoes.html", doacoes=doacoes)


def distancia_km(lat1, lon1, lat2, lon2):
    """Distância entre dois pontos (fórmula de Haversine), em km."""
    r = 6371
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


@app.route("/instituicoes")
@login_obrigatorio
def instituicoes():
    """2. Doe: lista instituições, ordenando pela mais próxima se o navegador enviar a localização."""
    lat = request.args.get("lat", type=float)
    lon = request.args.get("lon", type=float)
    lista = []
    for inst in Instituicao.query.filter_by(ativa=True).all():
        dist = None
        if lat is not None and lon is not None and inst.latitude is not None:
            dist = distancia_km(lat, lon, inst.latitude, inst.longitude)
        lista.append({"inst": inst, "distancia": dist})

    if lat is not None:
        lista.sort(key=lambda x: (x["distancia"] is None, x["distancia"] or 0))
    else:
        # Sem localização: mostra primeiro as da cidade do usuário
        lista.sort(key=lambda x: (x["inst"].cidade.lower() != g.usuario.cidade.lower(), x["inst"].nome))
    return render_template("instituicoes.html", lista=lista, com_localizacao=lat is not None)


def ranking_do_ano(limite=10):
    """Top doadores do ano atual (pontos de doações confirmadas no ano)."""
    ano = datetime.utcnow().year
    pontos = func.sum(Doacao.pontos).label("pontos")
    return (
        db.session.query(Usuario, pontos)
        .join(Doacao, Doacao.usuario_id == Usuario.id)
        .filter(Doacao.status == Doacao.CONFIRMADA,
                extract("year", Doacao.confirmada_em) == ano,
                Usuario.is_admin.is_(False))
        .group_by(Usuario.id)
        .order_by(pontos.desc())
        .limit(limite)
        .all()
    )


def usuario_no_top10(usuario_id):
    return any(u.id == usuario_id for u, _ in ranking_do_ano(10))


@app.route("/ranking")
@login_obrigatorio
def ranking():
    return render_template("ranking.html", ranking=ranking_do_ano(10), ano=datetime.utcnow().year)


@app.route("/premios")
@login_obrigatorio
def premios():
    lista = Premio.query.filter_by(ativo=True).order_by(Premio.custo_pontos).all()
    resgates = g.usuario.resgates.order_by(Resgate.criado_em.desc()).all()
    nivel_idx = ORDEM_NIVEIS.index(g.usuario.nivel["nome"])
    return render_template("premios.html", premios=lista, resgates=resgates,
                           nivel_idx=nivel_idx, ordem_niveis=ORDEM_NIVEIS)


@app.route("/premios/<int:premio_id>/resgatar", methods=["POST"])
@login_obrigatorio
def resgatar_premio(premio_id):
    """3. Ganhe: troca os pontos da carteira virtual por um prêmio."""
    premio = db.get_or_404(Premio, premio_id)
    u = g.usuario
    if not premio.ativo:
        flash("Prêmio indisponível.", "erro")
    elif ORDEM_NIVEIS.index(u.nivel["nome"]) < ORDEM_NIVEIS.index(premio.nivel_minimo):
        flash(f"Este prêmio exige o nível {premio.nivel_minimo}.", "erro")
    elif u.saldo_pontos < premio.custo_pontos:
        flash("Saldo de pontos insuficiente.", "erro")
    else:
        u.saldo_pontos -= premio.custo_pontos
        db.session.add(Resgate(usuario=u, premio=premio, pontos_gastos=premio.custo_pontos))
        db.session.commit()
        flash(f"Prêmio '{premio.nome}' resgatado com sucesso!", "sucesso")
    return redirect(url_for("premios"))


# ===========================================================================
# Área do administrador
# ===========================================================================
@app.route("/admin")
@admin_obrigatorio
def admin_doacoes():
    status = request.args.get("status", Doacao.PENDENTE)
    doacoes = Doacao.query.filter_by(status=status).order_by(Doacao.criada_em.desc()).all()
    resumo = {
        "usuarios": Usuario.query.filter_by(is_admin=False).count(),
        "pendentes": Doacao.query.filter_by(status=Doacao.PENDENTE).count(),
        "confirmadas": Doacao.query.filter_by(status=Doacao.CONFIRMADA).count(),
        "pecas": db.session.query(func.coalesce(func.sum(ItemDoacao.quantidade), 0))
                 .join(Doacao).filter(Doacao.status == Doacao.CONFIRMADA).scalar(),
    }
    return render_template("admin/doacoes.html", doacoes=doacoes, status=status, resumo=resumo)


@app.route("/admin/doacoes/<int:doacao_id>/<acao>", methods=["POST"])
@admin_obrigatorio
def admin_validar_doacao(doacao_id, acao):
    """A instituição (representada pelo admin) confirma ou recusa o recebimento."""
    doacao = db.get_or_404(Doacao, doacao_id)
    if doacao.status != Doacao.PENDENTE:
        flash("Esta doação já foi validada.", "aviso")
    elif acao == "confirmar":
        doacao.status = Doacao.CONFIRMADA
        doacao.confirmada_em = datetime.utcnow()
        doacao.usuario.pontos_total += doacao.pontos
        doacao.usuario.saldo_pontos += doacao.pontos
        db.session.commit()
        flash(f"Doação #{doacao.id} confirmada: +{doacao.pontos} pontos para {doacao.usuario.usuario}.", "sucesso")
    elif acao == "recusar":
        doacao.status = Doacao.RECUSADA
        db.session.commit()
        flash(f"Doação #{doacao.id} recusada.", "aviso")
    return redirect(url_for("admin_doacoes"))


@app.route("/admin/instituicoes", methods=["GET", "POST"])
@admin_obrigatorio
def admin_instituicoes():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        cidade = request.form.get("cidade", "").strip()
        estado = request.form.get("estado", "").strip().upper()
        if not nome or not cidade or estado not in ESTADOS:
            flash("Preencha nome, cidade e estado.", "erro")
        else:
            db.session.add(Instituicao(
                nome=nome, cidade=cidade, estado=estado,
                endereco=request.form.get("endereco", "").strip(),
                telefone=request.form.get("telefone", "").strip(),
                latitude=request.form.get("latitude", type=float),
                longitude=request.form.get("longitude", type=float),
            ))
            db.session.commit()
            flash(f"Instituição '{nome}' cadastrada.", "sucesso")
        return redirect(url_for("admin_instituicoes"))

    lista = Instituicao.query.order_by(Instituicao.nome).all()
    return render_template("admin/instituicoes.html", instituicoes=lista, estados=ESTADOS)


@app.route("/admin/instituicoes/<int:inst_id>/alternar", methods=["POST"])
@admin_obrigatorio
def admin_alternar_instituicao(inst_id):
    """Ativa/desativa uma instituição (não apaga, para manter o histórico de doações)."""
    inst = db.get_or_404(Instituicao, inst_id)
    inst.ativa = not inst.ativa
    db.session.commit()
    flash(f"'{inst.nome}' {'ativada' if inst.ativa else 'desativada'}.", "sucesso")
    return redirect(url_for("admin_instituicoes"))


@app.route("/admin/categorias", methods=["GET", "POST"])
@admin_obrigatorio
def admin_categorias():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        pontos = request.form.get("pontos_por_peca", type=int)
        if not nome or not pontos or pontos < 1:
            flash("Informe o nome e os pontos por peça.", "erro")
        elif Categoria.query.filter(func.lower(Categoria.nome) == nome.lower()).first():
            flash("Categoria já existe.", "erro")
        else:
            db.session.add(Categoria(nome=nome, pontos_por_peca=pontos))
            db.session.commit()
            flash(f"Categoria '{nome}' criada.", "sucesso")
        return redirect(url_for("admin_categorias"))
    return render_template("admin/categorias.html", categorias=Categoria.query.order_by(Categoria.nome).all())


@app.route("/admin/premios", methods=["GET", "POST"])
@admin_obrigatorio
def admin_premios():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        custo = request.form.get("custo_pontos", type=int)
        nivel = request.form.get("nivel_minimo", "Semente")
        if not nome or not custo or custo < 1 or nivel not in ORDEM_NIVEIS:
            flash("Preencha nome, custo e nível.", "erro")
        else:
            db.session.add(Premio(nome=nome, custo_pontos=custo, nivel_minimo=nivel,
                                  descricao=request.form.get("descricao", "").strip()))
            db.session.commit()
            flash(f"Prêmio '{nome}' cadastrado.", "sucesso")
        return redirect(url_for("admin_premios"))
    return render_template("admin/premios.html", premios=Premio.query.order_by(Premio.custo_pontos).all(),
                           niveis=ORDEM_NIVEIS)


@app.route("/admin/usuarios")
@admin_obrigatorio
def admin_usuarios():
    usuarios = Usuario.query.order_by(Usuario.pontos_total.desc()).all()
    return render_template("admin/usuarios.html", usuarios=usuarios)


# ===========================================================================
# Execução
# ===========================================================================
if __name__ == "__main__":
    inicializar_banco()
    app.run(debug=True)
