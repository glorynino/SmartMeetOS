import discord
import os
import asyncio
from typing import Optional, Dict, Callable, Any
from dotenv import load_dotenv

class DiscordClient:
    def __init__(self, token: str = None):
        """
        Initialise le client Discord avec les intents nécessaires.
        Si aucun token n'est fourni, il sera chargé depuis les variables d'environnement.
        """
        load_dotenv()
        self.token = token or os.getenv("DISCORD_TOKEN")
        if not self.token:
            raise ValueError(
                "Le token Discord est requis. "
                "Soit en paramètre, soit dans DISCORD_TOKEN (.env)"
            )
        
        # ⚠️ CORRECTION : Ajoute message_content intent
        intents = discord.Intents.default()
        intents.message_content = True  # ← CRITIQUE pour lire les messages
        intents.messages = True
        intents.dm_messages = True
        
        self.client = discord.Client(intents=intents)
        self.user_cache: Dict[int, discord.User] = {}
        self.message_handlers: Dict[str, Callable] = {}

    async def _get_user(self, user_id: int) -> Optional[discord.User]:
        """Récupère un utilisateur par son ID avec cache"""
        if user_id not in self.user_cache:
            try:
                self.user_cache[user_id] = await self.client.fetch_user(user_id)
            except discord.NotFound:
                return None
            except Exception as e:
                print(f"❌ Erreur fetch user {user_id}: {e}")
                return None
        return self.user_cache[user_id]

    async def send_direct_message(self, user_id: int, message: str) -> bool:
        """
        Envoie un message direct à un utilisateur Discord
        
        Args:
            user_id: L'ID Discord de l'utilisateur
            message: Le message à envoyer
            
        Returns:
            bool: True si le message a été envoyé avec succès, False sinon
        """
        user = await self._get_user(user_id)
        if not user:
            print(f"❌ Impossible de trouver l'utilisateur avec l'ID {user_id}")
            return False
            
        try:
            await user.send(message)
            # Note: user.discriminator peut être "0" pour les nouveaux usernames
            username = f"{user.name}" if user.discriminator == "0" else f"{user.name}#{user.discriminator}"
            print(f"✅ Message envoyé à {username}")
            return True
        except discord.Forbidden:
            print(f"❌ Messages privés désactivés pour {user.name}")
            return False
        except discord.HTTPException as e:
            print(f"❌ Erreur HTTP lors de l'envoi: {e}")
            return False
        except Exception as e:
            print(f"❌ Erreur inattendue: {e}")
            return False

    def register_message_handler(self, handler_name: str, callback: Callable):
        """
        Enregistre un gestionnaire de messages pour un type spécifique de message
        
        Args:
            handler_name: Le nom du gestionnaire
            callback: La fonction à appeler quand un message est reçu (async)
        """
        self.message_handlers[handler_name] = callback

    async def _on_message(self, message):
        """Gestionnaire interne des messages entrants"""
        # Ignore les messages du bot lui-même
        if message.author == self.client.user:
            return

        # Si c'est un message privé
        if isinstance(message.channel, discord.DMChannel):
            user_id = message.author.id
            content = message.content
            
            # Notifier tous les gestionnaires enregistrés
            for handler_name, callback in self.message_handlers.items():
                try:
                    await callback(user_id, content)
                except Exception as e:
                    print(f"❌ Erreur dans le gestionnaire '{handler_name}': {e}")
                    import traceback
                    traceback.print_exc()

    async def start_async(self):
        """Démarre le client Discord en mode async"""
        @self.client.event
        async def on_ready():
            print(f"🟢 Connecté en tant que {self.client.user}")
            print(f"📊 Bot ID: {self.client.user.id}")
            print(f"🔗 Invite: https://discord.com/api/oauth2/authorize?client_id={self.client.user.id}&permissions=2048&scope=bot")

        @self.client.event
        async def on_message(message):
            await self._on_message(message)

        await self.client.start(self.token)

    def start(self):
        """Démarre le client Discord (mode synchrone, bloquant)"""
        @self.client.event
        async def on_ready():
            print(f"🟢 Connecté en tant que {self.client.user}")

        @self.client.event
        async def on_message(message):
            await self._on_message(message)

        self.client.run(self.token)

    async def close(self):
        """Ferme la connexion au client Discord"""
        await self.client.close()

# Exemple d'utilisation
if __name__ == "__main__":
    # Test simple
    async def test():
        client = DiscordClient()
        
        async def handle_message(user_id: int, content: str):
            print(f"📩 Message de {user_id}: {content}")
            
            if "ping" in content.lower():
                await client.send_direct_message(user_id, "Pong! 🏓")
        
        client.register_message_handler("test_handler", handle_message)
        
        await client.start_async()
    
    asyncio.run(test())