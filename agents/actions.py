# agents/actions.py
"""
Système COMPLET utilisant 100% des capacités LangChain :
- Agents autonomes avec tool calling
- Memory (historique des transcriptions)
- Chains complexes
- Orchestration automatique
- Callbacks pour observabilité
"""

import os
import sys
from pathlib import Path
import asyncio
from typing import Dict, List, Optional, Any
from datetime import datetime
from dotenv import load_dotenv

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services.discord_client import DiscordClient
from typing import cast

# LangChain COMPLET - Imports pour version 1.2.x
from langchain_mistralai import ChatMistralAI
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.messages import HumanMessage, AIMessage, SystemMessage
from langchain_core.tools import tool
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.runnables import RunnablePassthrough, RunnableSequence

# Pour LangChain 1.2.x, on utilise LangGraph
try:
    from langgraph.prebuilt import create_react_agent
    USING_LANGGRAPH = True
    print("✅ Utilisation de LangGraph (version 1.2.x)")
except ImportError:
    USING_LANGGRAPH = False
    print("⚠️ LangGraph non disponible")

# Memory locale (plus fiable)
class ConversationBufferMemory:
    def __init__(self, memory_key="chat_history", return_messages=False):
        self.memory_key = memory_key
        self.return_messages = return_messages
        self.buffer = []

    def add_message(self, message):
        self.buffer.append(message)

    def save_context(self, inputs, outputs):
        self.buffer.append({"input": inputs, "output": outputs})

    def load_memory_variables(self, inputs):
        if self.return_messages:
            return {self.memory_key: self.buffer.copy()}
        else:
            return {self.memory_key: "\n".join(str(m) for m in self.buffer)}

from pydantic import BaseModel, Field

load_dotenv()

# STUDENT_ID = tu m'es L'id de la personne que tu veux notifier

# État global Discord (typé correctement)
discord_client_instance: Optional[DiscordClient] = None

# ============================================
# CALLBACK HANDLER (Observabilité)
# ============================================

class SmartMeetOSCallbackHandler(BaseCallbackHandler):
    """
    Callback pour observer TOUT ce que fait l'agent en temps réel.
    C'est une feature clé de LangChain pour le debugging et monitoring.
    """
    
    def on_llm_start(self, serialized: Dict[str, Any], prompts: List[str], **kwargs) -> None:
        """Appelé quand le LLM commence à réfléchir"""
        print("\n🧠 LLM Start : L'agent réfléchit...")
    
    def on_llm_end(self, response, **kwargs) -> None:
        """Appelé quand le LLM a fini de réfléchir"""
        print("✅ LLM End : Réflexion terminée")
    
    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **kwargs) -> None:
        """Appelé quand un tool est appelé"""
        tool_name = serialized.get("name", "unknown")
        print(f"\n🔧 Tool Start : {tool_name}")
        print(f"   Input : {input_str[:100]}...")
    
    def on_tool_end(self, output: str, **kwargs) -> None:
        """Appelé quand un tool a terminé"""
        print(f"✅ Tool End : {output[:100]}...")
    
    def on_agent_action(self, action, **kwargs) -> None:
        """Appelé quand l'agent décide d'une action"""
        print(f"\n🎯 Agent Action : {action.tool}")
        print(f"   Reasoning : {str(action.log)[:200]}...")
    
    def on_agent_finish(self, finish, **kwargs) -> None:
        """Appelé quand l'agent termine"""
        print(f"\n🏁 Agent Finish : {str(finish.return_values.get('output', ''))[:200]}...")

# ============================================
# MODÈLES PYDANTIC POUR STRUCTURED OUTPUT
# ============================================

class TranscriptAnalysisResult(BaseModel):
    """Résultat structuré de l'analyse"""
    has_important_info: bool = Field(description="Y a-t-il des infos importantes ?")
    event_type: str = Field(
        description="Type principal d'événement",
        pattern="^(meeting|exam|test|deadline|homework|announcement|other|none)$"
    )
    urgency: str = Field(
        description="Niveau d'urgence global",
        pattern="^(high|medium|low|none)$"
    )
    key_points: List[str] = Field(description="Points clés à retenir")
    summary: str = Field(description="Résumé en une phrase")
    confidence: float = Field(ge=0.0, le=1.0, description="Confiance de l'analyse")
    date_mentioned: Optional[str] = Field(default=None, description="Date mentionnée si présente")
    time_mentioned: Optional[str] = Field(default=None, description="Heure mentionnée si présente")

# ============================================
# TOOLS LANGCHAIN
# ============================================

@tool
def analyze_transcript_deep(transcript: str) -> dict:
    """
    Analyse en profondeur une transcription avec un LLM dédié.
    Ce tool utilise LUI-MÊME un LLM pour l'analyse (multi-agent pattern).
    
    Args:
        transcript: La transcription à analyser
        
    Returns:
        Analyse structurée avec événements détectés
    """
    print(f"🔍 Tool: Analyse profonde de {len(transcript)} caractères...")
    
    # Ce tool utilise son PROPRE LLM (pattern multi-agent)
    analyzer_llm = ChatMistralAI(
        model_name="mistral-large-latest",  # model_name au lieu de model
        api_key=os.getenv("MISTRAL_API_KEY"),
        temperature=0.1
    )
    
    # Chain spécialisée pour l'analyse
    analyzer_prompt = ChatPromptTemplate.from_messages([
        ("system", """Tu es un expert en analyse de transcriptions éducatives.

Analyse cette transcription et identifie :
- Type d'événement (meeting, exam, test, deadline, etc.)
- Niveau d'urgence (high, medium, low)
- Points clés importants
- Dates et heures mentionnées

Important : meetings, examens, deadlines = high priority
Bavardage, discussions informelles = low priority ou none

Retourne un JSON structuré."""),
        ("human", "{transcript}")
    ])
    
    chain = analyzer_prompt | analyzer_llm
    result = chain.invoke({"transcript": transcript})
    
    # Parse la réponse
    import json
    try:
        # Tente de parser le JSON
        content = result.content if isinstance(result.content, str) else str(result.content)
        
        # Nettoie les backticks markdown si présents
        if "```json" in content:
            parts = content.split("```json")
            if len(parts) > 1:
                content = parts[1].split("```")[0]
        elif "```" in content:
            parts = content.split("```")
            if len(parts) > 1:
                content = parts[1].split("```")[0]
        
        analysis = json.loads(content.strip())
        
        # Valide la structure
        if not all(k in analysis for k in ["has_important_info", "event_type", "urgency", "summary"]):
            raise ValueError("Structure JSON incomplète")
        
        return analysis
    
    except Exception as e:
        print(f"⚠️  Erreur parsing, analyse par défaut : {e}")
        # Fallback : analyse simple par mots-clés
        keywords_high = ["meeting", "réunion", "exam", "interro", "urgent", "deadline"]
        keywords_med = ["homework", "devoir", "projet", "rendu"]
        
        has_important = any(k in transcript.lower() for k in keywords_high + keywords_med)
        
        if any(k in transcript.lower() for k in keywords_high):
            urgency = "high"
            event_type = "meeting" if "meeting" in transcript.lower() else "exam"
        elif any(k in transcript.lower() for k in keywords_med):
            urgency = "medium"
            event_type = "homework"
        else:
            urgency = "none"
            event_type = "none"
        
        return {
            "has_important_info": has_important,
            "event_type": event_type,
            "urgency": urgency,
            "key_points": ["Analyse automatique par mots-clés"],
            "summary": "Analyse rapide de la transcription",
            "confidence": 0.7,
            "date_mentioned": None,
            "time_mentioned": None
        }

@tool
def check_previous_transcripts(query: str) -> str:
    """
    Vérifie les transcriptions précédentes pour contexte.
    Utilise la MEMORY de LangChain.
    
    Args:
        query: Ce qu'on cherche dans l'historique
        
    Returns:
        Contexte des transcriptions précédentes
    """
    print(f"📚 Tool: Recherche dans l'historique : '{query}'")
    
    # Ici tu pourrais utiliser un vector store (Chroma, Pinecone, etc.)
    # Pour l'instant, simulation simple
    
    return "Aucune transcription similaire récente trouvée."

@tool
async def send_discord_notification(user_id: int, message: str, urgency: str = "medium") -> str:
    """
    Envoie une notification Discord à un élève.
    
    Args:
        user_id: ID Discord de l'élève
        message: Message à envoyer
        urgency: Niveau d'urgence (high, medium, low)
        
    Returns:
        Statut de l'envoi
    """
    print(f"📨 Tool: Envoi Discord (urgence: {urgency})")
    
    if not discord_client_instance:
        return "❌ Discord non initialisé"
    
    # Ajoute un badge d'urgence au message
    if urgency == "high":
        message = f"🚨 **URGENT** 🚨\n\n{message}"
    elif urgency == "medium":
        message = f"📌 **Important**\n\n{message}"
    
    try:
        success = await discord_client_instance.send_direct_message(user_id, message)
        if success:
            return f"✅ Notification envoyée à {user_id}"
        else:
            return f"❌ Échec d'envoi à {user_id}"
    except Exception as e:
        return f"❌ Erreur : {str(e)}"

@tool
def format_for_student(analysis: dict) -> str:
    """
    Formate une analyse en message clair pour un élève.
    
    Args:
        analysis: Résultat de l'analyse
        
    Returns:
        Message formaté et clair
    """
    print("✏️  Tool: Formatage du message pour l'élève")
    
    event_icons = {
        "meeting": "📅",
        "exam": "📝",
        "test": "✍️",
        "deadline": "⏰",
        "homework": "📚",
        "announcement": "📢",
        "other": "📌",
        "none": "💬"
    }
    
    icon = event_icons.get(analysis.get("event_type", "none"), "📌")
    
    message = f"{icon} **{analysis.get('summary', 'Nouvelle information')}**\n\n"
    
    # Points clés
    key_points = analysis.get("key_points", [])
    if key_points:
        message += "**Points importants :**\n"
        for point in key_points[:3]:  # Max 3 points
            message += f"• {point}\n"
        message += "\n"
    
    # Date/Heure si mentionné
    if analysis.get("date_mentioned"):
        message += f"📅 Date : {analysis['date_mentioned']}\n"
    if analysis.get("time_mentioned"):
        message += f"⏰ Heure : {analysis['time_mentioned']}\n"
    
    return message

# ============================================
# AGENT PRINCIPAL (SUPERVISEUR)
# ============================================

class SmartMeetOSAgent:
    """
    Agent superviseur qui orchestre tout le workflow.
    
    Utilise :
    - Tool calling pour décisions
    - Memory pour contexte
    - Callbacks pour observabilité
    - Chains pour sous-tâches
    """
    
    def __init__(self, mistral_api_key: str, discord_token: str):
        # LLM principal avec tools
        self.llm = ChatMistralAI(
            model_name="mistral-large-latest",  # model_name au lieu de model
            api_key=mistral_api_key,
            temperature=0.1,
            callbacks=[SmartMeetOSCallbackHandler()]  # Observabilité
        )
        
        # Discord
        global discord_client_instance
        discord_client_instance = DiscordClient(token=discord_token)
        
        # Memory (historique des conversations)
        self.memory = ConversationBufferMemory(
            memory_key="chat_history",
            return_messages=True
        )
        
        # Tools disponibles
        self.tools = [
            analyze_transcript_deep,
            check_previous_transcripts,
            format_for_student,
            send_discord_notification
        ]
        
        # Crée l'agent avec LangGraph (version 1.2.x)
        if USING_LANGGRAPH:
            self.agent = create_react_agent(self.llm, self.tools)
        else:
            raise ImportError("LangGraph requis pour LangChain 1.2.x. Installez: pip install langgraph")
    
    async def process_transcript(self, transcript: str, student_id: int) -> Dict:
        """
        Traite une transcription de manière autonome
        
        Args:
            transcript: La transcription
            student_id: ID Discord de l'élève
            
        Returns:
            Résultat complet avec toutes les étapes
        """
        print("\n" + "="*60)
        print("🤖 AGENT SUPERVISEUR DÉMARRE")
        print("="*60 + "\n")
        
        try:
            # Prépare le message système avec instructions
            system_message = f"""Tu es un agent intelligent qui traite des transcriptions pour des étudiants.

🎯 TA MISSION COMPLÈTE :
1. Analyser la transcription avec analyze_transcript_deep
2. Vérifier le contexte avec check_previous_transcripts si nécessaire
3. Décider si c'est pertinent pour l'élève
4. Si OUI :
   a. Formater avec format_for_student
   b. Envoyer avec send_discord_notification
5. Si NON : expliquer pourquoi et s'arrêter

🧠 RÈGLES DE DÉCISION :
- Urgency "high" → Notifie TOUJOURS
- Urgency "medium" → Notifie si événement proche (< 7 jours)
- Urgency "low" ou "none" → NE notifie PAS
- Bavardage (event_type = "none") → NE notifie JAMAIS

Student ID : {student_id}
Date actuelle : {datetime.now().strftime("%Y-%m-%d")}"""

            user_message = f"""Nouvelle transcription à traiter :

--- TRANSCRIPTION ---
{transcript}
--- FIN TRANSCRIPTION ---

Analyse cette transcription, détermine si c'est important, et prends les actions appropriées."""

            # Invoque l'agent avec LangGraph
            messages = [
                {"role": "system", "content": system_message},
                {"role": "user", "content": user_message}
            ]
            
            result = await self.agent.ainvoke({"messages": messages})
            
            # Récupère la réponse finale
            output = ""
            if "messages" in result and isinstance(result["messages"], list):
                for msg in result["messages"]:
                    if hasattr(msg, "content") and isinstance(msg.content, str):
                        output += msg.content + "\n"
            
            # Sauvegarde dans la mémoire
            self.memory.save_context(
                {"input": transcript},
                {"output": output}
            )
            
            print("\n" + "="*60)
            print("✅ AGENT TERMINÉ")
            print("="*60)
            
            return {
                "success": True,
                "output": output,
                "steps": result.get("messages", [])
            }
        
        except Exception as e:
            print(f"\n❌ Erreur agent : {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}

# ============================================
# FONCTION PRINCIPALE
# ============================================

async def main():
    print("="*60)
    print("🚀 SYSTÈME 100% LANGCHAIN")
    print("="*60)
    print("Features:")
    print("  ✅ Agents autonomes avec tool calling")
    print("  ✅ Memory (historique)")
    print("  ✅ Callbacks (observabilité)")
    print("  ✅ Chains complexes")
    print("  ✅ Multi-agent pattern")
    print("="*60 + "\n")
    
    # Configuration
    mistral_key = os.getenv("MISTRAL_API_KEY")
    discord_token = os.getenv("DISCORD_TOKEN")
    
    if not mistral_key or not discord_token:
        print("❌ Clés API manquantes")
        return
    
    print("✅ Configuration chargée")
    print(f"📨 Notifications vers : {STUDENT_ID}\n")
    
    # Initialise l'agent superviseur
    print("🔧 Initialisation de l'agent superviseur...")
    agent = SmartMeetOSAgent(mistral_key, discord_token)
    print("✅ Agent prêt\n")
    
    # ============================================
    # 🔧 TRANSCRIPTIONS DE TEST
    # ============================================
    
    test_transcriptions = [

        {
            "name": "pas important",
            "transcript": """
            On a un meeting super important 
            demain à 14h pour le projet final voila , sinon hier je suis sorti avec djad c'etais bien
            """
        }
    ]
    
    # Démarre Discord
    if discord_client_instance is not None:
        @discord_client_instance.client.event
        async def on_ready():
            if discord_client_instance is None:
                return
                
            print(f"🟢 Discord connecté : {discord_client_instance.client.user}\n")
            print("="*60)
            print("🔄 L'AGENT TRAITE LES TRANSCRIPTIONS")
            print("="*60 + "\n")
            
            for i, test in enumerate(test_transcriptions, 1):
                print(f"\n{'='*60}")
                print(f"📄 TEST #{i} : {test['name']}")
                print(f"{'='*60}")
                # strip() appliqué correctement sur une chaîne
                transcript_text = test['transcript'].strip() if isinstance(test['transcript'], str) else str(test['transcript']).strip()
                print(f"Transcription :\n{transcript_text}\n")
                
                # L'agent décide TOUT de manière autonome
                result = await agent.process_transcript(
                    transcript_text,
                    STUDENT_ID
                )
                
                if result["success"]:
                    print(f"\n✅ Traitement réussi")
                    print(f"Résultat : {result['output']}")
                    print(f"Nombre d'étapes : {len(result.get('steps', []))}")
                else:
                    print(f"\n❌ Erreur : {result.get('error')}")
                
                print(f"\n{'='*60}\n")
                await asyncio.sleep(3)
            
            print("\n" + "="*60)
            print("✅ TOUS LES TESTS TERMINÉS")
            print("="*60)
            print("\n📊 Historique de la memory :")
            print(agent.memory.load_memory_variables({}))
            print("\n")
            
            await discord_client_instance.close()
        
        await discord_client_instance.client.start(discord_token)

if __name__ == "__main__":
    print("\n⚠️  DÉPENDANCES REQUISES :")
    print("pip install langchain langchain-mistralai langchain-community discord.py\n")
    
    try:
        asyncio.run(main())
    except ImportError as e:
        print(f"❌ Dépendance manquante : {e}")
        print("\nInstalle avec :")
        print("pip install langchain langchain-mistralai langchain-community discord.py")
    except Exception as e:
        print(f"❌ Erreur : {e}")
        import traceback
        traceback.print_exc()
