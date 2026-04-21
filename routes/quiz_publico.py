import json
from flask import (Blueprint, render_template, request, redirect,
                   url_for, flash, session, jsonify)
from models import db, Aluno, Quiz, RespostaQuiz, gerar_matricula

pub_bp = Blueprint('pub', __name__)


# ── Autocomplete de alunos ────────────────────────────────────────────────────

@pub_bp.route('/api/alunos/buscar')
def buscar_alunos():
    q = request.args.get('q', '').strip()
    if len(q) < 2:
        return jsonify([])
    alunos = (Aluno.query
              .filter(Aluno.nome.ilike(f'%{q}%'), Aluno.ativo == True)
              .order_by(Aluno.nome)
              .limit(12).all())
    return jsonify([{
        'id': a.id,
        'nome': a.nome,
        'matricula': a.matricula,
        'classe': a.classe or '',
        'igreja': a.igreja or '',
    } for a in alunos])


# ── Acesso ao quiz via link ───────────────────────────────────────────────────

@pub_bp.route('/quiz/<token>')
def acesso(token):
    quiz = Quiz.query.filter_by(token=token, ativo=True).first_or_404()
    # Se já tem aluno na sessão pública, ir direto
    aluno_id = session.get('pub_aluno_id')
    if aluno_id:
        aluno = Aluno.query.get(aluno_id)
        if aluno:
            ja = RespostaQuiz.query.filter_by(
                aluno_id=aluno_id, quiz_id=quiz.id).first()
            if ja:
                return redirect(url_for('pub.resultado', token=token))
            return redirect(url_for('pub.perguntas', token=token))
    return render_template('pub/acesso.html', quiz=quiz, token=token)


@pub_bp.route('/quiz/<token>/entrar', methods=['POST'])
def entrar(token):
    quiz = Quiz.query.filter_by(token=token, ativo=True).first_or_404()
    acao = request.form.get('acao', 'selecionar')

    if acao == 'selecionar':
        aluno_id = request.form.get('aluno_id', '').strip()
        if not aluno_id:
            flash('Selecione seu nome na lista.', 'danger')
            return redirect(url_for('pub.acesso', token=token))
        aluno = Aluno.query.get(aluno_id)
        if not aluno or not aluno.ativo:
            flash('Aluno não encontrado. Verifique o nome.', 'danger')
            return redirect(url_for('pub.acesso', token=token))

    else:  # cadastrar
        nome = request.form.get('nome', '').strip()
        if not nome:
            flash('O nome é obrigatório para se cadastrar.', 'danger')
            return redirect(url_for('pub.acesso', token=token))
        # Checar se já existe com o mesmo nome exato
        aluno = Aluno.query.filter(
            Aluno.nome.ilike(nome), Aluno.ativo == True).first()
        if not aluno:
            aluno = Aluno(
                matricula=gerar_matricula(),
                nome=nome,
                igreja=request.form.get('igreja', '').strip() or None,
                classe=request.form.get('classe', '').strip() or None,
            )
            db.session.add(aluno)
            db.session.commit()

    session['pub_aluno_id'] = aluno.id
    session['pub_aluno_nome'] = aluno.nome

    ja = RespostaQuiz.query.filter_by(
        aluno_id=aluno.id, quiz_id=quiz.id).first()
    if ja:
        flash('Você já respondeu este quiz. Veja seus resultados abaixo.', 'info')
        return redirect(url_for('pub.resultado', token=token))
    return redirect(url_for('pub.perguntas', token=token))


# ── Responder o quiz ──────────────────────────────────────────────────────────

@pub_bp.route('/quiz/<token>/perguntas')
def perguntas(token):
    quiz = Quiz.query.filter_by(token=token, ativo=True).first_or_404()
    aluno_id = session.get('pub_aluno_id')
    if not aluno_id:
        return redirect(url_for('pub.acesso', token=token))
    aluno = Aluno.query.get(aluno_id)
    if not aluno:
        session.pop('pub_aluno_id', None)
        return redirect(url_for('pub.acesso', token=token))
    ja = RespostaQuiz.query.filter_by(
        aluno_id=aluno.id, quiz_id=quiz.id).first()
    if ja:
        return redirect(url_for('pub.resultado', token=token))
    dados = json.loads(quiz.perguntas_json)
    return render_template('pub/quiz.html',
                           quiz=quiz, dados=dados, aluno=aluno, token=token)


@pub_bp.route('/quiz/<token>/enviar', methods=['POST'])
def enviar(token):
    quiz = Quiz.query.filter_by(token=token, ativo=True).first_or_404()
    aluno_id = session.get('pub_aluno_id')
    if not aluno_id:
        return redirect(url_for('pub.acesso', token=token))
    aluno = Aluno.query.get_or_404(aluno_id)

    # Bloqueio duplo
    ja = RespostaQuiz.query.filter_by(
        aluno_id=aluno.id, quiz_id=quiz.id).first()
    if ja:
        return redirect(url_for('pub.resultado', token=token))

    dados = json.loads(quiz.perguntas_json)
    perguntas_list = dados.get('perguntas', [])
    respostas_aluno = {}
    acertos = 0

    for p in perguntas_list:
        num = str(p['numero'])
        resp = request.form.get(f'q{num}', '')
        respostas_aluno[num] = resp
        if resp == p['resposta_correta']:
            acertos += 1

    total = len(perguntas_list)
    pontuacao = round(acertos / total * 100, 1) if total else 0

    db.session.add(RespostaQuiz(
        aluno_id=aluno.id,
        quiz_id=quiz.id,
        respostas_json=json.dumps(respostas_aluno),
        pontuacao=pontuacao,
        acertos=acertos,
        total_perguntas=total,
    ))
    db.session.commit()
    return redirect(url_for('pub.resultado', token=token))


# ── Resultado ─────────────────────────────────────────────────────────────────

@pub_bp.route('/quiz/<token>/resultado')
def resultado(token):
    quiz = Quiz.query.filter_by(token=token).first_or_404()
    aluno_id = session.get('pub_aluno_id')
    if not aluno_id:
        return redirect(url_for('pub.acesso', token=token))
    aluno = Aluno.query.get_or_404(aluno_id)

    resposta = RespostaQuiz.query.filter_by(
        aluno_id=aluno.id, quiz_id=quiz.id).first_or_404()
    dados = json.loads(quiz.perguntas_json)
    respostas_aluno = json.loads(resposta.respostas_json or '{}')

    # Evolução: últimos 6 quizzes (do mais antigo ao mais recente)
    historico = (RespostaQuiz.query
                 .filter_by(aluno_id=aluno.id)
                 .order_by(RespostaQuiz.data_resposta.desc())
                 .limit(6).all())
    historico = list(reversed(historico))

    return render_template('pub/resultado.html',
                           quiz=quiz, resposta=resposta, dados=dados,
                           respostas_aluno=respostas_aluno,
                           aluno=aluno, token=token, historico=historico)


# ── Trocar de aluno (sair da sessão pública) ──────────────────────────────────

@pub_bp.route('/quiz/<token>/trocar')
def trocar(token):
    session.pop('pub_aluno_id', None)
    session.pop('pub_aluno_nome', None)
    return redirect(url_for('pub.acesso', token=token))
