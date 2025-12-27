# agents/actions.py - Analyse + Envoi Discord automatique
"""
Analyse intelligente de transcriptions
Input dans le code, output envoyé en DM Discord
"""

import os
import sys
from pathlib import Path
import asyncio
from typing import Dict, List, Optional
from datetime import datetime
from dotenv import load_dotenv

# Ajoute le parent au PYTHONPATH
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from services.discord_client import DiscordClient

from langchain_mistralai import ChatMistralAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field

load_dotenv()

# ============================================
# CONFIGURATION
# ============================================

# 🔧 METS L'ID DISCORD DE L'ÉLÈVE ICI
STUDENT_ID = 320985146146684930  # ← Remplace par l'ID de l'élève

# ============================================
# MODÈLES PYDANTIC
# ============================================

class ImportantInfo(BaseModel):
    """Information importante extraite"""
    type: str = Field(
        description="Type d'info",
        pattern="^(meeting|exam|test|deadline|homework|announcement|warning|other)$"
    )
    content: str = Field(description="Contenu de l'info")
    date: Optional[str] = None
    time: Optional[str] = None
    urgency: str = Field(
        description="Niveau d'urgence",
        pattern="^(high|medium|low)$"
    )

class TranscriptAnalysis(BaseModel):
    """Résultat de l'analyse"""
    has_important_info: bool
    important_items: List[ImportantInfo]
    summary: str
    student_relevant: bool
    confidence: float = Field(ge=0.0, le=1.0)

# ============================================
# AGENT ANALYSEUR
# ============================================

class SmartTranscriptAnalyzer:
    """Agent qui analyse une transcription et filtre l'important"""
    
    def __init__(self, mistral_api_key: str, model: str = "mistral-large-latest"):
        self.llm = ChatMistralAI(
            model=model,
            api_key=mistral_api_key,
            temperature=0.2
        )
        
        self.parser = JsonOutputParser(pydantic_object=TranscriptAnalysis)
        self.prompt = self._build_prompt()
        self.chain = self.prompt | self.llm | self.parser
    
    def _build_prompt(self) -> ChatPromptTemplate:
        system_prompt = """Tu es un assistant intelligent pour étudiants. Analyse une transcription et extrait UNIQUEMENT les informations IMPORTANTES.

🎯 CE QUI EST IMPORTANT :
- Meetings, réunions, rendez-vous
- Examens, interros, tests, contrôles
- Devoirs, projets, travaux à rendre
- Deadlines, dates limites
- Annonces importantes (changement de salle, annulation)
- Avertissements, consignes critiques

❌ CE QUI N'EST PAS IMPORTANT :
- Blagues, humour
- Discussions sur jeux vidéo, séries, sports
- Bavardages hors-sujet
- Anecdotes personnelles

📋 RETOURNE CE JSON :
{{
  "has_important_info": true/false,
  "important_items": [
    {{
      "type": "meeting|exam|test|deadline|homework|announcement|warning|other",
      "content": "Description claire",
      "date": "YYYY-MM-DD ou null",
      "time": "HH:MM ou null",
      "urgency": "high|medium|low"
    }}
  ],
  "summary": "Résumé en UNE phrase",
  "student_relevant": true/false,
  "confidence": 0.0-1.0
}}

Date actuelle : {current_date}

EXEMPLES :

Input: "On a un meeting demain à 14h pour le projet. J'ai regardé Netflix hier."
Output: {{
  "has_important_info": true,
  "important_items": [
    {{
      "type": "meeting",
      "content": "Meeting pour le projet",
      "date": "2024-12-28",
      "time": "14:00",
      "urgency": "high"
    }}
  ],
  "summary": "Meeting projet demain 14h",
  "student_relevant": true,
  "confidence": 0.95
}}

Input: "J'ai joué à LOL toute la nuit mdr"
Output: {{
  "has_important_info": false,
  "important_items": [],
  "summary": "Discussion informelle sur les jeux",
  "student_relevant": false,
  "confidence": 0.98
}}

Retourne UNIQUEMENT le JSON."""

        return ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "Transcription:\n\n{transcript}")
        ])
    
    def analyze(self, transcript: str) -> Dict:
        """Analyse une transcription"""
        if not transcript or len(transcript.strip()) < 10:
            return {
                "has_important_info": False,
                "important_items": [],
                "summary": "Transcription trop courte",
                "student_relevant": False,
                "confidence": 1.0
            }
        
        current_date = datetime.now().strftime("%Y-%m-%d")
        
        result = self.chain.invoke({
            "transcript": transcript,
            "current_date": current_date
        })
        
        validated = TranscriptAnalysis(**result)
        return validated.model_dump()

# ============================================
# FORMATTEUR DE MESSAGE DISCORD
# ============================================

def format_discord_message(analysis: Dict) -> str:
    """Formate le résultat pour Discord"""
    
    items = analysis.get("important_items", [])
    
    # Si rien d'important, ne pas envoyer de message
    if not items or not analysis.get("student_relevant"):
        return None
    
    # En-tête selon l'urgence
    has_urgent = any(item["urgency"] == "high" for item in items)
    
    if has_urgent:
        message = "🚨 **INFORMATIONS IMPORTANTES** 🚨\n\n"
    else:
        message = "📌 **Informations à noter**\n\n"
    
    # Liste les infos
    for i, item in enumerate(items, 1):
        # Icône
        icon = {
            "meeting": "📅",
            "exam": "📝",
            "test": "✍️",
            "deadline": "⏰",
            "homework": "📚",
            "announcement": "📢",
            "warning": "⚠️",
            "other": "📌"
        }.get(item["type"], "📌")
        
        # Badge urgence
        urgency_badge = {
            "high": "🔴 URGENT",
            "medium": "🟠",
            "low": "🟢"
        }.get(item["urgency"], "")
        
        message += f"{icon} **{item['content']}** {urgency_badge}\n"
        
        if item.get("date"):
            message += f"   📅 {item['date']}"
            if item.get("time"):
                message += f" à {item['time']}"
            message += "\n"
        
        message += "\n"
    
    # Résumé
    message += f"💡 **Résumé :** {analysis['summary']}"
    
    return message

# ============================================
# FONCTION PRINCIPALE
# ============================================

async def test_with_discord():
    """Test avec envoi Discord automatique"""
    
    print("="*60)
    print("🚀 SMART TRANSCRIPT ANALYZER")
    print("="*60 + "\n")
    
    # Configuration
    mistral_key = os.getenv("MISTRAL_API_KEY")
    discord_token = os.getenv("DISCORD_TOKEN")
    
    if not mistral_key:
        print("❌ MISTRAL_API_KEY manquante dans .env")
        return
    
    if not discord_token:
        print("❌ DISCORD_TOKEN manquant dans .env")
        return
    
    print("✅ Configuration chargée")
    print(f"📨 Les résumés seront envoyés à l'ID : {STUDENT_ID}\n")
    
    # Initialisation
    print("🧠 Initialisation de l'analyseur...")
    analyzer = SmartTranscriptAnalyzer(mistral_api_key=mistral_key)
    print("✅ Analyseur prêt\n")
    
    print("💬 Initialisation Discord...")
    discord_client = DiscordClient(token=discord_token)
    print("✅ Discord prêt\n")
    
    # ============================================
    # 🔧 METS TES TRANSCRIPTIONS ICI
    # ============================================
    
    test_transcriptions = [
        {
            "name": "Meeting important",
            "transcript": """
            Bon les gars, n'oubliez pas qu'on a un meeting demain à 14h 
            pour le projet. Amenez vos laptops. Ah et j'ai regardé la 
            série Netflix hier, trop bien !
            """
        },
        {
            "name": "Uniquement bavardage",
            "transcript": """
            Hier j'ai passé toute la soirée à jouer à Call of Duty, 
            j'ai perdu tous mes matchs mdr. La nouvelle saison de 
            Valorant est trop bien aussi.
            """
        },
        {
            "name": "Plusieurs événements",
            "transcript": """
            Attention les élèves ! L'interro de maths prévue vendredi 
            est reportée à lundi prochain. Aussi, le cours de physique 
            de demain est annulé, le prof est malade.
            """
        },
        {
            "name": "Deadline urgent",
            "transcript": """
            URGENT : Le rendu du projet de programmation est avancé à 
            vendredi 15h au lieu de la semaine prochaine. N'oubliez pas !
            """
        },
    ]
    
    # Démarre Discord
    @discord_client.client.event
    async def on_ready():
        print(f"🟢 Bot connecté : {discord_client.client.user}\n")
        print("="*60)
        print("🔄 TRAITEMENT DES TRANSCRIPTIONS")
        print("="*60 + "\n")
        
        # Traite chaque transcription
        for i, test in enumerate(test_transcriptions, 1):
            print(f"\n{'='*60}")
            print(f"📄 TRANSCRIPTION #{i} : {test['name']}")
            print(f"{'='*60}")
            print(test['transcript'].strip())
            print(f"\n⏳ Analyse en cours...\n")
            
            try:
                # 1. Analyse
                result = analyzer.analyze(test['transcript'].strip())
                
                # Affiche dans la console
                print(f"📊 RÉSULTAT :")
                print(f"   • Résumé : {result['summary']}")
                print(f"   • Pertinent : {'✅ OUI' if result['student_relevant'] else '❌ NON'}")
                print(f"   • Infos importantes : {len(result['important_items'])}")
                print(f"   • Confiance : {result['confidence']:.0%}\n")
                
                # 2. Formate pour Discord
                discord_msg = format_discord_message(result)
                
                # 3. Envoie si pertinent
                if discord_msg:
                    print(f"📨 Envoi à Discord...\n")
                    success = await discord_client.send_direct_message(
                        STUDENT_ID,
                        discord_msg
                    )
                    
                    if success:
                        print(f"✅ Message envoyé avec succès\n")
                    else:
                        print(f"❌ Échec de l'envoi\n")
                else:
                    print(f"ℹ️  Rien d'important → Pas de notification envoyée\n")
                
                # Pause entre les messages (anti-spam)
                await asyncio.sleep(2)
            
            except Exception as e:
                print(f"❌ Erreur : {e}\n")
                import traceback
                traceback.print_exc()
        
        print("\n" + "="*60)
        print("✅ TOUS LES TESTS TERMINÉS")
        print("="*60 + "\n")
        
        # Ferme le bot
        print("👋 Fermeture du bot...")
        await discord_client.close()
    
    # Lance Discord
    await discord_client.client.start(discord_client.token)

# ============================================
# FONCTION POUR INTÉGRATION FUTURE
# ============================================

async def analyze_and_notify(transcript: str, student_id: int):
    """
    Fonction à appeler depuis un autre agent.
    Analyse une transcription et envoie automatiquement un DM si pertinent.
    
    Args:
        transcript: La transcription à analyser
        student_id: ID Discord de l'élève
    
    Returns:
        Dict avec les résultats de l'analyse
    
    Exemple d'utilisation depuis l'agent de transcription:
        from agents.actions import analyze_and_notify
        
        await analyze_and_notify(
            transcript=ma_transcription,
            student_id=320985146146684930
        )
    """
    mistral_key = os.getenv("MISTRAL_API_KEY")
    discord_token = os.getenv("DISCORD_TOKEN")
    
    if not mistral_key or not discord_token:
        raise ValueError("Clés API manquantes")
    
    # Analyse
    analyzer = SmartTranscriptAnalyzer(mistral_api_key=mistral_key)
    result = analyzer.analyze(transcript)
    
    # Envoie si pertinent
    discord_msg = format_discord_message(result)
    
    if discord_msg:
        discord_client = DiscordClient(token=discord_token)
        
        @discord_client.client.event
        async def on_ready():
            await discord_client.send_direct_message(student_id, discord_msg)
            await discord_client.close()
        
        await discord_client.client.start(discord_token)
    
    return result

# ============================================
# POINT D'ENTRÉE
# ============================================

if __name__ == "__main__":
    asyncio.run(test_with_discord())