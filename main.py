import discord
from discord import app_commands
from discord.ext import commands
import itertools
import sqlite3
import os
import random
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="/", intents=intents)

MAX_MATCHES = 3
MATCH_CHANNEL_ID = 1495481849189892197
ADMIN_ROLE_ID = 1494949360235188224
DB_FILE = "bot_data.db"

MAP_POOL = {
    "Brawl Ball": ["Backyard Bowl", "Center Stage", "Pinball Dreams"],
    "Gem Grab": ["Hard Rock Mine", "Crystal Arcade", "Double Swoosh"],
    "Heist": ["Safe Zone", "Hot Potato"],
    "Knockout": ["Goldarm Gulch", "Belle's Rock"]
}


def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS players (
            user_id INTEGER PRIMARY KEY,
            discord_name TEXT NOT NULL,
            brawl_id TEXT NOT NULL,
            elo INTEGER DEFAULT 1000,
            wins INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            streak INTEGER DEFAULT 0
        )
    """)
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS waiting_queue (
            user_id INTEGER PRIMARY KEY,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS active_matches (
            match_id INTEGER PRIMARY KEY AUTOINCREMENT,
            match_name TEXT UNIQUE NOT NULL,
            team1_player1 INTEGER,
            team1_player2 INTEGER,
            team1_player3 INTEGER,
            team2_player1 INTEGER,
            team2_player2 INTEGER,
            team2_player3 INTEGER,
            mode TEXT,
            map TEXT,
            status TEXT DEFAULT 'active',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    c.execute("""
        CREATE TABLE IF NOT EXISTS match_votes (
            match_id INTEGER,
            user_id INTEGER,
            team_voted TEXT,
            PRIMARY KEY (match_id, user_id)
        )
    """)
    
    conn.commit()
    conn.close()


def get_all_players():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT user_id, discord_name, brawl_id, elo, wins, losses, streak FROM players")
    rows = c.fetchall()
    conn.close()
    return {row[0]: {"discord_name": row[1], "brawl_id": row[2], "elo": row[3], 
                     "wins": row[4], "losses": row[5], "streak": row[6]} for row in rows}

def get_player(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT discord_name, brawl_id, elo, wins, losses, streak FROM players WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"discord_name": row[0], "brawl_id": row[1], "elo": row[2], 
                "wins": row[3], "losses": row[4], "streak": row[5]}
    return None

def add_player(user_id, discord_name, brawl_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT INTO players (user_id, discord_name, brawl_id, elo, wins, losses, streak) VALUES (?, ?, ?, 1000, 0, 0, 0)",
              (user_id, discord_name, brawl_id))
    conn.commit()
    conn.close()

def update_player_elo(user_id, new_elo):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE players SET elo = ? WHERE user_id = ?", (new_elo, user_id))
    conn.commit()
    conn.close()

def update_player_stats(user_id, elo_delta, is_win):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT elo, wins, losses, streak FROM players WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    
    new_elo = row[0] + elo_delta
    new_wins = row[1] + (1 if is_win else 0)
    new_losses = row[2] + (0 if is_win else 1)
    
    if is_win:
        new_streak = row[3] + 1 if row[3] >= 0 else 1
    else:
        new_streak = row[3] - 1 if row[3] <= 0 else -1
    
    c.execute("UPDATE players SET elo = ?, wins = ?, losses = ?, streak = ? WHERE user_id = ?",
              (new_elo, new_wins, new_losses, new_streak, user_id))
    conn.commit()
    conn.close()

def get_waiting_players():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT user_id FROM waiting_queue ORDER BY joined_at")
    rows = c.fetchall()
    conn.close()
    return [row[0] for row in rows]

def add_to_queue(user_ids):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    for user_id in user_ids:
        c.execute("INSERT OR IGNORE INTO waiting_queue (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

def remove_from_queue(user_ids):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    placeholders = ','.join('?' * len(user_ids))
    c.execute(f"DELETE FROM waiting_queue WHERE user_id IN ({placeholders})", user_ids)
    conn.commit()
    conn.close()

def clear_queue():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM waiting_queue")
    conn.commit()
    conn.close()

def is_in_queue(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT 1 FROM waiting_queue WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result is not None

def add_match(match_name, team1, team2, mode, map_name):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        INSERT INTO active_matches (match_name, team1_player1, team1_player2, team1_player3, 
                                     team2_player1, team2_player2, team2_player3, mode, map, status)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active')
    """, (match_name, team1[0], team1[1], team1[2], team2[0], team2[1], team2[2], mode, map_name))
    conn.commit()
    conn.close()

def get_all_matches():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT match_name, team1_player1, team1_player2, team1_player3,
               team2_player1, team2_player2, team2_player3, mode, map
        FROM active_matches WHERE status = 'active'
    """)
    rows = c.fetchall()
    conn.close()
    matches = {}
    for row in rows:
        team1 = [x for x in [row[1], row[2], row[3]] if x is not None]
        team2 = [x for x in [row[4], row[5], row[6]] if x is not None]
        matches[row[0]] = {
            "team1": team1,
            "team2": team2,
            "mode": row[7],
            "map": row[8]
        }
    return matches

def get_match_by_player(user_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("""
        SELECT match_id, match_name, team1_player1, team1_player2, team1_player3,
               team2_player1, team2_player2, team2_player3, mode, map
        FROM active_matches
        WHERE status = 'active' AND (
            team1_player1 = ? OR team1_player2 = ? OR team1_player3 = ?
            OR team2_player1 = ? OR team2_player2 = ? OR team2_player3 = ?
        )
    """, (user_id, user_id, user_id, user_id, user_id, user_id))
    row = c.fetchone()
    conn.close()
    if row:
        team1 = [x for x in [row[2], row[3], row[4]] if x is not None]
        team2 = [x for x in [row[5], row[6], row[7]] if x is not None]
        player_team = "team1" if user_id in team1 else "team2"
        return row[0], row[1], {"team1": team1, "team2": team2, "mode": row[8], "map": row[9]}, player_team
    return None, None, None, None

def finish_match(match_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE active_matches SET status = 'finished' WHERE match_id = ? AND status = 'active'", (match_id,))
    affected = c.rowcount
    conn.commit()
    conn.close()
    return affected > 0

def get_match_counter():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT MAX(match_id) FROM active_matches")
    result = c.fetchone()[0]
    conn.close()
    return result if result else 0

def add_vote(match_id, user_id, team):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute("INSERT INTO match_votes (match_id, user_id, team_voted) VALUES (?, ?, ?)",
                  (match_id, user_id, team))
        conn.commit()
        conn.close()
        return True
    except sqlite3.IntegrityError:
        conn.close()
        return False

def get_votes(match_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT user_id, team_voted FROM match_votes WHERE match_id = ?", (match_id,))
    rows = c.fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}

def count_team_votes(votes, team):
    return sum(1 for v in votes.values() if v == team)

def clear_match_votes(match_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM match_votes WHERE match_id = ?", (match_id,))
    conn.commit()
    conn.close()


def update_elo(team1, team2, result_team1):
    K = 50
    players = get_all_players()
    elo_t1 = sum(players[p]["elo"] for p in team1) / len(team1)
    elo_t2 = sum(players[p]["elo"] for p in team2) / len(team2)
    delta_t1, delta_t2 = {}, {}

    for p in team1:
        R = players[p]["elo"]
        E = 1 / (1 + 10 ** ((elo_t2 - R) / 400))
        delta = min(30, max(-20, K * (result_team1 - E)))
        delta_t1[p] = int(delta)

    for p in team2:
        R = players[p]["elo"]
        E = 1 / (1 + 10 ** ((elo_t1 - R) / 400))
        delta = min(30, max(-20, K * ((1 - result_team1) - E)))
        delta_t2[p] = int(delta)

    return delta_t1, delta_t2


def find_best_group_of_6():
    waiting = get_waiting_players()
    if len(waiting) < 6:
        return None
    players = get_all_players()
    sorted_players = sorted(waiting, key=lambda uid: players.get(uid, {}).get("elo", 1000))
    best_group, smallest_gap = None, float("inf")
    for i in range(len(sorted_players) - 5):
        group = sorted_players[i:i+6]
        gap = max(players[uid]["elo"] for uid in group) - min(players[uid]["elo"] for uid in group)
        if gap < smallest_gap:
            smallest_gap = gap
            best_group = group
    return best_group

def make_balanced_teams(group6):
    players = get_all_players()
    best_split, best_diff = None, float("inf")
    all_ids = set(group6)
    for combo in itertools.combinations(group6, 3):
        t1, t2 = list(combo), list(all_ids - set(combo))
        diff = abs(sum(players[uid]["elo"] for uid in t1) / 3 - sum(players[uid]["elo"] for uid in t2) / 3)
        if diff < best_diff:
            best_diff = diff
            best_split = (t1, t2)
    return best_split

async def try_launch_matches():
    channel = bot.get_channel(MATCH_CHANNEL_ID)
    if channel is None:
        return

    waiting = get_waiting_players()
    matches = get_all_matches()
    
    while len(waiting) >= 6 and len(matches) < MAX_MATCHES:
        group = find_best_group_of_6()
        if not group:
            break

        remove_from_queue(group)
        team1, team2 = make_balanced_teams(group)
        
        mode = random.choice(list(MAP_POOL.keys()))
        map_name = random.choice(MAP_POOL[mode])
        
        counter = get_match_counter() + 1
        match_name = f"active_match{counter}"
        add_match(match_name, team1, team2, mode, map_name)

        players = get_all_players()
        avg1 = int(sum(players[x]["elo"] for x in team1) / 3)
        avg2 = int(sum(players[x]["elo"] for x in team2) / 3)

        def format_team(team):
            return "\n".join(f"<@{p}> · {players[p]['brawl_id']} · Elo {players[p]['elo']}" for p in team)

        await channel.send(
            f"🎮 **{match_name}** — Match trouvé !\n"
            f"**Mode** : {mode}\n"
            f"**Map** : {map_name}\n\n"
            f"**Équipe 1** (moy. {avg1})\n{format_team(team1)}\n\n"
            f"**Équipe 2** (moy. {avg2})\n{format_team(team2)}"
        )
        
        waiting = get_waiting_players()
        matches = get_all_matches()


@bot.event
async def on_ready():
    init_db()
    await bot.tree.sync()
    players = get_all_players()
    waiting = get_waiting_players()
    matches = get_all_matches()
    print(f"✅ {bot.user} connecté | {len(players)} joueurs | {len(waiting)} en attente | {len(matches)} matchs actifs")


@bot.tree.command(name="inscription", description="S'inscrire au classement Elo avec son ID Brawl Stars")
@app_commands.describe(brawl_id="Ton identifiant Brawl Stars (ex: #ABC123)")
async def inscription(interaction: discord.Interaction, brawl_id: str):
    player = get_player(interaction.user.id)
    if player:
        await interaction.response.send_message(
            f"{interaction.user.name}, tu es déjà inscrit ! Ton Elo : **{player['elo']}**",
            ephemeral=True
        )
        return
    add_player(interaction.user.id, interaction.user.name, brawl_id)
    await interaction.response.send_message(
        f"✅ **{interaction.user.name}** inscrit avec succès !\n"
        f"ID Brawl Stars : `{brawl_id}` · Elo de départ : **1000**"
    )


@bot.tree.command(name="elo", description="Afficher ton Elo actuel")
async def elo(interaction: discord.Interaction):
    player = get_player(interaction.user.id)
    if not player:
        await interaction.response.send_message("Tu n'es pas encore inscrit. Utilise `/inscription` d'abord.", ephemeral=True)
        return
    await interaction.response.send_message(
        f"**{interaction.user.name}** · ID : `{player['brawl_id']}` · Elo : **{player['elo']}**",
        ephemeral=True
    )


@bot.tree.command(name="stats", description="Afficher tes statistiques complètes")
async def stats(interaction: discord.Interaction):
    player = get_player(interaction.user.id)
    if not player:
        await interaction.response.send_message("Tu n'es pas inscrit. Utilise `/inscription` d'abord.", ephemeral=True)
        return
    
    total = player['wins'] + player['losses']
    winrate = (player['wins'] / total * 100) if total > 0 else 0
    streak_text = f"+{player['streak']}" if player['streak'] > 0 else str(player['streak'])
    
    await interaction.response.send_message(
        f"📊 **Statistiques de {interaction.user.name}**\n"
        f"Elo : **{player['elo']}**\n"
        f"Victoires : **{player['wins']}**\n"
        f"Défaites : **{player['losses']}**\n"
        f"Winrate : **{winrate:.1f}%**\n"
        f"Streak : **{streak_text}**",
        ephemeral=True
    )


@bot.tree.command(name="joueurs", description="Afficher tous les joueurs inscrits")
async def joueurs(interaction: discord.Interaction):
    players = get_all_players()
    if not players:
        await interaction.response.send_message("Aucun joueur inscrit pour le moment.", ephemeral=True)
        return
    lignes = [f"**{p['discord_name']}** · `{p['brawl_id']}` · Elo {p['elo']}" for p in players.values()]
    await interaction.response.send_message("📋 **Joueurs inscrits :**\n" + "\n".join(lignes))


@bot.tree.command(name="file", description="Afficher les joueurs en attente d'un match")
async def file(interaction: discord.Interaction):
    waiting = get_waiting_players()
    if not waiting:
        await interaction.response.send_message("Aucun joueur en attente.", ephemeral=True)
        return
    players = get_all_players()
    noms = ", ".join(players[p]["discord_name"] for p in waiting)
    await interaction.response.send_message(f"⏳ **File d'attente** ({len(waiting)} joueur(s)) : {noms}")


@bot.tree.command(name="classement", description="Afficher le top 10 des joueurs par Elo")
async def classement(interaction: discord.Interaction):
    players = get_all_players()
    if not players:
        await interaction.response.send_message("Aucun joueur inscrit.", ephemeral=True)
        return
    top = sorted(players.values(), key=lambda p: p["elo"], reverse=True)[:10]
    medailles = ["🥇", "🥈", "🥉"]
    lignes = [
        f"{medailles[i] if i < 3 else f'`#{i+1}`'} **{p['discord_name']}** — Elo {p['elo']}"
        for i, p in enumerate(top)
    ]
    await interaction.response.send_message("🏆 **Classement Elo**\n" + "\n".join(lignes))


@bot.tree.command(name="leaderboard", description="Afficher le top 10 des joueurs par Elo")
async def leaderboard(interaction: discord.Interaction):
    players = get_all_players()
    if not players:
        await interaction.response.send_message("Aucun joueur inscrit.", ephemeral=True)
        return
    top = sorted(players.values(), key=lambda p: p["elo"], reverse=True)[:10]
    medailles = ["🥇", "🥈", "🥉"]
    lignes = [
        f"{medailles[i] if i < 3 else f'`#{i+1}`'} **{p['discord_name']}** — Elo {p['elo']}"
        for i, p in enumerate(top)
    ]
    await interaction.response.send_message("🏆 **Classement Elo**\n" + "\n".join(lignes))


@bot.tree.command(name="matches", description="Afficher les matchs en cours")
async def matches(interaction: discord.Interaction):
    active_matches = get_all_matches()
    if not active_matches:
        await interaction.response.send_message("Aucun match en cours.", ephemeral=True)
        return
    players = get_all_players()
    lignes = [
        f"**{name}** : [{' · '.join(players[p]['discord_name'] for p in m['team1'])}] ⚔️ [{' · '.join(players[p]['discord_name'] for p in m['team2'])}]"
        for name, m in active_matches.items()
    ]
    await interaction.response.send_message("⚔️ **Matchs en cours :**\n" + "\n".join(lignes))


@bot.tree.command(name="balance", description="Afficher l'équilibre Elo de ton match actif")
async def balance(interaction: discord.Interaction):
    match_id, match_name, match, player_team = get_match_by_player(interaction.user.id)
    
    if not match:
        await interaction.response.send_message("Tu n'es dans aucun match actif.", ephemeral=True)
        return
    
    players = get_all_players()
    avg1 = sum(players[p]["elo"] for p in match["team1"]) / len(match["team1"])
    avg2 = sum(players[p]["elo"] for p in match["team2"]) / len(match["team2"])
    diff = abs(avg1 - avg2)
    
    await interaction.response.send_message(
        f"⚖️ **Balance du match {match_name}**\n"
        f"**Équipe 1** : {int(avg1)} Elo (moy.)\n"
        f"**Équipe 2** : {int(avg2)} Elo (moy.)\n"
        f"**Différence** : {int(diff)} Elo",
        ephemeral=True
    )


@bot.tree.command(name="predict", description="Prédire le gagnant de ton match actif")
async def predict(interaction: discord.Interaction):
    match_id, match_name, match, player_team = get_match_by_player(interaction.user.id)
    
    if not match:
        await interaction.response.send_message("Tu n'es dans aucun match actif.", ephemeral=True)
        return
    
    players = get_all_players()
    avg1 = sum(players[p]["elo"] for p in match["team1"]) / len(match["team1"])
    avg2 = sum(players[p]["elo"] for p in match["team2"]) / len(match["team2"])
    
    prob1 = 1 / (1 + 10 ** ((avg2 - avg1) / 400))
    prob2 = 1 - prob1
    
    await interaction.response.send_message(
        f"🔮 **Prédiction pour {match_name}**\n"
        f"**Équipe 1** : {prob1 * 100:.1f}% de chances de gagner\n"
        f"**Équipe 2** : {prob2 * 100:.1f}% de chances de gagner",
        ephemeral=True
    )


@bot.tree.command(name="maps", description="Afficher la liste des maps par mode")
async def maps(interaction: discord.Interaction):
    lignes = []
    for mode, map_list in MAP_POOL.items():
        lignes.append(f"**{mode}** :")
        lignes.append("  " + ", ".join(map_list))
    await interaction.response.send_message("🗺️ **Maps disponibles**\n\n" + "\n".join(lignes))


@bot.tree.command(name="join", description="Rejoindre la file d'attente (seul ou avec jusqu'à 2 coéquipiers)")
@app_commands.describe(
    joueur2="Mentionne ton 2e coéquipier (optionnel)",
    joueur3="Mentionne ton 3e coéquipier (optionnel)"
)
async def join(interaction: discord.Interaction, joueur2: discord.Member = None, joueur3: discord.Member = None):
    if not get_player(interaction.user.id):
        await interaction.response.send_message("Tu n'es pas inscrit. Utilise `/inscription` d'abord.", ephemeral=True)
        return

    team = [interaction.user.id]
    for membre in [joueur2, joueur3]:
        if membre is None:
            continue
        if not get_player(membre.id):
            await interaction.response.send_message(f"**{membre.name}** n'est pas inscrit.", ephemeral=True)
            return
        if membre.id not in team:
            team.append(membre.id)

    for p in team:
        if is_in_queue(p):
            players = get_all_players()
            await interaction.response.send_message(f"**{players[p]['discord_name']}** est déjà dans la file !", ephemeral=True)
            return

    add_to_queue(team)
    players = get_all_players()
    waiting = get_waiting_players()
    noms = ", ".join(players[p]["discord_name"] for p in team)
    en_attente = ", ".join(players[p]["discord_name"] for p in waiting)
    await interaction.response.send_message(
        f"✅ **{noms}** ajouté(s) à la file !\n"
        f"⏳ En attente ({len(waiting)}/6) : {en_attente}"
    )
    await try_launch_matches()


@bot.tree.command(name="leave", description="Quitter la file d'attente")
async def leave(interaction: discord.Interaction):
    if not is_in_queue(interaction.user.id):
        await interaction.response.send_message("Tu n'es pas dans la file d'attente.", ephemeral=True)
        return
    remove_from_queue([interaction.user.id])
    await interaction.response.send_message(f"👋 **{interaction.user.name}** a quitté la file d'attente.")


@bot.tree.command(name="clearqueue", description="Vider la file d'attente (admin uniquement)")
@app_commands.checks.has_any_role(ADMIN_ROLE_ID)
async def clearqueue(interaction: discord.Interaction):
    clear_queue()
    await interaction.response.send_message("✅ File d'attente vidée.")

@clearqueue.error
async def clearqueue_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingAnyRole):
        await interaction.response.send_message("❌ Tu n'as pas les permissions nécessaires.", ephemeral=True)


@bot.tree.command(name="report", description="Voter pour le résultat de ton match")
@app_commands.describe(resultat="Choisis le résultat de ton match")
@app_commands.choices(resultat=[
    app_commands.Choice(name="Victoire", value="victoire"),
    app_commands.Choice(name="Défaite",  value="defaite"),
])
async def report(interaction: discord.Interaction, resultat: str):
    match_id, match_name, match, player_team = get_match_by_player(interaction.user.id)
    
    if not match:
        await interaction.response.send_message("Tu n'es dans aucun match actif.", ephemeral=True)
        return
    
    team_to_vote = player_team if resultat == "victoire" else ("team2" if player_team == "team1" else "team1")
    
    vote_success = add_vote(match_id, interaction.user.id, team_to_vote)
    if not vote_success:
        await interaction.response.send_message("❌ Tu as déjà voté pour ce match !", ephemeral=True)
        return
    
    votes = get_votes(match_id)
    team1_votes = count_team_votes(votes, "team1")
    team2_votes = count_team_votes(votes, "team2")
    
    await interaction.response.send_message(
        f"✅ Vote enregistré pour {'victoire' if resultat == 'victoire' else 'défaite'} !\n"
        f"Votes Équipe 1 : **{team1_votes}/2**\n"
        f"Votes Équipe 2 : **{team2_votes}/2**"
    )
    
    if team1_votes >= 2 or team2_votes >= 2:
        if not finish_match(match_id):
            return
        
        result_team1 = 1 if team1_votes >= 2 else 0
        
        delta_t1, delta_t2 = update_elo(match["team1"], match["team2"], result_team1)
        
        for p in match["team1"]:
            update_player_stats(p, delta_t1[p], result_team1 == 1)
        for p in match["team2"]:
            update_player_stats(p, delta_t2[p], result_team1 == 0)
        
        clear_match_votes(match_id)
        
        players = get_all_players()
        def format_result(team, deltas):
            return "\n".join(
                f"**{players[p]['discord_name']}** : {players[p]['elo']} Elo ({'+'if deltas[p]>0 else ''}{deltas[p]})"
                for p in team
            )
        
        channel = bot.get_channel(MATCH_CHANNEL_ID)
        if channel:
            await channel.send(
                f"🏁 **{match_name}** terminé !\n\n"
                f"**Équipe 1** :\n{format_result(match['team1'], delta_t1)}\n\n"
                f"**Équipe 2** :\n{format_result(match['team2'], delta_t2)}"
            )
        
        await try_launch_matches()


@bot.tree.command(name="setelo", description="Modifier manuellement l'Elo d'un joueur (réservé aux gérants)")
@app_commands.describe(
    membre="Le joueur dont tu veux modifier l'Elo",
    nouvel_elo="La nouvelle valeur d'Elo à attribuer"
)
@app_commands.checks.has_any_role("〃Developper")
async def setelo(interaction: discord.Interaction, membre: discord.Member, nouvel_elo: int):
    player = get_player(membre.id)
    if not player:
        await interaction.response.send_message(f"**{membre.name}** n'est pas inscrit.", ephemeral=True)
        return
    ancien_elo = player["elo"]
    update_player_elo(membre.id, nouvel_elo)
    await interaction.response.send_message(f"✅ Elo de **{membre.name}** modifié : {ancien_elo} → **{nouvel_elo}**")

@setelo.error
async def setelo_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingAnyRole):
        await interaction.response.send_message("❌ Tu n'as pas les permissions nécessaires.", ephemeral=True)


if not TOKEN:
    print("❌ ERREUR : Crée un fichier .env avec TOKEN=ton_token_discord")
else:
    bot.run(TOKEN)
