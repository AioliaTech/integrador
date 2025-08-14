#!/bin/bash

echo "🚗 Configurando Integrador de Veículos..."

# Criar diretórios
echo "📁 Criando estrutura de diretórios..."
mkdir -p templates static/css static/js static/images

# Criar arquivo de dependências
echo "📦 Criando requirements.txt..."
cat > requirements.txt << 'EOF'
Flask==2.3.3
psycopg2-binary==2.9.7
boto3==1.28.17
requests==2.31.0
Werkzeug==2.3.7
python-dotenv==1.0.0
EOF

# Criar arquivo de ambiente
echo "🔧 Criando arquivo .env..."
cat > .env << 'EOF'
# Configurações do Banco de Dados
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
BLAZE_BUCKET_NAME=seu_bucket_name
EOF

# Criar Dockerfile
echo "🐳 Criando Dockerfile..."
cat > Dockerfile << 'EOF'
FROM python:3.11-slim

WORKDIR /app

# Instalar dependências do sistema
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000

CMD ["python", "app.py"]
EOF

# Criar docker-compose.yml
echo "🔄 Criando docker-compose.yml..."
cat > docker-compose.yml << 'EOF'
version: '3.8'

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
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 30s
      timeout: 10s
      retries: 3

  app:
    build: .
    ports:
      - "5000:5000"
    environment:
      - DB_HOST=postgres
      - DB_NAME=integrador
      - DB_USER=postgres
      - DB_PASSWORD=password
      - AUTH_USERNAME=admin
      - AUTH_PASSWORD=admin123
      - SECRET_KEY=desenvolvimento_secret_key
      - CLIENT_TABLE=integrador_cliente01
    depends_on:
      postgres:
        condition: service_healthy
    volumes:
      - .:/app
    restart: unless-stopped

volumes:
  postgres_data:
EOF

# Criar .gitignore
echo "🚫 Criando .gitignore..."
cat > .gitignore << 'EOF'
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Ambiente
.env
.venv
venv/
ENV/

# IDE
.vscode/
.idea/
*.swp
*.swo

# Logs
*.log

# Database
*.sqlite3
*.db
EOF

echo "✅ Arquivos de configuração criados!"
echo "📝 Próximos passos:"
echo "1. Edite o arquivo .env com suas credenciais"
echo "2. Execute: pip install -r requirements.txt"
echo "3. Execute: python app.py"
echo "4. Ou use Docker: docker-compose up --build"
echo ""
echo "🚀 Para deploy no EasyPanel:"
echo "1. Faça upload dos arquivos para seu repositório Git"
echo "2. Crie uma nova app no EasyPanel apontando para o repositório"
echo "3. Configure as variáveis de ambiente no EasyPanel"
echo "4. Deploy!"
