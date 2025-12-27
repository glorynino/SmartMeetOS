# agents/event_detection_agent.py

import os
import json
from typing import Dict, Any, Optional
from datetime import datetime
from dotenv import load_dotenv
from langchain_mistralai import ChatMistralAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import JsonOutputParser
from pydantic import BaseModel, Field, field_validator

load_dotenv()

class EventDecision(BaseModel):
    """Modèle Pydantic pour la sortie structurée de l'agent"""
    is_event: bool = Field(description="True si le texte décrit un événement à venir")
    event_type: str = Field(
        description="Type d'événement détecté",
        pattern="^(meeting|exam|test|deadline|reminder|other|none)$"
    )
    date: Optional[str] = Field(
        default=None,
        description="Date au format YYYY-MM-DD ou null"
    )
    time: Optional[str] = Field(
        default=None,
        description="Heure au format HH:MM ou null"
    )
    notify: bool = Field(
        description="True si une notification doit être envoyée"
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description="Niveau de confiance entre 0 et 1"
    )
    
    @field_validator('date')
    @classmethod
    def validate_date_format(cls, v):
        """Valide le format de date"""
        if v is None:
            return v
        try:
            datetime.strptime(v, '%Y-%m-%d')
            return v
        except ValueError:
            raise ValueError("La date doit être au format YYYY-MM-DD")
    
    @field_validator('time')
    @classmethod
    def validate_time_format(cls, v):
        """Valide le format d'heure"""
        if v is None:
            return v
        try:
            datetime.strptime(v, '%H:%M')
            return v
        except ValueError:
            raise ValueError("L'heure doit être au format HH:MM")

class EventDetectionAgent:
    """
    Agent intelligent de détection d'événements.
    Analyse un texte en français et détermine s'il décrit un événement.
    Retourne UNIQUEMENT une décision structurée (pas d'action directe).
    """
    
    def __init__(self, mistral_api_key: Optional[str] = None, model: str = "mistral-large-latest"):
        """
        Initialise l'agent avec l'API Mistral.
        
        Args:
            mistral_api_key: Clé API Mistral (ou depuis MISTRAL_API_KEY en .env)
            model: Modèle Mistral à utiliser
        """
        self.api_key = mistral_api_key or os.getenv("MISTRAL_API_KEY")
        if not self.api_key:
            raise ValueError(
                "❌ Clé API Mistral manquante. "
                "Fournissez-la en paramètre ou via MISTRAL_API_KEY dans .env"
            )
        
        # Initialise le LLM Mistral
        self.llm = ChatMistralAI(
            model=model,
            api_key=self.api_key,
            temperature=0.1,  # Peu de créativité, on veut de la précision
        )
        
        # Parser JSON avec validation Pydantic
        self.parser = JsonOutputParser(pydantic_object=EventDecision)
        
        # Prompt système strict
        self.prompt = self._build_prompt()
        
        # Chaîne LangChain
        self.chain = self.prompt | self.llm | self.parser
    
    def _build_prompt(self) -> ChatPromptTemplate:
        """Construit le prompt système avec instructions strictes"""
        
        system_prompt = """Tu es un agent d'analyse d'événements. Ta SEULE mission est d'analyser un texte en français et de déterminer s'il décrit un événement futur nécessitant une notification.

RÈGLES STRICTES :
1. Tu dois TOUJOURS retourner un JSON valide avec cette structure exacte :
{{
  "is_event": boolean,
  "event_type": "meeting|exam|test|deadline|reminder|other|none",
  "date": "YYYY-MM-DD ou null",
  "time": "HH:MM ou null",
  "notify": boolean,
  "confidence": number entre 0.0 et 1.0
}}

2. DÉTECTION D'ÉVÉNEMENTS :
   - is_event = true si le texte mentionne un événement futur (meeting, examen, deadline, rappel, etc.)
   - is_event = false si c'est juste une conversation, une question, ou un événement passé

3. TYPES D'ÉVÉNEMENTS :
   - "meeting" : réunion, rendez-vous, call, visio
   - "exam" : examen, test écrit, évaluation
   - "test" : interro, quiz, contrôle
   - "deadline" : date limite, échéance, rendu
   - "reminder" : rappel, à ne pas oublier
   - "other" : autre événement identifiable
   - "none" : pas d'événement

4. EXTRACTION TEMPORELLE :
   - Date actuelle pour référence : {current_date}
   - Convertis les expressions temporelles en format strict :
     * "demain" → date du lendemain au format YYYY-MM-DD
     * "lundi prochain" → date du lundi suivant
     * "dans 3 jours" → calcule la date
     * "14h" → "14:00"
     * "à 9h30" → "09:30"
   - Si aucune date/heure n'est mentionnée → null

5. NOTIFICATION :
   - notify = true si :
     * is_event = true ET
     * La date est dans le futur proche (< 7 jours) OU
     * Le message contient des mots urgents ("urgent", "important", "asap", "critique")
   - notify = false sinon

6. CONFIANCE :
   - 0.9-1.0 : événement explicite avec date/heure claire
   - 0.7-0.9 : événement probable, date approximative
   - 0.5-0.7 : événement possible, peu d'informations
   - 0.0-0.5 : incertain ou pas d'événement

EXEMPLES :

Input: "On a meeting demain à 14h avec le client"
Output: {{"is_event": true, "event_type": "meeting", "date": "2024-12-28", "time": "14:00", "notify": true, "confidence": 0.95}}

Input: "N'oublie pas l'examen de maths lundi matin"
Output: {{"is_event": true, "event_type": "exam", "date": "2024-12-30", "time": null, "notify": true, "confidence": 0.85}}

Input: "Comment ça va ?"
Output: {{"is_event": false, "event_type": "none", "date": null, "time": null, "notify": false, "confidence": 0.95}}

IMPORTANT : Ne retourne QUE le JSON, aucun texte avant ou après."""

        return ChatPromptTemplate.from_messages([
            ("system", system_prompt),
            ("human", "{input_text}")
        ])
    
    def analyze(self, text: str) -> Dict[str, Any]:
        """
        Analyse un texte et retourne une décision structurée.
        
        Args:
            text: Le texte à analyser
            
        Returns:
            Dict contenant la décision (conforme à EventDecision)
            
        Raises:
            ValueError: Si le JSON retourné est invalide
            Exception: Si l'API Mistral échoue
        """
        if not text or not text.strip():
            raise ValueError("❌ Le texte d'entrée ne peut pas être vide")
        
        try:
            # Date actuelle pour contexte temporel
            current_date = datetime.now().strftime("%Y-%m-%d")
            
            # Invoque la chaîne LangChain
            result = self.chain.invoke({
                "input_text": text,
                "current_date": current_date
            })
            
            # Valide avec Pydantic
            validated = EventDecision(**result)
            
            print(f"✅ Analyse terminée (confiance: {validated.confidence})")
            return validated.model_dump()
            
        except json.JSONDecodeError as e:
            print(f"❌ Erreur de parsing JSON : {e}")
            raise ValueError(f"Le LLM n'a pas retourné un JSON valide : {e}")
        
        except Exception as e:
            print(f"❌ Erreur lors de l'analyse : {e}")
            raise

class EventNotificationOrchestrator:
    """
    Orchestre la logique métier :
    1. Analyse le texte avec l'agent
    2. Décide d'envoyer ou non une notification Discord
    """
    
    def __init__(self, agent: EventDetectionAgent, discord_client):
        """
        Args:
            agent: Instance de EventDetectionAgent
            discord_client: Instance de DiscordClient (fournie)
        """
        self.agent = agent
        self.discord_client = discord_client
    
    async def process_user_message(self, user_id: int, message: str):
        """
        Point d'entrée principal : analyse un message et agit si nécessaire.
        
        Args:
            user_id: ID Discord de l'utilisateur
            message: Le message à analyser
        """
        print(f"\n📥 Message reçu de {user_id}: {message}")
        
        try:
            # 1. L'AGENT ANALYSE (pas d'action)
            decision = self.agent.analyze(message)
            
            print(f"🧠 Décision de l'agent:")
            print(json.dumps(decision, indent=2, ensure_ascii=False))
            
            # 2. LOGIQUE MÉTIER DÉCIDE
            if decision["notify"] and decision["is_event"]:
                await self._send_notification(user_id, decision)
            else:
                print("ℹ️  Aucune notification nécessaire")
        
        except Exception as e:
            print(f"❌ Erreur lors du traitement : {e}")
    
    async def _send_notification(self, user_id: int, decision: Dict):
        """Envoie une notification Discord basée sur la décision de l'agent"""
        
        # Construit le message de notification
        event_type_fr = {
            "meeting": "Réunion",
            "exam": "Examen",
            "test": "Interro",
            "deadline": "Deadline",
            "reminder": "Rappel",
            "other": "Événement"
        }.get(decision["event_type"], "Événement")
        
        message = f"🔔 **{event_type_fr} détecté !**\n"
        
        if decision["date"]:
            message += f"📅 Date : {decision['date']}\n"
        if decision["time"]:
            message += f"⏰ Heure : {decision['time']}\n"
        
        message += f"\n✅ J'ai enregistré cet événement."
        
        # Envoie via le client Discord
        success = await self.discord_client.send_direct_message(user_id, message)
        
        if success:
            print(f"✅ Notification envoyée à {user_id}")
        else:
            print(f"❌ Échec d'envoi de la notification")