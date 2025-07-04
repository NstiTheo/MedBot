import discord
from discord.ext import commands
import asyncio
import logging
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta
import os
import json
import sqlite3
import pytz

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ],
    encoding='utf-8')
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
CARGOS_IDS = {
    "Estagiário": 1389789893181444116,
    "Visitante/Observador": 1390158085808586752
}

# Fuso horário de São Paulo
TZ_SAO_PAULO = pytz.timezone('America/Sao_Paulo')

# Arquivo para persistência dos dados de tempo em call
DADOS_TEMPO_FILE = "dados_tempo_call.json"

# URL do GIF de branding
SP_CAPITAL_GIF_URL = "https://cdn.discordapp.com/attachments/1388624317159440536/1388624464694087700/SP_Capital_GIF.gif"

# ID do canal para logs de plantão
CANAL_CONTROLE_PLANTOES_ID = 1389792336363655168 # sp-capital-controle-de-plantões
CANAL_MODERACAO_ID = 1389792372983992420 # moderação-e-disciplinas

# IDs de Cargos de Punição
CARGO_PUNICAO_1_ID = 1389790132160434227
CARGO_PUNICAO_2_ID = 1389790188452184226

# Estrutura Hierárquica de Cargos
HIERARQUIA_CARGOS = [
    {"nome": "Direção", "id": 1389788983214604338, "emoji": "🎖️"},
    {"nome": "Responsável HP", "id": 1389789535097061426, "emoji": "🛡️"},
    {"nome": "Auxiliar HP", "id": 1389789661769240606, "emoji": "🧰"},
    {"nome": "Diretor", "id": 1389789326287573013, "emoji": "🧠"},
    {"nome": "Vice Diretor", "id": 1389789427542397083, "emoji": "🧪"},
    {"nome": "Paramédico", "id": 1389789708539920517, "emoji": "🚑"},
    {"nome": "Médico", "id": 1389789787325730948, "emoji": "🩺"},
    {"nome": "Enfermeiro", "id": 1389789872134553650, "emoji": "💉"},
    {"nome": "Estagiário", "id": 1389789893181444116, "emoji": "🧪"},
    {"nome": "Visitante/Observador", "id": 1390158085808586752, "emoji": "🧾"}
]

# IDs de Cargos Profissionais (para o comando !setar)
CARGOS_SETAveis_IDS = {
    1389789708539920517, # Paramédico
    1389789787325730948, # Médico
    1389789872134553650  # Enfermeiro
}

# Cores Padrão
COR_PRINCIPAL = discord.Color.dark_red()
COR_VERDE = discord.Color.green()
COR_LARANJA = discord.Color.orange()

# ============== NOVO SISTEMA DE RASTREAMENTO DE CHAMADAS ==============


class CallTracker:
    """Sistema completo de rastreamento de chamadas de voz"""

    def __init__(self):
        self.db_path = "call_tracker.db"
        self.usuarios_ativos = {
        }  # {user_id: {'entrada': datetime, 'canal': str}}
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
            logger.info(
                f"Carregados {len(self.usuarios_ativos)} usuários ativos")

        except Exception as e:
            logger.error(f"Erro ao carregar usuários ativos: {e}")

    def registrar_entrada(self, user_id, user_name, canal):
        """Registra entrada de usuário em canal de voz"""
        try:
            entrada = datetime.now(TZ_SAO_PAULO)

            # Adiciona aos usuários ativos
            self.usuarios_ativos[user_id] = {
                'entrada': entrada,
                'canal': canal,
                'user_name': user_name
            }

            # Registra no banco
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute(
                '''
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
                logger.warning(
                    f"Usuário {user_name} saiu sem entrada registrada")
                return 0

            dados_entrada = self.usuarios_ativos.pop(user_id)
            entrada = dados_entrada['entrada']
            saida = datetime.now(TZ_SAO_PAULO)
            duracao = int((saida - entrada).total_seconds())

            # Atualiza no banco
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Atualiza a sessão
            cursor.execute(
                '''
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
            cursor.execute(
                '''
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
                  str(user_id), entrada.isoformat(), saida.isoformat(),
                  datetime.now(TZ_SAO_PAULO).isoformat()))

            conn.commit()
            conn.close()

            logger.info(
                f"🔇 {user_name} saiu do canal {canal}. Duração: {self.formatar_tempo(duracao)}"
            )
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
            cursor.execute(
                '''
                SELECT total_segundos, total_sessoes, primeira_call, ultima_call
                FROM call_stats
                WHERE user_id = ?
            ''', (str(user_id), ))

            result = cursor.fetchone()
            if not result:
                conn.close()
                return None

            total_segundos, total_sessoes, primeira_call, ultima_call = result

            # Busca última sessão
            cursor.execute(
                '''
                SELECT canal, entrada, saida, duracao_segundos
                FROM call_sessions
                WHERE user_id = ? AND saida IS NOT NULL
                ORDER BY entrada DESC
                LIMIT 1
            ''', (str(user_id), ))

            ultima_sessao = cursor.fetchone()

            conn.close()

            # Calcula média
            media_segundos = total_segundos / total_sessoes if total_sessoes > 0 else 0

            return {
                'total_segundos':
                total_segundos,
                'total_sessoes':
                total_sessoes,
                'media_segundos':
                media_segundos,
                'primeira_call':
                datetime.fromisoformat(primeira_call)
                if primeira_call else None,
                'ultima_call':
                datetime.fromisoformat(ultima_call) if ultima_call else None,
                'ultima_sessao':
                ultima_sessao,
                'em_call':
                user_id in self.usuarios_ativos
            }

        except Exception as e:
            logger.error(f"Erro ao obter estatísticas: {e}")
            return None

    def obter_ranking(self, limite=10):
        """Obtém ranking dos usuários mais ativos"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute(
                '''
                SELECT user_id, user_name, total_segundos, total_sessoes, ultima_call
                FROM call_stats
                ORDER BY total_segundos DESC
                LIMIT ?
            ''', (limite, ))

            ranking = []
            for row in cursor.fetchall():
                user_id, user_name, total_segundos, total_sessoes, ultima_call = row
                ranking.append({
                    'user_id':
                    int(user_id),
                    'user_name':
                    user_name,
                    'total_segundos':
                    total_segundos,
                    'total_sessoes':
                    total_sessoes,
                    'ultima_call':
                    datetime.fromisoformat(ultima_call)
                    if ultima_call else None
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
        tempo_atual = int(
            (datetime.now(TZ_SAO_PAULO) - entrada).total_seconds())
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

    def formatar_tempo_hhmmss(self, segundos):
        """Formata segundos para o formato HH:MM:SS."""
        segundos = int(segundos)
        horas = segundos // 3600
        minutos = (segundos % 3600) // 60
        segundos_restantes = segundos % 60
        return f"{horas:02}:{minutos:02}:{segundos_restantes:02}"

    def get_user_rank(self, user_id):
        """Obtém a posição de um usuário no ranking."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute('''
                SELECT user_id FROM call_stats ORDER BY total_segundos DESC
            ''')
            ranking = cursor.fetchall()
            conn.close()

            for i, (uid, ) in enumerate(ranking):
                if str(user_id) == uid:
                    return i + 1
            return None
        except Exception as e:
            logger.error(f"Erro ao obter rank do usuário {user_id}: {e}")
            return None

    def reset_user_calls(self, user_id):
        """Apaga todos os registros de chamadas e estatísticas de um usuário."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            # Apaga sessões individuais
            cursor.execute("DELETE FROM call_sessions WHERE user_id = ?", (str(user_id),))
            # Apaga estatísticas agregadas
            cursor.execute("DELETE FROM call_stats WHERE user_id = ?", (str(user_id),))
            conn.commit()
            conn.close()
            logger.info(f"Todos os registros de chamadas e estatísticas para o user_id {user_id} foram apagados.")
            return True
        except sqlite3.Error as e:
            logger.error(f"Erro ao apagar registros para o user_id {user_id}: {e}")
            return False

    def reset_all_calls(self):
        """Apaga TODOS os registros de chamadas e estatísticas do banco de dados."""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM call_sessions")
            cursor.execute("DELETE FROM call_stats")
            cursor.execute("DELETE FROM active_users")
            conn.commit()
            conn.close()
            self.usuarios_ativos.clear()
            logger.info("TODOS os registros de chamadas, estatísticas e usuários ativos foram apagados.")
            return True
        except sqlite3.Error as e:
            logger.error(f"Erro ao apagar todos os registros: {e}")
            return False

    def recuperar_usuarios_em_call(self, bot):
        """Recupera usuários em call após reinicialização"""
        try:
            for guild in bot.guilds:
                for channel in guild.voice_channels:
                    for member in channel.members:
                        if member.id not in self.usuarios_ativos:
                            self.registrar_entrada(member.id,
                                                   member.display_name,
                                                   channel.name)
                            logger.info(
                                f"Recuperado: {member.display_name} em {channel.name}"
                            )
        except Exception as e:
            logger.error(f"Erro ao recuperar usuários: {e}")


# Instância global do novo sistema
call_tracker = CallTracker()  # NOVO SISTEMA

# Configuração dos intents (permissões do bot)
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.voice_states = True

# Inicialização do bot
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# ============== EVENTOS ==============


@bot.event
async def on_ready():
    """Evento executado quando o bot se conecta ao Discord"""
    logger.info(f'{bot.user} está online!')
    logger.info(f'Bot conectado em {len(bot.guilds)} servidor(es)')

    # Recupera usuários que estavam em call antes do reinício
    call_tracker.recuperar_usuarios_em_call(bot)  # NOVO

    # Ativa o status do bot
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, name="novos membros e calls!"))


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
                description=
                f"Olá {member.mention}! Seja bem-vindo(a) ao **{member.guild.name}**!",
                color=discord.Color.green(),
                timestamp=datetime.now(TZ_SAO_PAULO))
            embed.add_field(
                name="📋 Próximos passos:",
                value=
                "• Leia as regras do servidor\n• Complete a verificação se necessário\n• Apresente-se para a comunidade!",
                inline=False)
            embed.add_field(
                name="⚡ Após a verificação:",
                value=
                "• Seu apelido será alterado para `Nome | ID`\n• Você receberá o cargo apropriado\n• Terá acesso aos canais do servidor",
                inline=False)
            embed.add_field(
                name="📌 Importante:",
                value=
                "Certifique-se de preencher todas as informações corretamente antes de enviar o formulário.",
                inline=False)
            embed.set_footer(
                text=
                "Sistema de Verificação • Clique no botão abaixo para começar")
            embed.set_thumbnail(url=SP_CAPITAL_GIF_URL)

            # Cria a view com o botão
            view = VerificationView()

            await welcome_channel.send(embed=embed, view=view)
            logger.info(f"Mensagem de boas-vindas enviada para {member.name}")

    except Exception as e:
        logger.error(f"Erro ao enviar boas-vindas para {member.name}: {e}")


@bot.event
async def on_voice_state_update(member, before, after):
    """Monitora as atividades de voz dos membros e registra no canal de plantão."""
    if member.bot:
        return

    canal_log = bot.get_channel(CANAL_CONTROLE_PLANTOES_ID)
    afk_channel_id = 1388624317159440539  # Certifique-se que este é o ID correto do seu canal AFK

    # Função auxiliar para enviar logs de forma segura
    async def enviar_log(embed):
        if canal_log:
            try:
                await canal_log.send(embed=embed)
            except Exception as e:
                logger.error(f"Falha ao enviar log para o canal de plantão: {e}")

    # Caso 1: Usuário entra em um canal de voz
    if before.channel is None and after.channel is not None:
        if after.channel.id != afk_channel_id:
            call_tracker.registrar_entrada(member.id, member.display_name, after.channel.name)

        embed = discord.Embed(
            description=f"▶️ {member.mention} entrou no canal de voz `{after.channel.name}`.",
            color=COR_VERDE,
            timestamp=datetime.now(TZ_SAO_PAULO)
        ).set_author(name=member.display_name, icon_url=member.display_avatar.url)
        await enviar_log(embed)

    # Caso 2: Usuário sai de um canal de voz
    elif before.channel is not None and after.channel is None:
        if before.channel.id != afk_channel_id:
            call_tracker.registrar_saida(member.id, member.display_name, before.channel.name)

        embed = discord.Embed(
            description=f"⏹️ {member.mention} saiu do canal de voz `{before.channel.name}`.",
            color=COR_PRINCIPAL,
            timestamp=datetime.now(TZ_SAO_PAULO)
        ).set_author(name=member.display_name, icon_url=member.display_avatar.url)
        await enviar_log(embed)

    # Caso 3: Usuário muda de canal de voz
    elif before.channel is not None and after.channel is not None and before.channel != after.channel:
        # Lógica de contagem de tempo com AFK
        # Saiu de um canal válido e foi para o AFK
        if before.channel.id != afk_channel_id and after.channel.id == afk_channel_id:
            call_tracker.registrar_saida(member.id, member.display_name, before.channel.name)
        # Saiu do AFK e foi para um canal válido
        elif before.channel.id == afk_channel_id and after.channel.id != afk_channel_id:
            call_tracker.registrar_entrada(member.id, member.display_name, after.channel.name)
        # Mudou entre dois canais válidos
        elif before.channel.id != afk_channel_id and after.channel.id != afk_channel_id:
            call_tracker.registrar_saida(member.id, member.display_name, before.channel.name)
            call_tracker.registrar_entrada(member.id, member.display_name, after.channel.name)

        embed = discord.Embed(
            description=f"🔄 {member.mention} mudou do canal `{before.channel.name}` para `{after.channel.name}`.",
            color=COR_LARANJA,
            timestamp=datetime.now(TZ_SAO_PAULO)
        ).set_author(name=member.display_name, icon_url=member.display_avatar.url)
        await enviar_log(embed)


# ============== LÓGICA DE PAGINAÇÃO PARA EMBEDS ==============

# Dicionário para traduzir meses
MESES_PT = {
    1: 'janeiro',
    2: 'fevereiro',
    3: 'março',
    4: 'abril',
    5: 'maio',
    6: 'junho',
    7: 'julho',
    8: 'agosto',
    9: 'setembro',
    10: 'outubro',
    11: 'novembro',
    12: 'dezembro'
}


def build_consultar_embed(sessoes_pagina, usuario, pagina_atual, total_paginas, total_segundos_geral, rank):
    """Constrói o embed modernizado para a consulta de histórico de chamadas."""
    embed = discord.Embed(
        title="📜 Histórico de Sessões",
        color=discord.Color.from_rgb(255, 0, 0), # Vermelho
        timestamp=datetime.now(TZ_SAO_PAULO)
    )
    embed.set_author(
        name=f"Relatório de {usuario.display_name}",
        icon_url=usuario.avatar.url if usuario.avatar else usuario.default_avatar.url
    )
    embed.set_thumbnail(url=SP_CAPITAL_GIF_URL)

    # --- Header com Resumo Geral e Ranking ---
    tempo_total_formatado = call_tracker.formatar_tempo_hhmmss(total_segundos_geral)

    rank_badge = ""
    if rank:
        if rank == 1:
            rank_badge = "🥇 **Lenda das Calls**"
        elif rank <= 10:
            rank_badge = f"🏆 **Top {rank}**"
        else:
            rank_badge = f"#{rank}"

    header_text = f"**Tempo Total:** `{tempo_total_formatado}`\n"
    if rank_badge:
        header_text += f"**Ranking:** {rank_badge}"

    embed.add_field(name="📈 Resumo de Performance", value=header_text, inline=False)

    # --- Detalhes das Sessões na Página ---
    if not sessoes_pagina:
        embed.description = "Não há sessões de voz registradas para esta página."
    else:
        lista_sessoes_str = []
        last_date_str = None
        for s in sessoes_pagina:
            entrada = datetime.fromisoformat(s[4]).astimezone(TZ_SAO_PAULO)
            duracao_segundos = s[6] if s[6] is not None else 0
            duracao_formatada = call_tracker.formatar_tempo_hhmmss(duracao_segundos)
            canal_nome = s[3] if s[3] else "N/A"

            nome_mes_pt = MESES_PT[entrada.month]
            current_date_str = entrada.strftime(f'%d de {nome_mes_pt} de %Y')

            if current_date_str != last_date_str:
                if last_date_str is not None:
                    lista_sessoes_str.append("") # Espaço entre dias
                # Adiciona separador de data
                lista_sessoes_str.append(f"**__{current_date_str}__**")
                last_date_str = current_date_str

            hora_formatada = entrada.strftime('%H:%M')

            lista_sessoes_str.append(f"› **`{hora_formatada}`** em `{canal_nome}` | **Duração:** `{duracao_formatada}`")

        embed.description = "\n".join(lista_sessoes_str)

    embed.set_footer(text=f"Página {pagina_atual}/{total_paginas} • Histórico de {usuario.display_name}")
    return embed


class PaginationView(discord.ui.View):
    """View para criar embeds com botões de paginação para o histórico de chamadas."""

    def __init__(self,
                 author: discord.Member,
                 all_sessoes: list,
                 usuario_alvo: discord.Member,
                 total_segundos: int,
                 rank: int,
                 items_per_page: int = 5):
        super().__init__(timeout=180)
        self.author = author
        self.all_sessoes = all_sessoes
        self.usuario_alvo = usuario_alvo
        self.total_segundos = total_segundos
        self.rank = rank
        self.items_per_page = items_per_page
        self.current_page = 1
        self.total_pages = max(
            1, (len(self.all_sessoes) + self.items_per_page - 1) //
            self.items_per_page)
        self.update_buttons()

    async def interaction_check(self,
                                interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "❌ Você não tem permissão para usar estes botões.",
                ephemeral=True)
            return False
        return True

    def get_page_data(self):
        start_index = (self.current_page - 1) * self.items_per_page
        end_index = start_index + self.items_per_page
        return self.all_sessoes[start_index:end_index]

    def update_buttons(self):
        self.children[0].disabled = self.current_page == 1
        self.children[1].disabled = self.current_page == 1
        self.children[3].disabled = self.current_page == self.total_pages
        self.children[4].disabled = self.current_page == self.total_pages
        self.children[
            2].label = f"Página {self.current_page}/{self.total_pages}"

    async def update_embed(self, interaction: discord.Interaction):
        sessoes_pagina = self.get_page_data()
        self.update_buttons()
        embed = build_consultar_embed(sessoes_pagina, self.usuario_alvo,
                                      self.current_page, self.total_pages,
                                      self.total_segundos, self.rank)
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="⏪", style=discord.ButtonStyle.primary, row=0)
    async def first_page(self, interaction: discord.Interaction,
                         button: discord.ui.Button):
        self.current_page = 1
        await self.update_embed(interaction)

    @discord.ui.button(label="⬅️", style=discord.ButtonStyle.secondary, row=0)
    async def prev_page(self, interaction: discord.Interaction,
                        button: discord.ui.Button):
        if self.current_page > 1:
            self.current_page -= 1
        await self.update_embed(interaction)

    @discord.ui.button(label="Página X/Y",
                       style=discord.ButtonStyle.grey,
                       disabled=True,
                       row=0)
    async def page_label(self, interaction: discord.Interaction,
                         button: discord.ui.Button):
        pass

    @discord.ui.button(label="➡️", style=discord.ButtonStyle.secondary, row=0)
    async def next_page(self, interaction: discord.Interaction,
                        button: discord.ui.Button):
        if self.current_page < self.total_pages:
            self.current_page += 1
        await self.update_embed(interaction)

    @discord.ui.button(label="⏩", style=discord.ButtonStyle.primary, row=0)
    async def last_page(self, interaction: discord.Interaction,
                        button: discord.ui.Button):
        self.current_page = self.total_pages
        await self.update_embed(interaction)


class ConfirmationView(discord.ui.View):
    """View para confirmação de ações críticas."""

    def __init__(self, author: discord.Member, target_user: discord.Member):
        super().__init__(timeout=60)
        self.author = author
        self.target_user = target_user
        self.confirmed = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "❌ Você não tem permissão para usar estes botões.",
                ephemeral=True
            )
            return False
        return True

    async def disable_buttons(self, interaction: discord.Interaction):
        for item in self.children:
            item.disabled = True
        await interaction.message.edit(view=self)

    @discord.ui.button(label="Confirmar", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        await self.disable_buttons(interaction)
        self.stop()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = False
        await self.disable_buttons(interaction)
        self.stop()


# ============== COMANDOS ORIGINAIS ==============


@bot.command(name='verificar')
async def verificar(ctx):
    """Comando para iniciar o sistema de verificação"""
    # Cria o embed de verificação
    embed = discord.Embed(
        title="✅ Sistema de Verificação Hospitalar",
        description=
        "Para acessar o servidor, você precisa se verificar preenchendo o formulário abaixo.",
        color=discord.Color.from_rgb(255, 0, 0), # Vermelho
        timestamp=datetime.now(TZ_SAO_PAULO))
    embed.add_field(
        name="📋 Informações necessárias:",
        value=
        "• **Nome completo** (máx. 50 caracteres)\n• **ID** (5 dígitos numéricos)\n• **Telefone** (formato: 000-000)\n• **Tipo de acesso** (Visitante ou Médico)",
        inline=False)
    embed.add_field(
        name="⚡ Após a verificação:",
        value=
        "• Seu apelido será alterado para `Nome | ID`\n• Você receberá o cargo apropriado\n• Terá acesso aos canais do servidor",
        inline=False)
    embed.add_field(
        name="📌 Importante:",
        value=
        "Certifique-se de preencher todas as informações corretamente antes de enviar o formulário.",
        inline=False)
    embed.set_footer(
        text="Sistema de Verificação • Clique no botão abaixo para começar")

    # Cria a view com o botão
    view = VerificationView()

    await ctx.send(embed=embed, view=view)
    logger.info(f"Sistema de verificação iniciado por {ctx.author.name}")


@bot.command(name='ping')
async def ping(ctx):
    """Comando para verificar a latência do bot"""
    latency = round(bot.latency * 1000)

    embed = discord.Embed(title="🏓 Pong!",
                          description=f"Latência: **{latency}ms**",
                          color=COR_PRINCIPAL)
    embed.set_thumbnail(url=SP_CAPITAL_GIF_URL)

    await ctx.send(embed=embed)
    logger.info(f"Comando ping executado por {ctx.author.name}")


@bot.command(name='tempo')
async def tempo(ctx):
    """Comando para mostrar a hora atual"""
    agora = datetime.now(TZ_SAO_PAULO)
    nome_mes_pt = MESES_PT[agora.month]
    data_formatada = agora.strftime(f'%d de {nome_mes_pt} de %Y')
    hora_formatada = agora.strftime('%H:%M:%S')

    embed = discord.Embed(
        title="🕐 Hora Atual",
        description=f"**{data_formatada} às {hora_formatada}**",
        color=COR_PRINCIPAL,
        timestamp=datetime.now(TZ_SAO_PAULO))
    embed.set_thumbnail(url=SP_CAPITAL_GIF_URL)

    await ctx.send(embed=embed)
    logger.info(f"Comando tempo executado por {ctx.author.name}")


@bot.command(name='chamada', aliases=['minhachamada'])
async def chamada(ctx):
    """Exibe um painel com o status da sua sessão de chamada atual."""
    user_id = ctx.author.id

    if user_id not in call_tracker.usuarios_ativos:
        embed = discord.Embed(
            title="**📞 Status da Chamada**",
            description="Você não está em uma chamada de voz no momento.",
            color=discord.Color.from_rgb(255, 0, 0), # Vermelho
        )
        embed.set_thumbnail(url=SP_CAPITAL_GIF_URL)
        embed.set_footer(text="Entre em um canal de voz para ver seu status.")
        await ctx.send(embed=embed)
        return

    # Dados da sessão ativa
    dados_sessao = call_tracker.usuarios_ativos[user_id]
    canal_nome = dados_sessao['canal']
    entrada = dados_sessao['entrada']
    duracao_segundos = (datetime.now(TZ_SAO_PAULO) - entrada).total_seconds()

    embed = discord.Embed(
        title="**📞 Painel de Sessão Ativa**",
        color=COR_VERDE,
        timestamp=datetime.now(TZ_SAO_PAULO)
    )
    embed.set_thumbnail(url=SP_CAPITAL_GIF_URL)
    embed.set_author(
        name=ctx.author.display_name,
        icon_url=ctx.author.avatar.url if ctx.author.avatar else ctx.author.default_avatar.url
    )
    embed.add_field(
        name="**Status**",
        value="🟢 **Online**",
        inline=True
    )
    embed.add_field(
        name="**Canal Atual**",
        value=f"`{canal_nome}`",
        inline=True
    )
    embed.add_field(
        name="**Tempo da Sessão**",
        value=f"**`{call_tracker.formatar_tempo_hhmmss(duracao_segundos)}`**",
        inline=False
    )
    embed.set_footer(text="Este é um snapshot do momento atual.")

    await ctx.send(embed=embed)
    logger.info(f"Comando chamada executado por {ctx.author.name}")


@bot.command(name='rankingchamadas', aliases=['topcalls'])
async def ranking_chamadas(ctx):
    """Exibe o ranking dos usuários mais ativos em chamadas de voz."""
    try:
        ranking_data = call_tracker.obter_ranking(10)

        if not ranking_data:
            embed = discord.Embed(
                title="🏆 Ranking de Chamadas",
                description="Ainda não há dados de chamadas para exibir no ranking.",
                color=discord.Color.from_rgb(255, 0, 0) # Vermelho
            )
            embed.set_thumbnail(url=SP_CAPITAL_GIF_URL)
            await ctx.send(embed=embed)
            return

        embed = discord.Embed(
            title="🏆 Ranking de Atividade em Chamada",
            description="Os membros mais lendários do servidor, classificados por tempo total em chamada.",
            color=COR_PRINCIPAL,
            timestamp=datetime.now(TZ_SAO_PAULO)
        )
        embed.set_thumbnail(url=SP_CAPITAL_GIF_URL)

        ranking_list_str = []
        medals = ["🥇", "🥈", "🥉"]

        for i, user_data in enumerate(ranking_data):
            position = i + 1
            try:
                user = await bot.fetch_user(user_data['user_id'])
                display_name = user.display_name
            except discord.NotFound:
                display_name = user_data.get('user_name', 'Usuário Desconhecido')

            medal = medals[i] if i < 3 else f"`#{position:02}`"

            total_time_formatted = call_tracker.formatar_tempo_hhmmss(user_data['total_segundos'])

            ranking_list_str.append(
                f"{medal} **{display_name}**\n"
                f"> `Tempo Total:` {total_time_formatted}"
            )

        embed.add_field(
            name="Top 10 - Lendas das Calls",
            value="\n\n".join(ranking_list_str),
            inline=False
        )

        embed.set_footer(text="Use !consultar para ver seus detalhes ou !statscall para o de outros.")

        await ctx.send(embed=embed)
        logger.info(f"Comando rankingchamadas executado por {ctx.author.name}")

    except Exception as e:
        logger.error(f"Erro no comando rankingchamadas: {e}")
        await ctx.send("❌ Ocorreu um erro ao obter o ranking de chamadas.")


@bot.command(name='statscall')
async def stats_call(ctx, member: discord.Member = None):
    """Exibe um relatório de atividade em chamadas de um usuário."""
    try:
        target_user = member or ctx.author

        if member and not ctx.author.guild_permissions.manage_messages:
            await ctx.send("\u274c Você não tem permissão para consultar as estatísticas de outros usuários.")
            return

        stats = call_tracker.obter_estatisticas_usuario(target_user.id)

        if not stats or stats['total_sessoes'] == 0:
            embed = discord.Embed(
                title="\ud83d\udcbb Análise de Atividade",
                description=f"{target_user.mention} ainda não possui um histórico de chamadas.",
                color=discord.Color.from_rgb(255, 170, 0)  # Laranja
            )
            embed.set_author(name=target_user.display_name, icon_url=target_user.display_avatar.url)
            embed.set_thumbnail(url=SP_CAPITAL_GIF_URL)
            await ctx.send(embed=embed)
            return

        user_rank = call_tracker.get_user_rank(target_user.id)
        rank_badge = "\ud83c\udf96\ufe0f Top " + str(user_rank) if user_rank and user_rank <= 10 else f"#{user_rank}"
        rank_text = f"**Posição no Ranking:** {rank_badge}" if user_rank else "Não ranqueado"

        embed = discord.Embed(
            title="\ud83d\udcbb Análise de Atividade de Chamada",
            color=COR_PRINCIPAL,
            timestamp=datetime.now(TZ_SAO_PAULO)
        )
        embed.set_author(name=target_user.display_name, icon_url=target_user.display_avatar.url)
        embed.set_thumbnail(url=SP_CAPITAL_GIF_URL)

        # --- Estatísticas Gerais ---
        embed.add_field(
            name="\ud83d\udcca Estatísticas Gerais",
            value=f"\u23f1\ufe0f **Tempo Total:** `{call_tracker.formatar_tempo_hhmmss(stats['total_segundos'])}`\n"
                  f"\ud83c\udf99\ufe0f **Sessões:** `{stats['total_sessoes']}`\n"
                  f"\ud83c\udfc6 {rank_text}",
            inline=False
        )

        # --- Análise de Atividade ---
        embed.add_field(
            name="\ud83d\udcc8 Análise de Atividade",
            value=f"\ud83d\udcc9 **Média / Sessão:** `{call_tracker.formatar_tempo_hhmmss(stats['media_segundos'])}`\n"
                  f"\ud83d\udcc5 **Última Atividade:** {stats['ultima_call'].strftime('%d/%m/%Y às %H:%M')}",
            inline=False
        )

        # --- Status Atual ---
        if target_user.id in call_tracker.usuarios_ativos:
            dados_sessao = call_tracker.usuarios_ativos[target_user.id]
            duracao_segundos = (datetime.now(TZ_SAO_PAULO) - dados_sessao['entrada']).total_seconds()
            status_value = f"""\ud83d\udfe2 **Online** no canal `{dados_sessao['canal']}`
**Duração:** `{call_tracker.formatar_tempo_hhmmss(duracao_segundos)}`"""
            embed.color = discord.Color.from_rgb(0, 255, 136) # Verde Neon
        else:
            status_value = "\ud83d\udd34 **Offline** - Não está em uma chamada."

        embed.add_field(
            name="\ud83d\udce1 Status da Conexão",
            value=status_value,
            inline=False
        )

        embed.set_footer(text="Relatório gerado pelo Sistema de Monitoramento MedBot")

        await ctx.send(embed=embed)
        logger.info(f"Comando statscall executado por {ctx.author.name} para {target_user.name}")

    except Exception as e:
        logger.error(f"Erro no comando statscall: {e}")
        await ctx.send("\u274c Ocorreu um erro ao gerar o relatório de atividade.")


@bot.command(name='analisar')
async def analisar_desempenho(ctx):
    """Comando para gerar uma análise interpretativa do desempenho em calls"""
    try:
        stats = call_tracker.obter_estatisticas_usuario(ctx.author.id)

        if not stats:
            await ctx.send(
                "📉 Você ainda não participou de nenhuma call registrada no sistema."
            )
            return

        tempo_total = stats['total_segundos']
        sessoes = stats['total_sessoes']
        media = stats['media_segundos']
        primeira = stats['primeira_call']
        ultima = stats['ultima_call']

        # Garante que os datetimes do banco de dados sejam 'aware' (cientes do fuso horário)
        if primeira and primeira.tzinfo is None:
            primeira = TZ_SAO_PAULO.localize(primeira)
        if ultima and ultima.tzinfo is None:
            ultima = TZ_SAO_PAULO.localize(ultima)

        interpretacao = []

        # Interpretação do tempo total
        if tempo_total > 36000:  # +10h
            interpretacao.append(
                "🔋 Você é extremamente presente nas chamadas, demonstrando forte engajamento."
            )
        elif tempo_total > 14400:  # +4h
            interpretacao.append(
                "📶 Sua participação é consistente e relevante.")
        elif tempo_total > 3600:  # +1h
            interpretacao.append(
                "🕒 Sua atividade em call é moderada, com espaço para crescimento."
            )
        else:
            interpretacao.append(
                "💤 Você participou de poucas chamadas até agora. Que tal se envolver mais?"
            )

        # Interpretação da média por sessão
        if media >= 1800:  # +30 minutos
            interpretacao.append(
                "🧘 Suas sessões costumam ser longas e estáveis, sinal de dedicação."
            )
        elif media >= 900:  # +15 minutos
            interpretacao.append(
                "📈 Sessões equilibradas, demonstrando boa constância.")
        else:
            interpretacao.append(
                "⚡ Sessões rápidas — talvez esteja entrando e saindo com frequência."
            )

        # Análise temporal
        tempo_desde_primeira = (datetime.now(TZ_SAO_PAULO) -
                                primeira).days if primeira else None
        if tempo_desde_primeira:
            if tempo_desde_primeira > 60:
                interpretacao.append(
                    "📅 Sua jornada em chamadas começou há bastante tempo!")
            else:
                interpretacao.append(
                    "🚀 Você começou recentemente, e ainda tem muito a evoluir."
                )

        # Monta embed
        embed = discord.Embed(title="📊 Análise Pessoal de Calls",
                              description="\n".join(interpretacao),
                              color=discord.Color.teal(),
                              timestamp=datetime.now(TZ_SAO_PAULO))
        embed.set_thumbnail(url=SP_CAPITAL_GIF_URL)

        embed.add_field(
            name="⏱️ Tempo Total",
            value=f"**{call_tracker.formatar_tempo(tempo_total)}**",
            inline=True)
        embed.add_field(name="🎙️ Sessões", value=f"**{sessoes}**", inline=True)
        embed.add_field(name="📈 Média por Sessão",
                        value=f"**{call_tracker.formatar_tempo(media)}**",
                        inline=True)

        if primeira:
            embed.add_field(name="🎯 Primeira Call",
                            value=f"{primeira.strftime('%d/%m/%Y às %H:%M')}",
                            inline=True)
        if ultima:
            embed.add_field(name="📅 Última Call",
                            value=f"{ultima.strftime('%d/%m/%Y às %H:%M')}",
                            inline=True)

        embed.set_author(name=ctx.author.display_name,
                         icon_url=ctx.author.avatar.url if ctx.author.avatar
                         else ctx.author.default_avatar.url)
        embed.set_footer(
            text="Relatório analítico gerado com base no seu histórico")

        await ctx.send(embed=embed)
        logger.info(f"Comando analisar executado por {ctx.author.name}")

    except Exception as e:
        logger.error(f"Erro no comando analisar: {e}")
        await ctx.send(
            "❌ Ocorreu um erro ao gerar a análise do seu desempenho.")


@bot.command(name='consultar',
             aliases=['pontos_consultar'],
             help="Consulta seu histórico de tempo em chamadas.")
async def consultar_command(ctx, usuario: discord.Member = None):
    """Consulta o histórico de tempo em chamadas de um usuário com a nova interface."""
    if usuario is None:
        usuario = ctx.author

    # Permissão para consultar outros
    if usuario != ctx.author and not ctx.author.guild_permissions.manage_messages:
        await ctx.send("❌ Você não tem permissão para consultar o histórico de outros usuários.")
        return

    try:
        # Obter estatísticas e ranking
        stats = call_tracker.obter_estatisticas_usuario(usuario.id)
        rank = call_tracker.get_user_rank(usuario.id)
        total_segundos_geral = stats['total_segundos'] if stats else 0

        # Obter todas as sessões
        conn = sqlite3.connect(call_tracker.db_path)
        cursor = conn.cursor()
        cursor.execute(
            '''
            SELECT id, user_id, user_name, canal, entrada, saida, duracao_segundos
            FROM call_sessions
            WHERE user_id = ? AND duracao_segundos IS NOT NULL
            ORDER BY entrada DESC
        ''', (str(usuario.id), ))
        sessoes = cursor.fetchall()
        conn.close()

        if not sessoes:
            embed = discord.Embed(
                title="📜 Histórico de Atividade",
                description="💤 Este usuário ainda não possui um histórico de chamadas para exibir.",
                color=discord.Color.from_rgb(255, 170, 0) # Laranja
            )
            embed.set_author(name=f"Relatório de: {usuario.display_name}",
                             icon_url=usuario.avatar.url if usuario.avatar else usuario.default_avatar.url)
            embed.set_thumbnail(url=SP_CAPITAL_GIF_URL)
            embed.set_footer(text="Nenhuma sessão encontrada.")
            await ctx.send(embed=embed)
            return

        # Configura a view de paginação com os novos dados
        view = PaginationView(author=ctx.author,
                              all_sessoes=sessoes,
                              usuario_alvo=usuario,
                              total_segundos=total_segundos_geral,
                              rank=rank,
                              items_per_page=5)

        # Constrói e envia o embed inicial
        sessoes_iniciais = view.get_page_data()
        embed = build_consultar_embed(sessoes_iniciais, usuario, 1, view.total_pages, total_segundos_geral, rank)

        await ctx.send(embed=embed, view=view)
        logger.info(
            f"Comando consultar executado por {ctx.author.name} para {usuario.name}"
        )

    except Exception as e:
        logger.error(f"Erro no comando consultar: {e}", exc_info=True)
        await ctx.send(
            "❌ Ocorreu um erro ao consultar o histórico de chamadas.")


# ============== COMANDO DE AJUDA INTERATIVO ==============


class HelpSelect(discord.ui.Select):
    """Dropdown para selecionar categorias de ajuda."""

    def __init__(self):
        options = [
            discord.SelectOption(label="Comandos Gerais",
                                 description="Comandos para todos os membros.",
                                 emoji="🛠️"),
            discord.SelectOption(
                label="Estatísticas de Chamadas",
                description="Comandos para visualizar tempos e rankings.",
                emoji="📊"),
            discord.SelectOption(
                label="Moderação",
                description="Comandos para a equipe de moderação.",
                emoji="🔨")
        ]
        super().__init__(placeholder="Selecione uma categoria...",
                         min_values=1,
                         max_values=1,
                         options=options)

    async def callback(self, interaction: discord.Interaction):
        # Obtém a categoria selecionada e cria um novo embed
        selected_category = self.values[0]
        embed = discord.Embed(title=f"💻 Categoria: {selected_category}",
                              color=COR_PRINCIPAL,
                              timestamp=datetime.now(TZ_SAO_PAULO))
        embed.set_thumbnail(url=SP_CAPITAL_GIF_URL)
        embed.set_footer(text="Use !help <comando> para mais detalhes.")

        if selected_category == "Comandos Gerais":
            embed.description = "Comandos essenciais disponíveis para todos."
            embed.add_field(name="`!ping`", value="Verifica a latência do bot.", inline=False)
            embed.add_field(name="`!tempo`", value="Mostra a data e hora atuais.", inline=False)
            embed.add_field(name="`!help`", value="Exibe esta mensagem de ajuda.", inline=False)
            embed.add_field(name="`!verificar`", value="Inicia o processo de verificação.", inline=False)

        elif selected_category == "Estatísticas de Chamadas":
            embed.description = "Comandos para acompanhar sua atividade em chamadas."
            embed.add_field(name="`!chamada` (ou `!minhachamada`)", value="Painel com o status da sua chamada atual.", inline=False)
            embed.add_field(name="`!statscall [usuário]`", value="Relatório de atividade de um usuário (ou seu).", inline=False)
            embed.add_field(name="`!consultar [usuário]`", value="Seu histórico paginado de sessões.", inline=False)
            embed.add_field(name="`!rankingchamadas` (ou `!topcalls`)", value="Ranking dos usuários mais ativos.", inline=False)
            embed.add_field(name="`!analisar`", value="Análise sobre seu desempenho em chamadas.", inline=False)

        elif selected_category == "Moderação":
            embed.description = "Comandos para a equipe administrativa."
            embed.add_field(name="`!resetcalls` `[usuário]`", value="Reseta os dados de chamadas de um usuário.", inline=False)
            embed.add_field(name="`!resetallcalls`", value="Reseta todos os dados de chamadas do servidor.", inline=False)
            embed.add_field(name="`!clear` `[quantidade]`", value="Limpa até 100 mensagens no canal.", inline=False)
            embed.add_field(name="`!punir` `[membro]` `[nível]`", value="Aplica uma punição (nível 1 ou 2) a um membro.", inline=False)
            embed.add_field(name="`!setar` `[membro]` `[cargo]`", value="Atribui um cargo profissional a um membro.", inline=False)
            embed.add_field(name="`!say` `[canal]` `[mensagem]`", value="Envia uma mensagem através do bot.", inline=False)
            embed.add_field(name="`!hierarquia`", value="Mostra a hierarquia de cargos do servidor.", inline=False)

        # Edita a mensagem original com o novo embed da categoria
        await interaction.response.edit_message(embed=embed)


class HelpView(discord.ui.View):
    """View que contém o dropdown de ajuda."""

    def __init__(self):
        super().__init__(timeout=180)  # O menu expira em 3 minutos
        self.add_item(HelpSelect())


@bot.command(name='help', help="Mostra esta mensagem de ajuda interativa.")
async def help_command(ctx):
    """Mostra uma mensagem de ajuda interativa com um menu de seleção."""
    embed = discord.Embed(
        title="💻 Central de Ajuda do MedBot",
        description="Bem-vindo(a) à central de ajuda! Use o menu abaixo para navegar pelas categorias de comandos.",
        color=COR_PRINCIPAL,
        timestamp=datetime.now(TZ_SAO_PAULO))
    embed.set_thumbnail(url=SP_CAPITAL_GIF_URL)
    embed.set_footer(text="Selecione uma categoria para ver os comandos.")

    view = HelpView()
    await ctx.send(embed=embed, view=view)


# ============== SISTEMA DE VERIFICAÇÃO (MANTIDO INTOCADO) ==============


class VerificationModal(discord.ui.Modal, title='Formulário de Verificação'):
    """Modal para coleta de informações de verificação"""

    def __init__(self):
        super().__init__()

        # Campo nome
        self.nome = discord.ui.TextInput(
            label="📋 Nome Completo",
            placeholder="Digite seu nome completo",
            required=True,
            max_length=50)
        self.add_item(self.nome)

        # Campo ID
        self.id_usuario = discord.ui.TextInput(label="🆔 ID (até 5 dígitos)",
                                               placeholder="Ex: 12345",
                                               required=True,
                                               min_length=1,
                                               max_length=5)
        self.add_item(self.id_usuario)

        # Campo telefone
        self.telefone = discord.ui.TextInput(label="📞 Telefone",
                                             placeholder="Ex: 123-456",
                                             required=True,
                                             min_length=7,
                                             max_length=7)
        self.add_item(self.telefone)

        # Campo tipo de acesso
        self.tipo_acesso = discord.ui.TextInput(
            label="🏷️ Tipo de Acesso",
            placeholder="Digite: Visitante ou Médico",
            required=True,
            max_length=15)
        self.add_item(self.tipo_acesso)

    async def on_submit(self, interaction: discord.Interaction):
        """Processa o formulário de verificação"""
        try:
            # Validações dos campos
            if not self.id_usuario.value.isdigit():
                await interaction.response.send_message(
                    "❌ ID deve conter apenas números!", ephemeral=True)
                return

            if not self.telefone.value.count('-') == 1:
                await interaction.response.send_message(
                    "❌ Telefone deve estar no formato XXX-XXX!",
                    ephemeral=True)
                return

            tipo_valido = self.tipo_acesso.value.strip().lower()
            if tipo_valido not in ['visitante', 'médico', 'medico']:
                await interaction.response.send_message(
                    "❌ Tipo de acesso deve ser 'Visitante' ou 'Médico'!",
                    ephemeral=True)
                return

            # Processamento e atribuição de cargos
            guild = interaction.guild
            tipo_final = "Médico" if tipo_valido in ['médico', 'medico'
                                                     ] else "Visitante"

            cargo_key = "Estagiário" if tipo_final == "Médico" else "Visitante/Observador"
            cargo_id = CARGOS_IDS.get(cargo_key)
            cargo = guild.get_role(cargo_id) if cargo_id else None

            if not cargo:
                await interaction.response.send_message(
                    f"❌ O cargo '{cargo_key}' não foi encontrado ou configurado. Contate um admin.",
                    ephemeral=True)
                return

            await interaction.user.add_roles(cargo)

            # Altera apelido
            novo_apelido = f"{self.nome.value} | {self.id_usuario.value}"
            await interaction.user.edit(nick=novo_apelido)

            # Mensagem de sucesso bonita com tema vermelho
            embed_sucesso = discord.Embed(
                title="⚕️ Verificação Concluída ⚕️",
                description=
                f"Bem-vindo(a) ao sistema, **{interaction.user.mention}**!",
                color=discord.Color.red(),
                timestamp=datetime.now(TZ_SAO_PAULO))
            embed_sucesso.set_thumbnail(
                url=interaction.user.avatar.url if interaction.user.
                avatar else interaction.user.default_avatar.url)

            embed_sucesso.add_field(name="__Informações Registradas__",
                                    value=f"**Nome:** `{self.nome.value}`\n"
                                    f"**ID:** `{self.id_usuario.value}`\n"
                                    f"**Telefone:** `{self.telefone.value}`\n"
                                    f"**Tipo:** `{tipo_final}`",
                                    inline=False)

            # Adiciona um campo em branco para espaçamento
            embed_sucesso.add_field(name="\u200b",
                                    value="\u200b",
                                    inline=False)

            embed_sucesso.add_field(
                name="__Alterações Aplicadas__",
                value=f"**Apelido alterado para:** `{novo_apelido}`\n"
                f"**Cargo atribuído:** {cargo.mention}",
                inline=False)

            embed_sucesso.set_footer(
                text=f"Sistema de Verificação • {interaction.guild.name}")
            await interaction.response.send_message(embed=embed_sucesso,
                                                    ephemeral=True)
            logger.info(
                f"Usuário {interaction.user.name} verificado com sucesso.")

            # Envia log para canal de logs se existir (com tema vermelho)
            canal_logs = guild.get_channel(
                CANAIS_TEXTO.get("logs-de-inscrição"))
            if canal_logs:
                log_embed = discord.Embed(
                    title="⚕️ Nova Verificação Realizada ⚕️",
                    color=discord.Color.dark_red(),
                    timestamp=datetime.now(TZ_SAO_PAULO))
                log_embed.set_thumbnail(
                    url=interaction.user.avatar.url if interaction.user.
                    avatar else interaction.user.default_avatar.url)

                log_embed.add_field(
                    name="👤 Usuário",
                    value=
                    f"{interaction.user.mention}\n`{interaction.user.name}` (ID: `{interaction.user.id}`)",
                    inline=False)

                log_embed.add_field(name="📋 Nome Completo",
                                    value=f"**`{self.nome.value}`**",
                                    inline=True)
                log_embed.add_field(name="🆔 ID",
                                    value=f"**`{self.id_usuario.value}`**",
                                    inline=True)
                log_embed.add_field(name="📞 Telefone",
                                    value=f"**`{self.telefone.value}`**",
                                    inline=True)

                log_embed.add_field(name="🏷️ Tipo",
                                    value=f"**`{tipo_final}`**",
                                    inline=True)
                log_embed.add_field(name="📝 Apelido",
                                    value=f"**`{novo_apelido}`**",
                                    inline=True)
                log_embed.add_field(name="🎯 Cargo Atribuído",
                                    value=f"**{cargo.mention}**",
                                    inline=True)

                log_embed.set_footer(
                    text=f"Sistema de Verificação • {interaction.guild.name}")

                await canal_logs.send(embed=log_embed)

        except Exception as e:
            logger.error(
                f"Erro na verificação de {interaction.user.name}: {e}")
            await interaction.response.send_message(
                "❌ Ocorreu um erro inesperado. Tente novamente.",
                ephemeral=True)


class VerificationView(discord.ui.View):
    """View com botão para iniciar verificação"""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Iniciar Verificação",
                       style=discord.ButtonStyle.green,
                       emoji="✅")
    async def start_verification(self, interaction: discord.Interaction,
                                 button: discord.ui.Button):
        """Inicia o processo de verificação"""
        modal = VerificationModal()
        await interaction.response.send_modal(modal)


# ============== COMANDOS ADMINISTRATIVOS ==============

@bot.command(name='resetcalls')
@commands.has_permissions(administrator=True)
async def reset_calls(ctx, usuario: discord.Member):
    """Apaga todos os dados de chamadas de um usuário (Apenas Admin)."""
    if not usuario:
        await ctx.send("❌ Você precisa mencionar um usuário para resetar os dados.")
        return

    view = ConfirmationView(author=ctx.author, target_user=usuario)

    embed = discord.Embed(
        title="⚠️ Confirmação de Exclusão de Dados ⚠️",
        description=f"Você está prestes a apagar **TODOS** os registros de chamadas de **{usuario.mention}**.\n\n"
                    f"Esta ação é **irreversível**.\n\n"
                    "Por favor, confirme sua decisão clicando nos botões abaixo.",
        color=discord.Color.dark_red()
    )
    embed.set_footer(text="Esta solicitação expirá em 60 segundos.")

    confirmation_message = await ctx.send(embed=embed, view=view)

    await view.wait()

    for item in view.children:
        item.disabled = True

    if view.confirmed is True:
        if call_tracker.reset_user_calls(usuario.id):
            success_embed = discord.Embed(
                title="✅ Dados Apagados com Sucesso",
                description=f"Todos os registros de chamadas e estatísticas de {usuario.mention} foram permanentemente apagados.",
                color=discord.Color.green()
            )
            await confirmation_message.edit(embed=success_embed, view=view)
            logger.info(f"O administrador {ctx.author.name} resetou os dados de {usuario.name}.")
        else:
            error_embed = discord.Embed(
                title="❌ Erro na Exclusão",
                description=f"Ocorreu um erro ao tentar apagar os dados de {usuario.mention}. Verifique os logs.",
                color=discord.Color.red()
            )
            await confirmation_message.edit(embed=error_embed, view=view)

    elif view.confirmed is False:
        cancel_embed = discord.Embed(
            title="🚫 Operação Cancelada",
            description=f"A exclusão dos dados de {usuario.mention} foi cancelada.",
            color=discord.Color.light_grey()
        )
        await confirmation_message.edit(embed=cancel_embed, view=view)

    else:  # Timeout
        timeout_embed = discord.Embed(
            title="⏳ Tempo Esgotado",
            description=f"A solicitação para apagar os dados de {usuario.mention} expirou e foi cancelada.",
            color=discord.Color.orange()
        )
        await confirmation_message.edit(embed=timeout_embed, view=view)

@reset_calls.error
async def reset_calls_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Você não tem permissão de administrador para usar este comando.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Por favor, mencione o usuário cujos dados você deseja resetar. Ex: `!resetcalls @usuario`")
    else:
        logger.error(f"Erro inesperado no comando !resetcalls: {error}")
        await ctx.send("❌ Ocorreu um erro inesperado ao processar o comando.")


class ResetAllConfirmationView(discord.ui.View):
    """View para confirmação de reset geral de dados."""
    def __init__(self, author: discord.Member):
        super().__init__(timeout=60)
        self.author = author
        self.confirmed = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author.id:
            await interaction.response.send_message(
                "❌ Apenas o autor do comando pode confirmar esta ação.",
                ephemeral=True)
            return False
        return True

    async def disable_buttons(self, interaction: discord.Interaction):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="DESTRUIR TODOS OS DADOS", style=discord.ButtonStyle.danger, emoji="💥")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = True
        await self.disable_buttons(interaction)
        self.stop()

    @discord.ui.button(label="Cancelar", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.confirmed = False
        await self.disable_buttons(interaction)
        self.stop()


@bot.command(name='resetallcalls', aliases=['resetgeral'])
@commands.has_permissions(administrator=True)
async def reset_all_calls_command(ctx):
    """Apaga TODOS os dados de chamadas do servidor (Apenas Admin)."""
    view = ResetAllConfirmationView(author=ctx.author)

    embed = discord.Embed(
        title="🚨 ALERTA MÁXIMO: RESET GERAL DE DADOS 🚨",
        description=(
            f"Você está prestes a apagar **TODOS OS REGISTROS DE CHAMADAS DE TODOS OS USUÁRIOS** do servidor.\n\n"
            "**ESTA AÇÃO É IRREVERSÍVEL E DESTRUIRÁ TODOS OS DADOS DE TEMPO EM CALL.**\n\n"
            "Tem certeza absoluta de que deseja prosseguir?"
        ),
        color=discord.Color.from_rgb(255, 0, 0)
    )
    embed.set_footer(text="Esta solicitação de alto risco expira em 60 segundos.")
    embed.set_thumbnail(url=SP_CAPITAL_GIF_URL)

    confirmation_message = await ctx.send(embed=embed, view=view)

    await view.wait()

    if view.confirmed is True:
        if call_tracker.reset_all_calls():
            success_embed = discord.Embed(
                title="✅ Reset Geral Concluído",
                description="Todos os dados de chamadas do servidor foram permanentemente apagados.",
                color=COR_VERDE
            )
            await confirmation_message.edit(embed=success_embed, view=None)
        else:
            error_embed = discord.Embed(
                title="❌ Erro no Reset Geral",
                description="Ocorreu um erro ao tentar apagar os dados. Verifique os logs do bot.",
                color=COR_PRINCIPAL
            )
            await confirmation_message.edit(embed=error_embed, view=None)
    elif view.confirmed is False:
        cancel_embed = discord.Embed(
            title="🚫 Operação Cancelada",
            description="O reset geral de dados foi cancelado.",
            color=COR_LARANJA
        )
        await confirmation_message.edit(embed=cancel_embed, view=None)
    else: # Timeout
        timeout_embed = discord.Embed(
            title="⏰ Tempo Esgotado",
            description="A solicitação para resetar os dados expirou.",
            color=discord.Color.greyple()
        )
        await confirmation_message.edit(embed=timeout_embed, view=None)


@reset_all_calls_command.error
async def reset_all_calls_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Você não tem permissão de administrador para usar este comando.")
    else:
        logger.error(f"Erro inesperado no comando !resetallcalls: {error}")
        await ctx.send("❌ Ocorreu um erro inesperado ao processar o comando.")


# ============== COMANDOS DE MODERAÇÃO ==============

@bot.command(name='say')
@commands.has_permissions(administrator=True)
async def say_command(ctx, canal: discord.TextChannel, *, mensagem: str):
    """Envia uma mensagem para um canal específico."""
    try:
        await canal.send(mensagem)
        await ctx.message.add_reaction('✅')
        await ctx.message.delete(delay=5)
    except discord.Forbidden:
        await ctx.send(f"❌ O bot não tem permissão para enviar mensagens no canal {canal.mention}.")
    except Exception as e:
        await ctx.send("❌ Ocorreu um erro ao tentar enviar a mensagem.")
        logger.error(f"Erro no comando !say: {e}")

@say_command.error
async def say_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Você não tem permissão de administrador para usar este comando.")
    elif isinstance(error, (commands.MissingRequiredArgument, commands.BadArgument)):
        await ctx.send("❌ Uso incorreto. Exemplo: `!say #canal Sua mensagem aqui`")
    elif isinstance(error, commands.ChannelNotFound):
        await ctx.send("❌ Canal não encontrado. Por favor, mencione um canal de texto válido.")
    else:
        logger.error(f"Erro inesperado no comando !say: {error}")
        await ctx.send("❌ Ocorreu um erro inesperado ao processar o comando.")

@bot.command(name='clear', aliases=['limpar'])
@commands.has_permissions(manage_messages=True)
async def clear_command(ctx, amount: int):
    """Limpa uma quantidade de mensagens no canal (máximo: 100)."""
    if amount <= 0:
        await ctx.send("❌ Por favor, insira um número positivo de mensagens para apagar.")
        return
    if amount > 100:
        await ctx.send("❌ Não é possível limpar mais de 100 mensagens de uma vez.")
        return

    # O +1 é para apagar o comando !clear também
    deleted = await ctx.channel.purge(limit=amount + 1)
    await ctx.send(f"✅ {len(deleted) - 1} mensagens foram limpas por {ctx.author.mention}.", delete_after=5)
    logger.info(f"{ctx.author.name} limpou {len(deleted) - 1} mensagens no canal {ctx.channel.name}.")

@clear_command.error
async def clear_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Você não tem permissão para gerenciar mensagens.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Uso incorreto. Exemplo: `!clear 10`")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Por favor, forneça um número válido de mensagens para limpar.")
    else:
        logger.error(f"Erro no comando !clear: {error}")
        await ctx.send("❌ Ocorreu um erro ao tentar limpar as mensagens.")


@bot.command(name='punir')
@commands.has_permissions(administrator=True)
async def punir_command(ctx, membro: discord.Member, nivel: int):
    """Aplica um cargo de punição a um membro (nível 1 ou 2)."""
    if nivel not in [1, 2]:
        await ctx.send("❌ Nível de punição inválido. Use 1 ou 2.")
        return

    cargo_id = CARGO_PUNICAO_1_ID if nivel == 1 else CARGO_PUNICAO_2_ID
    cargo = ctx.guild.get_role(cargo_id)

    if not cargo:
        await ctx.send(f"❌ O cargo de Punição {nivel} não foi encontrado no servidor.")
        logger.error(f"Cargo de Punição {nivel} (ID: {cargo_id}) não encontrado.")
        return

    try:
        await membro.add_roles(cargo)
        embed = discord.Embed(
            title="⚖️ Punição Aplicada",
            description=f"O membro {membro.mention} recebeu o cargo **{cargo.name}**.",
            color=COR_PRINCIPAL,
            timestamp=datetime.now(TZ_SAO_PAULO)
        )
        embed.set_footer(text=f"Ação executada por {ctx.author.display_name}")
        await ctx.send(embed=embed)
        logger.info(f"{ctx.author.name} aplicou a punição de nível {nivel} em {membro.name}.")

        # Envia o log para o canal de moderação
        canal_log_mod = bot.get_channel(CANAL_MODERACAO_ID)
        if canal_log_mod:
            log_embed = discord.Embed(
                title="📝 Log de Punição",
                color=COR_LARANJA,
                timestamp=datetime.now(TZ_SAO_PAULO)
            )
            log_embed.add_field(name="Usuário Punido", value=membro.mention, inline=True)
            log_embed.add_field(name="Moderador", value=ctx.author.mention, inline=True)
            log_embed.add_field(name="Punição Aplicada", value=f"**{cargo.name}** (Nível {nivel})", inline=False)
            log_embed.set_footer(text=f"ID do Usuário: {membro.id}")

            try:
                await canal_log_mod.send(embed=log_embed)
            except Exception as e:
                logger.error(f"Falha ao enviar log de punição para o canal {CANAL_MODERACAO_ID}: {e}")
        else:
            logger.warning(f"Canal de log de moderação (ID: {CANAL_MODERACAO_ID}) não encontrado.")
    except discord.Forbidden:
        await ctx.send("❌ O bot não tem permissão para adicionar este cargo.")
    except Exception as e:
        await ctx.send("❌ Ocorreu um erro ao tentar aplicar a punição.")
        logger.error(f"Erro no comando !punir: {e}")

@punir_command.error
async def punir_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Você não tem permissão de administrador para usar este comando.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Uso incorreto. Exemplo: `!punir @membro 1`")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Argumentos inválidos. Certifique-se de mencionar um membro e fornecer um nível de punição (1 ou 2).")
    else:
        logger.error(f"Erro inesperado no comando !punir: {error}")
        await ctx.send("❌ Ocorreu um erro inesperado ao processar o comando.")


@bot.command(name='setar')
@commands.has_permissions(administrator=True)
async def setar_cargo_command(ctx, membro: discord.Member, cargo: discord.Role):
    """Atribui um cargo profissional a um membro."""
    cargos_permitidos = CARGOS_SETAveis_IDS

    if cargo.id not in cargos_permitidos:
        await ctx.send("❌ Você só pode setar os cargos de `Paramédico`, `Médico` ou `Enfermeiro`.")
        return

    try:
        await membro.add_roles(cargo)
        embed = discord.Embed(
            title="✅ Cargo Atribuído",
            description=f"O membro {membro.mention} agora tem o cargo {cargo.mention}.",
            color=COR_VERDE,
            timestamp=datetime.now(TZ_SAO_PAULO)
        )
        embed.set_footer(text=f"Ação executada por {ctx.author.display_name}")
        await ctx.send(embed=embed)
        logger.info(f"{ctx.author.name} setou o cargo {cargo.name} para {membro.name}.")
    except discord.Forbidden:
        await ctx.send("❌ O bot não tem permissão para gerenciar este cargo.")
    except Exception as e:
        await ctx.send("❌ Ocorreu um erro ao tentar atribuir o cargo.")
        logger.error(f"Erro no comando !setar: {e}")

@setar_cargo_command.error
async def setar_cargo_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Você não tem permissão de administrador para usar este comando.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Uso incorreto. Exemplo: `!setar @membro @cargo`")
    elif isinstance(error, commands.BadArgument):
        await ctx.send("❌ Argumentos inválidos. Certifique-se de mencionar um membro e um cargo válidos.")
    else:
        logger.error(f"Erro inesperado no comando !setar: {error}")
        await ctx.send("❌ Ocorreu um erro inesperado ao processar o comando.")


class HierarquiaView(discord.ui.View):
    def __init__(self, ctx, cargos_por_pagina=3):
        super().__init__(timeout=180)
        self.ctx = ctx
        self.cargos_por_pagina = cargos_por_pagina
        self.pagina_atual = 0
        self.total_paginas = (len(HIERARQUIA_CARGOS) + self.cargos_por_pagina - 1) // self.cargos_por_pagina

    async def criar_embed_pagina(self):
        start_index = self.pagina_atual * self.cargos_por_pagina
        end_index = start_index + self.cargos_por_pagina
        cargos_da_pagina = HIERARQUIA_CARGOS[start_index:end_index]

        embed = discord.Embed(
            title="📊 Estrutura Hierárquica do Servidor",
            description="*Atualizado ao vivo - Mostrando cargos e membros organizados por autoridade*",
            color=COR_PRINCIPAL
        )

        total_membros_listados = 0
        for cargo_info in cargos_da_pagina:
            cargo = self.ctx.guild.get_role(cargo_info['id'])
            if cargo:
                membros = [m.mention for m in cargo.members if not m.bot]
                total_membros_listados += len(membros)
                membros_str = '\n'.join(membros) if membros else "Nenhum membro encontrado."
                embed.add_field(
                    name=f"{cargo_info['emoji']} **{cargo.name}**",
                    value=membros_str,
                    inline=False
                )

        embed.set_footer(text=f"Página {self.pagina_atual + 1}/{self.total_paginas} | 👥 Total de membros listados: {total_membros_listados}")
        return embed

    async def atualizar_botoes(self):
        self.children[0].disabled = self.pagina_atual == 0
        self.children[1].disabled = self.pagina_atual == self.total_paginas - 1

    @discord.ui.button(label="Anterior", style=discord.ButtonStyle.grey)
    async def anterior_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.pagina_atual > 0:
            self.pagina_atual -= 1
            await self.atualizar_botoes()
            embed = await self.criar_embed_pagina()
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Próximo", style=discord.ButtonStyle.grey)
    async def proximo_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.pagina_atual < self.total_paginas - 1:
            self.pagina_atual += 1
            await self.atualizar_botoes()
            embed = await self.criar_embed_pagina()
            await interaction.response.edit_message(embed=embed, view=self)

@bot.command(name='hierarquia')
@commands.has_permissions(administrator=True)
async def hierarquia_command(ctx):
    """Mostra a hierarquia de cargos do servidor com paginação."""
    view = HierarquiaView(ctx)
    await view.atualizar_botoes()
    embed = await view.criar_embed_pagina()
    await ctx.send(embed=embed, view=view)

@hierarquia_command.error
async def hierarquia_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ Você não tem permissão para usar este comando.")
    else:
        logger.error(f"Erro inesperado no comando !hierarquia: {error}")
        await ctx.send("❌ Ocorreu um erro inesperado.")


# ==================== EXECUÇÃO ====================

import os
from dotenv import load_dotenv

[{ ... }]
async def main():
    """Função principal para iniciar o bot"""
    try:
        # Carrega variáveis de ambiente do arquivo .env
        load_dotenv()
        TOKEN = os.getenv("DISCORD_TOKEN")

        if not TOKEN or TOKEN == "seu_token_aqui":
            logger.error(
                "❌ Token do bot não configurado! Crie um arquivo .env e adicione seu DISCORD_TOKEN."
            )
            return

        await bot.start(TOKEN)

    except discord.LoginFailure:
        logger.error(
            "❌ Token inválido! Verifique se o token no arquivo .env está correto."
        )
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
