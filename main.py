import discord
from discord import app_commands
from discord.ext import commands
import itertools
import json
import os
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="/", intents=intents)

players = {}
waiting_players = []
active_matches = {}
MAX_MATCHES = 3
match_counter = 0
MATCH_CHANNEL_ID = 1495481849189892197

PLAYERS_FILE = "players.json"
WAITING_FILE = "waiting.json"
MATCHES_FILE = "matches.json"


def save_players():
    with open(PLAYERS_FILE, "w", encoding="utf-8") as f:
        json.dump({str(k): v for k, v in players.items()}, f, ensure_ascii=False, indent=2)

def save_waiting():
    with open(WAITING_FILE, "w", encoding="utf-8") as f:
        json.dump(waiting_players, f, ensure_ascii=False, indent=2)

def save_matches():
    with open(MATCHES_FILE, "w", encoding="utf-8") as f:
        json.dump(active_matches, f, ensure_ascii=False, indent=2)

def load_players():
    global players
    try:
        with open(PLAYERS_FILE, "r", encoding="utf-8") as f:
            players = {int(k): v for k, v in json.load(f).items()}
    except FileNotFoundError:
        players = {}

def load_waiting():
    global waiting_players
    try:
        with open(WAITING_FILE, "r", encoding="utf-8") as f:
            waiting_players[:] = [int(x) for x in json.load(f)]
    except FileNotFoundError:
        waiting_players = []

def load_matches():
    global active_matches
    try:
        with open(MATCHES_FILE, "r", encoding="utf-8") as f:
            active_matches = json.load(f)
            for m in active_matches.values():
                m["team1"] = [int(x) for x in m.get("team1", [])]
                m["team2"] = [int(x) for x in m.get("team2", [])]
    except FileNotFoundError:
        active_matches = {}

def init_match_counter():
    global match_counter
    max_seen = 0
    for key in active_matches.keys():
        if key.startswith("active_match"):
            try:
                n = int(key.replace("active_match", ""))
                if n > max_seen:
                    max_seen = n
            except ValueError:
                continue
    match_counter = max_seen


def update_elo(team1, team2, result_team1):
    K = 50
    elo_t1 = sum(players[p]["elo"] for p in team1) / len(team1)
    elo_t2 = sum(players[p]["elo"] for p in team2) / len(team2)
    delta_t1, delta_t2 = {}, {}

    for p in team1:
        R = players[p]["elo"]
        E = 1 / (1 + 10 ** ((elo_t2 - R) / 400))
        delta = min(30, max(-20, K * (result_team1 - E)))
        players[p]["elo"] = int(R + delta)
        delta_t1[p] = int(delta)

    for p in team2:
        R = players[p]["elo"]
        E = 1 / (1 + 10 ** ((elo_t1 - R) / 400))
        delta = min(30, max(-20, K * ((1 - result_team1) - E)))
        players[p]["elo"] = int(R + delta)
        delta_t2[p] = int(delta)

    save_players()
    return delta_t1, delta_t2


def find_best_group_of_6():
    if len(waiting_players) < 6:
        return None
    sorted_players = sorted(waiting_players, key=lambda uid: players.get(uid, {}).get("elo", 1000))
    best_group, smallest_gap = None, float("inf")
    for i in range(len(sorted_players) - 5):
        group = sorted_players[i:i+6]
        gap = max(players[uid]["elo"] for uid in group) - min(players[uid]["elo"] for uid in group)
        if gap < smallest_gap:
            smallest_gap = gap
            best_group = group
    return best_group

def make_balanced_teams(group6):
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
    global match_counter
    channel = bot.get_channel(MATCH_CHANNEL_ID)
    if channel is None:
        return

    while len(waiting_players) >= 6 and len(active_matches) < MAX_MATCHES:
        group = find_best_group_of_6()
        if not group:
            break

        for uid in group:
            waiting_players.remove(uid)

        team1, team2 = make_balanced_teams(group)
        match_counter += 1
        match_name = f"active_match{match_counter}"
        active_matches[match_name] = {"team1": team1, "team2": team2}
        save_waiting()
        save_matches()

        avg1 = int(sum(players[x]["elo"] for x in team1) / 3)
        avg2 = int(sum(players[x]["elo"] for x in team2) / 3)

        def format_team(team):
            return "\n".join(f"<@{p}> · {players[p]['brawl_id']} · Elo {players[p]['elo']}" for p in team)

        await channel.send(
            f"🎮 **{match_name}** — Match trouvé !\n\n"
            f"**Équipe 1** (moy. {avg1})\n{format_team(team1)}\n\n"
            f"**Équipe 2** (moy. {avg2})\n{format_team(team2)}"
        )


@bot.event
async def on_ready():
    load_players()
    load_waiting()
    load_matches()
    init_match_counter()
    await bot.tree.sync()
    print(f"✅ {bot.user} connecté | {len(players)} joueurs | {len(waiting_players)} en attente | {len(active_matches)} matchs actifs")


@bot.tree.command(name="inscription", description="S'inscrire au classement Elo avec son ID Brawl Stars")
@app_commands.describe(brawl_id="Ton identifiant Brawl Stars (ex: #ABC123)")
async def inscription(interaction: discord.Interaction, brawl_id: str):
    if interaction.user.id in players:
        await interaction.response.send_message(
            f"{interaction.user.name}, tu es déjà inscrit ! Ton Elo : **{players[interaction.user.id]['elo']}**",
            ephemeral=True
        )
        return
    players[interaction.user.id] = {"discord_name": interaction.user.name, "brawl_id": brawl_id, "elo": 1000}
    save_players()
    await interaction.response.send_message(
        f"✅ **{interaction.user.name}** inscrit avec succès !\n"
        f"ID Brawl Stars : `{brawl_id}` · Elo de départ : **1000**"
    )


@bot.tree.command(name="elo", description="Afficher ton Elo actuel")
async def elo(interaction: discord.Interaction):
    if interaction.user.id not in players:
        await interaction.response.send_message("Tu n'es pas encore inscrit. Utilise `/inscription` d'abord.", ephemeral=True)
        return
    p = players[interaction.user.id]
    await interaction.response.send_message(
        f"**{interaction.user.name}** · ID : `{p['brawl_id']}` · Elo : **{p['elo']}**",
        ephemeral=True
    )


@bot.tree.command(name="joueurs", description="Afficher tous les joueurs inscrits")
async def joueurs(interaction: discord.Interaction):
    if not players:
        await interaction.response.send_message("Aucun joueur inscrit pour le moment.", ephemeral=True)
        return
    lignes = [f"**{p['discord_name']}** · `{p['brawl_id']}` · Elo {p['elo']}" for p in players.values()]
    await interaction.response.send_message("📋 **Joueurs inscrits :**\n" + "\n".join(lignes))


@bot.tree.command(name="file", description="Afficher les joueurs en attente d'un match")
async def file(interaction: discord.Interaction):
    if not waiting_players:
        await interaction.response.send_message("Aucun joueur en attente.", ephemeral=True)
        return
    noms = ", ".join(players[p]["discord_name"] for p in waiting_players)
    await interaction.response.send_message(f"⏳ **File d'attente** ({len(waiting_players)} joueur(s)) : {noms}")


@bot.tree.command(name="classement", description="Afficher le top 10 des joueurs par Elo")
async def classement(interaction: discord.Interaction):
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
    if not active_matches:
        await interaction.response.send_message("Aucun match en cours.", ephemeral=True)
        return
    lignes = [
        f"**{name}** : [{' · '.join(players[p]['discord_name'] for p in m['team1'])}] ⚔️ [{' · '.join(players[p]['discord_name'] for p in m['team2'])}]"
        for name, m in active_matches.items()
    ]
    await interaction.response.send_message("⚔️ **Matchs en cours :**\n" + "\n".join(lignes))


@bot.tree.command(name="join", description="Rejoindre la file d'attente (seul ou avec jusqu'à 2 coéquipiers)")
@app_commands.describe(
    joueur2="Mentionne ton 2e coéquipier (optionnel)",
    joueur3="Mentionne ton 3e coéquipier (optionnel)"
)
async def join(interaction: discord.Interaction, joueur2: discord.Member = None, joueur3: discord.Member = None):
    if interaction.user.id not in players:
        await interaction.response.send_message("Tu n'es pas inscrit. Utilise `/inscription` d'abord.", ephemeral=True)
        return

    team = [interaction.user.id]
    for membre in [joueur2, joueur3]:
        if membre is None:
            continue
        if membre.id not in players:
            await interaction.response.send_message(f"**{membre.name}** n'est pas inscrit.", ephemeral=True)
            return
        if membre.id not in team:
            team.append(membre.id)

    for p in team:
        if p in waiting_players:
            await interaction.response.send_message(f"**{players[p]['discord_name']}** est déjà dans la file !", ephemeral=True)
            return

    waiting_players.extend(team)
    save_waiting()

    noms = ", ".join(players[p]["discord_name"] for p in team)
    en_attente = ", ".join(players[p]["discord_name"] for p in waiting_players)
    await interaction.response.send_message(
        f"✅ **{noms}** ajouté(s) à la file !\n"
        f"⏳ En attente ({len(waiting_players)}/6) : {en_attente}"
    )
    await try_launch_matches()


@bot.tree.command(name="leave", description="Quitter la file d'attente")
async def leave(interaction: discord.Interaction):
    if interaction.user.id not in waiting_players:
        await interaction.response.send_message("Tu n'es pas dans la file d'attente.", ephemeral=True)
        return
    waiting_players.remove(interaction.user.id)
    save_waiting()
    await interaction.response.send_message(f"👋 **{interaction.user.name}** a quitté la file d'attente.")


@bot.tree.command(name="endmatch", description="Déclarer le résultat de ton match en cours")
@app_commands.describe(resultat="Choisis le résultat de ton match")
@app_commands.choices(resultat=[
    app_commands.Choice(name="Victoire", value="victoire"),
    app_commands.Choice(name="Défaite",  value="defaite"),
])
async def endmatch(interaction: discord.Interaction, resultat: str):
    user_id = interaction.user.id
    match_found, player_team = None, None

    for match_name, match in active_matches.items():
        if user_id in match["team1"]:
            match_found, player_team = match_name, "team1"
            break
        if user_id in match["team2"]:
            match_found, player_team = match_name, "team2"
            break

    if not match_found:
        await interaction.response.send_message("Tu n'es dans aucun match actif.", ephemeral=True)
        return

    match = active_matches.pop(match_found)
    result_team1 = 1 if (resultat == "victoire" and player_team == "team1") or \
                        (resultat == "defaite"  and player_team == "team2") else 0

    delta_t1, delta_t2 = update_elo(match["team1"], match["team2"], result_team1)
    save_matches()

    def format_result(team, deltas):
        return "\n".join(
            f"**{players[p]['discord_name']}** : {players[p]['elo']} Elo ({'+'if deltas[p]>0 else ''}{deltas[p]})"
            for p in team
        )

    await interaction.response.send_message(
        f"🏁 **{match_found}** terminé !\n\n"
        f"**Équipe 1** :\n{format_result(match['team1'], delta_t1)}\n\n"
        f"**Équipe 2** :\n{format_result(match['team2'], delta_t2)}"
    )
    await try_launch_matches()


@bot.tree.command(name="setelo", description="Modifier manuellement l'Elo d'un joueur (réservé aux gérants)")
@app_commands.describe(
    membre="Le joueur dont tu veux modifier l'Elo",
    nouvel_elo="La nouvelle valeur d'Elo à attribuer"
)
@app_commands.checks.has_role("〃Developper")
async def setelo(interaction: discord.Interaction, membre: discord.Member, nouvel_elo: int):
    if membre.id not in players:
        await interaction.response.send_message(f"**{membre.name}** n'est pas inscrit.", ephemeral=True)
        return
    ancien_elo = players[membre.id]["elo"]
    players[membre.id]["elo"] = nouvel_elo
    save_players()
    await interaction.response.send_message(f"✅ Elo de **{membre.name}** modifié : {ancien_elo} → **{nouvel_elo}**")

@setelo.error
async def setelo_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingRole):
        await interaction.response.send_message("❌ Tu n'as pas le rôle dev.", ephemeral=True)


if not TOKEN:
    print("❌ ERREUR : Crée un fichier .env avec TOKEN=ton_token_discord")
else:
    bot.run(TOKEN)