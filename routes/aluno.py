from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from models import db, Aluno, Quiz, RespostaQuiz, Desafio, Trimestre, LogAcesso
from datetime import date, datetime
import json

aluno_bp = Blueprint('aluno', __name__, url_prefix='/aluno')


def get_aluno_atual():
    aluno_id = session.get('aluno_id')
    if not aluno_id:
        return None
    return Aluno.query.get(aluno_id)


def aluno_session_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('aluno_id'):
            flash('Faça login com sua matrícula para continuar.', 'warning')
            return redirect(url_for('auth.login_aluno'))
        return f(*args, **kwargs)
    return decorated


def registrar_log(acao, detalhes='', aluno_id=None):
    log = LogAcesso(
        aluno_id=aluno_id,
        acao=acao,
        detalhes=detalhes,
        ip=request.remote_addr
    )
    db.session.add(log)
    db.session.commit()


# ── PAINEL ────────────────────────────────────────────────────────────────────

@aluno_bp.route('/painel')
@aluno_session_required
def painel():
    aluno = get_aluno_atual()
    respostas = RespostaQuiz.query.filter_by(aluno_id=aluno.id)\
        .order_by(RespostaQuiz.data_resposta.desc()).all()

    # Quizzes disponíveis (ativos, não respondidos)
    respondidos_ids = {r.quiz_id for r in respostas}
    quizzes_disp = Quiz.query.filter_by(ativo=True)\
        .filter(~Quiz.id.in_(respondidos_ids)).all()

    # Desafio de hoje
    hoje = date.today()
    desafio_hoje = Desafio.query.filter_by(
        aluno_id=aluno.id, data=hoje
    ).first()

    # Streak de desafios
    streak = calcular_streak(aluno.id)

    return render_template('aluno/painel.html', aluno=aluno,
                           respostas=respostas,
                           quizzes_disponiveis=quizzes_disp,
                           desafio_hoje=desafio_hoje,
                           streak=streak)


def calcular_streak(aluno_id):
    """Calcula sequência de dias com pelo menos 1 desafio marcado."""
    from datetime import timedelta
    hoje = date.today()
    streak = 0
    dia = hoje
    while True:
        d = Desafio.query.filter_by(aluno_id=aluno_id, data=dia).first()
        if d and d.total_marcado > 0:
            streak += 1
            dia -= timedelta(days=1)
        else:
            break
    return streak


# ── QUIZ ─────────────────────────────────────────────────────────────────────

@aluno_bp.route('/quiz/<int:quiz_id>')
@aluno_session_required
def ver_quiz(quiz_id):
    aluno = get_aluno_atual()
    quiz = Quiz.query.get_or_404(quiz_id)

    if not quiz.ativo:
        flash('Este quiz não está disponível no momento.', 'warning')
        return redirect(url_for('aluno.painel'))

    # Verificar se já respondeu
    ja_respondeu = RespostaQuiz.query.filter_by(
        aluno_id=aluno.id, quiz_id=quiz_id
    ).first()
    if ja_respondeu:
        flash('Você já respondeu este quiz. Cada quiz pode ser respondido apenas uma vez.', 'info')
        return redirect(url_for('aluno.resultado_quiz', quiz_id=quiz_id))

    dados = json.loads(quiz.perguntas_json)
    return render_template('aluno/quiz.html', quiz=quiz, dados=dados, aluno=aluno)


@aluno_bp.route('/quiz/<int:quiz_id>/enviar', methods=['POST'])
@aluno_session_required
def enviar_quiz(quiz_id):
    aluno = get_aluno_atual()
    quiz = Quiz.query.get_or_404(quiz_id)

    # Dupla verificação
    ja_respondeu = RespostaQuiz.query.filter_by(
        aluno_id=aluno.id, quiz_id=quiz_id
    ).first()
    if ja_respondeu:
        flash('Você já respondeu este quiz.', 'info')
        return redirect(url_for('aluno.resultado_quiz', quiz_id=quiz_id))

    dados = json.loads(quiz.perguntas_json)
    perguntas = dados.get('perguntas', [])
    respostas_aluno = {}
    acertos = 0

    for p in perguntas:
        num = str(p['numero'])
        resposta_aluno = request.form.get(f'q{num}', '')
        respostas_aluno[num] = resposta_aluno
        if resposta_aluno == p['resposta_correta']:
            acertos += 1

    total = len(perguntas)
    pontuacao = round((acertos / total * 100), 1) if total > 0 else 0

    resposta = RespostaQuiz(
        aluno_id=aluno.id,
        quiz_id=quiz_id,
        respostas_json=json.dumps(respostas_aluno),
        pontuacao=pontuacao,
        acertos=acertos,
        total_perguntas=total,
    )
    db.session.add(resposta)
    db.session.commit()

    registrar_log('QUIZ_RESPONDIDO',
                  f'Quiz {quiz_id} | Acertos: {acertos}/{total} | {pontuacao}%',
                  aluno.id)

    flash(f'Quiz enviado! Você acertou {acertos} de {total} questões ({pontuacao}%).', 'success')
    return redirect(url_for('aluno.resultado_quiz', quiz_id=quiz_id))


@aluno_bp.route('/quiz/<int:quiz_id>/resultado')
@aluno_session_required
def resultado_quiz(quiz_id):
    aluno = get_aluno_atual()
    quiz = Quiz.query.get_or_404(quiz_id)
    resposta = RespostaQuiz.query.filter_by(
        aluno_id=aluno.id, quiz_id=quiz_id
    ).first_or_404()

    dados = json.loads(quiz.perguntas_json)
    respostas_aluno = json.loads(resposta.respostas_json or '{}')

    historico = (RespostaQuiz.query
                 .filter_by(aluno_id=aluno.id)
                 .order_by(RespostaQuiz.data_resposta.desc())
                 .limit(6).all())
    historico = list(reversed(historico))

    return render_template('aluno/resultado_quiz.html',
                           quiz=quiz, resposta=resposta,
                           dados=dados, respostas_aluno=respostas_aluno,
                           aluno=aluno, historico=historico)


# ── DESAFIOS ──────────────────────────────────────────────────────────────────

@aluno_bp.route('/desafios', methods=['GET', 'POST'])
@aluno_session_required
def desafios():
    aluno = get_aluno_atual()
    hoje = date.today()

    desafio_hoje = Desafio.query.filter_by(
        aluno_id=aluno.id, data=hoje
    ).first()

    if request.method == 'POST':
        leitura = 'leitura' in request.form
        oracao = 'oracao' in request.form
        culto = 'culto' in request.form
        meditacao = 'meditacao' in request.form

        if desafio_hoje:
            desafio_hoje.leitura = leitura
            desafio_hoje.oracao = oracao
            desafio_hoje.culto = culto
            desafio_hoje.meditacao = meditacao
        else:
            desafio_hoje = Desafio(
                aluno_id=aluno.id,
                data=hoje,
                leitura=leitura,
                oracao=oracao,
                culto=culto,
                meditacao=meditacao,
            )
            db.session.add(desafio_hoje)
        db.session.commit()
        flash('Desafios registrados com sucesso!', 'success')
        return redirect(url_for('aluno.desafios'))

    # Histórico dos últimos 30 dias
    from datetime import timedelta
    historico = Desafio.query.filter(
        Desafio.aluno_id == aluno.id,
        Desafio.data >= hoje - timedelta(days=29)
    ).order_by(Desafio.data.desc()).all()

    streak = calcular_streak(aluno.id)

    return render_template('aluno/desafios.html', aluno=aluno,
                           desafio_hoje=desafio_hoje, historico=historico,
                           streak=streak, hoje=hoje)
