from datetime import datetime, date
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import random
import string

db = SQLAlchemy()


def gerar_matricula():
    """Gera matrícula única no formato EBD-XXXXXX"""
    while True:
        codigo = ''.join(random.choices(string.digits, k=6))
        matricula = f"EBD-{codigo}"
        if not Aluno.query.filter_by(matricula=matricula).first():
            return matricula


class AdminUser(UserMixin, db.Model):
    __tablename__ = 'admin_users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def get_id(self):
        return f"admin-{self.id}"


class Aluno(db.Model):
    __tablename__ = 'alunos'
    id = db.Column(db.Integer, primary_key=True)
    matricula = db.Column(db.String(20), unique=True, nullable=False)
    nome = db.Column(db.String(150), nullable=False)
    telefone = db.Column(db.String(20))
    data_nascimento = db.Column(db.Date)
    sexo = db.Column(db.String(10))
    igreja = db.Column(db.String(150))
    classe = db.Column(db.String(50))
    ativo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    respostas = db.relationship('RespostaQuiz', backref='aluno', lazy=True)
    desafios = db.relationship('Desafio', backref='aluno', lazy=True)
    logs = db.relationship('LogAcesso', backref='aluno', lazy=True)

    def get_id(self):
        return f"aluno-{self.id}"

    @property
    def media_geral(self):
        if not self.respostas:
            return 0
        total = sum(r.pontuacao for r in self.respostas)
        return round(total / len(self.respostas), 1)

    @property
    def total_acertos(self):
        return sum(r.acertos for r in self.respostas)


class Trimestre(db.Model):
    __tablename__ = 'trimestres'
    id = db.Column(db.Integer, primary_key=True)
    ano = db.Column(db.Integer, nullable=False)
    numero = db.Column(db.Integer, nullable=False)  # 1 a 4
    tema = db.Column(db.String(200), nullable=False)
    ativo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    licoes = db.relationship('Licao', backref='trimestre', lazy=True,
                             order_by='Licao.numero')
    quizzes = db.relationship('Quiz', backref='trimestre', lazy=True)

    @property
    def nome_display(self):
        nomes = {1: '1º', 2: '2º', 3: '3º', 4: '4º'}
        return f"{nomes.get(self.numero, self.numero)} Trimestre de {self.ano}"

    def __repr__(self):
        return f"<Trimestre {self.nome_display}>"


class Licao(db.Model):
    __tablename__ = 'licoes'
    id = db.Column(db.Integer, primary_key=True)
    trimestre_id = db.Column(db.Integer, db.ForeignKey('trimestres.id'),
                             nullable=False)
    numero = db.Column(db.Integer, nullable=False)  # 1 a 13
    titulo = db.Column(db.String(200), nullable=False)
    link = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('trimestre_id', 'numero', name='uq_licao_trimestre'),
    )


class Quiz(db.Model):
    __tablename__ = 'quizzes'
    id = db.Column(db.Integer, primary_key=True)
    trimestre_id = db.Column(db.Integer, db.ForeignKey('trimestres.id'),
                             nullable=False)
    titulo = db.Column(db.String(200))
    perguntas_json = db.Column(db.Text, nullable=False)  # JSON das perguntas
    nivel = db.Column(db.String(20), default='intermediario')
    tipo = db.Column(db.String(20), default='normal')     # 'normal' | 'mega'
    escopo = db.Column(db.String(20), default='trimestre') # 'trimestre' | 'licao'
    licao_id = db.Column(db.Integer, db.ForeignKey('licoes.id'), nullable=True)
    token = db.Column(db.String(32), unique=True, nullable=True)  # link público
    ativo = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    respostas = db.relationship('RespostaQuiz', backref='quiz', lazy=True)
    licao = db.relationship('Licao', foreign_keys=[licao_id])


class RespostaQuiz(db.Model):
    __tablename__ = 'respostas_quiz'
    id = db.Column(db.Integer, primary_key=True)
    aluno_id = db.Column(db.Integer, db.ForeignKey('alunos.id'), nullable=False)
    quiz_id = db.Column(db.Integer, db.ForeignKey('quizzes.id'), nullable=False)
    respostas_json = db.Column(db.Text)  # JSON das respostas do aluno
    pontuacao = db.Column(db.Float, default=0)   # percentual 0-100
    acertos = db.Column(db.Integer, default=0)
    total_perguntas = db.Column(db.Integer, default=20)
    data_resposta = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('aluno_id', 'quiz_id', name='uq_resposta_aluno_quiz'),
    )


class Desafio(db.Model):
    __tablename__ = 'desafios'
    id = db.Column(db.Integer, primary_key=True)
    aluno_id = db.Column(db.Integer, db.ForeignKey('alunos.id'), nullable=False)
    data = db.Column(db.Date, nullable=False, default=date.today)
    leitura = db.Column(db.Boolean, default=False)
    oracao = db.Column(db.Boolean, default=False)
    culto = db.Column(db.Boolean, default=False)
    meditacao = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (
        db.UniqueConstraint('aluno_id', 'data', name='uq_desafio_aluno_dia'),
    )

    @property
    def total_marcado(self):
        return sum([self.leitura, self.oracao, self.culto, self.meditacao])


class Configuracao(db.Model):
    """Armazena configurações do sistema (chave/valor)."""
    __tablename__ = 'configuracoes'
    id = db.Column(db.Integer, primary_key=True)
    chave = db.Column(db.String(60), unique=True, nullable=False)
    valor = db.Column(db.Text, default='')

    @staticmethod
    def get(chave, padrao=''):
        c = Configuracao.query.filter_by(chave=chave).first()
        return c.valor if c else padrao

    @staticmethod
    def set(chave, valor):
        c = Configuracao.query.filter_by(chave=chave).first()
        if c:
            c.valor = valor
        else:
            c = Configuracao(chave=chave, valor=valor)
            db.session.add(c)


class LogAcesso(db.Model):
    __tablename__ = 'logs_acesso'
    id = db.Column(db.Integer, primary_key=True)
    aluno_id = db.Column(db.Integer, db.ForeignKey('alunos.id'), nullable=True)
    acao = db.Column(db.String(100))
    detalhes = db.Column(db.String(300))
    ip = db.Column(db.String(50))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
