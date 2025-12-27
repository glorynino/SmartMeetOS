"""Test ultra-simple de connexion Discord"""

import os
import discord
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

if not TOKEN:
    print("❌ DISCORD_TOKEN manquant dans .env")
    exit(1)

print(f"✅ Token trouvé : {TOKEN[:20]}...")

# Intents nécessaires
intents = discord.Intents.default()
intents.message_content = True
intents.messages = True
intents.dm_messages = True

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print("\n" + "="*60)
    print(f"✅ BOT CONNECTÉ AVEC SUCCÈS !")
    print("="*60)
    print(f"Nom : {client.user.name}")
    print(f"ID  : {client.user.id}")
    print(f"\n🔗 URL d'invitation :")
    print(f"https://discord.com/api/oauth2/authorize?client_id={client.user.id}&permissions=2048&scope=bot")
    print("\n📨 Envoie un message privé au bot pour tester !")
    print("="*60 + "\n")

@client.event
async def on_message(message):
    # Ignore les messages du bot
    if message.author == client.user:
        return
    
    # Messages privés (DM)
    if isinstance(message.channel, discord.DMChannel):
        print(f"\n📩 MESSAGE REÇU !")
        print(f"De : {message.author.name} (ID: {message.author.id})")
        print(f"Contenu : {message.content}")
        
        # Répond automatiquement
        await message.channel.send(f"✅ Message reçu : '{message.content}'")
        print(f"✅ Réponse envoyée\n")

print("\n🚀 Démarrage du bot de test...\n")

try:
    client.run(TOKEN)
except discord.LoginFailure:
    print("\n❌ ERREUR : Token Discord invalide")
    print("Vérifie ton .env et le token sur https://discord.com/developers/applications")
except discord.PrivilegedIntentsRequired:
    print("\n❌ ERREUR : Intents manquants")
    print("Va sur https://discord.com/developers/applications")
    print("Bot → Privileged Gateway Intents → Active MESSAGE CONTENT INTENT")
except KeyboardInterrupt:
    print("\n👋 Arrêt du test")
except Exception as e:
    print(f"\n❌ ERREUR : {e}")
    import traceback
    traceback.print_exc()