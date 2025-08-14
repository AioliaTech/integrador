<!-- No seu dashboard.html, substitua a seção do header por esta: -->

<header class="bg-white shadow-sm border-b sticky top-0 z-40">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div class="flex justify-between items-center py-4">
            <div class="flex items-center">
                <div class="bg-orange rounded-lg p-2 mr-3">
                    <i class="fas fa-car text-white text-xl"></i>
                </div>
                <div>
                    <h1 class="text-xl font-bold text-gray-800">Integrador de Veículos</h1>
                    <span class="text-sm text-gray-medium">{{ client_table }}</span>
                </div>
            </div>
            <div class="flex items-center space-x-3">
                <a href="/admin" 
                   class="bg-purple-500 text-white px-4 py-2 rounded-lg hover:bg-purple-600 transition-all hover-scale flex items-center">
                    <i class="fas fa-cog mr-2"></i>Admin
                </a>
                <a href="/xml" target="_blank" 
                   class="bg-green-500 text-white px-4 py-2 rounded-lg hover:bg-green-600 transition-all hover-scale flex items-center">
                    <i class="fas fa-link mr-2"></i>Endpoint JSON
                </a>
                <a href="{{ url_for('logout') }}" 
                   class="bg-gray-500 text-white px-4 py-2 rounded-lg hover:bg-gray-600 transition-all hover-scale flex items-center">
                    <i class="fas fa-sign-out-alt mr-2"></i>Sair
                </a>
            </div>
        </div>
    </div>
</header>
