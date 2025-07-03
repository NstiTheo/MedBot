import discord
from discord.ext import commands
import asyncio
import logging
from datetime import datetime, timedelta
import os
import json
import sqlite3

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============== CONSTANTES E CONFIGURAÇÕES ==============

# IDs dos canais de voz
CANAIS_VOZ = {
    "🎧・Sala de Espera": 1389792125645885510,
    "🗣️・Recepção": 1389792153718489269,
    "🩺・Triagem": 1389792175163969626,
    "🚑・Atendimento": 1389792201311125524,
    "📢・Reunião de Equipe": 1389792233548415047,
    "🎓・Treinamento": 1389792257489637377
}

# IDs dos canais de texto
CANAIS_TEXTO = {
    "logs-de-inscrição": 1389792394685186108,
    "verificação": 1389791314236932207,
    "suporte-hospitalar": 1389791338580410410,
    "formulário-de-inscrição": 1389791381425487873,
    "acompanhar-inscrição": 1389791407819980800,
    "entrevistas-agendadas": 1389791431010418778
}

# IDs dos cargos
CARGOS = {
    "Visitante": 1390158085808586752,
    "Médico": 1389789893181444116
}

# Arquivo para persistência dos dados de tempo em call
DADOS_TEMPO_FILE = "dados_tempo_call.json"

# ============== NOVO SISTEMA DE RASTREAMENTO DE CHAMADAS ==============

class CallTracker:
    """Sistema completo de rastreamento de chamadas de voz"""

    def __init__(self):
        self.db_path = "call_tracker.db"
        self.usuarios_ativos = {}  # {user_id: {'entrada': datetime, 'canal': str}}
        self.init_database()
        self.carregar_usuarios_ativos()

    def init_database(self):
        """Inicializa o banco de dados SQLite"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Tabela para sessões de call
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS call_sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    user_name TEXT NOT NULL,
                    canal TEXT NOT NULL,
                    entrada DATETIME NOT NULL,
                    saida DATETIME,
                    duracao_segundos INTEGER,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Tabela para estatísticas agregadas
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS call_stats (
                    user_id TEXT PRIMARY KEY,
                    user_name TEXT NOT NULL,
                    total_segundos INTEGER DEFAULT 0,
                    total_sessoes INTEGER DEFAULT 0,
                    primeira_call DATETIME,
                    ultima_call DATETIME,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            conn.commit()
            conn.close()
            logger.info("Banco de dados inicializado com sucesso")

        except Exception as e:
            logger.error(f"Erro ao inicializar banco de dados: {e}")

    def carregar_usuarios_ativos(self):
        """Carrega usuários que estavam em call na última execução"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Busca sessões não finalizadas
            cursor.execute('''
                SELECT user_id, user_name, canal, entrada 
                FROM call_sessions 
                WHERE saida IS NULL
            ''')

            for row in cursor.fetchall():
                user_id, user_name, canal, entrada_str = row
                entrada = datetime.fromisoformat(entrada_str)
                self.usuarios_ativos[int(user_id)] = {
                    'entrada': entrada,
                    'canal': canal,
                    'user_name': user_name
                }

            conn.close()
            logger.info(f"Carregados {len(self.usuarios_ativos)} usuários ativos")

        except Exception as e:
            logger.error(f"Erro ao carregar usuários ativos: {e}")

    def registrar_entrada(self, user_id, user_name, canal):
        """Registra entrada de usuário em canal de voz"""
        try:
            entrada = datetime.now()

            # Adiciona aos usuários ativos
            self.usuarios_ativos[user_id] = {
                'entrada': entrada,
                'canal': canal,
                'user_name': user_name
            }

            # Registra no banco
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                INSERT INTO call_sessions (user_id, user_name, canal, entrada)
                VALUES (?, ?, ?, ?)
            ''', (str(user_id), user_name, canal, entrada.isoformat()))

            conn.commit()
            conn.close()

            logger.info(f"🔊 {user_name} entrou no canal {canal}")

        except Exception as e:
            logger.error(f"Erro ao registrar entrada: {e}")

    def registrar_saida(self, user_id, user_name, canal):
        """Registra saída de usuário e calcula duração"""
        try:
            if user_id not in self.usuarios_ativos:
                logger.warning(f"Usuário {user_name} saiu sem entrada registrada")
                return 0

            dados_entrada = self.usuarios_ativos.pop(user_id)
            entrada = dados_entrada['entrada']
            saida = datetime.now()
            duracao = int((saida - entrada).total_seconds())

            # Atualiza no banco
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Atualiza a sessão
            cursor.execute('''
                UPDATE call_sessions 
                SET saida = ?, duracao_segundos = ?
                WHERE id = (
                    SELECT id FROM call_sessions
                    WHERE user_id = ? AND saida IS NULL
                    ORDER BY entrada DESC
                    LIMIT 1
                )
            ''', (saida.isoformat(), duracao, str(user_id)))

            # Atualiza estatísticas
            cursor.execute('''
                INSERT OR REPLACE INTO call_stats 
                (user_id, user_name, total_segundos, total_sessoes, primeira_call, ultima_call, updated_at)
                VALUES (
                    ?, ?, 
                    COALESCE((SELECT total_segundos FROM call_stats WHERE user_id = ?), 0) + ?,
                    COALESCE((SELECT total_sessoes FROM call_stats WHERE user_id = ?), 0) + 1,
                    COALESCE((SELECT primeira_call FROM call_stats WHERE user_id = ?), ?),
                    ?, ?
                )
            ''', (str(user_id), user_name, str(user_id), duracao, str(user_id), 
                  str(user_id), entrada.isoformat(), saida.isoformat(), datetime.now().isoformat()))

            conn.commit()
            conn.close()

            logger.info(f"🔇 {user_name} saiu do canal {canal}. Duração: {self.formatar_tempo(duracao)}")
            return duracao

        except Exception as e:
            logger.error(f"Erro ao registrar saída: {e}")
            return 0

    def obter_estatisticas_usuario(self, user_id):
        """Obtém estatísticas completas do usuário"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Busca estatísticas gerais
            cursor.execute('''
                SELECT total_segundos, total_sessoes, primeira_call, ultima_call
                FROM call_stats
                WHERE user_id = ?
            ''', (str(user_id),))

            result = cursor.fetchone()
            if not result:
                conn.close()
                return None

            total_segundos, total_sessoes, primeira_call, ultima_call = result

            # Busca última sessão
            cursor.execute('''
                SELECT canal, entrada, saida, duracao_segundos
                FROM call_sessions
                WHERE user_id = ? AND saida IS NOT NULL
                ORDER BY entrada DESC
                LIMIT 1
            ''', (str(user_id),))

            ultima_sessao = cursor.fetchone()

            conn.close()

            # Calcula média
            media_segundos = total_segundos / total_sessoes if total_sessoes > 0 else 0

            return {
                'total_segundos': total_segundos,
                'total_sessoes': total_sessoes,
                'media_segundos': media_segundos,
                'primeira_call': datetime.fromisoformat(primeira_call) if primeira_call else None,
                'ultima_call': datetime.fromisoformat(ultima_call) if ultima_call else None,
                'ultima_sessao': ultima_sessao,
                'em_call': user_id in self.usuarios_ativos
            }

        except Exception as e:
            logger.error(f"Erro ao obter estatísticas: {e}")
            return None

    def obter_ranking(self, limite=10):
        """Obtém ranking dos usuários mais ativos"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                SELECT user_id, user_name, total_segundos, total_sessoes, ultima_call
                FROM call_stats
                ORDER BY total_segundos DESC
                LIMIT ?
            ''', (limite,))

            ranking = []
            for row in cursor.fetchall():
                user_id, user_name, total_segundos, total_sessoes, ultima_call = row
                ranking.append({
                    'user_id': int(user_id),
                    'user_name': user_name,
                    'total_segundos': total_segundos,
                    'total_sessoes': total_sessoes,
                    'ultima_call': datetime.fromisoformat(ultima_call) if ultima_call else None
                })

            conn.close()
            return ranking

        except Exception as e:
            logger.error(f"Erro ao obter ranking: {e}")
            return []

    def obter_tempo_atual(self, user_id):
        """Obtém tempo da sessão atual se usuário estiver em call"""
        if user_id not in self.usuarios_ativos:
            return None

        entrada = self.usuarios_ativos[user_id]['entrada']
        tempo_atual = int((datetime.now() - entrada).total_seconds())
        return tempo_atual

    def formatar_tempo(self, segundos):
        """Formata tempo em segundos para formato legível"""
        if segundos < 60:
            return f"{segundos}s"
        elif segundos < 3600:
            mins = segundos // 60
            secs = segundos % 60
            return f"{mins}m {secs}s"
        else:
            hours = segundos // 3600
            mins = (segundos % 3600) // 60
            secs = segundos % 60
            return f"{hours}h {mins}m {secs}s"

    def recuperar_usuarios_em_call(self, bot):
        """Recupera usuários em call após reinicialização"""
        try:
            for guild in bot.guilds:
                for channel in guild.voice_channels:
                    for member in channel.members:
                        if member.id not in self.usuarios_ativos:
                            self.registrar_entrada(member.id, member.display_name, channel.name)
                            logger.info(f"Recuperado: {member.display_name} em {channel.name}")
        except Exception as e:
            logger.error(f"Erro ao recuperar usuários: {e}")

# ============== SISTEMA DE TEMPO EM CALL (MANTIDO PARA COMPATIBILIDADE) ==============

class SistemaTempoCall:
    """Sistema para gerenciar tempo de usuários em calls de voz"""

    def __init__(self):
        self.usuarios_ativos = {}  # {user_id: datetime_entrada}
        self.dados_tempo = {}      # {user_id: {total_segundos, historico}}
        self.carregar_dados()

    def carregar_dados(self):
        """Carrega dados salvos do arquivo JSON"""
        try:
            if os.path.exists(DADOS_TEMPO_FILE):
                with open(DADOS_TEMPO_FILE, 'r', encoding='utf-8') as f:
                    self.dados_tempo = json.load(f)
                logger.info("Dados de tempo em call carregados com sucesso")
            else:
                logger.info("Arquivo de dados não encontrado, iniciando com dados vazios")
        except Exception as e:
            logger.error(f"Erro ao carregar dados de tempo: {e}")
            self.dados_tempo = {}

    def salvar_dados(self):
        """Salva dados no arquivo JSON"""
        try:
            with open(DADOS_TEMPO_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.dados_tempo, f, ensure_ascii=False, indent=2)
            logger.info("Dados de tempo em call salvos com sucesso")
        except Exception as e:
            logger.error(f"Erro ao salvar dados de tempo: {e}")

    def registrar_entrada(self, user_id, canal_nome):
        """Registra entrada de usuário em canal de voz"""
        agora = datetime.now()
        self.usuarios_ativos[user_id] = agora

        # Inicializa dados do usuário se não existir
        if str(user_id) not in self.dados_tempo:
            self.dados_tempo[str(user_id)] = {
                "total_segundos": 0,
                "historico": []
            }

        logger.info(f"Usuário {user_id} entrou no canal {canal_nome} às {agora.strftime('%H:%M:%S')}")

    def registrar_saida(self, user_id, canal_nome):
        """Registra saída de usuário e calcula tempo da sessão"""
        if user_id not in self.usuarios_ativos:
            logger.warning(f"Usuário {user_id} saiu sem entrada registrada")
            return 0

        agora = datetime.now()
        entrada = self.usuarios_ativos.pop(user_id)
        tempo_sessao = (agora - entrada).total_seconds()

        # Atualiza dados do usuário
        user_data = self.dados_tempo[str(user_id)]
        user_data["total_segundos"] += tempo_sessao
        user_data["historico"].append({
            "entrada": entrada.isoformat(),
            "saida": agora.isoformat(),
            "canal": canal_nome,
            "duracao_segundos": tempo_sessao
        })

        # Salva dados automaticamente
        self.salvar_dados()

        logger.info(f"Usuário {user_id} saiu do canal {canal_nome}. Tempo da sessão: {self.formatar_tempo(tempo_sessao)}")
        return tempo_sessao

    def obter_tempo_total(self, user_id):
        """Obtém tempo total acumulado do usuário"""
        if str(user_id) not in self.dados_tempo:
            return 0
        return self.dados_tempo[str(user_id)]["total_segundos"]

    def obter_tempo_atual(self, user_id):
        """Obtém tempo da sessão atual (se em call)"""
        if user_id not in self.usuarios_ativos:
            return None, None

        entrada = self.usuarios_ativos[user_id]
        tempo_atual = (datetime.now() - entrada).total_seconds()
        return entrada, tempo_atual

    def esta_em_call(self, user_id):
        """Verifica se usuário está em call no momento"""
        return user_id in self.usuarios_ativos

    def formatar_tempo(self, segundos):
        """Formata tempo em segundos para formato legível"""
        if segundos < 60:
            return f"{int(segundos)}s"
        elif segundos < 3600:
            mins = int(segundos // 60)
            secs = int(segundos % 60)
            return f"{mins}m {secs}s"
        else:
            hours = int(segundos // 3600)
            mins = int((segundos % 3600) // 60)
            secs = int(segundos % 60)
            return f"{hours}h {mins}m {secs}s"

    def recuperar_usuarios_ativos(self, bot):
        """Recupera usuários que estavam em call quando o bot foi reiniciado"""
        try:
            for guild in bot.guilds:
                for channel in guild.voice_channels:
                    for member in channel.members:
                        if member.id not in self.usuarios_ativos:
                            self.registrar_entrada(member.id, channel.name)
                            logger.info(f"Recuperado usuário {member.name} em {channel.name}")
        except Exception as e:
            logger.error(f"Erro ao recuperar usuários ativos: {e}")

# Instâncias globais dos sistemas
sistema_tempo = SistemaTempoCall()
call_tracker = CallTracker()  # NOVO SISTEMA

# Configuração dos intents (permissões do bot)
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

# Inicialização do bot
bot = commands.Bot(command_prefix='!', intents=intents)

# ============== EVENTOS ==============

@bot.event
async def on_ready():
    """Evento executado quando o bot se conecta ao Discord"""
    logger.info(f'{bot.user} está online!')
    logger.info(f'Bot conectado em {len(bot.guilds)} servidor(es)')

    # Recupera usuários que estavam em call antes do reinício
    sistema_tempo.recuperar_usuarios_ativos(bot)
    call_tracker.recuperar_usuarios_em_call(bot)  # NOVO

    # Ativa o status do bot
    await bot.change_presence(
        activity=discord.Activity(type=discord.ActivityType.watching, name="novos membros e calls!")
    )

@bot.event
async def on_member_join(member):
    """Evento executado quando um membro entra no servidor"""
    try:
        # Procura por canal de boas-vindas
        welcome_channel = None
        for channel in member.guild.channels:
            if channel.name in ['boas-vindas', 'welcome', 'geral', 'general']:
                welcome_channel = channel
                break

        if welcome_channel:
            # Embed de boas-vindas
            embed = discord.Embed(
                title="🎉 Bem-vindo(a)!",
                description=f"Olá {member.mention}! Seja bem-vindo(a) ao **{member.guild.name}**!",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )
            embed.add_field(
                name="📋 Próximos passos:",
                value="• Leia as regras do servidor\n• Complete a verificação se necessário\n• Apresente-se para a comunidade!",
                inline=False
            )
            embed.set_thumbnail(url=member.avatar.url if member.avatar else member.default_avatar.url)
            embed.set_footer(text=f"Membro #{member.guild.member_count}")

            await welcome_channel.send(embed=embed)
            logger.info(f"Mensagem de boas-vindas enviada para {member.name}")

    except Exception as e:
        logger.error(f"Erro ao enviar boas-vindas para {member.name}: {e}")

@bot.event
async def on_voice_state_update(member, before, after):
    """Evento executado quando há mudanças no estado de voz dos membros"""
    try:
        # Entrada em canal de voz
        if before.channel is None and after.channel is not None:
            logger.info(f"🔊 {member.name} entrou no canal de voz: {after.channel.name}")
            # Registra entrada no sistema de tempo (MANTIDO)
            sistema_tempo.registrar_entrada(member.id, after.channel.name)
            # Registra entrada no novo sistema (NOVO)
            call_tracker.registrar_entrada(member.id, member.display_name, after.channel.name)

        # Saída de canal de voz
        elif before.channel is not None and after.channel is None:
            logger.info(f"🔇 {member.name} saiu do canal de voz: {before.channel.name}")
            # Registra saída e calcula tempo da sessão (MANTIDO)
            tempo_sessao = sistema_tempo.registrar_saida(member.id, before.channel.name)
            # Registra saída no novo sistema (NOVO)
            call_tracker.registrar_saida(member.id, member.display_name, before.channel.name)

        # Mudança entre canais de voz
        elif before.channel != after.channel and before.channel is not None and after.channel is not None:
            logger.info(f"🔄 {member.name} mudou de {before.channel.name} para {after.channel.name}")
            # Registra saída do canal anterior e entrada no novo (MANTIDO)
            sistema_tempo.registrar_saida(member.id, before.channel.name)
            sistema_tempo.registrar_entrada(member.id, after.channel.name)
            # Registra mudança no novo sistema (NOVO)
            call_tracker.registrar_saida(member.id, member.display_name, before.channel.name)
            call_tracker.registrar_entrada(member.id, member.display_name, after.channel.name)

    except Exception as e:
        logger.error(f"Erro no sistema de tempo em call: {e}")

# ============== COMANDOS ORIGINAIS (MANTIDOS) ==============

@bot.command(name='ping')
async def ping(ctx):
    """Comando para verificar a latência do bot"""
    latency = round(bot.latency * 1000)

    embed = discord.Embed(
        title="🏓 Pong!",
        description=f"Latência: **{latency}ms**",
        color=discord.Color.blue()
    )

    await ctx.send(embed=embed)
    logger.info(f"Comando ping executado por {ctx.author.name}")

@bot.command(name='tempo')
async def tempo(ctx):
    """Comando para mostrar a hora atual"""
    now = datetime.now()
    time_formatted = now.strftime("%d/%m/%Y às %H:%M:%S")

    embed = discord.Embed(
        title="🕐 Hora Atual",
        description=f"**{time_formatted}**",
        color=discord.Color.gold(),
        timestamp=now
    )

    await ctx.send(embed=embed)
    logger.info(f"Comando tempo executado por {ctx.author.name}")

@bot.command(name='verificar')
async def verificar(ctx):
    """Comando para iniciar o sistema de verificação"""
    # Cria o embed de verificação
    embed = discord.Embed(
        title="✅ Sistema de Verificação Hospitalar",
        description="Para acessar o servidor, você precisa se verificar preenchendo o formulário abaixo.",
        color=discord.Color.green()
    )
    embed.add_field(
        name="📋 Informações necessárias:",
        value="• **Nome completo** (máx. 50 caracteres)\n• **ID** (5 dígitos numéricos)\n• **Telefone** (formato: 000-000)\n• **Tipo de acesso** (Visitante ou Médico)",
        inline=False
    )
    embed.add_field(
        name="⚡ Após a verificação:",
        value="• Seu apelido será alterado para `Nome | ID`\n• Você receberá o cargo apropriado\n• Terá acesso aos canais do servidor",
        inline=False
    )
    embed.add_field(
        name="📌 Importante:",
        value="Certifique-se de preencher todas as informações corretamente antes de enviar o formulário.",
        inline=False
    )
    embed.set_footer(text="Sistema de Verificação • Clique no botão abaixo para começar")

    # Cria a view com o botão
    view = VerificationView()

    await ctx.send(embed=embed, view=view)
    logger.info(f"Sistema de verificação iniciado por {ctx.author.name}")

@bot.command(name='pontototal')
async def pontototal(ctx):
    """Comando para verificar tempo total acumulado em calls"""
    try:
        user_id = ctx.author.id

        # Obtém tempo total acumulado
        tempo_total = sistema_tempo.obter_tempo_total(user_id)

        # Verifica se está em call atualmente
        entrada_atual, tempo_atual = sistema_tempo.obter_tempo_atual(user_id)

        # Cria embed com informações
        embed = discord.Embed(
            title="⏱️ Tempo Total em Calls",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )

        embed.add_field(
            name="📊 Tempo Total Acumulado",
            value=f"**{sistema_tempo.formatar_tempo(tempo_total)}**",
            inline=False
        )

        if entrada_atual:
            # Usuário está em call
            embed.add_field(
                name="🔊 Status Atual",
                value=f"**Em call** desde {entrada_atual.strftime('%d/%m/%Y às %H:%M:%S')}\n"
                      f"Tempo da sessão atual: **{sistema_tempo.formatar_tempo(tempo_atual)}**",
                inline=False
            )
            embed.color = discord.Color.green()
        else:
            # Usuário não está em call
            embed.add_field(
                name="🔇 Status Atual",
                value="**Não está em call no momento**",
                inline=False
            )

        # Adiciona informações do usuário
        embed.set_author(
            name=f"Relatório de {ctx.author.display_name}",
            icon_url=ctx.author.avatar.url if ctx.author.avatar else ctx.author.default_avatar.url
        )
        embed.set_footer(text="Sistema de Pontos por Call")

        await ctx.send(embed=embed)
        logger.info(f"Comando pontototal executado por {ctx.author.name}")

    except Exception as e:
        logger.error(f"Erro no comando pontototal: {e}")
        await ctx.send("❌ Ocorreu um erro ao obter suas informações de tempo!")

# ============== NOVOS COMANDOS DE RASTREAMENTO DE CHAMADAS ==============

@bot.command(name='minhachamada')
async def minha_chamada(ctx):
    """Comando individual para consultar estatísticas pessoais de calls"""
    try:
        user_id = ctx.author.id
        stats = call_tracker.obter_estatisticas_usuario(user_id)

        if not stats:
            embed = discord.Embed(
                title="📊 Suas Estatísticas de Calls",
                description="Você ainda não possui histórico de calls registradas.",
                color=discord.Color.orange()
            )
            embed.set_author(
                name=ctx.author.display_name,
                icon_url=ctx.author.avatar.url if ctx.author.avatar else ctx.author.default_avatar.url
            )
            await ctx.send(embed=embed)
            return

        # Cria embed com estatísticas
        embed = discord.Embed(
            title="📊 Suas Estatísticas de Calls",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )

        # Tempo total
        embed.add_field(
            name="⏱️ Tempo Total em Calls",
            value=f"**{call_tracker.formatar_tempo(stats['total_segundos'])}**",
            inline=True
        )

        # Quantidade de sessões
        embed.add_field(
            name="🎙️ Total de Sessões",
            value=f"**{stats['total_sessoes']}**",
            inline=True
        )

        # Média por sessão
        embed.add_field(
            name="📈 Média por Sessão",
            value=f"**{call_tracker.formatar_tempo(stats['media_segundos'])}**",
            inline=True
        )

        # Status atual
        tempo_atual = call_tracker.obter_tempo_atual(user_id)
        if tempo_atual:
            embed.add_field(
                name="🔊 Status Atual",
                value=f"**Em call agora!**\nTempo da sessão atual: **{call_tracker.formatar_tempo(tempo_atual)}**",
                inline=False
            )
            embed.color = discord.Color.green()
        else:
            embed.add_field(
                name="🔇 Status Atual",
                value="**Não está em call no momento**",
                inline=False
            )

        # Última call
        if stats['ultima_call']:
            embed.add_field(
                name="📅 Última Call",
                value=f"**{stats['ultima_call'].strftime('%d/%m/%Y às %H:%M')}**",
                inline=True
            )

# Primeira call
        if stats['primeira_call']:
            embed.add_field(
                name="🔹 Primeira Call",
                value=f"**{stats['primeira_call'].strftime('%d/%m/%Y às %H:%M')}**",
                inline=True
            )

        # Adiciona autor
        embed.set_author(
            name=f"Relatório de {ctx.author.display_name}",
            icon_url=ctx.author.avatar.url if ctx.author.avatar else ctx.author.default_avatar.url
        )
        embed.set_footer(text="Sistema de Rastreamento de Calls • Atualizado")

        await ctx.send(embed=embed)
        logger.info(f"Comando minhachamada executado por {ctx.author.name}")

    except Exception as e:
        logger.error(f"Erro no comando minhachamada: {e}")
        await ctx.send("❌ Ocorreu um erro ao obter suas estatísticas de calls!")

@bot.command(name='rankingchamadas')
async def ranking_chamadas(ctx):
    """Comando para mostrar ranking dos usuários mais ativos em calls"""
    try:
        ranking = call_tracker.obter_ranking(10)

        if not ranking:
            embed = discord.Embed(
                title="🏆 Ranking de Calls",
                description="Ainda não há dados de calls registradas no servidor.",
                color=discord.Color.orange()
            )
            await ctx.send(embed=embed)
            return

        # Cria embed principal
        embed = discord.Embed(
            title="🏆 Ranking de Calls - Top 10",
            description="Os usuários mais ativos em chamadas de voz do servidor:",
            color=discord.Color.gold(),
            timestamp=datetime.now()
        )

        # Emojis de medalhas
        medals = ["🥇", "🥈", "🥉"]
        colors = [discord.Color.gold(), discord.Color.from_rgb(192, 192, 192), discord.Color.from_rgb(205, 127, 50)]

        for i, user_data in enumerate(ranking):
            position = i + 1
            medal = medals[i] if i < 3 else f"{position}º"

            # Busca o usuário no servidor
            user = ctx.guild.get_member(user_data['user_id'])
            display_name = user.display_name if user else user_data['user_name']

            # Calcula média por sessão
            media_segundos = user_data['total_segundos'] / user_data['total_sessoes']

            # Formata última call
            ultima_call = "Não registrada"
            if user_data['ultima_call']:
                ultima_call = user_data['ultima_call'].strftime('%d/%m/%Y às %H:%M')

            # Cria campo para cada usuário
            field_value = (
                f"⏱️ **Tempo Total:** {call_tracker.formatar_tempo(user_data['total_segundos'])}\n"
                f"🎙️ **Sessões:** {user_data['total_sessoes']}\n"
                f"📈 **Média:** {call_tracker.formatar_tempo(media_segundos)}\n"
                f"📅 **Última Call:** {ultima_call}"
            )

            embed.add_field(
                name=f"{medal} {display_name}",
                value=field_value,
                inline=True
            )

            # Adiciona separador a cada 3 usuários para melhor visualização
            if position % 3 == 0 and position < len(ranking):
                embed.add_field(name="\u200b", value="\u200b", inline=False)

        # Muda cor do embed baseado no top 3
        if len(ranking) > 0:
            embed.color = colors[0]  # Ouro para o ranking geral

        embed.set_footer(text=f"Ranking atualizado • {len(ranking)} usuários ativos")

        await ctx.send(embed=embed)
        logger.info(f"Comando rankingchamadas executado por {ctx.author.name}")

    except Exception as e:
        logger.error(f"Erro no comando rankingchamadas: {e}")
        await ctx.send("❌ Ocorreu um erro ao obter o ranking de calls!")

@bot.command(name='statscall')
async def stats_call(ctx, member: discord.Member = None):
    """Comando para moderadores consultarem estatísticas de qualquer usuário"""
    try:
        # Se não especificar usuário, mostra do próprio autor
        target_user = member or ctx.author

        # Verifica se o autor tem permissão para ver stats de outros
        if member and not ctx.author.guild_permissions.manage_messages:
            await ctx.send("❌ Você não tem permissão para consultar estatísticas de outros usuários!")
            return

        stats = call_tracker.obter_estatisticas_usuario(target_user.id)

        if not stats:
            embed = discord.Embed(
                title="📊 Estatísticas de Calls",
                description=f"{target_user.display_name} ainda não possui histórico de calls registradas.",
                color=discord.Color.orange()
            )
            embed.set_author(
                name=target_user.display_name,
                icon_url=target_user.avatar.url if target_user.avatar else target_user.default_avatar.url
            )
            await ctx.send(embed=embed)
            return

        # Cria embed detalhado
        embed = discord.Embed(
            title="📊 Estatísticas Detalhadas de Calls",
            color=discord.Color.purple(),
            timestamp=datetime.now()
        )

        # Informações principais
        embed.add_field(
            name="⏱️ Tempo Total",
            value=f"**{call_tracker.formatar_tempo(stats['total_segundos'])}**",
            inline=True
        )

        embed.add_field(
            name="🎙️ Sessões Totais",
            value=f"**{stats['total_sessoes']}**",
            inline=True
        )

        embed.add_field(
            name="📈 Média/Sessão",
            value=f"**{call_tracker.formatar_tempo(stats['media_segundos'])}**",
            inline=True
        )

        # Status atual
        tempo_atual = call_tracker.obter_tempo_atual(target_user.id)
        if tempo_atual:
            canal_info = call_tracker.usuarios_ativos.get(target_user.id, {})
            canal_nome = canal_info.get('canal', 'Canal desconhecido')

            embed.add_field(
                name="🔊 Status Atual",
                value=f"**Em call no canal:** {canal_nome}\n**Tempo da sessão:** {call_tracker.formatar_tempo(tempo_atual)}",
                inline=False
            )
            embed.color = discord.Color.green()
        else:
            embed.add_field(
                name="🔇 Status Atual",
                value="**Offline** - Não está em call no momento",
                inline=False
            )

        # Histórico
        if stats['primeira_call']:
            embed.add_field(
                name="🎯 Primeira Call",
                value=f"**{stats['primeira_call'].strftime('%d/%m/%Y às %H:%M')}**",
                inline=True
            )

        if stats['ultima_call']:
            embed.add_field(
                name="📅 Última Call",
                value=f"**{stats['ultima_call'].strftime('%d/%m/%Y às %H:%M')}**",
                inline=True
            )

        # Última sessão detalhada
        if stats['ultima_sessao']:
            canal, entrada, saida, duracao = stats['ultima_sessao']
            entrada_dt = datetime.fromisoformat(entrada)
            saida_dt = datetime.fromisoformat(saida) if saida else None

            if saida_dt:
                embed.add_field(
                    name="📝 Última Sessão",
                    value=f"**Canal:** {canal}\n**Duração:** {call_tracker.formatar_tempo(duracao)}\n**Data:** {entrada_dt.strftime('%d/%m/%Y às %H:%M')}",
                    inline=False
                )

        # Adiciona autor
        embed.set_author(
            name=f"Relatório de {target_user.display_name}",
            icon_url=target_user.avatar.url if target_user.avatar else target_user.default_avatar.url
        )
        embed.set_footer(text="Sistema Avançado de Rastreamento • Consulta Detalhada")

        await ctx.send(embed=embed)
        logger.info(f"Comando statscall executado por {ctx.author.name} para {target_user.name}")

    except Exception as e:
        logger.error(f"Erro no comando statscall: {e}")
        await ctx.send("❌ Ocorreu um erro ao obter as estatísticas detalhadas!")

@bot.command(name='topcalls')
async def top_calls(ctx):
    """Comando para mostrar estatísticas gerais do servidor"""
    try:
        ranking = call_tracker.obter_ranking(5)  # Top 5 para visão geral

        if not ranking:
            embed = discord.Embed(
                title="📊 Estatísticas Gerais do Servidor",
                description="Ainda não há dados de calls registradas no servidor.",
                color=discord.Color.orange()
            )
            await ctx.send(embed=embed)
            return

        # Calcula estatísticas gerais
        total_segundos_servidor = sum(user['total_segundos'] for user in ranking)
        total_sessoes_servidor = sum(user['total_sessoes'] for user in ranking)
        usuarios_ativos = len([user for user in ranking if user['total_segundos'] > 0])

        # Cria embed
        embed = discord.Embed(
            title="📊 Estatísticas Gerais do Servidor",
            description="Resumo da atividade em calls de voz:",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )

        # Estatísticas gerais
        embed.add_field(
            name="⏱️ Tempo Total do Servidor",
            value=f"**{call_tracker.formatar_tempo(total_segundos_servidor)}**",
            inline=True
        )

        embed.add_field(
            name="🎙️ Sessões Totais",
            value=f"**{total_sessoes_servidor}**",
            inline=True
        )

        embed.add_field(
            name="👥 Usuários Ativos",
            value=f"**{usuarios_ativos}**",
            inline=True
        )

        # Top 5 usuários
        top_users = ""
        for i, user_data in enumerate(ranking):
            medal = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"][i]
            user = ctx.guild.get_member(user_data['user_id'])
            display_name = user.display_name if user else user_data['user_name']

            top_users += f"{medal} **{display_name}** - {call_tracker.formatar_tempo(user_data['total_segundos'])}\n"

        embed.add_field(
            name="🏆 Top 5 Usuários",
            value=top_users,
            inline=False
        )

        # Usuários online em call
        usuarios_online = []
        for user_id, data in call_tracker.usuarios_ativos.items():
            user = ctx.guild.get_member(user_id)
            if user:
                tempo_atual = call_tracker.obter_tempo_atual(user_id)
                usuarios_online.append(f"🔊 **{user.display_name}** - {call_tracker.formatar_tempo(tempo_atual)} ({data['canal']})")

        if usuarios_online:
            embed.add_field(
                name="🔊 Usuários Online em Call",
                value="\n".join(usuarios_online[:5]),  # Máximo 5 para não poluir
                inline=False
            )
        else:
            embed.add_field(
                name="🔇 Usuários Online em Call",
                value="Nenhum usuário em call no momento",
                inline=False
            )

        embed.set_footer(text=f"Estatísticas do Servidor • {ctx.guild.name}")

        await ctx.send(embed=embed)
        logger.info(f"Comando topcalls executado por {ctx.author.name}")

    except Exception as e:
        logger.error(f"Erro no comando topcalls: {e}")
        await ctx.send("❌ Ocorreu um erro ao obter as estatísticas do servidor!")

# ============== SISTEMA DE VERIFICAÇÃO (MANTIDO INTOCADO) ==============

class VerificationModal(discord.ui.Modal):
    """Modal para coleta de informações de verificação"""

    def __init__(self):
        super().__init__(title="Verificação Hospitalar")

        # Campo nome
        self.nome = discord.ui.TextInput(
            label="Nome Completo",
            placeholder="Digite seu nome completo...",
            required=True,
            max_length=50
        )
        self.add_item(self.nome)

        # Campo ID
        self.id_usuario = discord.ui.TextInput(
            label="ID (5 dígitos)",
            placeholder="Ex: 12345",
            required=True,
            min_length=5,
            max_length=5
        )
        self.add_item(self.id_usuario)

        # Campo telefone
        self.telefone = discord.ui.TextInput(
            label="Telefone",
            placeholder="Ex: 123-456",
            required=True,
            min_length=7,
            max_length=7
        )
        self.add_item(self.telefone)

        # Campo tipo de acesso
        self.tipo_acesso = discord.ui.TextInput(
            label="Tipo de Acesso",
            placeholder="Digite: Visitante ou Médico",
            required=True,
            max_length=15
        )
        self.add_item(self.tipo_acesso)

    async def on_submit(self, interaction: discord.Interaction):
        """Processa o formulário de verificação"""
        try:
            # Valida ID (apenas números)
            if not self.id_usuario.value.isdigit():
                await interaction.response.send_message("❌ ID deve conter apenas números!", ephemeral=True)
                return

            # Valida telefone (formato XXX-XXX)
            if not self.telefone.value.count('-') == 1:
                await interaction.response.send_message("❌ Telefone deve estar no formato XXX-XXX!", ephemeral=True)
                return

            # Valida tipo de acesso
            tipo_valido = self.tipo_acesso.value.lower()
            if tipo_valido not in ['visitante', 'médico', 'medico']:
                await interaction.response.send_message("❌ Tipo de acesso deve ser 'Visitante' ou 'Médico'!", ephemeral=True)
                return

            # Normaliza tipo de acesso
            tipo_final = "Médico" if tipo_valido in ['médico', 'medico'] else "Visitante"

            # Cria novo apelido
            novo_apelido = f"{self.nome.value} | {self.id_usuario.value}"

            # Altera apelido do usuário
            try:
                await interaction.user.edit(nick=novo_apelido)
            except discord.Forbidden:
                await interaction.response.send_message("❌ Não tenho permissão para alterar seu apelido!", ephemeral=True)
                return

            # Adiciona cargo
            guild = interaction.guild
            cargo_id = CARGOS.get(tipo_final)

            if cargo_id:
                cargo = guild.get_role(cargo_id)
                if cargo:
                    await interaction.user.add_roles(cargo)
                else:
                    logger.warning(f"Cargo {tipo_final} não encontrado no servidor")

            # Cria embed de confirmação
            embed = discord.Embed(
                title="✅ Verificação Concluída!",
                description=f"Bem-vindo(a) ao sistema hospitalar, **{self.nome.value}**!",
                color=discord.Color.green(),
                timestamp=datetime.now()
            )

            embed.add_field(
                name="📋 Informações Registradas:",
                value=f"**Nome:** {self.nome.value}\n"
                      f"**ID:** {self.id_usuario.value}\n"
                      f"**Telefone:** {self.telefone.value}\n"
                      f"**Tipo de Acesso:** {tipo_final}",
                inline=False
            )

            embed.add_field(
                name="⚡ Alterações Aplicadas:",
                value=f"• Apelido alterado para: `{novo_apelido}`\n"
                      f"• Cargo adicionado: **{tipo_final}**\n"
                      f"• Acesso liberado aos canais do servidor",
                inline=False
            )

            embed.set_footer(text="Sistema de Verificação Hospitalar")
            embed.set_thumbnail(url=interaction.user.avatar.url if interaction.user.avatar else interaction.user.default_avatar.url)

            await interaction.response.send_message(embed=embed, ephemeral=True)

            # Log da verificação
            logger.info(f"Verificação concluída: {self.nome.value} ({self.id_usuario.value}) - {tipo_final}")

            # Envia log para canal de logs se existir
            canal_logs = guild.get_channel(CANAIS_TEXTO.get("logs-de-inscrição"))
            if canal_logs:
                log_embed = discord.Embed(
                    title="📝 Nova Verificação",
                    description=f"Usuário verificado com sucesso",
                    color=discord.Color.blue(),
                    timestamp=datetime.now()
                )
                log_embed.add_field(
                    name="👤 Usuário",
                    value=f"**{interaction.user.mention}**\n`{interaction.user.name}`",
                    inline=True
                )
                log_embed.add_field(
                    name="📋 Dados",
                    value=f"**Nome:** {self.nome.value}\n**ID:** {self.id_usuario.value}\n**Tipo:** {tipo_final}",
                    inline=True
                )
                log_embed.set_thumbnail(url=interaction.user.avatar.url if interaction.user.avatar else interaction.user.default_avatar.url)

                await canal_logs.send(embed=log_embed)

        except Exception as e:
            logger.error(f"Erro na verificação: {e}")
            await interaction.response.send_message("❌ Ocorreu um erro durante a verificação. Tente novamente!", ephemeral=True)

class VerificationView(discord.ui.View):
    """View com botão para iniciar verificação"""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Iniciar Verificação", style=discord.ButtonStyle.green, emoji="✅")
    async def start_verification(self, interaction: discord.Interaction, button: discord.ui.Button):
        """Inicia o processo de verificação"""
        modal = VerificationModal()
        await interaction.response.send_modal(modal)

# ==================== EXECUÇÃO ====================

async def main():
    """Função principal para iniciar o bot"""
    try:
        TOKEN = os.getenv ("DISCORD_TOKEN")

        if TOKEN == "DISCORD_TOKEN":
            logger.error("❌ Token do bot não configurado! Edite o código e adicione seu token.")
            return

        await bot.start(TOKEN)

    except discord.LoginFailure:
        logger.error("❌ Token inválido! Verifique se o token está correto.")
    except discord.HTTPException as e:
        logger.error(f"❌ Erro HTTP: {e}")
    except Exception as e:
        logger.error(f"❌ Erro inesperado: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Bot interrompido pelo usuário")
    except Exception as e:
        logger.error(f"❌ Erro fatal: {e}")
    finally:
        print("Bot finalizado.")
