# 👕 VesteBem

**Conectando solidariedade a benefícios reais para nossa cidade.**

## 📌 Sobre o Projeto

O VesteBem é um aplicativo gamificado em Python projetado para resolver a falta de logística e incentivo nas doações de roupas locais. O sistema permite que usuários categorizem peças em casa, direcionem as doações para instituições parceiras da cidade (como APAE e Instituto São José) e acumulem pontos a cada doação validada.

## ⚙️ Como Funciona

1. **Separe:** o doador faz a triagem e cadastra os itens no app, organizando por categoria (Camisas, Calças, Sapatos etc.).
2. **Doe:** escolhe a instituição parceira ou o ponto de coleta mais próximo via geolocalização.
3. **Ganhe:** quando a instituição confirma o recebimento, os pontos são creditados na carteira virtual do usuário para troca por prêmios.

## 🏆 Sistema de Benefícios

| Nível | Pontos | Benefício |
|---|---|---|
| Semente | Até 100 | Cupons para sorteios na ACIAC |
| Ramo | 101 a 300 | Descontos exclusivos no comércio local parceiro |
| Árvore | Acima de 300 | Percentual de desconto no carnê do IPTU |
| Floresta | Top 10 do ano | Certificado Cidadão Solidário e prêmios especiais |

## 🛠️ Tecnologias

- **Linguagem:** Python 3.10+
- **Framework web:** Flask
- **Banco de dados:** SQLite com SQLAlchemy (Flask-SQLAlchemy)
- **Autenticação:** sessão do Flask + senhas criptografadas (hash) com Werkzeug

---

## 🚀 Como rodar o projeto

### 1. Clonar o repositório

```bash
git clone https://github.com/Veste-Bem-UEMG/Veste-Bem-UEMG.git
cd Veste-Bem-UEMG
```

### 2. Criar o ambiente virtual e instalar as dependências

```bash
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Criar e popular o banco de dados

```bash
python seed.py
```

Isso cria o arquivo `instance/vestebem.db` e insere:

- o usuário **admin / 123**
- um login para cada instituição: **apae**, **saojose** e **coleta_uemg** (senha `123`)
- 8 categorias de peças (com a pontuação de cada uma)
- 3 instituições (APAE, Instituto São José e um ponto de coleta)
- 5 prêmios
- 5 usuários de exemplo (`maria`, `joao`, `ana`, `pedro`, `lucas`, todos com senha `123`) com doações

Para **apagar tudo e recriar do zero**:

```bash
python seed.py --reset
```

> ⚠️ Os endereços e as coordenadas das instituições em `seed.py` são **exemplos**. Ajuste as variáveis `CIDADE`, `ESTADO`, `LAT_CENTRO`, `LON_CENTRO` e a lista `INSTITUICOES` para os dados reais da cidade.

### 4. Rodar o site

```bash
python main.py
```

Acesse **http://127.0.0.1:5000**

---

## 🔐 Autenticação

Todo o site exige login. Apenas as páginas `/login` e `/cadastro` são públicas.

O sistema tem **3 perfis de acesso**. Cada um só enxerga as páginas do seu perfil e, ao entrar, cai direto na sua página inicial.

| Perfil | Como entra | O que pode fazer |
|---|---|---|
| **Administrador** | `admin` / `123` (criado automaticamente, **apenas para teste**) | Gerenciar o sistema: cadastrar instituições e os logins delas, categorias e prêmios; ver usuários e a visão geral das doações (somente leitura) |
| **Instituição** | Login criado pelo admin (no seed: `apae`, `saojose`, `coleta_uemg` / `123`) | Ver **apenas** as doações destinadas à sua instituição e **confirmar** o recebimento (credita os pontos) ou **recusar** informando o motivo |
| **Doador** | Cria a conta em `/cadastro` | Registrar doações, ver instituições próximas, acompanhar pontos e nível, trocar pontos por prêmios, ver o ranking |

**Fluxo de uma doação:** o doador registra a doação (*pendente*) → leva as peças até a instituição → a instituição entra no seu login e confirma (*confirmada*, pontos creditados) ou recusa com um motivo (*recusada*, o doador vê o motivo em "Minhas doações").

**Cadastro:** pede **usuário**, **senha** (com confirmação), **cidade** e **estado**. O sistema verifica se o nome de usuário já existe antes de criar a conta. Maiúsculas e minúsculas são tratadas como iguais, então `Maria` e `maria` são o mesmo usuário.

**Como funciona por dentro (`main.py`):**

- A senha nunca é salva em texto puro: `Usuario.definir_senha()` guarda só o **hash** (`generate_password_hash`), e o login compara com `check_password_hash`.
- Ao logar, o `id` do usuário é guardado em `session` (um cookie assinado com a `SECRET_KEY`).
- O perfil vem da tabela `usuarios`: `is_admin = True` → admin; `instituicao_id` preenchido → instituição; senão → doador.
- `@login_obrigatorio` exige login; `@doador_obrigatorio`, `@instituicao_obrigatorio` e `@admin_obrigatorio` liberam cada rota só para o perfil certo.
- Uma instituição não consegue ver nem validar doações de outra (a rota responde 404).

> Em produção, troque a senha do admin e defina a variável de ambiente `SECRET_KEY` com um valor secreto.

---

## 🗂️ Estrutura do projeto

```
Veste-Bem-UEMG/
├── main.py              # Aplicação Flask: configuração, autenticação e todas as rotas
├── models.py            # Modelos do banco (tabelas) com SQLAlchemy
├── seed.py              # Script para criar e popular o banco
├── requirements.txt     # Dependências
├── static/
│   └── style.css        # Estilo do site
├── templates/           # Páginas HTML (Jinja2)
│   ├── base.html        # Layout com menu
│   ├── login.html / cadastro.html
│   ├── painel.html      # Carteira, nível e últimas doações
│   ├── doar.html        # 1. Separe + 2. Doe
│   ├── minhas_doacoes.html
│   ├── instituicoes.html  # lista ordenada por distância (geolocalização)
│   ├── premios.html     # 3. Ganhe: troca de pontos
│   ├── ranking.html     # Floresta: Top 10 do ano
│   ├── instituicao/     # Página da instituição: confirmar ou recusar doações
│   └── admin/           # Páginas do administrador
└── instance/vestebem.db # Banco SQLite (gerado automaticamente, não vai para o Git)
```

## 🧩 Modelo de dados

```
usuarios (id, usuario*, senha_hash, cidade, estado, is_admin, instituicao_id → instituicoes, pontos_total, saldo_pontos)
categorias (id, nome*, pontos_por_peca)
instituicoes (id, nome, endereco, cidade, estado, telefone, latitude, longitude, ativa)
doacoes (id, usuario_id → usuarios, instituicao_id → instituicoes, status, motivo_recusa, pontos, criada_em, confirmada_em)
itens_doacao (id, doacao_id → doacoes, categoria_id → categorias, quantidade)
premios (id, nome, descricao, custo_pontos, nivel_minimo)
resgates (id, usuario_id → usuarios, premio_id → premios, pontos_gastos, criado_em)
* = único
```

- `pontos_total`: tudo que o usuário já ganhou. Define o nível (Semente, Ramo, Árvore).
- `saldo_pontos`: carteira virtual. Diminui quando o usuário troca pontos por prêmios.
- Status da doação: `pendente` → `confirmada` (os pontos são creditados) ou `recusada` (com `motivo_recusa`).

> **Já tinha o banco da versão anterior?** Não precisa apagar: ao rodar `python main.py` ou `python seed.py`, as colunas novas são criadas automaticamente e o `seed.py` cria os logins das instituições.

### Trocar para MySQL ou PostgreSQL

Basta definir a variável de ambiente `DATABASE_URL` (e instalar o driver):

```bash
pip install pymysql
export DATABASE_URL="mysql+pymysql://usuario:senha@localhost/vestebem"
python seed.py
```

---

## 👥 Equipe

Projeto desenvolvido por alunos de Sistemas de Informação da UEMG:

- José Maria de Sousa Junior
- Ryan Filipe
- Pablo Coelho
- Guilherme Augusto Ferraz (orientador)

## 📄 Licença

Este projeto está licenciado sob a licença MIT. Consulte o arquivo LICENSE para mais detalhes.
