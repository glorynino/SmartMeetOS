import discord
import os
import threading
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("TOKEN")

if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN manquant")

#HERE U PUT THE ID   USER_ID =   

intents = discord.Intents.default()
client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f"🟢 Bot connecté : {client.user}")

    def console_input():
        while True:
            msg = input("YOU > ")
            if msg.strip():
                # On fetch l'utilisateur à chaque fois pour être sûr
                async def send_dm():
                    user = await client.fetch_user(USER_ID)
                    await user.send(msg)
                    print("BOT → DM envoyé")
                client.loop.create_task(send_dm())

    threading.Thread(target=console_input, daemon=True).start()

@client.event
async def on_message(message):
    # Écouter uniquement les DMs venant de l'utilisateur cible
    if isinstance(message.channel, discord.DMChannel) and message.author.id == USER_ID:
        print(f"\nUSER > {message.content}\nYOU > ", end="")

client.run(TOKEN)
