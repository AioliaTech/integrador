# app.py
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
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Tabela principal da FIPE
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS integrador (
            id SERIAL PRIMARY KEY,
            tipo VARCHAR(10) NOT NULL,
            marca_id INTEGER,
            marca_nome VARCHAR(100),
            modelo_id INTEGER,
            modelo_nome VARCHAR(200),
            versao_id INTEGER,
            versao_nome VARCHAR(300),
            ano_modelo INTEGER,
            combustivel VARCHAR(50),
            motor VARCHAR(100),
            portas INTEGER,
            categoria VARCHAR(100),
            cilindrada VARCHAR(50),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Tabela dinâmica do cliente
    cursor.execute(f'''
        CREATE TABLE IF NOT EXISTS {CLIENT_TABLE} (
            id SERIAL PRIMARY KEY,
            tipo VARCHAR(10) NOT NULL,
            marca_id INTEGER,
            marca_nome VARCHAR(100),
            modelo_id INTEGER,
            modelo_nome VARCHAR(200),
            versao_id INTEGER,
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

# API FIPE
class FipeAPI:
    BASE_URL = "https://parallelum.com.br/fipe/api/v1"
    
    @staticmethod
    def get_marcas(tipo):
        """Busca marcas por tipo (carros/motos)"""
        endpoint = f"{FipeAPI.BASE_URL}/{tipo}/marcas"
        try:
            response = requests.get(endpoint, timeout=10)
            return response.json() if response.status_code == 200 else []
        except:
            return []
    
    @staticmethod
    def get_modelos(tipo, marca_id):
        """Busca modelos por marca"""
        endpoint = f"{FipeAPI.BASE_URL}/{tipo}/marcas/{marca_id}/modelos"
        try:
            response = requests.get(endpoint, timeout=10)
            return response.json().get('modelos', []) if response.status_code == 200 else []
        except:
            return []
    
    @staticmethod
    def get_anos(tipo, marca_id, modelo_id):
        """Busca anos por modelo"""
        endpoint = f"{FipeAPI.BASE_URL}/{tipo}/marcas/{marca_id}/modelos/{modelo_id}/anos"
        try:
            response = requests.get(endpoint, timeout=10)
            return response.json() if response.status_code == 200 else []
        except:
            return []
    
    @staticmethod
    def get_detalhes(tipo, marca_id, modelo_id, ano_codigo):
        """Busca detalhes do veículo"""
        endpoint = f"{FipeAPI.BASE_URL}/{tipo}/marcas/{marca_id}/modelos/{modelo_id}/anos/{ano_codigo}"
        try:
            response = requests.get(endpoint, timeout=10)
            return response.json() if response.status_code == 200 else {}
        except:
            return {}

# Upload de imagens
def upload_to_blaze(file, filename):
    """Upload de arquivo para o Bucket Blaze"""
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

# Rotas
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
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    cursor.execute(f'SELECT * FROM {CLIENT_TABLE} ORDER BY created_at DESC')
    veiculos = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    return render_template('dashboard.html', veiculos=veiculos, client_table=CLIENT_TABLE)

@app.route('/veiculo/novo')
@login_required
def novo_veiculo():
    return render_template('veiculo_form.html', veiculo=None)

@app.route('/veiculo/editar/<int:veiculo_id>')
@login_required
def editar_veiculo(veiculo_id):
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

@app.route('/veiculo/salvar', methods=['POST'])
@login_required
def salvar_veiculo():
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
        fotos_existentes = json.loads(data['fotos_existentes'])
        fotos.extend(fotos_existentes)
    
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

@app.route('/veiculo/excluir/<int:veiculo_id>', methods=['POST'])
@login_required
def excluir_veiculo(veiculo_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(f'DELETE FROM {CLIENT_TABLE} WHERE id = %s', (veiculo_id,))
    
    conn.commit()
    cursor.close()
    conn.close()
    
    flash('Veículo excluído com sucesso!', 'success')
    return redirect(url_for('dashboard'))

@app.route('/veiculo/toggle/<int:veiculo_id>', methods=['POST'])
@login_required
def toggle_veiculo(veiculo_id):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(f'UPDATE {CLIENT_TABLE} SET ativo = NOT ativo WHERE id = %s', (veiculo_id,))
    
    conn.commit()
    cursor.close()
    conn.close()
    
    return jsonify({'success': True})

# APIs FIPE - Modificadas para usar cache local
@app.route('/api/marcas/<tipo>')
@login_required
def api_marcas(tipo):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    # Primeiro tenta buscar do cache local
    cursor.execute('''
        SELECT DISTINCT marca_id as codigo, marca_nome as nome 
        FROM integrador 
        WHERE tipo = %s 
        ORDER BY marca_nome
    ''', (tipo,))
    marcas_cache = cursor.fetchall()
    
    if marcas_cache:
        # Se tem no cache, usa os dados locais
        marcas = [{'codigo': m['codigo'], 'nome': m['nome']} for m in marcas_cache]
    else:
        # Se não tem no cache, busca da API e salva
        marcas = FipeAPI.get_marcas(tipo)
        
        # Salvar no cache (opcional - pode ser feito em background)
        for marca in marcas:
            try:
                cursor.execute('''
                    INSERT INTO integrador (tipo, marca_id, marca_nome, modelo_id, modelo_nome, versao_id, versao_nome, ano_modelo)
                    VALUES (%s, %s, %s, 0, 'PLACEHOLDER', 0, 'PLACEHOLDER', 0)
                    ON CONFLICT (tipo, marca_id, modelo_id, versao_id, ano_modelo) DO NOTHING
                ''', (tipo, marca['codigo'], marca['nome']))
            except:
                pass  # Ignora erros de duplicação
        conn.commit()
    
    cursor.close()
    conn.close()
    return jsonify(marcas)

@app.route('/api/modelos/<tipo>/<marca_id>')
@login_required
def api_modelos(tipo, marca_id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    # Buscar do cache local
    cursor.execute('''
        SELECT DISTINCT modelo_id as codigo, modelo_nome as nome 
        FROM integrador 
        WHERE tipo = %s AND marca_id = %s AND modelo_id > 0
        ORDER BY modelo_nome
    ''', (tipo, marca_id))
    modelos_cache = cursor.fetchall()
    
    if modelos_cache:
        modelos = [{'codigo': m['codigo'], 'nome': m['nome']} for m in modelos_cache]
    else:
        # Buscar da API se não tem no cache
        modelos = FipeAPI.get_modelos(tipo, marca_id)
        
        # Salvar no cache
        for modelo in modelos:
            try:
                cursor.execute('''
                    INSERT INTO integrador (tipo, marca_id, marca_nome, modelo_id, modelo_nome, versao_id, versao_nome, ano_modelo)
                    SELECT %s, %s, marca_nome, %s, %s, 0, 'PLACEHOLDER', 0
                    FROM integrador WHERE marca_id = %s LIMIT 1
                    ON CONFLICT (tipo, marca_id, modelo_id, versao_id, ano_modelo) DO NOTHING
                ''', (tipo, marca_id, modelo['codigo'], modelo['nome'], marca_id))
            except:
                pass
        conn.commit()
    
    cursor.close()
    conn.close()
    return jsonify(modelos)

@app.route('/api/anos/<tipo>/<marca_id>/<modelo_id>')
@login_required
def api_anos(tipo, marca_id, modelo_id):
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    # Buscar do cache local
    cursor.execute('''
        SELECT DISTINCT ano_modelo, versao_nome, versao_id
        FROM integrador 
        WHERE tipo = %s AND marca_id = %s AND modelo_id = %s AND ano_modelo > 0
        ORDER BY ano_modelo DESC, versao_nome
    ''', (tipo, marca_id, modelo_id))
    anos_cache = cursor.fetchall()
    
    if anos_cache:
        anos = []
        for ano in anos_cache:
            codigo = f"{ano['ano_modelo']}-{ano['versao_id']}"
            nome = f"{ano['ano_modelo']} - {ano['versao_nome']}"
            anos.append({'codigo': codigo, 'nome': nome})
    else:
        # Buscar da API se não tem no cache
        anos = FipeAPI.get_anos(tipo, marca_id, modelo_id)
        
        # Para cada ano, buscar detalhes e salvar
        for ano in anos:
            try:
                detalhes = FipeAPI.get_detalhes(tipo, marca_id, modelo_id, ano['codigo'])
                if detalhes:
                    cursor.execute('''
                        INSERT INTO integrador (
                            tipo, marca_id, marca_nome, modelo_id, modelo_nome, 
                            versao_id, versao_nome, ano_modelo, combustivel, motor, categoria
                        )
                        SELECT %s, %s, marca_nome, %s, modelo_nome, %s, %s, %s, %s, %s, %s
                        FROM integrador WHERE marca_id = %s AND modelo_id = %s LIMIT 1
                        ON CONFLICT (tipo, marca_id, modelo_id, versao_id, ano_modelo) DO UPDATE SET
                            combustivel = EXCLUDED.combustivel,
                            motor = EXCLUDED.motor,
                            categoria = EXCLUDED.categoria
                    ''', (
                        tipo, marca_id, int(ano['codigo'].split('-')[0]), 
                        detalhes.get('CodigoFipe', ano['codigo']), 
                        detalhes.get('Modelo', ano['nome']),
                        detalhes.get('AnoModelo', ano['codigo'].split('-')[0]),
                        detalhes.get('Combustivel', ''),
                        detalhes.get('SiglaCombustivel', ''),
                        detalhes.get('TipoVeiculo', ''),
                        marca_id, modelo_id
                    ))
            except:
                pass
        conn.commit()
    
    cursor.close()
    conn.close()
    return jsonify(anos)

@app.route('/api/detalhes/<tipo>/<marca_id>/<modelo_id>/<ano_codigo>')
@login_required
def api_detalhes(tipo, marca_id, modelo_id, ano_codigo):
    # Extrair ano e versão do código
    try:
        if '-' in ano_codigo:
            ano_modelo = int(ano_codigo.split('-')[0])
            versao_id = ano_codigo.split('-')[1]
        else:
            ano_modelo = int(ano_codigo)
            versao_id = None
    except:
        ano_modelo = 2020
        versao_id = None
    
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    # Buscar do cache local
    cursor.execute('''
        SELECT * FROM integrador 
        WHERE tipo = %s AND marca_id = %s AND modelo_id = %s AND ano_modelo = %s
        ORDER BY created_at DESC LIMIT 1
    ''', (tipo, marca_id, modelo_id, ano_modelo))
    detalhes_cache = cursor.fetchone()
    
    if detalhes_cache and detalhes_cache['combustivel']:
        # Usar dados do cache
        detalhes = {
            'AnoModelo': detalhes_cache['ano_modelo'],
            'Combustivel': detalhes_cache['combustivel'],
            'SiglaCombustivel': detalhes_cache['motor'],
            'Modelo': detalhes_cache['versao_nome'],
            'TipoVeiculo': detalhes_cache['categoria']
        }
    else:
        # Buscar da API como fallback
        detalhes = FipeAPI.get_detalhes(tipo, marca_id, modelo_id, ano_codigo)
        
        # Salvar no cache
        if detalhes:
            try:
                cursor.execute('''
                    INSERT INTO integrador (
                        tipo, marca_id, marca_nome, modelo_id, modelo_nome, 
                        versao_id, versao_nome, ano_modelo, combustivel, motor, categoria
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tipo, marca_id, modelo_id, versao_id, ano_modelo) DO UPDATE SET
                        combustivel = EXCLUDED.combustivel,
                        motor = EXCLUDED.motor,
                        categoria = EXCLUDED.categoria
                ''', (
                    tipo, int(marca_id), detalhes.get('Marca', ''), int(modelo_id), 
                    detalhes.get('Modelo', ''), versao_id or 0, detalhes.get('Modelo', ''),
                    detalhes.get('AnoModelo', ano_modelo), detalhes.get('Combustivel', ''),
                    detalhes.get('SiglaCombustivel', ''), detalhes.get('TipoVeiculo', '')
                ))
                conn.commit()
            except Exception as e:
                print(f"Erro ao salvar cache: {e}")
    
    cursor.close()
    conn.close()
    return jsonify(detalhes)

# Rota para popular cache da FIPE (versão assíncrona)
@app.route('/admin/popular-fipe')
@login_required
def popular_fipe():
    """Popula a tabela integrador com dados da FIPE - versão rápida"""
    import threading
    
    def popular_em_background():
        conn = get_db_connection()
        cursor = conn.cursor()
        
        tipos = ['carros', 'motos']
        total_inseridos = 0
        
        # Marcas principais para não sobrecarregar
        marcas_principais = {
            'carros': ['Volkswagen', 'Chevrolet', 'Ford', 'Fiat', 'Toyota', 'Honda', 'Hyundai'],
            'motos': ['Honda', 'Yamaha', 'Suzuki', 'Kawasaki', 'BMW']
        }
        
        for tipo in tipos:
            print(f"[BACKGROUND] Populando {tipo}...")
            
            # Buscar marcas
            marcas = FipeAPI.get_marcas(tipo)
            
            # Filtrar apenas marcas principais
            if tipo in marcas_principais:
                marcas_filtradas = [m for m in marcas if any(principal.lower() in m['nome'].lower() 
                                                          for principal in marcas_principais[tipo])]
            else:
                marcas_filtradas = marcas[:5]  # Primeiras 5 se não estiver na lista
            
            for marca in marcas_filtradas:
                print(f"[BACKGROUND] Processando {marca['nome']}")
                
                # Buscar modelos (limitar a 10 por marca)
                modelos = FipeAPI.get_modelos(tipo, marca['codigo'])[:10]
                
                for modelo in modelos:
                    # Buscar anos (limitar a 3 por modelo)
                    anos = FipeAPI.get_anos(tipo, marca['codigo'], modelo['codigo'])[:3]
                    
                    for ano in anos:
                        try:
                            # Buscar detalhes
                            detalhes = FipeAPI.get_detalhes(tipo, marca['codigo'], modelo['codigo'], ano['codigo'])
                            
                            if detalhes:
                                cursor.execute('''
                                    INSERT INTO integrador (
                                        tipo, marca_id, marca_nome, modelo_id, modelo_nome,
                                        versao_id, versao_nome, ano_modelo, combustivel, motor, categoria
                                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                                    ON CONFLICT (tipo, marca_id, modelo_id, versao_id, ano_modelo) DO UPDATE SET
                                        combustivel = EXCLUDED.combustivel,
                                        motor = EXCLUDED.motor,
                                        categoria = EXCLUDED.categoria
                                ''', (
                                    tipo, marca['codigo'], marca['nome'], modelo['codigo'], modelo['nome'],
                                    detalhes.get('CodigoFipe', ano['codigo']), detalhes.get('Modelo', ano['nome']),
                                    detalhes.get('AnoModelo', 2020), detalhes.get('Combustivel', ''),
                                    detalhes.get('SiglaCombustivel', ''), detalhes.get('TipoVeiculo', '')
                                ))
                                total_inseridos += 1
                                
                                if total_inseridos % 20 == 0:
                                    conn.commit()
                                    print(f"[BACKGROUND] Inseridos: {total_inseridos}")
                        except Exception as e:
                            print(f"[BACKGROUND] Erro: {e}")
                            continue
        
        conn.commit()
        cursor.close()
        conn.close()
        print(f"[BACKGROUND] Finalizado! Total: {total_inseridos}")
    
    # Iniciar processo em background
    thread = threading.Thread(target=popular_em_background)
    thread.daemon = True
    thread.start()
    
    return jsonify({
        'success': True,
        'message': 'Processo iniciado em background. Aguarde alguns minutos e verifique o status.',
        'status': 'processando'
    })

# Nova rota para popular apenas algumas marcas (mais rápido)
@app.route('/admin/popular-basico')
@login_required
def popular_basico():
    """Popula apenas dados básicos - mais rápido"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Dados básicos para teste
    dados_basicos = [
        # Carros
        ('carros', 59, 'Volkswagen', 5940, 'Gol', '2020-1', 'Gol 1.0', 2020, 'Flex', '1.0', 'Hatch'),
        ('carros', 59, 'Volkswagen', 5965, 'Fox', '2019-1', 'Fox 1.0', 2019, 'Flex', '1.0', 'Hatch'),
        ('carros', 22, 'Chevrolet', 7328, 'Onix', '2020-1', 'Onix 1.0', 2020, 'Flex', '1.0', 'Hatch'),
        ('carros', 26, 'Ford', 5035, 'Ka', '2020-1', 'Ka 1.0', 2020, 'Flex', '1.0', 'Hatch'),
        ('carros', 25, 'Fiat', 4828, 'Argo', '2020-1', 'Argo 1.0', 2020, 'Flex', '1.0', 'Hatch'),
        
        # Motos
        ('motos', 26, 'Honda', 1446, 'CG 160', '2020-1', 'CG 160 Titan', 2020, 'Gasolina', '160cc', 'Street'),
        ('motos', 26, 'Honda', 1483, 'CB 600F', '2020-1', 'CB 600F Hornet', 2020, 'Gasolina', '600cc', 'Naked'),
        ('motos', 52, 'Yamaha', 2467, 'Factor 125', '2020-1', 'Factor 125i', 2020, 'Gasolina', '125cc', 'Street'),
        ('motos', 46, 'Suzuki', 2100, 'GSX-R 1000', '2020-1', 'GSX-R 1000', 2020, 'Gasolina', '1000cc', 'Esportiva'),
    ]
    
    total_inseridos = 0
    
    for dados in dados_basicos:
        try:
            cursor.execute('''
                INSERT INTO integrador (
                    tipo, marca_id, marca_nome, modelo_id, modelo_nome,
                    versao_id, versao_nome, ano_modelo, combustivel, motor, categoria
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tipo, marca_id, modelo_id, versao_id, ano_modelo) DO UPDATE SET
                    combustivel = EXCLUDED.combustivel,
                    motor = EXCLUDED.motor,
                    categoria = EXCLUDED.categoria
            ''', dados)
            total_inseridos += 1
        except Exception as e:
            print(f"Erro ao inserir: {e}")
    
    conn.commit()
    cursor.close()
    conn.close()
    
    return jsonify({
        'success': True,
        'message': f'Cache básico populado com {total_inseridos} registros',
        'total_inseridos': total_inseridos
    })

# Rota para verificar status do cache
@app.route('/admin/status-cache')
@login_required
def status_cache():
    """Verifica quantos registros tem no cache"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Estatísticas gerais
    cursor.execute('SELECT COUNT(*) FROM integrador')
    total = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(DISTINCT marca_id) FROM integrador WHERE tipo = %s', ('carros',))
    marcas_carros = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(DISTINCT marca_id) FROM integrador WHERE tipo = %s', ('motos',))
    marcas_motos = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(DISTINCT modelo_id) FROM integrador WHERE tipo = %s', ('carros',))
    modelos_carros = cursor.fetchone()[0]
    
    cursor.execute('SELECT COUNT(DISTINCT modelo_id) FROM integrador WHERE tipo = %s', ('motos',))
    modelos_motos = cursor.fetchone()[0]
    
    cursor.close()
    conn.close()
    
    return jsonify({
        'total_registros': total,
        'marcas_carros': marcas_carros,
        'marcas_motos': marcas_motos,
        'modelos_carros': modelos_carros,
        'modelos_motos': modelos_motos
    })
@app.route('/xml')
def xml_endpoint():
    conn = get_db_connection()
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    
    cursor.execute(f'SELECT * FROM {CLIENT_TABLE} WHERE ativo = TRUE ORDER BY created_at DESC')
    veiculos = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    # Converter para formato serializável
    veiculos_json = []
    for veiculo in veiculos:
        veiculo_dict = dict(veiculo)
        # Converter datetime para string
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

@app.route('/json')
def json_endpoint():
    return xml_endpoint()  # Mesmo endpoint para JSON

# requirements.txt
"""
Flask==2.3.3
psycopg2-binary==2.9.7
boto3==1.28.17
requests==2.31.0
Werkzeug==2.3.7
"""

# templates/base.html
BASE_HTML = '''
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Integrador de Veículos{% endblock %}</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            theme: {
                extend: {
                    colors: {
                        'orange': '#ff6b35',
                        'orange-dark': '#e55a2b',
                        'gray-medium': '#6b7280',
                        'gray-light': '#f3f4f6'
                    }
                }
            }
        }
    </script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
    <style>
        .fade-in {
            animation: fadeIn 0.5s ease-in;
        }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(20px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .slide-in {
            animation: slideIn 0.3s ease-out;
        }
        
        @keyframes slideIn {
            from { transform: translateX(-100%); }
            to { transform: translateX(0); }
        }
        
        .bounce-in {
            animation: bounceIn 0.6s cubic-bezier(0.68, -0.55, 0.265, 1.55);
        }
        
        @keyframes bounceIn {
            0% { transform: scale(0); }
            50% { transform: scale(1.1); }
            100% { transform: scale(1); }
        }
        
        .hover-scale {
            transition: transform 0.2s ease;
        }
        
        .hover-scale:hover {
            transform: scale(1.05);
        }
        
        .glass {
            background: rgba(255, 255, 255, 0.1);
            backdrop-filter: blur(10px);
            border: 1px solid rgba(255, 255, 255, 0.2);
        }
        
        .gradient-bg {
            background: linear-gradient(135deg, #ff6b35 0%, #f4f4f4 100%);
        }
    </style>
</head>
<body class="bg-gray-100 min-h-screen">
    {% block content %}{% endblock %}
    
    <script src="https://cdnjs.cloudflare.com/ajax/libs/jquery/3.6.0/jquery.min.js"></script>
    <script>
        // Animações globais
        $(document).ready(function() {
            $('.fade-in').css('opacity', '0').animate({opacity: 1}, 500);
            
            // Toast notifications
            setTimeout(function() {
                $('.alert').fadeOut();
            }, 5000);
        });
        
        // Função para mostrar loading
        function showLoading() {
            const loading = `
                <div id="loading" class="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
                    <div class="bg-white p-6 rounded-lg glass bounce-in">
                        <div class="flex items-center">
                            <i class="fas fa-spinner fa-spin text-orange mr-3"></i>
                            <span class="text-gray-800">Carregando...</span>
                        </div>
                    </div>
                </div>
            `;
            $('body').append(loading);
        }
        
        function hideLoading() {
            $('#loading').remove();
        }
    </script>
    
    {% block scripts %}{% endblock %}
</body>
</html>
'''

# templates/login.html
LOGIN_HTML = '''
{% extends "base.html" %}

{% block title %}Login - Integrador de Veículos{% endblock %}

{% block content %}
<div class="min-h-screen gradient-bg flex items-center justify-center p-4">
    <div class="bg-white rounded-2xl shadow-2xl p-8 w-full max-w-md bounce-in">
        <div class="text-center mb-8">
            <i class="fas fa-car text-orange text-4xl mb-4"></i>
            <h1 class="text-2xl font-bold text-gray-800">Integrador de Veículos</h1>
            <p class="text-gray-medium mt-2">Faça login para continuar</p>
        </div>
        
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert bg-red-100 border border-red-400 text-red-700 px-4 py-3 rounded mb-4">
                        {{ message }}
                    </div>
                {% endfor %}
            {% endif %}
        {% endwith %}
        
        <form method="POST" class="space-y-6">
            <div>
                <label class="block text-gray-700 text-sm font-bold mb-2">
                    <i class="fas fa-user mr-2"></i>Usuário
                </label>
                <input type="text" name="username" required
                       class="w-full px-3 py-3 border border-gray-300 rounded-lg focus:outline-none focus:border-orange transition-colors">
            </div>
            
            <div>
                <label class="block text-gray-700 text-sm font-bold mb-2">
                    <i class="fas fa-lock mr-2"></i>Senha
                </label>
                <input type="password" name="password" required
                       class="w-full px-3 py-3 border border-gray-300 rounded-lg focus:outline-none focus:border-orange transition-colors">
            </div>
            
            <button type="submit" 
                    class="w-full bg-orange text-white py-3 rounded-lg font-semibold hover:bg-orange-dark transition-colors hover-scale">
                <i class="fas fa-sign-in-alt mr-2"></i>Entrar
            </button>
        </form>
    </div>
</div>
{% endblock %}
'''

# templates/dashboard.html  
DASHBOARD_HTML = '''
{% extends "base.html" %}

{% block title %}Dashboard - Integrador de Veículos{% endblock %}

{% block content %}
<div class="bg-gray-100 min-h-screen">
    <!-- Header -->
    <header class="bg-white shadow-sm border-b">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div class="flex justify-between items-center py-4">
                <div class="flex items-center">
                    <i class="fas fa-car text-orange text-2xl mr-3"></i>
                    <h1 class="text-xl font-bold text-gray-800">Integrador de Veículos</h1>
                    <span class="ml-4 text-sm text-gray-medium bg-gray-100 px-3 py-1 rounded-full">{{ client_table }}</span>
                </div>
                <div class="flex items-center space-x-4">
                    <a href="/xml" target="_blank" 
                       class="bg-green-500 text-white px-4 py-2 rounded-lg hover:bg-green-600 transition-colors hover-scale">
                        <i class="fas fa-link mr-2"></i>Link XML/JSON
                    </a>
                    <a href="{{ url_for('logout') }}" 
                       class="bg-gray-500 text-white px-4 py-2 rounded-lg hover:bg-gray-600 transition-colors hover-scale">
                        <i class="fas fa-sign-out-alt mr-2"></i>Sair
                    </a>
                </div>
            </div>
        </div>
    </header>

    <!-- Main Content -->
    <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {% with messages = get_flashed_messages(with_categories=true) %}
            {% if messages %}
                {% for category, message in messages %}
                    <div class="alert mb-6 p-4 rounded-lg {% if category == 'success' %}bg-green-100 text-green-800 border border-green-300{% else %}bg-red-100 text-red-800 border border-red-300{% endif %}">
                        {{ message }}
                    </div>
                {% endfor %}
            {% endif %}
        {% endwith %}

        <!-- Actions -->
        <div class="flex justify-between items-center mb-6">
            <h2 class="text-2xl font-bold text-gray-800">Veículos Cadastrados</h2>
            <a href="{{ url_for('novo_veiculo') }}" 
               class="bg-orange text-white px-6 py-3 rounded-lg font-semibold hover:bg-orange-dark transition-colors hover-scale">
                <i class="fas fa-plus mr-2"></i>Novo Veículo
            </a>
        </div>

        <!-- Vehicles Grid -->
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {% for veiculo in veiculos %}
            <div class="bg-white rounded-lg shadow-md overflow-hidden hover:shadow-lg transition-shadow fade-in">
                <div class="relative">
                    {% if veiculo.fotos and veiculo.fotos|length > 0 %}
                        <img src="{{ veiculo.fotos[0] }}" alt="{{ veiculo.marca_nome }} {{ veiculo.modelo_nome }}" 
                             class="w-full h-48 object-cover">
                    {% else %}
                        <div class="w-full h-48 bg-gray-200 flex items-center justify-center">
                            <i class="fas fa-car text-gray-400 text-4xl"></i>
                        </div>
                    {% endif %}
                    
                    <!-- Status Badge -->
                    <div class="absolute top-2 right-2">
                        <span class="px-2 py-1 rounded-full text-xs font-semibold {% if veiculo.ativo %}bg-green-100 text-green-800{% else %}bg-red-100 text-red-800{% endif %}">
                            {% if veiculo.ativo %}Ativo{% else %}Inativo{% endif %}
                        </span>
                    </div>
                </div>
                
                <div class="p-4">
                    <h3 class="font-bold text-lg text-gray-800 mb-1">{{ veiculo.marca_nome }} {{ veiculo.modelo_nome }}</h3>
                    <p class="text-gray-medium text-sm mb-2">{{ veiculo.versao_nome }}</p>
                    
                    <div class="grid grid-cols-2 gap-2 text-sm text-gray-600 mb-3">
                        <div><i class="fas fa-calendar mr-1"></i>{{ veiculo.ano_modelo }}/{{ veiculo.ano_fabricacao }}</div>
                        <div><i class="fas fa-tachometer-alt mr-1"></i>{{ "{:,}".format(veiculo.km).replace(',', '.') }} km</div>
                        <div><i class="fas fa-palette mr-1"></i>{{ veiculo.cor }}</div>
                        <div><i class="fas fa-gas-pump mr-1"></i>{{ veiculo.combustivel }}</div>
                    </div>
                    
                    {% if veiculo.preco %}
                    <div class="text-orange font-bold text-lg mb-3">
                        R$ {{ "{:,.2f}".format(veiculo.preco).replace(',', '.') }}
                    </div>
                    {% endif %}
                    
                    <!-- Actions -->
                    <div class="flex space-x-2">
                        <a href="{{ url_for('editar_veiculo', veiculo_id=veiculo.id) }}" 
                           class="flex-1 bg-blue-500 text-white px-3 py-2 rounded text-center text-sm hover:bg-blue-600 transition-colors">
                            <i class="fas fa-edit mr-1"></i>Editar
                        </a>
                        
                        <button onclick="toggleVeiculo({{ veiculo.id }})" 
                                class="flex-1 {% if veiculo.ativo %}bg-yellow-500 hover:bg-yellow-600{% else %}bg-green-500 hover:bg-green-600{% endif %} text-white px-3 py-2 rounded text-sm transition-colors">
                            <i class="fas fa-{% if veiculo.ativo %}pause{% else %}play{% endif %} mr-1"></i>
                            {% if veiculo.ativo %}Pausar{% else %}Ativar{% endif %}
                        </button>
                        
                        <button onclick="excluirVeiculo({{ veiculo.id }})" 
                                class="bg-red-500 text-white px-3 py-2 rounded text-sm hover:bg-red-600 transition-colors">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                </div>
            </div>
            {% endfor %}
        </div>

        {% if not veiculos %}
        <div class="text-center py-12">
            <i class="fas fa-car text-gray-300 text-6xl mb-4"></i>
                        <h3 class="text-xl font-medium text-gray-500 mb-2">Nenhum veículo cadastrado</h3>
            <p class="text-gray-400">Clique em "Novo Veículo" para começar</p>
        </div>
        {% endif %}
    </main>
</div>

<script>
function toggleVeiculo(id) {
    showLoading();
    
    fetch(`/veiculo/toggle/${id}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
    })
    .then(response => response.json())
    .then(data => {
        hideLoading();
        if (data.success) {
            location.reload();
        }
    })
    .catch(error => {
        hideLoading();
        alert('Erro ao alterar status do veículo');
    });
}

function excluirVeiculo(id) {
    if (confirm('Tem certeza que deseja excluir este veículo?')) {
        showLoading();
        
        fetch(`/veiculo/excluir/${id}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
        })
        .then(response => {
            hideLoading();
            if (response.ok) {
                location.reload();
            } else {
                alert('Erro ao excluir veículo');
            }
        })
        .catch(error => {
            hideLoading();
            alert('Erro ao excluir veículo');
        });
    }
}
</script>
{% endblock %}
'''

# templates/veiculo_form.html
VEICULO_FORM_HTML = '''
{% extends "base.html" %}

{% block title %}{% if veiculo %}Editar{% else %}Novo{% endif %} Veículo - Integrador{% endblock %}

{% block content %}
<div class="bg-gray-100 min-h-screen">
    <!-- Header -->
    <header class="bg-white shadow-sm border-b">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div class="flex justify-between items-center py-4">
                <div class="flex items-center">
                    <a href="{{ url_for('dashboard') }}" class="text-orange hover:text-orange-dark mr-4">
                        <i class="fas fa-arrow-left text-xl"></i>
                    </a>
                    <h1 class="text-xl font-bold text-gray-800">
                        {% if veiculo %}Editar Veículo{% else %}Novo Veículo{% endif %}
                    </h1>
                </div>
                <a href="{{ url_for('logout') }}" 
                   class="bg-gray-500 text-white px-4 py-2 rounded-lg hover:bg-gray-600 transition-colors">
                    <i class="fas fa-sign-out-alt mr-2"></i>Sair
                </a>
            </div>
        </div>
    </header>

    <!-- Form -->
    <main class="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <form id="veiculoForm" method="POST" enctype="multipart/form-data" class="bg-white rounded-lg shadow-md p-6">
            {% if veiculo %}
                <input type="hidden" name="id" value="{{ veiculo.id }}">
                <input type="hidden" id="fotosExistentes" name="fotos_existentes" value="{{ veiculo.fotos|tojson if veiculo.fotos else '[]' }}">
            {% endif %}

            <!-- Tipo -->
            <div class="mb-6">
                <label class="block text-gray-700 text-sm font-bold mb-2">
                    <i class="fas fa-car mr-2"></i>Tipo de Veículo
                </label>
                <select name="tipo" id="tipo" required 
                        class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:border-orange">
                    <option value="">Selecione o tipo</option>
                    <option value="carros" {% if veiculo and veiculo.tipo == 'carros' %}selected{% endif %}>Carro</option>
                    <option value="motos" {% if veiculo and veiculo.tipo == 'motos' %}selected{% endif %}>Moto</option>
                </select>
            </div>

            <!-- Marca -->
            <div class="mb-6">
                <label class="block text-gray-700 text-sm font-bold mb-2">
                    <i class="fas fa-industry mr-2"></i>Marca
                </label>
                <select name="marca_id" id="marca" required disabled
                        class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:border-orange">
                    <option value="">Selecione a marca</option>
                </select>
                <input type="hidden" name="marca_nome" id="marcaNome">
            </div>

            <!-- Modelo -->
            <div class="mb-6">
                <label class="block text-gray-700 text-sm font-bold mb-2">
                    <i class="fas fa-car-side mr-2"></i>Modelo
                </label>
                <select name="modelo_id" id="modelo" required disabled
                        class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:border-orange">
                    <option value="">Selecione o modelo</option>
                </select>
                <input type="hidden" name="modelo_nome" id="modeloNome">
            </div>

            <!-- Versão -->
            <div class="mb-6">
                <label class="block text-gray-700 text-sm font-bold mb-2">
                    <i class="fas fa-cog mr-2"></i>Versão
                </label>
                <select name="versao_id" id="versao" required disabled
                        class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:border-orange">
                    <option value="">Selecione a versão</option>
                </select>
                <input type="hidden" name="versao_nome" id="versaoNome">
            </div>

            <!-- Dados do Veículo -->
            <div id="dadosVeiculo" class="{% if not veiculo %}hidden{% endif %}">
                <h3 class="text-lg font-semibold text-gray-800 mb-4 border-b pb-2">
                    <i class="fas fa-info-circle mr-2"></i>Dados do Veículo
                </h3>

                <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
                    <div>
                        <label class="block text-gray-700 text-sm font-bold mb-2">Ano Modelo</label>
                        <input type="number" name="ano_modelo" id="anoModelo" required disabled
                               value="{{ veiculo.ano_modelo if veiculo else '' }}"
                               class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:border-orange">
                    </div>

                    <div>
                        <label class="block text-gray-700 text-sm font-bold mb-2">Ano Fabricação</label>
                        <input type="number" name="ano_fabricacao" required disabled
                               value="{{ veiculo.ano_fabricacao if veiculo else '' }}"
                               class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:border-orange">
                    </div>

                    <div>
                        <label class="block text-gray-700 text-sm font-bold mb-2">KM</label>
                        <input type="number" name="km" required disabled
                               value="{{ veiculo.km if veiculo else '' }}"
                               class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:border-orange">
                    </div>

                    <div>
                        <label class="block text-gray-700 text-sm font-bold mb-2">Cor</label>
                        <input type="text" name="cor" required disabled
                               value="{{ veiculo.cor if veiculo else '' }}"
                               class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:border-orange">
                    </div>

                    <div>
                        <label class="block text-gray-700 text-sm font-bold mb-2">Combustível</label>
                        <input type="text" name="combustivel" id="combustivel" readonly disabled
                               value="{{ veiculo.combustivel if veiculo else '' }}"
                               class="w-full px-3 py-2 border border-gray-300 rounded-lg bg-gray-100">
                    </div>

                    <div>
                        <label class="block text-gray-700 text-sm font-bold mb-2">Câmbio</label>
                        <select name="cambio" required disabled
                                class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:border-orange">
                            <option value="">Selecione</option>
                            <option value="Manual" {% if veiculo and veiculo.cambio == 'Manual' %}selected{% endif %}>Manual</option>
                            <option value="Automático" {% if veiculo and veiculo.cambio == 'Automático' %}selected{% endif %}>Automático</option>
                            <option value="CVT" {% if veiculo and veiculo.cambio == 'CVT' %}selected{% endif %}>CVT</option>
                        </select>
                    </div>

                    <div>
                        <label class="block text-gray-700 text-sm font-bold mb-2">Motor</label>
                        <input type="text" name="motor" id="motor" readonly disabled
                               value="{{ veiculo.motor if veiculo else '' }}"
                               class="w-full px-3 py-2 border border-gray-300 rounded-lg bg-gray-100">
                    </div>

                    <div>
                        <label class="block text-gray-700 text-sm font-bold mb-2">Portas</label>
                        <input type="number" name="portas" id="portas" readonly disabled
                               value="{{ veiculo.portas if veiculo else '' }}"
                               class="w-full px-3 py-2 border border-gray-300 rounded-lg bg-gray-100">
                    </div>

                    <div>
                        <label class="block text-gray-700 text-sm font-bold mb-2">Categoria</label>
                        <input type="text" name="categoria" required disabled
                               value="{{ veiculo.categoria if veiculo else '' }}"
                               class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:border-orange">
                    </div>

                    <div id="cilindradaDiv" class="{% if not veiculo or veiculo.tipo != 'motos' %}hidden{% endif %}">
                        <label class="block text-gray-700 text-sm font-bold mb-2">Cilindrada</label>
                        <input type="text" name="cilindrada" disabled
                               value="{{ veiculo.cilindrada if veiculo else '' }}"
                               class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:border-orange">
                    </div>

                    <div>
                        <label class="block text-gray-700 text-sm font-bold mb-2">Preço</label>
                        <input type="number" step="0.01" name="preco" required disabled
                               value="{{ veiculo.preco if veiculo else '' }}"
                               class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:border-orange">
                    </div>
                </div>

                <!-- Fotos -->
                <div class="mb-6">
                    <label class="block text-gray-700 text-sm font-bold mb-2">
                        <i class="fas fa-images mr-2"></i>Fotos
                    </label>
                    <input type="file" name="fotos" multiple accept="image/*" disabled
                           class="w-full px-3 py-2 border border-gray-300 rounded-lg focus:outline-none focus:border-orange">
                    
                    {% if veiculo and veiculo.fotos %}
                    <div class="mt-4">
                        <h4 class="text-sm font-semibold text-gray-700 mb-2">Fotos Atuais:</h4>
                        <div id="fotosAtuais" class="grid grid-cols-2 md:grid-cols-4 gap-4">
                            {% for foto in veiculo.fotos %}
                            <div class="relative group">
                                <img src="{{ foto }}" alt="Foto do veículo" class="w-full h-24 object-cover rounded">
                                <button type="button" onclick="removerFoto('{{ foto }}')"
                                        class="absolute top-1 right-1 bg-red-500 text-white rounded-full w-6 h-6 text-xs hover:bg-red-600">
                                    <i class="fas fa-times"></i>
                                </button>
                            </div>
                            {% endfor %}
                        </div>
                    </div>
                    {% endif %}
                </div>

                <!-- Botões -->
                <div class="flex space-x-4">
                    <button type="submit" 
                            class="bg-orange text-white px-6 py-3 rounded-lg font-semibold hover:bg-orange-dark transition-colors hover-scale">
                        <i class="fas fa-save mr-2"></i>Salvar Veículo
                    </button>
                    <a href="{{ url_for('dashboard') }}" 
                       class="bg-gray-500 text-white px-6 py-3 rounded-lg font-semibold hover:bg-gray-600 transition-colors">
                        <i class="fas fa-times mr-2"></i>Cancelar
                    </a>
                </div>
            </div>
        </form>
    </main>
</div>

<script>
let fotosExistentes = {% if veiculo and veiculo.fotos %}{{ veiculo.fotos|tojson }}{% else %}[]{% endif %};

$(document).ready(function() {
    // Carregar marcas quando tipo for selecionado
    $('#tipo').change(function() {
        const tipo = $(this).val();
        if (tipo) {
            carregarMarcas(tipo);
            $('#marca').prop('disabled', false);
        } else {
            $('#marca, #modelo, #versao').prop('disabled', true).html('<option value="">Selecione</option>');
        }
    });

    // Carregar modelos quando marca for selecionada
    $('#marca').change(function() {
        const marcaId = $(this).val();
        const marcaNome = $(this).find('option:selected').text();
        $('#marcaNome').val(marcaNome);
        
        if (marcaId) {
            carregarModelos($('#tipo').val(), marcaId);
            $('#modelo').prop('disabled', false);
        } else {
            $('#modelo, #versao').prop('disabled', true).html('<option value="">Selecione</option>');
        }
    });

    // Carregar versões quando modelo for selecionado
    $('#modelo').change(function() {
        const modeloId = $(this).val();
        const modeloNome = $(this).find('option:selected').text();
        $('#modeloNome').val(modeloNome);
        
        if (modeloId) {
            carregarAnos($('#tipo').val(), $('#marca').val(), modeloId);
            $('#versao').prop('disabled', false);
        } else {
            $('#versao').prop('disabled', true).html('<option value="">Selecione</option>');
        }
    });

    // Carregar detalhes quando versão for selecionada
    $('#versao').change(function() {
        const anoId = $(this).val();
        const versaoNome = $(this).find('option:selected').text();
        $('#versaoNome').val(versaoNome);
        
        if (anoId) {
            carregarDetalhes($('#tipo').val(), $('#marca').val(), $('#modelo').val(), anoId);
            liberarCampos();
        } else {
            bloquearCampos();
        }
    });

    // Se estiver editando, carregar dados
    {% if veiculo %}
        setTimeout(function() {
            $('#tipo').trigger('change');
            setTimeout(function() {
                $('#marca').val({{ veiculo.marca_id }}).trigger('change');
                setTimeout(function() {
                    $('#modelo').val({{ veiculo.modelo_id }}).trigger('change');
                    setTimeout(function() {
                        $('#versao').val('{{ veiculo.ano_modelo }}-1');
                        liberarCampos();
                    }, 1000);
                }, 1000);
            }, 1000);
        }, 500);
    {% endif %}
});

function carregarMarcas(tipo) {
    showLoading();
    
    $.get(`/api/marcas/${tipo}`)
        .done(function(marcas) {
            let options = '<option value="">Selecione a marca</option>';
            marcas.forEach(function(marca) {
                options += `<option value="${marca.codigo}">${marca.nome}</option>`;
            });
            $('#marca').html(options);
        })
        .fail(function() {
            alert('Erro ao carregar marcas');
        })
        .always(function() {
            hideLoading();
        });
}

function carregarModelos(tipo, marcaId) {
    showLoading();
    
    $.get(`/api/modelos/${tipo}/${marcaId}`)
        .done(function(modelos) {
            let options = '<option value="">Selecione o modelo</option>';
            modelos.forEach(function(modelo) {
                options += `<option value="${modelo.codigo}">${modelo.nome}</option>`;
            });
            $('#modelo').html(options);
        })
        .fail(function() {
            alert('Erro ao carregar modelos');
        })
        .always(function() {
            hideLoading();
        });
}

function carregarAnos(tipo, marcaId, modeloId) {
    showLoading();
    
    $.get(`/api/anos/${tipo}/${marcaId}/${modeloId}`)
        .done(function(anos) {
            let options = '<option value="">Selecione a versão</option>';
            anos.forEach(function(ano) {
                options += `<option value="${ano.codigo}">${ano.nome}</option>`;
            });
            $('#versao').html(options);
        })
        .fail(function() {
            alert('Erro ao carregar versões');
        })
        .always(function() {
            hideLoading();
        });
}

function carregarDetalhes(tipo, marcaId, modeloId, anoId) {
    showLoading();
    
    $.get(`/api/detalhes/${tipo}/${marcaId}/${modeloId}/${anoId}`)
        .done(function(detalhes) {
            $('#anoModelo').val(detalhes.AnoModelo);
            $('#combustivel').val(detalhes.Combustivel);
            $('#motor').val(detalhes.SiglaCombustivel);
            
            // Mostrar/ocultar cilindrada baseado no tipo
            if (tipo === 'motos') {
                $('#cilindradaDiv').removeClass('hidden');
            } else {
                $('#cilindradaDiv').addClass('hidden');
            }
        })
        .fail(function() {
            alert('Erro ao carregar detalhes');
        })
        .always(function() {
            hideLoading();
        });
}

function liberarCampos() {
    $('#dadosVeiculo').removeClass('hidden');
    $('#dadosVeiculo input, #dadosVeiculo select').not('[readonly]').prop('disabled', false);
}

function bloquearCampos() {
    $('#dadosVeiculo').addClass('hidden');
    $('#dadosVeiculo input, #dadosVeiculo select').prop('disabled', true);
}

function removerFoto(fotoUrl) {
    if (confirm('Remover esta foto?')) {
        fotosExistentes = fotosExistentes.filter(foto => foto !== fotoUrl);
        $('#fotosExistentes').val(JSON.stringify(fotosExistentes));
        
        // Remover visualmente
        $(`img[src="${fotoUrl}"]`).closest('.group').remove();
    }
}

// Submit do formulário
$('#veiculoForm').submit(function(e) {
    showLoading();
});
</script>
{% endblock %}
'''

# requirements.txt
REQUIREMENTS = '''Flask==2.3.3
psycopg2-binary==2.9.7
boto3==1.28.17
requests==2.31.0
Werkzeug==2.3.7
python-dotenv==1.0.0'''

# .env template
ENV_TEMPLATE = '''# Configurações do Banco de Dados
DB_HOST=localhost
DB_NAME=integrador
DB_USER=postgres
DB_PASSWORD=sua_senha
DB_PORT=5432

# Configurações de Autenticação
AUTH_USERNAME=admin
AUTH_PASSWORD=sua_senha_admin
SECRET_KEY=sua_chave_secreta_muito_segura

# Nome da Tabela do Cliente
CLIENT_TABLE=integrador_cliente01

# Configurações do Bucket Blaze
BLAZE_ENDPOINT_URL=https://s3.us-west-004.backblazeb2.com
BLAZE_ACCESS_KEY=sua_access_key
BLAZE_SECRET_KEY=sua_secret_key
BLAZE_BUCKET_NAME=seu_bucket_name'''

# docker-compose.yml para desenvolvimento
DOCKER_COMPOSE = '''version: '3.8'

services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: integrador
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: password
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

  app:
    build: .
    ports:
      - "5000:5000"
    environment:
      - DB_HOST=postgres
      - DB_NAME=integrador
      - DB_USER=postgres
      - DB_PASSWORD=password
    depends_on:
      - postgres
    volumes:
      - .:/app

volumes:
  postgres_data:'''

# Dockerfile
DOCKERFILE = '''FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["python", "app.py"]'''

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
