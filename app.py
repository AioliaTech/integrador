from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
import psycopg2
import psycopg2.extras
import requests
import os
import json
from datetime import datetime
import uuid
from functools import wraps
import boto3
from botocore.exceptions import ClientError
import time
import threading

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-here')

# Configurações do banco de dados
DATABASE_CONFIG = {
    'host': os.environ.get('DB_HOST', 'localhost'),
    'database': os.environ.get('DB_NAME', 'integrador'),
    'user': os.environ.get('DB_USER', 'postgres'),
    'password': os.environ.get('DB_PASSWORD', 'password'),
    'port': os.environ.get('DB_PORT', '5432')
}

# Configurações do Bucket Blaze
BLAZE_CONFIG = {
    'endpoint_url': os.environ.get('BLAZE_ENDPOINT_URL'),
    'aws_access_key_id': os.environ.get('BLAZE_ACCESS_KEY'),
    'aws_secret_access_key': os.environ.get('BLAZE_SECRET_KEY'),
    'bucket_name': os.environ.get('BLAZE_BUCKET_NAME')
}

# Configurações de autenticação
AUTH_CONFIG = {
    'username': os.environ.get('AUTH_USERNAME', 'admin'),
    'password': os.environ.get('AUTH_PASSWORD', 'admin123')
}

# Nome da tabela do cliente (configurável via env)
CLIENT_TABLE = os.environ.get('CLIENT_TABLE', 'integrador_cliente01')

# Variável global para controlar o status da importação
importacao_status = {
    'em_andamento': False,
    'progresso': 0,
    'total': 0,
    'atual': '',
    'erro': None
}

# Configuração do S3 (Bucket Blaze)
def get_s3_client():
    return boto3.client(
        's3',
        endpoint_url=BLAZE_CONFIG['endpoint_url'],
        aws_access_key_id=BLAZE_CONFIG['aws_access_key_id'],
        aws_secret_access_key=BLAZE_CONFIG['aws_secret_access_key']
    )

# Decorador para autenticação
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Conexão com banco de dados
def get_db_connection():
    return psycopg2.connect(**DATABASE_CONFIG)

# Inicialização do banco de dados
def init_db():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Tabela principal da FIPE
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS integrador (
                id SERIAL PRIMARY KEY,
                tipo VARCHAR(10) NOT NULL CHECK (tipo IN ('carros', 'motos')),
                marca_id INTEGER,
                marca_nome VARCHAR(100),
                modelo_id INTEGER,
                modelo_nome VARCHAR(200),
                versao_id VARCHAR(50),
                versao_nome VARCHAR(300),
                ano_modelo INTEGER,
                combustivel VARCHAR(50),
                motor VARCHAR(100),
                portas INTEGER,
                categoria VARCHAR(100),
                cilindrada VARCHAR(50),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(tipo, marca_id, modelo_id, versao_id, ano_modelo)
            )
        ''')
        
        # Tabela dinâmica do cliente
        cursor.execute(f'''
            CREATE TABLE IF NOT EXISTS {CLIENT_TABLE} (
                id SERIAL PRIMARY KEY,
                tipo VARCHAR(10) NOT NULL CHECK (tipo IN ('carros', 'motos')),
                marca_id INTEGER,
                marca_nome VARCHAR(100),
                modelo_id INTEGER,
                modelo_nome VARCHAR(200),
                versao_id VARCHAR(50),
                versao_nome VARCHAR(300),
                ano_modelo INTEGER,
                ano_fabricacao INTEGER,
                km INTEGER,
                cor VARCHAR(50),
                combustivel VARCHAR(50),
                cambio VARCHAR(50),
                motor VARCHAR(100),
                portas INTEGER,
                categoria VARCHAR(100),
                cilindrada VARCHAR(50),
                preco DECIMAL(12,2),
                fotos TEXT[],
                ativo BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        conn.commit()
        cursor.close()
        conn.close()
        print("Banco de dados inicializado com sucesso!")
        
    except Exception as e:
        print(f"Erro ao inicializar banco: {e}")

# API FIPE
class FipeAPI:
    BASE_URL = "https://parallelum.com.br/fipe/api/v1"
    
    @staticmethod
    def get_marcas(tipo):
        endpoint = f"{FipeAPI.BASE_URL}/{tipo}/marcas"
        try:
            response = requests.get(endpoint, timeout=10)
            return response.json() if response.status_code == 200 else []
        except:
            return []
    
    @staticmethod
    def get_modelos(tipo, marca_id):
        endpoint = f"{FipeAPI.BASE_URL}/{tipo}/marcas/{marca_id}/modelos"
        try:
            response = requests.get(endpoint, timeout=10)
            return response.json().get('modelos', []) if response.status_code == 200 else []
        except:
            return []
    
    @staticmethod
    def get_anos(tipo, marca_id, modelo_id):
        endpoint = f"{FipeAPI.BASE_URL}/{tipo}/marcas/{marca_id}/modelos/{modelo_id}/anos"
        try:
            response = requests.get(endpoint, timeout=10)
            return response.json() if response.status_code == 200 else []
        except:
            return []
    
    @staticmethod
    def get_detalhes(tipo, marca_id, modelo_id, ano_codigo):
        endpoint = f"{FipeAPI.BASE_URL}/{tipo}/marcas/{marca_id}/modelos/{modelo_id}/anos/{ano_codigo}"
        try:
            response = requests.get(endpoint, timeout=10)
            return response.json() if response.status_code == 200 else {}
        except:
            return {}

# Upload de imagens
def upload_to_blaze(file, filename):
    try:
        s3_client = get_s3_client()
        s3_client.upload_fileobj(
            file,
            BLAZE_CONFIG['bucket_name'],
            filename,
            ExtraArgs={'ACL': 'public-read'}
        )
        return f"{BLAZE_CONFIG['endpoint_url']}/{BLAZE_CONFIG['bucket_name']}/{filename}"
    except Exception as e:
        print(f"Erro no upload: {e}")
        return None

# Função que faz a importação completa da FIPE
def importar_dados_fipe(tipo):
    global importacao_status
    
    try:
        importacao_status.update({
            'em_andamento': True,
            'progresso': 0,
            'total': 0,
            'atual': f'Iniciando importação de {tipo}...',
            'erro': None
        })
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # 1. Buscar marcas
        importacao_status['atual'] = f'Buscando marcas de {tipo}...'
        marcas = FipeAPI.get_marcas(tipo)
        
        if not marcas:
            raise Exception(f'Nenhuma marca encontrada para {tipo}')
        
        importacao_status['total'] = len(marcas)
        total_inseridos = 0
        
        for i, marca in enumerate(marcas):
            if not importacao_status['em_andamento']:
                break
                
            marca_id = marca['codigo']
            marca_nome = marca['nome']
            
            importacao_status.update({
                'progresso': i + 1,
                'atual': f'Processando marca: {marca_nome}'
            })
            
            # 2. Buscar modelos da marca
            modelos = FipeAPI.get_modelos(tipo, marca_id)
            
            for modelo in modelos:
                if not importacao_status['em_andamento']:
                    break
                    
                modelo_id = modelo['codigo']
                modelo_nome = modelo['nome']
                
                importacao_status['atual'] = f'Processando modelo: {marca_nome} {modelo_nome}'
                
                # 3. Buscar anos do modelo
                anos = FipeAPI.get_anos(tipo, marca_id, modelo_id)
                
                for ano in anos[:3]:  # Limitar a 3 anos por modelo
                    if not importacao_status['em_andamento']:
                        break
                        
                    ano_codigo = ano['codigo']
                    
                    # 4. Buscar detalhes
                    detalhes = FipeAPI.get_detalhes(tipo, marca_id, modelo_id, ano_codigo)
                    
                    if detalhes:
                        try:
                            ano_modelo = detalhes.get('AnoModelo', 2020)
                            combustivel = detalhes.get('Combustivel', 'Flex')
                            motor = detalhes.get('SiglaCombustivel', '1.0')
                            versao_nome = detalhes.get('Modelo', modelo_nome)
                            categoria = detalhes.get('TipoVeiculo', 'Sedan')
                            
                            # Extrair portas do nome do modelo
                            portas = None
                            if 'Portas' in versao_nome:
                                import re
                                match = re.search(r'(\d+)\s*Portas?', versao_nome, re.IGNORECASE)
                                if match:
                                    portas = int(match.group(1))
                            
                            # Para motos, extrair cilindrada
                            cilindrada = None
                            if tipo == 'motos':
                                cilindrada = motor
                            
                            # Inserir no banco
                            cursor.execute('''
                                INSERT INTO integrador (
                                    tipo, marca_id, marca_nome, modelo_id, modelo_nome,
                                    versao_id, versao_nome, ano_modelo, combustivel, 
                                    motor, portas, categoria, cilindrada
                                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                ON CONFLICT (tipo, marca_id, modelo_id, versao_id, ano_modelo) 
                                DO NOTHING
                            ''', (
                                tipo, marca_id, marca_nome, modelo_id, modelo_nome,
                                ano_codigo, versao_nome, ano_modelo, combustivel,
                                motor, portas, categoria, cilindrada
                            ))
                            
                            if cursor.rowcount > 0:
                                total_inseridos += 1
                                
                            conn.commit()
                            time.sleep(0.1)
                            
                        except Exception as e:
                            print(f"Erro ao inserir {marca_nome} {modelo_nome}: {e}")
                            continue
        
        cursor.close()
        conn.close()
        
        importacao_status.update({
            'em_andamento': False,
            'atual': f'Importação concluída! {total_inseridos} registros inseridos.',
            'progresso': importacao_status['total']
        })
        
    except Exception as e:
        importacao_status.update({
            'em_andamento': False,
            'erro': str(e),
            'atual': f'Erro na importação: {str(e)}'
        })

# Rotas principais
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        if username == AUTH_CONFIG['username'] and password == AUTH_CONFIG['password']:
            session['user_id'] = username
            return redirect(url_for('dashboard'))
        else:
            flash('Credenciais inválidas', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        cursor.execute(f'SELECT * FROM {CLIENT_TABLE} ORDER BY created_at DESC')
        veiculos = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return render_template('dashboard.html', veiculos=veiculos, client_table=CLIENT_TABLE)
    except Exception as e:
        flash(f'Erro ao carregar dashboard: {e}', 'error')
        return render_template('dashboard.html', veiculos=[], client_table=CLIENT_TABLE)

@app.route('/veiculo/novo')
@login_required
def novo_veiculo():
    return render_template('veiculo_form.html', veiculo=None)

@app.route('/veiculo/editar/<int:veiculo_id>')
@login_required
def editar_veiculo(veiculo_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        cursor.execute(f'SELECT * FROM {CLIENT_TABLE} WHERE id = %s', (veiculo_id,))
        veiculo = cursor.fetchone()
        
        cursor.close()
        conn.close()
        
        if not veiculo:
            flash('Veículo não encontrado', 'error')
            return redirect(url_for('dashboard'))
        
        return render_template('veiculo_form.html', veiculo=veiculo)
    except Exception as e:
        flash(f'Erro ao carregar veículo: {e}', 'error')
        return redirect(url_for('dashboard'))

@app.route('/veiculo/salvar', methods=['POST'])
@login_required
def salvar_veiculo():
    try:
        data = request.form.to_dict()
        veiculo_id = data.get('id')
        
        # Upload de fotos
        fotos = []
        if 'fotos' in request.files:
            files = request.files.getlist('fotos')
            for file in files:
                if file.filename:
                    filename = f"{uuid.uuid4()}_{secure_filename(file.filename)}"
                    url = upload_to_blaze(file, filename)
                    if url:
                        fotos.append(url)
        
        # Manter fotos existentes se estiver editando
        if veiculo_id and 'fotos_existentes' in data:
            try:
                fotos_existentes = json.loads(data['fotos_existentes'])
                fotos.extend(fotos_existentes)
            except:
                pass
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        if veiculo_id:  # Editar
            cursor.execute(f'''
                UPDATE {CLIENT_TABLE} SET
                tipo = %s, marca_id = %s, marca_nome = %s, modelo_id = %s, modelo_nome = %s,
                versao_id = %s, versao_nome = %s, ano_modelo = %s, ano_fabricacao = %s,
                km = %s, cor = %s, combustivel = %s, cambio = %s, motor = %s, portas = %s,
                categoria = %s, cilindrada = %s, preco = %s, fotos = %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            ''', (
                data['tipo'], data['marca_id'], data['marca_nome'], data['modelo_id'], data['modelo_nome'],
                data['versao_id'], data['versao_nome'], data['ano_modelo'], data['ano_fabricacao'],
                data['km'], data['cor'], data['combustivel'], data['cambio'], data['motor'], data['portas'],
                data['categoria'], data.get('cilindrada'), data['preco'], fotos, veiculo_id
            ))
        else:  # Criar
            cursor.execute(f'''
                INSERT INTO {CLIENT_TABLE} (
                    tipo, marca_id, marca_nome, modelo_id, modelo_nome, versao_id, versao_nome,
                    ano_modelo, ano_fabricacao, km, cor, combustivel, cambio, motor, portas,
                    categoria, cilindrada, preco, fotos
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ''', (
                data['tipo'], data['marca_id'], data['marca_nome'], data['modelo_id'], data['modelo_nome'],
                data['versao_id'], data['versao_nome'], data['ano_modelo'], data['ano_fabricacao'],
                data['km'], data['cor'], data['combustivel'], data['cambio'], data['motor'], data['portas'],
                data['categoria'], data.get('cilindrada'), data['preco'], fotos
            ))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('Veículo salvo com sucesso!', 'success')
        return redirect(url_for('dashboard'))
        
    except Exception as e:
        flash(f'Erro ao salvar veículo: {e}', 'error')
        return redirect(url_for('dashboard'))

@app.route('/veiculo/excluir/<int:veiculo_id>', methods=['POST'])
@login_required
def excluir_veiculo(veiculo_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute(f'DELETE FROM {CLIENT_TABLE} WHERE id = %s', (veiculo_id,))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        flash('Veículo excluído com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao excluir veículo: {e}', 'error')
    
    return redirect(url_for('dashboard'))

@app.route('/veiculo/toggle/<int:veiculo_id>', methods=['POST'])
@login_required
def toggle_veiculo(veiculo_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute(f'UPDATE {CLIENT_TABLE} SET ativo = NOT ativo WHERE id = %s', (veiculo_id,))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

# ADMIN ROUTES
@app.route('/admin')
@login_required
def admin_importacao():
    return render_template('admin_importacao.html')

@app.route('/admin/iniciar-importacao/<tipo>')
@login_required
def iniciar_importacao_fipe(tipo):
    global importacao_status
    
    if importacao_status['em_andamento']:
        return jsonify({
            'success': False,
            'message': 'Já existe uma importação em andamento'
        })
    
    thread = threading.Thread(target=importar_dados_fipe, args=(tipo,))
    thread.daemon = True
    thread.start()
    
    return jsonify({
        'success': True,
        'message': f'Importação de {tipo} iniciada em background'
    })

@app.route('/admin/status-importacao')
@login_required
def status_importacao():
    return jsonify(importacao_status)

@app.route('/admin/parar-importacao')
@login_required
def parar_importacao():
    global importacao_status
    importacao_status['em_andamento'] = False
    return jsonify({'success': True, 'message': 'Importação interrompida'})

@app.route('/admin/importacao-rapida')
@login_required
def importacao_rapida():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        marcas_populares = {
            'carros': [
                {'codigo': 59, 'nome': 'Volkswagen'},
                {'codigo': 22, 'nome': 'Chevrolet'}, 
                {'codigo': 26, 'nome': 'Ford'},
                {'codigo': 25, 'nome': 'Fiat'},
                {'codigo': 21, 'nome': 'Hyundai'},
                {'codigo': 320, 'nome': 'Toyota'}
            ],
            'motos': [
                {'codigo': 26, 'nome': 'Honda'},
                {'codigo': 52, 'nome': 'Yamaha'},
                {'codigo': 46, 'nome': 'Suzuki'},
                {'codigo': 28, 'nome': 'Kawasaki'}
            ]
        }
        
        total_inseridos = 0
        
        for tipo, marcas in marcas_populares.items():
            for marca in marcas:
                marca_id = marca['codigo']
                marca_nome = marca['nome']
                
                modelos = FipeAPI.get_modelos(tipo, marca_id)
                
                for modelo in modelos[:5]:
                    modelo_id = modelo['codigo']
                    modelo_nome = modelo['nome']
                    
                    anos = FipeAPI.get_anos(tipo, marca_id, modelo_id)
                    
                    for ano in anos[:2]:
                        ano_codigo = ano['codigo']
                        
                        detalhes = FipeAPI.get_detalhes(tipo, marca_id, modelo_id, ano_codigo)
                        
                        if detalhes:
                            try:
                                cursor.execute('''
                                    INSERT INTO integrador (
                                        tipo, marca_id, marca_nome, modelo_id, modelo_nome,
                                        versao_id, versao_nome, ano_modelo, combustivel, 
                                        motor, categoria
                                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                    ON CONFLICT (tipo, marca_id, modelo_id, versao_id, ano_modelo) 
                                    DO NOTHING
                                ''', (
                                    tipo, marca_id, marca_nome, modelo_id, modelo_nome,
                                    ano_codigo, detalhes.get('Modelo', modelo_nome), 
                                    detalhes.get('AnoModelo', 2020),
                                    detalhes.get('Combustivel', 'Flex'),
                                    detalhes.get('SiglaCombustivel', '1.0'),
                                    detalhes.get('TipoVeiculo', 'Sedan')
                                ))
                                
                                if cursor.rowcount > 0:
                                    total_inseridos += 1
                                    
                                conn.commit()
                                time.sleep(0.05)
                                
                            except Exception as e:
                                continue
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'Importação rápida concluída! {total_inseridos} registros inseridos.',
            'total_inseridos': total_inseridos
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/admin/verificar-dados')
@login_required
def verificar_dados():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        cursor.execute('SELECT COUNT(*) as total FROM integrador')
        total = cursor.fetchone()['total']
        
        cursor.execute('''
            SELECT tipo, COUNT(*) as quantidade 
            FROM integrador 
            GROUP BY tipo
        ''')
        por_tipo = cursor.fetchall()
        
        cursor.execute('''
            SELECT tipo, COUNT(DISTINCT marca_id) as marcas 
            FROM integrador 
            WHERE marca_id IS NOT NULL
            GROUP BY tipo
        ''')
        marcas_por_tipo = cursor.fetchall()
        
        cursor.execute('''
            SELECT marca_nome, modelo_nome, ano_modelo, tipo 
            FROM integrador 
            ORDER BY created_at DESC 
            LIMIT 5
        ''')
        amostra = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'total_registros': total,
            'por_tipo': [dict(row) for row in por_tipo],
            'marcas_por_tipo': [dict(row) for row in marcas_por_tipo],
            'amostra': [dict(row) for row in amostra]
        })
        
    except Exception as e:
        return jsonify({
            'total_registros': 0,
            'por_tipo': [],
            'marcas_por_tipo': [],
            'amostra': [],
            'error': str(e)
        })

# APIs FIPE - ENDPOINTS CORRIGIDOS - Buscar APENAS da tabela integrador
@app.route('/api/marcas/<tipo>')
@login_required
def api_marcas(tipo):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        cursor.execute('''
            SELECT DISTINCT marca_id as codigo, marca_nome as nome 
            FROM integrador 
            WHERE tipo = %s 
            AND marca_id IS NOT NULL 
            AND marca_nome IS NOT NULL 
            ORDER BY marca_nome
        ''', (tipo,))
        
        marcas = [{'codigo': m['codigo'], 'nome': m['nome']} for m in cursor.fetchall()]
        
        cursor.close()
        conn.close()
        
        return jsonify(marcas)
        
    except Exception as e:
        print(f"Erro ao buscar marcas: {e}")
        return jsonify([])

@app.route('/api/modelos/<tipo>/<marca_id>')
@login_required
def api_modelos(tipo, marca_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        cursor.execute('''
            SELECT DISTINCT modelo_id as codigo, modelo_nome as nome 
            FROM integrador 
            WHERE tipo = %s AND marca_id = %s 
            AND modelo_id IS NOT NULL 
            AND modelo_nome IS NOT NULL 
            ORDER BY modelo_nome
        ''', (tipo, int(marca_id)))
        
        modelos = [{'codigo': m['codigo'], 'nome': m['nome']} for m in cursor.fetchall()]
        
        cursor.close()
        conn.close()
        
        return jsonify(modelos)
        
    except Exception as e:
        print(f"Erro ao buscar modelos: {e}")
        return jsonify([])

@app.route('/api/anos/<tipo>/<marca_id>/<modelo_id>')
@login_required
def api_anos(tipo, marca_id, modelo_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        cursor.execute('''
            SELECT DISTINCT ano_modelo, versao_nome, versao_id
            FROM integrador 
            WHERE tipo = %s AND marca_id = %s AND modelo_id = %s 
            AND ano_modelo IS NOT NULL
            ORDER BY ano_modelo DESC, versao_nome
        ''', (tipo, int(marca_id), int(modelo_id)))
        
        anos = []
        for row in cursor.fetchall():
            codigo = f"{row['ano_modelo']}-{row['versao_id']}" if row['versao_id'] else str(row['ano_modelo'])
            nome = f"{row['ano_modelo']} - {row['versao_nome']}"
            anos.append({'codigo': codigo, 'nome': nome})
        
        cursor.close()
        conn.close()
        
        return jsonify(anos)
        
    except Exception as e:
        print(f"Erro ao buscar anos: {e}")
        return jsonify([])

@app.route('/api/detalhes/<tipo>/<marca_id>/<modelo_id>/<ano_codigo>')
@login_required
def api_detalhes(tipo, marca_id, modelo_id, ano_codigo):
    try:
        if '-' in ano_codigo:
            ano_modelo = int(ano_codigo.split('-')[0])
        else:
            ano_modelo = int(ano_codigo)
        
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        cursor.execute('''
            SELECT * FROM integrador 
            WHERE tipo = %s AND marca_id = %s AND modelo_id = %s AND ano_modelo = %s
            ORDER BY created_at DESC LIMIT 1
        ''', (tipo, int(marca_id), int(modelo_id), ano_modelo))
        
        row = cursor.fetchone()
        
        if row:
            detalhes = {
                'AnoModelo': row['ano_modelo'],
                'Combustivel': row['combustivel'] or 'Flex',
                'SiglaCombustivel': row['motor'] or '1.0',
                'Modelo': row['versao_nome'] or row['modelo_nome'],
                'TipoVeiculo': row['categoria'] or 'Sedan'
            }
        else:
            detalhes = {
                'AnoModelo': ano_modelo,
                'Combustivel': 'Flex',
                'SiglaCombustivel': '1.0',
                'Modelo': 'Veiculo',
                'TipoVeiculo': 'Sedan'
            }
        
        cursor.close()
        conn.close()
        
        return jsonify(detalhes)
        
    except Exception as e:
        print(f"Erro ao buscar detalhes: {e}")
        return jsonify({
            'AnoModelo': 2020,
            'Combustivel': 'Flex',
            'SiglaCombustivel': '1.0',
            'Modelo': 'Veiculo',
            'TipoVeiculo': 'Sedan'
        })

@app.route('/xml')
def xml_endpoint():
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        cursor.execute(f'SELECT * FROM {CLIENT_TABLE} WHERE ativo = TRUE ORDER BY created_at DESC')
        veiculos = cursor.fetchall()
        
        cursor.close()
        conn.close()
        
        veiculos_json = []
        for veiculo in veiculos:
            veiculo_dict = dict(veiculo)
            if veiculo_dict.get('created_at'):
                veiculo_dict['created_at'] = veiculo_dict['created_at'].isoformat()
            if veiculo_dict.get('updated_at'):
                veiculo_dict['updated_at'] = veiculo_dict['updated_at'].isoformat()
            veiculos_json.append(veiculo_dict)
        
        return jsonify({
            'veiculos': veiculos_json,
            'total': len(veiculos_json),
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            'veiculos': [],
            'total': 0,
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        })

@app.route('/json')
def json_endpoint():
    return xml_endpoint()

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
