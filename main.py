"""
main.py - Aplicação principal do VesteBem (Flask).
\\teste

Como rodar:
    pip install -r requirements.txt
    python seed.py        # (opcional) cria e popula o banco com dados de exemplo
    python main.py        # sobe o servidor em http://127.0.0.1:5000

Perfis de acesso:
    admin        -> gerencia o sistema (instituições, categorias, prêmios, usuários)
    instituicao  -> confirma ou recusa as doações destinadas à sua instituição
    doador       -> registra doações, acumula pontos e troca por prêmios

Login de administrador padrão (APENAS PARA TESTE):
    usuário: admin   senha: 123
"""
import csv
import io
import math
import os
import unicodedata
from datetime import datetime, timedelta
from functools import wraps

from flask import Flask, Response, abort, flash, g, redirect, render_template, request, session, url_for
from sqlalchemy import extract, func, inspect, text

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


def atualizar_esquema():
    """
    Adiciona colunas novas em bancos criados por versões anteriores do projeto
    (o db.create_all() cria tabelas novas, mas não altera tabelas que já existem).
    """
    colunas_novas = {
        "usuarios": {"instituicao_id": "INTEGER REFERENCES instituicoes(id)"},
        "doacoes": {"motivo_recusa": "VARCHAR(255)"},
    }
    inspetor = inspect(db.engine)
    for tabela, colunas in colunas_novas.items():
        existentes = {c["name"] for c in inspetor.get_columns(tabela)}
        for coluna, tipo in colunas.items():
            if coluna not in existentes:
                db.session.execute(text(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}"))
    db.session.commit()


def inicializar_banco():
    """Cria as tabelas (se não existirem), atualiza o esquema e cria o admin padrão."""
    with app.app_context():
        db.create_all()
        atualizar_esquema()
        criar_admin_padrao()


# ===========================================================================
# Autenticação
# ===========================================================================
@app.before_request
def carregar_usuario_logado():
    """Antes de cada requisição, carrega o usuário da sessão em g.usuario."""
    usuario_id = session.get("usuario_id")
    g.usuario = db.session.get(Usuario, usuario_id) if usuario_id else None


def pagina_inicial(usuario):
    """Cada perfil tem sua página inicial."""
    return {
        "admin": url_for("admin_doacoes"),
        "instituicao": url_for("instituicao_doacoes"),
    }.get(usuario.perfil, url_for("painel"))


def login_obrigatorio(view):
    """Decorator: só deixa acessar a rota se estiver logado."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if g.usuario is None:
            flash("Faça login para acessar o VesteBem.", "aviso")
            return redirect(url_for("login", proximo=request.path))
        return view(*args, **kwargs)
    return wrapper


def perfil_obrigatorio(perfis, mensagem):
    """Cria um decorator que só deixa acessar a rota quem tem um dos perfis indicados."""
    if isinstance(perfis, str):
        perfis = (perfis,)

    def decorator(view):
        @wraps(view)
        @login_obrigatorio
        def wrapper(*args, **kwargs):
            if g.usuario.perfil not in perfis:
                flash(mensagem, "erro")
                return redirect(pagina_inicial(g.usuario))
            return view(*args, **kwargs)
        return wrapper
    return decorator


admin_obrigatorio = perfil_obrigatorio("admin", "Acesso restrito ao administrador.")
instituicao_obrigatorio = perfil_obrigatorio("instituicao", "Acesso restrito às instituições parceiras.")
doador_obrigatorio = perfil_obrigatorio("doador", "Esta página é exclusiva para doadores.")
relatorio_obrigatorio = perfil_obrigatorio(("admin", "instituicao"),
                                           "Relatórios disponíveis apenas para instituições e administradores.")


@app.route("/login", methods=["GET", "POST"])
def login():
    if g.usuario:
        return redirect(pagina_inicial(g.usuario))

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
            return redirect(pagina_inicial(usuario))

        flash("Usuário ou senha inválidos.", "erro")

    return render_template("login.html")


@app.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    if g.usuario:
        return redirect(pagina_inicial(g.usuario))

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
    return redirect(pagina_inicial(g.usuario))


@app.route("/painel")
@doador_obrigatorio
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
@doador_obrigatorio
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
@doador_obrigatorio
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
@doador_obrigatorio
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
                Usuario.is_admin.is_(False),
                Usuario.instituicao_id.is_(None))
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
@doador_obrigatorio
def premios():
    lista = Premio.query.filter_by(ativo=True).order_by(Premio.custo_pontos).all()
    resgates = g.usuario.resgates.order_by(Resgate.criado_em.desc()).all()
    nivel_idx = ORDEM_NIVEIS.index(g.usuario.nivel["nome"])
    return render_template("premios.html", premios=lista, resgates=resgates,
                           nivel_idx=nivel_idx, ordem_niveis=ORDEM_NIVEIS)


@app.route("/premios/<int:premio_id>/resgatar", methods=["POST"])
@doador_obrigatorio
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
# Área da instituição parceira
# ===========================================================================
@app.route("/instituicao")
@instituicao_obrigatorio
def instituicao_doacoes():
    """A instituição vê somente as doações destinadas a ela."""
    status = request.args.get("status", Doacao.PENDENTE)
    minhas = Doacao.query.filter_by(instituicao_id=g.usuario.instituicao_id)
    doacoes = minhas.filter_by(status=status).order_by(Doacao.criada_em.desc()).all()
    resumo = {
        "pendentes": minhas.filter_by(status=Doacao.PENDENTE).count(),
        "confirmadas": minhas.filter_by(status=Doacao.CONFIRMADA).count(),
        "recusadas": minhas.filter_by(status=Doacao.RECUSADA).count(),
        "pecas": db.session.query(func.coalesce(func.sum(ItemDoacao.quantidade), 0)).join(Doacao)
                 .filter(Doacao.instituicao_id == g.usuario.instituicao_id,
                         Doacao.status == Doacao.CONFIRMADA).scalar(),
    }
    return render_template("instituicao/doacoes.html", doacoes=doacoes, status=status, resumo=resumo)


@app.route("/instituicao/doacoes/<int:doacao_id>/<acao>", methods=["POST"])
@instituicao_obrigatorio
def instituicao_validar_doacao(doacao_id, acao):
    """3. Ganhe: a instituição confirma (credita os pontos) ou recusa o recebimento."""
    doacao = db.get_or_404(Doacao, doacao_id)
    # Uma instituição não pode mexer em doações de outra
    if doacao.instituicao_id != g.usuario.instituicao_id:
        abort(404)

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
        motivo = request.form.get("motivo", "").strip()
        if not motivo:
            flash("Informe o motivo da recusa.", "erro")
        else:
            doacao.status = Doacao.RECUSADA
            doacao.motivo_recusa = motivo[:255]
            db.session.commit()
            flash(f"Doação #{doacao.id} recusada.", "aviso")
    else:
        abort(404)
    return redirect(url_for("instituicao_doacoes"))


# ===========================================================================
# Área do administrador (gerencia o sistema; quem valida doações é a instituição)
# ===========================================================================
@app.route("/admin")
@admin_obrigatorio
def admin_doacoes():
    """Visão geral (somente leitura) de todas as doações."""
    status = request.args.get("status", Doacao.PENDENTE)
    doacoes = Doacao.query.filter_by(status=status).order_by(Doacao.criada_em.desc()).all()
    resumo = {
        "usuarios": Usuario.query.filter_by(is_admin=False, instituicao_id=None).count(),
        "pendentes": Doacao.query.filter_by(status=Doacao.PENDENTE).count(),
        "confirmadas": Doacao.query.filter_by(status=Doacao.CONFIRMADA).count(),
        "pecas": db.session.query(func.coalesce(func.sum(ItemDoacao.quantidade), 0))
                 .join(Doacao).filter(Doacao.status == Doacao.CONFIRMADA).scalar(),
    }
    return render_template("admin/doacoes.html", doacoes=doacoes, status=status, resumo=resumo,
                           instituicoes=Instituicao.query.order_by(Instituicao.nome).all())


@app.route("/admin/instituicoes", methods=["GET", "POST"])
@admin_obrigatorio
def admin_instituicoes():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        cidade = request.form.get("cidade", "").strip()
        estado = request.form.get("estado", "").strip().upper()
        login = request.form.get("login", "").strip().lower()
        senha = request.form.get("senha", "")
        if not nome or not cidade or estado not in ESTADOS:
            flash("Preencha nome, cidade e estado.", "erro")
        elif login and (erro := validar_novo_login(login, senha)):
            flash(erro, "erro")
        else:
            inst = Instituicao(
                nome=nome, cidade=cidade, estado=estado,
                endereco=request.form.get("endereco", "").strip(),
                telefone=request.form.get("telefone", "").strip(),
                latitude=request.form.get("latitude", type=float),
                longitude=request.form.get("longitude", type=float),
            )
            db.session.add(inst)
            if login:
                criar_login_instituicao(inst, login, senha)
            db.session.commit()
            flash(f"Instituição '{nome}' cadastrada" + (f" com o login '{login}'." if login else "."), "sucesso")
        return redirect(url_for("admin_instituicoes"))

    lista = Instituicao.query.order_by(Instituicao.nome).all()
    return render_template("admin/instituicoes.html", instituicoes=lista, estados=ESTADOS)


def validar_novo_login(login, senha):
    """Retorna uma mensagem de erro, ou None se o login puder ser criado."""
    if len(login) < 3 or not login.replace("_", "").replace(".", "").isalnum():
        return "O login deve ter ao menos 3 caracteres (letras, números, '.' ou '_')."
    if Usuario.query.filter_by(usuario=login).first():
        return f"O login '{login}' já está em uso."
    if len(senha) < 3:
        return "A senha deve ter ao menos 3 caracteres."
    return None


def criar_login_instituicao(inst, login, senha):
    """Cria o usuário com perfil 'instituicao' vinculado à instituição."""
    responsavel = Usuario(usuario=login, cidade=inst.cidade, estado=inst.estado, instituicao=inst)
    responsavel.definir_senha(senha)
    db.session.add(responsavel)
    return responsavel


@app.route("/admin/instituicoes/<int:inst_id>/acesso", methods=["POST"])
@admin_obrigatorio
def admin_criar_acesso_instituicao(inst_id):
    """Cria mais um login para uma instituição já cadastrada."""
    inst = db.get_or_404(Instituicao, inst_id)
    login = request.form.get("login", "").strip().lower()
    senha = request.form.get("senha", "")
    erro = validar_novo_login(login, senha)
    if erro:
        flash(erro, "erro")
    else:
        criar_login_instituicao(inst, login, senha)
        db.session.commit()
        flash(f"Login '{login}' criado para {inst.nome}.", "sucesso")
    return redirect(url_for("admin_instituicoes"))


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
    perfil = request.args.get("perfil", "")
    usuarios = Usuario.query.order_by(Usuario.pontos_total.desc()).all()
    if perfil:
        usuarios = [u for u in usuarios if u.perfil == perfil]
    return render_template("admin/usuarios.html", usuarios=usuarios, perfil=perfil)


# ===========================================================================
# Nosso impacto (gráficos) e relatório CSV
# ===========================================================================
MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"]
PERIODOS = {"12m": "Últimos 12 meses", "ano": "Este ano", "tudo": "Desde o início"}


def somar_meses(ano, mes, n):
    """Avança (ou volta, se n < 0) n meses a partir de ano/mês."""
    total = ano * 12 + (mes - 1) + n
    return total // 12, total % 12 + 1


def dados_impacto(periodo):
    """Agrega as doações CONFIRMADAS do período para os gráficos da página de impacto."""
    agora = datetime.utcnow()
    if periodo == "ano":
        inicio = datetime(agora.year, 1, 1)
    elif periodo == "tudo":
        inicio = None
    else:  # "12m": o mês atual e os 11 anteriores
        ano, mes = somar_meses(agora.year, agora.month, -11)
        inicio = datetime(ano, mes, 1)

    consulta = Doacao.query.filter(Doacao.status == Doacao.CONFIRMADA)
    if inicio:
        consulta = consulta.filter(Doacao.confirmada_em >= inicio)
    doacoes = consulta.all()

    # Somas feitas em Python para funcionar igual em SQLite, MySQL ou PostgreSQL
    por_mes, por_categoria, por_instituicao = {}, {}, {}
    for d in doacoes:
        chave = (d.confirmada_em.year, d.confirmada_em.month)
        por_mes[chave] = por_mes.get(chave, 0) + d.total_pecas
        por_instituicao[d.instituicao.nome] = por_instituicao.get(d.instituicao.nome, 0) + d.total_pecas
        for item in d.itens:
            por_categoria[item.categoria.nome] = por_categoria.get(item.categoria.nome, 0) + item.quantidade

    # Eixo de meses contínuo (meses sem doação aparecem com 0)
    if inicio is None:
        primeiro = min(por_mes) if por_mes else (agora.year, agora.month)
        inicio_eixo = max(primeiro, somar_meses(agora.year, agora.month, -35))  # no máximo 36 meses
    else:
        inicio_eixo = (inicio.year, inicio.month)
    meses, atual = [], inicio_eixo
    while atual <= (agora.year, agora.month):
        meses.append({"rotulo": f"{MESES[atual[1] - 1]}/{str(atual[0])[2:]}", "pecas": por_mes.get(atual, 0)})
        atual = somar_meses(atual[0], atual[1], 1)

    def ordenar(dicionario):
        return sorted(dicionario.items(), key=lambda par: (-par[1], par[0]))

    return {
        "totais": {
            "pecas": sum(d.total_pecas for d in doacoes),
            "doacoes": len(doacoes),
            "doadores": len({d.usuario_id for d in doacoes}),
            "instituicoes": len({d.instituicao_id for d in doacoes}),
        },
        "meses": meses,
        "max_mes": max((m["pecas"] for m in meses), default=0),
        "categorias": ordenar(por_categoria),
        "instituicoes": ordenar(por_instituicao),
    }


@app.route("/impacto")
@login_obrigatorio
def impacto():
    """Página "Nosso impacto": visível para todos os perfis logados."""
    periodo = request.args.get("periodo", "12m")
    if periodo not in PERIODOS:
        periodo = "12m"
    return render_template("impacto.html", dados=dados_impacto(periodo), periodo=periodo, periodos=PERIODOS)


def ler_data(texto):
    """Converte 'AAAA-MM-DD' (formato do <input type="date">) em datetime; vazio -> None."""
    return datetime.strptime(texto, "%Y-%m-%d") if texto else None


def celula_segura(valor):
    """Evita que um texto digitado pelo usuário vire fórmula ao abrir o CSV no Excel."""
    texto = "" if valor is None else str(valor)
    return "'" + texto if texto[:1] in ("=", "+", "-", "@", "\t", "\r") else texto


def nome_de_arquivo(texto):
    """'Instituto São José' -> 'instituto-sao-jose'"""
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return "-".join("".join(c if c.isalnum() else " " for c in texto.lower()).split())


@app.route("/relatorio/doacoes.csv")
@relatorio_obrigatorio
def relatorio_doacoes_csv():
    """
    Exporta as doações do período em CSV (abre direto no Excel).
    - Instituição: somente as doações destinadas a ela.
    - Admin: todas, com filtro opcional por instituição.
    Filtros: inicio/fim (data de registro da doação) e status.
    """
    try:
        inicio = ler_data(request.args.get("inicio", ""))
        fim = ler_data(request.args.get("fim", ""))
    except ValueError:
        flash("Data inválida no filtro do relatório.", "erro")
        return redirect(pagina_inicial(g.usuario))
    if inicio and fim and fim < inicio:
        flash("A data final do relatório não pode ser anterior à inicial.", "erro")
        return redirect(pagina_inicial(g.usuario))

    consulta = Doacao.query
    if g.usuario.is_instituicao:
        instituicao = g.usuario.instituicao
    else:
        instituicao = db.session.get(Instituicao, request.args.get("instituicao_id", type=int) or 0)
    if instituicao:
        consulta = consulta.filter(Doacao.instituicao_id == instituicao.id)
    if inicio:
        consulta = consulta.filter(Doacao.criada_em >= inicio)
    if fim:
        consulta = consulta.filter(Doacao.criada_em < fim + timedelta(days=1))  # inclui o dia final
    status = request.args.get("status", "")
    if status in (Doacao.PENDENTE, Doacao.CONFIRMADA, Doacao.RECUSADA):
        consulta = consulta.filter(Doacao.status == status)
    doacoes = consulta.order_by(Doacao.criada_em).all()

    categorias = Categoria.query.order_by(Categoria.nome).all()
    saida = io.StringIO()
    # ";" é o separador que o Excel em português espera
    planilha = csv.writer(saida, delimiter=";")
    planilha.writerow(["ID", "Data de registro", "Data de confirmação", "Doador", "Cidade", "UF",
                       "Instituição", "Status", "Motivo da recusa", "Observação"]
                      + [c.nome for c in categorias] + ["Total de peças", "Pontos"])
    for d in doacoes:
        quantidades = {item.categoria_id: item.quantidade for item in d.itens}
        planilha.writerow(
            [d.id, d.criada_em.strftime("%d/%m/%Y"),
             d.confirmada_em.strftime("%d/%m/%Y") if d.confirmada_em else "",
             celula_segura(d.usuario.usuario), celula_segura(d.usuario.cidade), d.usuario.estado,
             celula_segura(d.instituicao.nome), d.status,
             celula_segura(d.motivo_recusa), celula_segura(d.observacao)]
            + [quantidades.get(c.id, 0) for c in categorias] + [d.total_pecas, d.pontos])

    partes = ["doacoes", nome_de_arquivo(instituicao.nome) if instituicao else "todas",
              inicio.strftime("%Y-%m-%d") if inicio else "inicio",
              fim.strftime("%Y-%m-%d") if fim else datetime.utcnow().strftime("%Y-%m-%d")]
    # "﻿" (BOM) faz o Excel reconhecer os acentos (UTF-8)
    return Response("﻿" + saida.getvalue(), mimetype="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{"_".join(partes)}.csv"'})


# ===========================================================================
# Execução
# ===========================================================================
if __name__ == "__main__":
    inicializar_banco()
    app.run(debug=True)
