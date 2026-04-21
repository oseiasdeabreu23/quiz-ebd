import re
import json
import secrets
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from flask_login import login_required
from models import db, Aluno, Trimestre, Licao, Quiz, RespostaQuiz, Desafio, LogAcesso, Configuracao, gerar_matricula
from datetime import datetime, date

try:
    import anthropic as _anthropic_mod
    _ANTHROPIC_OK = True
except ImportError:
    _ANTHROPIC_OK = False

try:
    import openai as _openai_mod
    _OPENAI_OK = True
except ImportError:
    _OPENAI_OK = False

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# ── Modelos disponíveis por provedor ─────────────────────────────────────────

MODELOS = {
    'anthropic': [
        ('claude-opus-4-6',          'Claude Opus 4.6 (mais capaz)'),
        ('claude-sonnet-4-6',        'Claude Sonnet 4.6 (equilibrado)'),
        ('claude-haiku-4-5-20251001','Claude Haiku 4.5 (mais rápido)'),
    ],
    'openai': [
        ('gpt-4o',       'GPT-4o (mais capaz)'),
        ('gpt-4o-mini',  'GPT-4o Mini (econômico)'),
        ('gpt-4-turbo',  'GPT-4 Turbo'),
        ('gpt-3.5-turbo','GPT-3.5 Turbo (mais rápido)'),
    ],
}


# ── DASHBOARD ────────────────────────────────────────────────────────────────

@admin_bp.route('/dashboard')
@login_required
def dashboard():
    stats = {
        'total_alunos':    Aluno.query.filter_by(ativo=True).count(),
        'total_trimestres': Trimestre.query.count(),
        'total_quizzes':   Quiz.query.count(),
        'total_respostas': RespostaQuiz.query.count(),
    }
    trimestres = Trimestre.query.order_by(
        Trimestre.ano.desc(), Trimestre.numero.desc()
    ).limit(4).all()
    logs = LogAcesso.query.order_by(LogAcesso.timestamp.desc()).limit(10).all()
    return render_template('admin/dashboard.html', stats=stats,
                           trimestres=trimestres, logs=logs)


# ── ALUNOS ───────────────────────────────────────────────────────────────────

@admin_bp.route('/alunos')
@login_required
def alunos():
    busca  = request.args.get('busca', '')
    classe = request.args.get('classe', '')
    q = Aluno.query.filter_by(ativo=True)
    if busca:
        q = q.filter(Aluno.nome.ilike(f'%{busca}%') |
                     Aluno.matricula.ilike(f'%{busca}%'))
    if classe:
        q = q.filter_by(classe=classe)
    alunos_list = q.order_by(Aluno.nome).all()
    classes = db.session.query(Aluno.classe).distinct().filter(
        Aluno.classe.isnot(None)).all()
    return render_template('admin/alunos.html', alunos=alunos_list,
                           classes=[c[0] for c in classes],
                           busca=busca, classe_sel=classe)


@admin_bp.route('/alunos/novo', methods=['GET', 'POST'])
@login_required
def novo_aluno():
    if request.method == 'POST':
        try:
            dn_str = request.form.get('data_nascimento')
            dn = datetime.strptime(dn_str, '%Y-%m-%d').date() if dn_str else None
            aluno = Aluno(
                matricula=gerar_matricula(),
                nome=request.form['nome'].strip(),
                telefone=request.form.get('telefone', '').strip(),
                data_nascimento=dn,
                sexo=request.form.get('sexo'),
                igreja=request.form.get('igreja', '').strip(),
                classe=request.form.get('classe', '').strip(),
            )
            db.session.add(aluno)
            db.session.commit()
            flash(f'Aluno cadastrado com matrícula: {aluno.matricula}', 'success')
            return redirect(url_for('admin.alunos'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao cadastrar aluno: {str(e)}', 'danger')
    return render_template('admin/novo_aluno.html')


@admin_bp.route('/alunos/<int:aluno_id>/editar', methods=['GET', 'POST'])
@login_required
def editar_aluno(aluno_id):
    aluno = Aluno.query.get_or_404(aluno_id)
    if request.method == 'POST':
        try:
            dn_str = request.form.get('data_nascimento')
            aluno.nome      = request.form['nome'].strip()
            aluno.telefone  = request.form.get('telefone', '').strip()
            aluno.data_nascimento = (datetime.strptime(dn_str, '%Y-%m-%d').date()
                                     if dn_str else None)
            aluno.sexo   = request.form.get('sexo')
            aluno.igreja = request.form.get('igreja', '').strip()
            aluno.classe = request.form.get('classe', '').strip()
            db.session.commit()
            flash('Aluno atualizado com sucesso!', 'success')
            return redirect(url_for('admin.alunos'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro: {str(e)}', 'danger')
    return render_template('admin/editar_aluno.html', aluno=aluno)


@admin_bp.route('/alunos/<int:aluno_id>/desativar', methods=['POST'])
@login_required
def desativar_aluno(aluno_id):
    aluno = Aluno.query.get_or_404(aluno_id)
    aluno.ativo = False
    db.session.commit()
    flash(f'Aluno {aluno.nome} desativado.', 'warning')
    return redirect(url_for('admin.alunos'))


@admin_bp.route('/alunos/<int:aluno_id>/desempenho')
@login_required
def desempenho_aluno(aluno_id):
    aluno     = Aluno.query.get_or_404(aluno_id)
    respostas = RespostaQuiz.query.filter_by(aluno_id=aluno_id)\
                    .order_by(RespostaQuiz.data_resposta).all()
    desafios  = Desafio.query.filter_by(aluno_id=aluno_id)\
                    .order_by(Desafio.data.desc()).limit(30).all()
    return render_template('admin/desempenho_aluno.html', aluno=aluno,
                           respostas=respostas, desafios=desafios)


# ── LANÇAMENTO MANUAL DE PONTUAÇÕES ──────────────────────────────────────────

@admin_bp.route('/lancamentos')
@login_required
def lancamentos():
    """Lista todos os lançamentos manuais e exibe o formulário."""
    quizzes = (Quiz.query
               .join(Trimestre)
               .order_by(Trimestre.ano.desc(), Trimestre.numero.desc(), Quiz.titulo)
               .all())
    # Agrupa por trimestre para o select
    trimestres = (Trimestre.query
                  .order_by(Trimestre.ano.desc(), Trimestre.numero.desc())
                  .all())
    # Últimos 50 lançamentos para a tabela
    recentes = (RespostaQuiz.query
                .filter(RespostaQuiz.respostas_json == '{}')
                .order_by(RespostaQuiz.data_resposta.desc())
                .limit(50).all())
    return render_template('admin/lancamentos.html',
                           quizzes=quizzes,
                           trimestres=trimestres,
                           recentes=recentes,
                           now=datetime.utcnow())


@admin_bp.route('/lancamentos/salvar', methods=['POST'])
@login_required
def salvar_lancamento():
    aluno_id       = request.form.get('aluno_id', '').strip()
    quiz_id        = request.form.get('quiz_id', '').strip()
    acertos_str    = request.form.get('acertos', '').strip()
    total_str      = request.form.get('total_perguntas', '').strip()
    data_str       = request.form.get('data_resposta', '').strip()

    # Validações básicas
    if not aluno_id or not quiz_id or not acertos_str or not total_str:
        flash('Preencha todos os campos obrigatórios.', 'danger')
        return redirect(url_for('admin.lancamentos'))

    try:
        acertos = int(acertos_str)
        total   = int(total_str)
        if total <= 0 or acertos < 0 or acertos > total:
            raise ValueError()
    except ValueError:
        flash('Valores inválidos: acertos deve ser entre 0 e o total de questões.', 'danger')
        return redirect(url_for('admin.lancamentos'))

    aluno = Aluno.query.get(aluno_id)
    quiz  = Quiz.query.get(quiz_id)
    if not aluno or not quiz:
        flash('Aluno ou quiz não encontrado.', 'danger')
        return redirect(url_for('admin.lancamentos'))

    data_resp = datetime.utcnow()
    if data_str:
        try:
            data_resp = datetime.strptime(data_str, '%Y-%m-%d')
        except ValueError:
            pass

    pontuacao = round(acertos / total * 100, 1)

    # Verifica se já existe — se sim, atualiza; se não, cria
    existente = RespostaQuiz.query.filter_by(
        aluno_id=aluno.id, quiz_id=quiz.id
    ).first()

    if existente:
        existente.acertos        = acertos
        existente.total_perguntas = total
        existente.pontuacao      = pontuacao
        existente.data_resposta  = data_resp
        existente.respostas_json = '{}'
        flash(f'Pontuação de {aluno.nome} atualizada: {acertos}/{total} ({pontuacao}%)', 'success')
    else:
        novo = RespostaQuiz(
            aluno_id=aluno.id,
            quiz_id=quiz.id,
            respostas_json='{}',
            acertos=acertos,
            total_perguntas=total,
            pontuacao=pontuacao,
            data_resposta=data_resp,
        )
        db.session.add(novo)
        flash(f'Pontuação de {aluno.nome} lançada: {acertos}/{total} ({pontuacao}%)', 'success')

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao salvar: {str(e)}', 'danger')

    return redirect(url_for('admin.lancamentos'))


@admin_bp.route('/lancamentos/<int:resposta_id>/excluir', methods=['POST'])
@login_required
def excluir_lancamento(resposta_id):
    r = RespostaQuiz.query.get_or_404(resposta_id)
    nome = r.aluno.nome
    db.session.delete(r)
    db.session.commit()
    flash(f'Lançamento de {nome} excluído.', 'warning')
    return redirect(url_for('admin.lancamentos'))


@admin_bp.route('/api/quizzes-por-trimestre')
@login_required
def api_quizzes_por_trimestre():
    trimestre_id = request.args.get('trimestre_id', '')
    quizzes = (Quiz.query
               .filter_by(trimestre_id=trimestre_id)
               .order_by(Quiz.titulo)
               .all())
    return jsonify([{
        'id': q.id,
        'titulo': q.titulo,
        'total': len(json.loads(q.perguntas_json).get('perguntas', [])),
    } for q in quizzes])


# ── TRIMESTRES ────────────────────────────────────────────────────────────────

@admin_bp.route('/trimestres')
@login_required
def trimestres():
    lista = Trimestre.query.order_by(
        Trimestre.ano.desc(), Trimestre.numero.desc()
    ).all()
    return render_template('admin/trimestres.html', trimestres=lista)


@admin_bp.route('/trimestres/novo', methods=['GET', 'POST'])
@login_required
def novo_trimestre():
    if request.method == 'POST':
        try:
            t = Trimestre(
                ano=int(request.form['ano']),
                numero=int(request.form['numero']),
                tema=request.form['tema'].strip(),
            )
            db.session.add(t)
            db.session.commit()
            flash('Trimestre criado com sucesso!', 'success')
            return redirect(url_for('admin.trimestres'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro: {str(e)}', 'danger')
    return render_template('admin/novo_trimestre.html', ano_atual=datetime.now().year)


@admin_bp.route('/trimestres/<int:tri_id>/editar', methods=['GET', 'POST'])
@login_required
def editar_trimestre(tri_id):
    trimestre = Trimestre.query.get_or_404(tri_id)
    if request.method == 'POST':
        try:
            trimestre.ano    = int(request.form['ano'])
            trimestre.numero = int(request.form['numero'])
            trimestre.tema   = request.form['tema'].strip()
            db.session.commit()
            flash('Trimestre atualizado com sucesso!', 'success')
            return redirect(url_for('admin.trimestres'))
        except Exception as e:
            db.session.rollback()
            flash(f'Erro: {str(e)}', 'danger')
    return render_template('admin/editar_trimestre.html', trimestre=trimestre)


@admin_bp.route('/trimestres/<int:tri_id>/excluir', methods=['POST'])
@login_required
def excluir_trimestre(tri_id):
    trimestre = Trimestre.query.get_or_404(tri_id)
    try:
        # Excluir na ordem correta para respeitar FK
        quiz_ids = [q.id for q in trimestre.quizzes]
        if quiz_ids:
            RespostaQuiz.query.filter(RespostaQuiz.quiz_id.in_(quiz_ids)).delete(synchronize_session=False)
            Quiz.query.filter(Quiz.trimestre_id == tri_id).delete(synchronize_session=False)
        Licao.query.filter_by(trimestre_id=tri_id).delete(synchronize_session=False)
        db.session.delete(trimestre)
        db.session.commit()
        flash(f'Trimestre "{trimestre.nome_display}" excluído com sucesso.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Erro ao excluir: {str(e)}', 'danger')
    return redirect(url_for('admin.trimestres'))


@admin_bp.route('/trimestres/<int:tri_id>/licoes', methods=['GET', 'POST'])
@login_required
def licoes(tri_id):
    trimestre = Trimestre.query.get_or_404(tri_id)
    if request.method == 'POST':
        try:
            for i in range(1, 14):
                titulo = request.form.get(f'titulo_{i}', '').strip()
                link   = request.form.get(f'link_{i}', '').strip()
                if not titulo:
                    continue
                licao = Licao.query.filter_by(trimestre_id=tri_id, numero=i).first()
                if licao:
                    licao.titulo = titulo
                    licao.link   = link
                else:
                    db.session.add(Licao(trimestre_id=tri_id, numero=i,
                                        titulo=titulo, link=link))
            db.session.commit()
            flash('Lições salvas com sucesso!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro: {str(e)}', 'danger')
    licoes_map = {l.numero: l for l in trimestre.licoes}
    return render_template('admin/licoes.html', trimestre=trimestre,
                           licoes_map=licoes_map, range13=range(1, 14))


# ── QUIZ ─────────────────────────────────────────────────────────────────────

@admin_bp.route('/quizzes')
@login_required
def quizzes():
    lista = Quiz.query.order_by(Quiz.created_at.desc()).all()
    return render_template('admin/quizzes.html', quizzes=lista)


@admin_bp.route('/quizzes/gerar', methods=['GET', 'POST'])
@login_required
def gerar_quiz():
    trimestres_list = Trimestre.query.order_by(
        Trimestre.ano.desc(), Trimestre.numero.desc()
    ).all()

    # Dados de lições por trimestre para o JS — evita problema de escaping em atributos HTML
    trimestres_data = {
        str(t.id): {
            'tema': t.tema,
            'licoes': [
                {'numero': l.numero, 'titulo': l.titulo, 'link': l.link or ''}
                for l in t.licoes
            ]
        }
        for t in trimestres_list
    }

    cfg = {
        'provedor':         Configuracao.get('ia_provedor', 'anthropic'),
        'chave_api':        Configuracao.get('ia_chave_api', ''),
        'modelo_anthropic': Configuracao.get('ia_modelo_anthropic', 'claude-opus-4-6'),
        'modelo_openai':    Configuracao.get('ia_modelo_openai', 'gpt-4o'),
        'prompt_base':      Configuracao.get('prompt_base', ''),
    }

    if request.method == 'POST':
        try:
            tri_id_str = request.form.get('trimestre_id', '').strip()
            if not tri_id_str:
                flash('Selecione um trimestre.', 'danger')
                return redirect(url_for('admin.gerar_quiz'))

            tri_id    = int(tri_id_str)
            escopo    = request.form.get('escopo', 'trimestre')
            tipo      = request.form.get('tipo', 'normal')
            trimestre = Trimestre.query.get(tri_id)
            if not trimestre:
                flash('Trimestre não encontrado.', 'danger')
                return redirect(url_for('admin.gerar_quiz'))

            api_key  = Configuracao.get('ia_chave_api', '').strip()
            provedor = Configuracao.get('ia_provedor', 'anthropic')
            modelo   = (Configuracao.get('ia_modelo_anthropic', 'claude-opus-4-6')
                        if provedor == 'anthropic'
                        else Configuracao.get('ia_modelo_openai', 'gpt-4o'))

            if not api_key:
                flash('Chave de API não configurada. Acesse Configurações para adicioná-la.', 'danger')
                return redirect(url_for('admin.configuracoes'))

            prompt_instrucoes = request.form.get('prompt_texto', '').strip() or cfg['prompt_base']

            if escopo == 'trimestre':
                _gerar_quiz_trimestre(trimestre, tipo, prompt_instrucoes,
                                      api_key, provedor, modelo, request.form)

            elif escopo == 'licao':
                licao_num_str = request.form.get('licao_numero', '').strip()
                if not licao_num_str:
                    flash('Selecione a lição.', 'danger')
                    return redirect(url_for('admin.gerar_quiz'))
                licao_num = int(licao_num_str)
                licao = Licao.query.filter_by(
                    trimestre_id=tri_id, numero=licao_num
                ).first()
                if not licao:
                    flash(f'Lição {licao_num} não encontrada.', 'warning')
                    return redirect(url_for('admin.gerar_quiz'))
                if not licao.link:
                    flash(f'Lição {licao_num} não tem link cadastrado.', 'warning')
                    return redirect(url_for('admin.gerar_quiz'))
                _gerar_quiz_licao(trimestre, licao, prompt_instrucoes,
                                  api_key, provedor, modelo, request.form)

            elif escopo == 'todas':
                licoes_com_link = [l for l in trimestre.licoes if l.link]
                if not licoes_com_link:
                    flash('Nenhuma lição com link neste trimestre.', 'warning')
                    return redirect(url_for('admin.gerar_quiz'))
                _gerar_todas_licoes(trimestre, licoes_com_link, prompt_instrucoes,
                                    api_key, provedor, modelo,
                                    nivel=request.form.get('nivel', 'intermediario'))

            return redirect(url_for('admin.quizzes'))

        except Exception as e:
            import traceback
            current_app.logger.error('Erro gerar_quiz:\n' + traceback.format_exc())
            flash(f'Erro ao gerar quiz: {str(e)}', 'danger')

    return render_template('admin/gerar_quiz.html',
                           trimestres=trimestres_list,
                           trimestres_data=trimestres_data,
                           cfg=cfg,
                           modelos=MODELOS)


# ── helpers de geração ────────────────────────────────────────────────────────

FORMAT_JSON_QUIZ = (
    '\n\nFORMATO DE SAÍDA (JSON obrigatório — não inclua nada fora do JSON):\n'
    '{\n'
    '  "nivel": "intermediario",\n'
    '  "perguntas": [\n'
    '    {\n'
    '      "numero": 1,\n'
    '      "pergunta": "Texto da pergunta",\n'
    '      "alternativas": {"a": "...", "b": "...", "c": "...", "d": "..."},\n'
    '      "resposta_correta": "a"\n'
    '    }\n'
    '  ]\n'
    '}'
)


def _montar_prompt(instrucoes: str, num_q: int, links: list[str], nivel: str = '',
                   licao_titulo: str = '') -> str:
    inst = instrucoes.replace('{num_perguntas}', str(num_q))
    if nivel:
        inst = inst.replace(
            'Definir nível: iniciante, intermediário ou avançado.',
            f'Nível das perguntas: {nivel}. Todas as perguntas devem ser do nível {nivel}.'
        )

    links_txt = '\n'.join(links)

    # Quando é uma única lição, adiciona instrução explícita de escopo restrito
    if len(links) == 1:
        titulo_info = f' intitulada "{licao_titulo}"' if licao_titulo else ''
        restricao = (
            f'\n\n⚠️ RESTRIÇÃO OBRIGATÓRIA: Você deve ler o conteúdo do link fornecido'
            f'{titulo_info} e criar EXCLUSIVAMENTE perguntas baseadas no texto dessa lição.'
            f' NÃO use conhecimento geral bíblico nem conteúdo de outras lições.'
            f' Cada pergunta deve ser respondível apenas com base no texto dessa lição específica.'
        )
        return f"{inst}{restricao}{FORMAT_JSON_QUIZ}\n\nLINK DA LIÇÃO:\n{links_txt}"

    return f"{inst}{FORMAT_JSON_QUIZ}\n\nLINKS DAS LIÇÕES:\n{links_txt}"


def _extrair_json(texto: str) -> dict:
    """Extrai JSON da resposta da IA, suportando markdown code blocks e texto livre."""
    candidatos = []

    # 1) Bloco de código markdown: ```json ... ``` ou ``` ... ```
    for m in re.finditer(r'```(?:json)?\s*([\s\S]*?)```', texto):
        candidatos.append(m.group(1).strip())

    # 2) Qualquer { ... } no texto (greedy — pega do primeiro { ao último })
    m = re.search(r'\{[\s\S]*\}', texto)
    if m:
        candidatos.append(m.group())

    for candidato in candidatos:
        try:
            dados = json.loads(candidato)
            if isinstance(dados, dict) and dados.get('perguntas'):
                if len(dados['perguntas']) < 5:
                    raise ValueError(
                        f"A IA retornou poucas perguntas ({len(dados['perguntas'])}). "
                        "Tente novamente."
                    )
                return dados
        except json.JSONDecodeError:
            continue

    # Nenhum candidato válido — incluir trecho da resposta para diagnóstico
    trecho = texto[:300].replace('\n', ' ') if texto else '(vazia)'
    raise ValueError(
        f"JSON não encontrado na resposta da IA. "
        f"Resposta recebida: \"{trecho}...\""
    )


def _gerar_quiz_trimestre(trimestre, tipo, prompt_instrucoes,
                          api_key, provedor, modelo, form):
    num_q  = 30 if tipo == 'mega' else 20
    nivel  = form.get('nivel', 'intermediario')
    links  = [l.link for l in trimestre.licoes if l.link]
    if not links:
        raise ValueError('Nenhuma lição com link cadastrada neste trimestre.')

    prompt   = _montar_prompt(prompt_instrucoes, num_q, links, nivel)
    resposta = _chamar_ia(provedor, api_key, modelo, prompt)
    dados    = _extrair_json(resposta)

    titulo = form.get('titulo', '').strip()
    if not titulo:
        titulo = f"Quiz {trimestre.nome_display}"
        if tipo == 'mega':
            titulo += ' — Mega Quiz (30 questões)'

    quiz = Quiz(
        trimestre_id=trimestre.id,
        titulo=titulo,
        perguntas_json=json.dumps(dados, ensure_ascii=False),
        nivel=nivel,
        tipo=tipo,
        escopo='trimestre',
        token=secrets.token_urlsafe(20),
    )
    db.session.add(quiz)
    db.session.commit()
    n = len(dados['perguntas'])
    flash(f'Quiz "{titulo}" gerado com {n} perguntas! Modelo: {modelo}', 'success')


def _gerar_quiz_licao(trimestre, licao, prompt_instrucoes,
                      api_key, provedor, modelo, form):
    num_q    = int(form.get('num_perguntas_licao', 10))
    nivel    = form.get('nivel', 'intermediario')
    prompt   = _montar_prompt(prompt_instrucoes, num_q, [licao.link], nivel,
                              licao_titulo=f"Lição {licao.numero}: {licao.titulo}")
    resposta = _chamar_ia(provedor, api_key, modelo, prompt)
    dados    = _extrair_json(resposta)

    titulo = form.get('titulo', '').strip()
    if not titulo:
        titulo = f"Quiz — Lição {licao.numero}: {licao.titulo}"

    quiz = Quiz(
        trimestre_id=trimestre.id,
        titulo=titulo,
        perguntas_json=json.dumps(dados, ensure_ascii=False),
        nivel=nivel,
        tipo='normal',
        escopo='licao',
        token=secrets.token_urlsafe(20),
        licao_id=licao.id,
    )
    db.session.add(quiz)
    db.session.commit()
    n = len(dados['perguntas'])
    flash(f'Quiz da lição {licao.numero} gerado com {n} perguntas! Nível: {nivel}', 'success')


def _gerar_todas_licoes(trimestre, licoes, prompt_instrucoes,
                        api_key, provedor, modelo, nivel='intermediario'):
    """Gera um quiz individual para cada lição em chamadas separadas."""
    criados = 0
    erros = []
    num_q = 10

    for licao in licoes:
        try:
            prompt = _montar_prompt(prompt_instrucoes, num_q, [licao.link], nivel,
                                    licao_titulo=f"Lição {licao.numero}: {licao.titulo}")
            resposta = _chamar_ia(provedor, api_key, modelo, prompt)
            dados = _extrair_json(resposta)

            titulo = f"Lição {licao.numero}: {licao.titulo}"
            quiz = Quiz(
                trimestre_id=trimestre.id,
                titulo=titulo,
                perguntas_json=json.dumps(dados, ensure_ascii=False),
                nivel=nivel,
                tipo='normal',
                escopo='licao',
                token=secrets.token_urlsafe(20),
                licao_id=licao.id,
            )
            db.session.add(quiz)
            db.session.commit()
            criados += 1
        except Exception as e:
            erros.append(f'Lição {licao.numero}: {str(e)[:60]}')

    if criados:
        flash(f'{criados} quiz(zes) gerados com sucesso (10 questões cada)!', 'success')
    if erros:
        flash(f'Erros em {len(erros)} lição(ões): ' + ' | '.join(erros), 'warning')


def _chamar_ia(provedor: str, api_key: str, modelo: str, prompt: str) -> str:
    """Chama a IA selecionada e retorna o texto da resposta."""
    if provedor == 'anthropic':
        if not _ANTHROPIC_OK:
            raise RuntimeError(
                "Pacote 'anthropic' não encontrado. "
                "Feche o servidor, execute 'pip install anthropic' e reinicie."
            )
        client = _anthropic_mod.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model=modelo,
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}]
        )
        return msg.content[0].text

    elif provedor == 'openai':
        if not _OPENAI_OK:
            raise RuntimeError(
                "Pacote 'openai' não encontrado. "
                "Feche o servidor, execute 'pip install openai' e reinicie."
            )
        client = _openai_mod.OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model=modelo,
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}]
        )
        return resp.choices[0].message.content

    else:
        raise ValueError(f"Provedor desconhecido: {provedor}")


@admin_bp.route('/quizzes/<int:quiz_id>/visualizar')
@login_required
def visualizar_quiz(quiz_id):
    quiz     = Quiz.query.get_or_404(quiz_id)
    dados    = json.loads(quiz.perguntas_json)
    respostas = RespostaQuiz.query.filter_by(quiz_id=quiz_id).all()
    return render_template('admin/visualizar_quiz.html', quiz=quiz,
                           dados=dados, respostas=respostas)


@admin_bp.route('/quizzes/<int:quiz_id>/toggle', methods=['POST'])
@login_required
def toggle_quiz(quiz_id):
    quiz = Quiz.query.get_or_404(quiz_id)
    quiz.ativo = not quiz.ativo
    db.session.commit()
    flash(f'Quiz {"ativado" if quiz.ativo else "desativado"} com sucesso.', 'success')
    return redirect(url_for('admin.quizzes'))


# ── CONFIGURAÇÕES ─────────────────────────────────────────────────────────────

@admin_bp.route('/configuracoes', methods=['GET', 'POST'])
@login_required
def configuracoes():
    if request.method == 'POST':
        try:
            Configuracao.set('ia_provedor',         request.form.get('ia_provedor', 'anthropic'))
            Configuracao.set('ia_chave_api',         request.form.get('ia_chave_api', '').strip())
            Configuracao.set('ia_modelo_anthropic',  request.form.get('ia_modelo_anthropic', 'claude-opus-4-6'))
            Configuracao.set('ia_modelo_openai',     request.form.get('ia_modelo_openai', 'gpt-4o'))
            Configuracao.set('prompt_base',          request.form.get('prompt_base', ''))
            db.session.commit()
            flash('Configurações salvas com sucesso!', 'success')
        except Exception as e:
            db.session.rollback()
            flash(f'Erro ao salvar: {str(e)}', 'danger')
        return redirect(url_for('admin.configuracoes'))

    cfg = {
        'ia_provedor':         Configuracao.get('ia_provedor', 'anthropic'),
        'ia_chave_api':        Configuracao.get('ia_chave_api', ''),
        'ia_modelo_anthropic': Configuracao.get('ia_modelo_anthropic', 'claude-opus-4-6'),
        'ia_modelo_openai':    Configuracao.get('ia_modelo_openai', 'gpt-4o'),
        'prompt_base':         Configuracao.get('prompt_base', ''),
    }
    return render_template('admin/configuracoes.html', cfg=cfg, modelos=MODELOS)


# ── RELATÓRIOS ────────────────────────────────────────────────────────────────

@admin_bp.route('/relatorios')
@login_required
def relatorios():
    from sqlalchemy import func
    ranking = db.session.query(
        Aluno,
        func.avg(RespostaQuiz.pontuacao).label('media'),
        func.count(RespostaQuiz.id).label('total')
    ).join(RespostaQuiz, Aluno.id == RespostaQuiz.aluno_id)\
     .filter(Aluno.ativo == True)\
     .group_by(Aluno.id)\
     .order_by(func.avg(RespostaQuiz.pontuacao).desc())\
     .limit(10).all()

    return render_template('admin/relatorios.html', ranking=ranking)
