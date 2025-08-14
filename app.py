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

# APIs FIPE - Modificadas para usar cache local
@app.route('/api/marcas/<tipo>')
@login_required
def api_marcas(tipo):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Primeiro tenta buscar do cache local
        cursor.execute('''
            SELECT DISTINCT marca_id as codigo, marca_nome as nome 
            FROM integrador 
            WHERE tipo = %s AND marca_id IS NOT NULL AND marca_nome IS NOT NULL
            ORDER BY marca_nome
        ''', (tipo,))
        marcas_cache = cursor.fetchall()
        
        if marcas_cache:
            # Se tem no cache, usa os dados locais
            marcas = [{'codigo': m['codigo'], 'nome': m['nome']} for m in marcas_cache]
        else:
            # Se não tem no cache, busca da API
            marcas = FipeAPI.get_marcas(tipo)
        
        cursor.close()
        conn.close()
        return jsonify(marcas)
    except Exception as e:
        return jsonify([])

@app.route('/api/modelos/<tipo>/<marca_id>')
@login_required
def api_modelos(tipo, marca_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Buscar do cache local
        cursor.execute('''
            SELECT DISTINCT modelo_id as codigo, modelo_nome as nome 
            FROM integrador 
            WHERE tipo = %s AND marca_id = %s AND modelo_id IS NOT NULL AND modelo_nome IS NOT NULL
            ORDER BY modelo_nome
        ''', (tipo, marca_id))
        modelos_cache = cursor.fetchall()
        
        if modelos_cache:
            modelos = [{'codigo': m['codigo'], 'nome': m['nome']} for m in modelos_cache]
        else:
            # Buscar da API se não tem no cache
            modelos = FipeAPI.get_modelos(tipo, marca_id)
        
        cursor.close()
        conn.close()
        return jsonify(modelos)
    except Exception as e:
        return jsonify([])

@app.route('/api/anos/<tipo>/<marca_id>/<modelo_id>')
@login_required
def api_anos(tipo, marca_id, modelo_id):
    try:
        conn = get_db_connection()
        cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        
        # Buscar do cache local
        cursor.execute('''
            SELECT DISTINCT ano_modelo, versao_nome, versao_id
            FROM integrador 
            WHERE tipo = %s AND marca_id = %s AND modelo_id = %s AND ano_modelo IS NOT NULL
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
        
        cursor.close()
        conn.close()
        return jsonify(anos)
    except Exception as e:
        return jsonify([])

@app.route('/api/detalhes/<tipo>/<marca_id>/<modelo_id>/<ano_codigo>')
@login_required
def api_detalhes(tipo, marca_id, modelo_id, ano_codigo):
    try:
        # Extrair ano do código
        if '-' in ano_codigo:
            ano_modelo = int(ano_codigo.split('-')[0])
        else:
            ano_modelo = int(ano_codigo)
        
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
        
        cursor.close()
        conn.close()
        return jsonify(detalhes)
    except Exception as e:
        return jsonify({})

# Rotas administrativas
@app.route('/admin/status-cache')
@login_required
def status_cache():
    """Verifica quantos registros tem no cache"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Estatísticas gerais
        cursor.execute('SELECT COUNT(*) FROM integrador')
        total = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(DISTINCT marca_id) FROM integrador WHERE tipo = %s', ('carros',))
        marcas_carros = cursor.fetchone()[0]
        
        cursor.execute('SELECT COUNT(DISTINCT marca_id) FROM integrador WHERE tipo = %s', ('motos',))
        marcas_motos = cursor.fetchone()[0]
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'total_registros': total,
            'marcas_carros': marcas_carros,
            'marcas_motos': marcas_motos
        })
    except Exception as e:
        return jsonify({'error': str(e)})

@app.route('/admin/popular-basico')
@login_required
def popular_basico():
    """Popula apenas dados básicos"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Dados básicos para teste
        dados_basicos = [
            ('carros', 59, 'Volkswagen', 5940, 'Gol', '2020-1', 'Gol 1.0', 2020, 'Flex', '1.0', 'Hatch'),
            ('carros', 22, 'Chevrolet', 7328, 'Onix', '2020-1', 'Onix 1.0', 2020, 'Flex', '1.0', 'Hatch'),
            ('carros', 26, 'Ford', 5035, 'Ka', '2020-1', 'Ka 1.0', 2020, 'Flex', '1.0', 'Hatch'),
            ('motos', 26, 'Honda', 1446, 'CG 160', '2020-1', 'CG 160 Titan', 2020, 'Gasolina', '160cc', 'Street'),
            ('motos', 52, 'Yamaha', 2467, 'Factor 125', '2020-1', 'Factor 125i', 2020, 'Gasolina', '125cc', 'Street'),
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
                
                conn.commit()
                total_inseridos += 1
                
            except Exception as e:
                conn.rollback()
                print(f"Erro ao inserir: {e}")
                continue
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'Cache básico populado com {total_inseridos} registros',
            'total_inseridos': total_inseridos
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# Rota de debug detalhado
@app.route('/admin/debug-inserir')
@login_required
def debug_inserir():
    """Debug detalhado da inserção"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        debug_info = {
            'step1_conexao': 'OK',
            'step2_tabela_existe': False,
            'step3_estrutura': [],
            'step4_teste_insert': {},
            'step5_count_atual': 0
        }
        
        # Verificar se tabela existe
        cursor.execute("""
            SELECT EXISTS (
                SELECT 1 FROM information_schema.tables 
                WHERE table_name = 'integrador'
            )
        """)
        debug_info['step2_tabela_existe'] = cursor.fetchone()[0]
        
        if debug_info['step2_tabela_existe']:
            # Verificar estrutura da tabela
            cursor.execute("""
                SELECT column_name, data_type, is_nullable 
                FROM information_schema.columns 
                WHERE table_name = 'integrador'
                ORDER BY ordinal_position
            """)
            debug_info['step3_estrutura'] = cursor.fetchall()
            
            # Contar registros atuais
            cursor.execute('SELECT COUNT(*) FROM integrador')
            debug_info['step5_count_atual'] = cursor.fetchone()[0]
            
            # Teste de inserção individual
            try:
                cursor.execute('''
                    INSERT INTO integrador (
                        tipo, marca_id, marca_nome, modelo_id, modelo_nome,
                        versao_id, versao_nome, ano_modelo, combustivel, motor, categoria
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ''', ('carros', 999, 'TESTE', 999, 'MODELO TESTE', '999-1', 'VERSAO TESTE', 2025, 'FLEX', '1.0', 'TESTE'))
                
                conn.commit()
                debug_info['step4_teste_insert'] = {'success': True, 'error': None}
                
                # Contar novamente
                cursor.execute('SELECT COUNT(*) FROM integrador')
                debug_info['step5_count_final'] = cursor.fetchone()[0]
                
            except Exception as e:
                conn.rollback()
                debug_info['step4_teste_insert'] = {'success': False, 'error': str(e)}
        
        cursor.close()
        conn.close()
        
        return jsonify(debug_info)
        
    except Exception as e:
        return jsonify({'error_geral': str(e)})

@app.route('/admin/criar-tabela')
@login_required
def criar_tabela():
    """Força criação da tabela integrador"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Dropar tabela se existir (cuidado!)
        cursor.execute('DROP TABLE IF EXISTS integrador CASCADE')
        
        # Criar tabela do zero
        cursor.execute('''
            CREATE TABLE integrador (
                id SERIAL PRIMARY KEY,
                tipo VARCHAR(10) NOT NULL,
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Inserir dados de teste
        cursor.execute('''
            INSERT INTO integrador (
                tipo, marca_id, marca_nome, modelo_id, modelo_nome,
                versao_id, versao_nome, ano_modelo, combustivel, motor, categoria
            ) VALUES 
            ('carros', 59, 'Volkswagen', 5940, 'Gol', '2020-1', 'Gol 1.0', 2020, 'Flex', '1.0', 'Hatch'),
            ('carros', 22, 'Chevrolet', 7328, 'Onix', '2020-1', 'Onix 1.0', 2020, 'Flex', '1.0', 'Hatch'),
            ('carros', 26, 'Ford', 5035, 'Ka', '2020-1', 'Ka 1.0', 2020, 'Flex', '1.0', 'Hatch'),
            ('motos', 26, 'Honda', 1446, 'CG 160', '2020-1', 'CG 160 Titan', 2020, 'Gasolina', '160cc', 'Street'),
            ('motos', 52, 'Yamaha', 2467, 'Factor 125', '2020-1', 'Factor 125i', 2020, 'Gasolina', '125cc', 'Street')
        ''')
        
        conn.commit()
        
        # Verificar se inseriu
        cursor.execute('SELECT COUNT(*) FROM integrador')
        total = cursor.fetchone()[0]
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'Tabela recriada e populada com {total} registros',
            'total_inseridos': total
        })
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
@app.route('/xml')
def xml_endpoint():
    try:
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
