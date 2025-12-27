import discord
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("TOKEN")

if not TOKEN:
    raise RuntimeError("TOKEN manquant dans le fichier .env")


intents = discord.Intents.default()
intents.members = True
intents.guilds = True

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"🟢 Bot connecté : {client.user}")
    print(f"📊 Serveurs détectés : {len(client.guilds)}\n")
    
    # Parcourt tous les serveurs
    for guild in client.guilds:
        print(f"📥 Récupération de {guild.name} ({guild.member_count} membres)...")
        
        member_ids = []
        
        # Récupère tous les membres
        async for member in guild.fetch_members(limit=None):
            member_ids.append(str(member.id))
        
        # Génère le nom du fichier
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"ids_{guild.name.replace(' ', '_')}_{timestamp}.txt"
        
        # Sauvegarde dans un fichier texte
        with open(filename, 'w', encoding='utf-8') as f:
            f.write('\n'.join(member_ids))
        
        print(f"✅ {len(member_ids)} IDs sauvegardés dans {filename}\n")
    
    print("🎉 Terminé ! Fermeture du bot...")
    await client.close()

try:
    client.run(TOKEN)
except KeyboardInterrupt:
    print("\n👋 Arrêt du bot")
except Exception as e:
    print(f"❌ Erreur : {e}")