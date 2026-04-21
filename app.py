import json
from flask import Flask
from flask_login import LoginManager
from models import db, AdminUser
from config import Config

PROMPT_PADRAO = """Crie um quiz bíblico com {num_perguntas} perguntas de múltipla escolha, numeradas de 1 a {num_perguntas}, com base exclusivamente no conteúdo dos links das lições que serão fornecidos.

REGRAS IMPORTANTES:

1. As perguntas devem ser elaboradas apenas com base no conteúdo principal das lições.
2. NÃO utilizar informações de:
- Comentários
- Referências
- Notas de rodapé
- Comentários bibliográficos

3. Cada pergunta deve conter 4 alternativas:
   a)
   b)
   c)
   d)

4. Apenas UMA alternativa correta.

5. As respostas corretas devem ser distribuídas de forma equilibrada entre as letras (a, b, c, d), evitando padrões.

6. As alternativas corretas e incorretas devem ter tamanho semelhante.

7. Variar entre perguntas de interpretação, conhecimento e aplicação.

8. Definir nível: iniciante, intermediário ou avançado.

9. Basear-se nas 13 lições do trimestre."""


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)

    @app.template_filter('fromjson')
    def fromjson_filter(value):
        try:
            return json.loads(value)
        except Exception:
            return {}

    login_manager = LoginManager(app)
    login_manager.login_view = 'auth.login_admin'
    login_manager.login_message = 'Faça login para acessar esta página.'
    login_manager.login_message_category = 'warning'

    @login_manager.user_loader
    def load_user(user_id):
        if user_id and user_id.startswith('admin-'):
            return AdminUser.query.get(int(user_id.split('-')[1]))
        return None

    from routes.auth import auth_bp
    from routes.admin import admin_bp
    from routes.aluno import aluno_bp
    from routes.quiz_publico import pub_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(aluno_bp)
    app.register_blueprint(pub_bp)

    with app.app_context():
        db.create_all()
        _migrate_colunas()
        _criar_admin_padrao(app)
        _seed_configuracoes()
        _seed_tokens()

    return app


def _migrate_colunas():
    """Adiciona colunas novas em tabelas existentes sem quebrar dados."""
    from sqlalchemy import text
    with db.engine.connect() as conn:
        for stmt in [
            "ALTER TABLE quizzes ADD COLUMN tipo VARCHAR(20) DEFAULT 'normal'",
            "ALTER TABLE quizzes ADD COLUMN escopo VARCHAR(20) DEFAULT 'trimestre'",
            "ALTER TABLE quizzes ADD COLUMN licao_id INTEGER REFERENCES licoes(id)",
            "ALTER TABLE quizzes ADD COLUMN token VARCHAR(32)",
        ]:
            try:
                conn.execute(text(stmt))
                conn.commit()
            except Exception:
                pass  # Coluna já existe


def _criar_admin_padrao(app):
    username = app.config['ADMIN_USERNAME']
    password = app.config['ADMIN_PASSWORD']
    if not AdminUser.query.filter_by(username=username).first():
        admin = AdminUser(username=username)
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        print(f"[EBD Digital] Admin criado: {username} / {password}")


def _seed_configuracoes():
    from models import Configuracao
    defaults = {
        'ia_provedor':          'anthropic',
        'ia_chave_api':         '',
        'ia_modelo_anthropic':  'claude-opus-4-6',
        'ia_modelo_openai':     'gpt-4o',
        'prompt_base':          PROMPT_PADRAO,
    }
    for chave, valor in defaults.items():
        if not Configuracao.query.filter_by(chave=chave).first():
            db.session.add(Configuracao(chave=chave, valor=valor))
    db.session.commit()


def _seed_tokens():
    """Gera token público para quizzes que ainda não têm."""
    import secrets
    from models import Quiz
    sem_token = Quiz.query.filter(Quiz.token == None).all()
    for q in sem_token:
        q.token = secrets.token_urlsafe(20)
    if sem_token:
        db.session.commit()


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='0.0.0.0', port=5000)
