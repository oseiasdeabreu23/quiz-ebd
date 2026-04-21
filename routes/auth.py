from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from models import db, AdminUser, Aluno, LogAcesso

auth_bp = Blueprint('auth', __name__)


def registrar_log(acao, detalhes='', aluno_id=None):
    log = LogAcesso(
        aluno_id=aluno_id,
        acao=acao,
        detalhes=detalhes,
        ip=request.remote_addr
    )
    db.session.add(log)
    db.session.commit()


@auth_bp.route('/')
def index():
    return redirect(url_for('auth.login_aluno'))


@auth_bp.route('/aluno/login', methods=['GET', 'POST'])
def login_aluno():
    if request.method == 'POST':
        matricula = request.form.get('matricula', '').strip().upper()
        aluno = Aluno.query.filter_by(matricula=matricula, ativo=True).first()
        if aluno:
            session['aluno_id'] = aluno.id
            session['aluno_nome'] = aluno.nome
            registrar_log('LOGIN_ALUNO', f'Aluno: {aluno.nome}', aluno.id)
            return redirect(url_for('aluno.painel'))
        flash('Matrícula não encontrada. Verifique o número informado.', 'danger')
    return render_template('aluno/login.html')


@auth_bp.route('/aluno/logout')
def logout_aluno():
    session.clear()
    return redirect(url_for('auth.login_aluno'))


@auth_bp.route('/admin/login', methods=['GET', 'POST'])
def login_admin():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        admin = AdminUser.query.filter_by(username=username).first()
        if admin and admin.check_password(password):
            login_user(admin)
            registrar_log('LOGIN_ADMIN', f'Admin: {username}')
            return redirect(url_for('admin.dashboard'))
        flash('Usuário ou senha inválidos.', 'danger')
    return render_template('admin/login.html')


@auth_bp.route('/admin/logout')
@login_required
def logout_admin():
    logout_user()
    return redirect(url_for('auth.login_admin'))
