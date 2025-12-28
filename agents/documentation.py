# agent_notion_role_clair.py - Groq génère rapport + Mermaid → Notion
from dataclasses import dataclass, asdict
from langchain.agents import create_agent
from langchain_groq import ChatGroq
from langchain.tools import tool, ToolRuntime
import os
from typing import List, Optional, Dict, Any
from datetime import datetime
import json
import time
import random
from services.notion_client import NotionManager
import re
from langchain_core.messages import SystemMessage, HumanMessage
from toon_python import encode

# CONFIG GROQ
api_key = os.getenv("GROQ_API_KEY")  
notion_manager = NotionManager()

# MODÈLES GROQ
model_rapport = ChatGroq(
    model_name="llama-3.1-8b-instant",
    temperature=0.3,
    max_tokens=4096
)

model_mermaid = ChatGroq(
    model_name="llama-3.1-8b-instant", 
    temperature=0.2,
    max_tokens=1024
)

from langchain_core.tools import tool
from typing import Any
import json

@tool
def get_meeting_data(meeting_id: str = "CHAOS-2024-001") -> str:
    """Récupère les données structurées d'une réunion au format TOON optimisé pour LLM.

    Args:
        meeting_id: L'ID de la réunion à récupérer (défaut: CHAOS-2024-001)

    Returns:
        Une chaîne TOON contenant toutes les données structurées de la réunion.
    """

    # Données structurées (au lieu du texte libre)
    meetings_data = {
        "CHAOS-2024-001": {
            "info": {
                "id": "CHAOS-2024-001",
                "projet": "PROJET CHAOS - APPLICATION GESTION DE CRISE",
                "client": "IMPORTANT CLIENT SA",
                "date": "15 janvier 2024 à 14h30",
                "urgence": "HAUTE",
                "budget": "50 000€"
            },
            "participants": [
                {"nom": "Alice", "statut": "PRÉSENT"},
                {"nom": "Pierre", "statut": "PRÉSENT"},
                {"nom": "Marie", "statut": "ABSENTE"},
                {"nom": "Jean", "statut": "ABSENT"}
            ],
            "contexte": "Développement application gestion de crise. Date limite : mars 2024.",
            "decisions": [
                "Utiliser React pour le frontend",
                "Python/Flask pour le backend",
                "Base de données PostgreSQL"
            ],
            "actions": [
                {"id": 1, "description": "Setup environnement dev", "responsable": "Alice", "echeance": "avant 22 janvier 2024"},
                {"id": 2, "description": "Architecture base de données", "responsable": "Pierre", "echeance": "avant 25 janvier 2024"},
                {"id": 3, "description": "Maquettes interface", "responsable": "Marie", "echeance": "avant 30 janvier 2024"}
            ]
        },
        "PROJET-2024-002": { ... }  # même structure
    }

    data = meetings_data.get(meeting_id, meetings_data["CHAOS-2024-001"])

    # Conversion en TOON → super compact et lisible par le LLM
    toon_str = encode(data)

    print(f"[OUTIL] Données TOON retournées pour {meeting_id} (~{len(toon_str.split())} tokens estimés)")
    return toon_str

@tool
def extraire_actions_en_toon(rapport_markdown: str) -> str:
    """Extrait les actions du rapport et les retourne en TOON pour stockage ou suivi."""
    pass

@tool
def generer_mermaid(notes: str) -> str:
    """Génère un diagramme au format Mermaid à partir des notes d'une réunion.

    Analyse les notes et produit un flowchart représentant les décisions,
    tâches et responsables mentionnés.

    Args:
        notes: Le texte complet des notes de la réunion (brutes ou résumées).

    Returns:
        Une chaîne contenant le code Mermaid brut valide (flowchart TD).
    """
    print(f"[OUTIL] Génération Mermaid à partir des notes")

    # On utilise directement ta fonction dédiée pour tout le travail
    mermaid_code = generer_diagramme_mermaid(notes)

    print(f"[OUTIL] Diagramme Mermaid généré avec succès")
    return mermaid_code

@tool
def publier_notion(title: str, rapport_markdown: str, mermaid_code: str) -> str:
    """Crée une page Notion contenant le rapport Markdown et le diagramme Mermaid.

    Args:
        title: Titre de la page Notion à créer.
        rapport_markdown: Contenu du rapport au format Markdown.
        mermaid_code: Code Mermaid brut à intégrer dans la page.

    Returns:
        Une chaîne JSON avec le statut, l'URL de la page et d'autres métadonnées.
    """
    print(f"[OUTIL] Publication dans Notion en cours pour : {title}")

    # Supposons que cette fonction existe dans ton code
    result = creer_page_notion(title, rapport_markdown, mermaid_code)
    page_id = result[0]
    url_notion = result[1]

    result_json = json.dumps({
        "status": "success",
        "page_url": url_notion,
        "page_id": page_id,
        "blocks_count": len(rapport_markdown.split('\n')) + 2  # Estimation approximative
    }, ensure_ascii=False)

    print(f"[OUTIL] Page Notion créée : {url_notion}")
    return result_json

# CONTEXTE
@dataclass
class Context:
    meeting_id: str

# PROMPT SYSTÈME POUR RAPPORT

PROMPT_RAPPORT = """Tu es un expert en rédaction de comptes-rendus de réunion professionnels.

Tu vas recevoir les données de réunion au format TOON (Token-Oriented Object Notation), un format optimisé pour les IA :
- Structure hiérarchique avec indentation
- Tableaux avec [N]{champs} et lignes de valeurs séparées par virgules
- Très compact, sans répétition de clés

EXEMPLE DE TOON :
info{id,projet,client,date,urgence,budget}:
 CHAOS-2024-001,PROJET CHAOS - APPLICATION GESTION DE CRISE,IMPORTANT CLIENT SA,15 janvier 2024 à 14h30,HAUTE,50 000€
participants[4]{nom,statut}:
 Alice,PRÉSENT
 Pierre,PRÉSENT
 Marie,ABSENTE
 Jean,ABSENT
actions[3]{id,description,responsable,echeance}:
 1,Setup environnement dev,Alice,avant 22 janvier 2024
 ...

TA MISSION :
1. Utilise l'outil 'get_meeting_data' → tu recevras les données en TOON
2. Analyse précisément ces données structurées
3. Génère un rapport professionnel en Markdown (titres, listes, tableaux si besoin)
4. Puis utilise 'generer_mermaid' avec les notes clés
5. Enfin 'publier_notion'

RÈGLES :
- Sois exhaustif : mentionne toutes les actions, responsables, échéances
- Structure claire : # Titre, ## Participants, ## Décisions, ## Actions à suivre, etc.
- NE JAMAIS inclure le code Mermaid dans le Markdown
- Le diagramme sera ajouté séparément

Réponds étape par étape en utilisant les outils."""

# PROMPT mermaid
PROMPT_MERMAID = """Tu es un expert en diagrammes Mermaid pour la visualisation de projets et de réunions.  
Ton objectif est de générer **un diagramme Mermaid 100 % valide, clair et professionnel**, à partir de notes de réunion.

### 1️- Types de diagrammes disponibles
- flowchart TD : flux de travail, décisions, étapes du projet (préféré pour la majorité des réunions)
- mindmap : structuration hiérarchique des idées, points discutés
- sequenceDiagram : interactions entre personnes ou systèmes

### 2️- Instructions STRICTES pour la génération
1. Choisis **un seul type de diagramme** selon le contenu des notes.
2. Commence directement par la déclaration du type (ex: `flowchart TD`, `mindmap` ou `sequenceDiagram`).
3. **Chaque ligne doit correspondre à une instruction Mermaid valide.**
4. **Indentation de 4 espaces pour chaque niveau ou branche.**
5. **Pas de texte explicatif**, pas de titres additionnels, pas de blocs ```mermaid, pas de commentaires hors syntaxe Mermaid.
6. **Pas d’informations hors diagramme** : tout texte doit être une tâche, étape, décision ou interaction directement représentable.
7. **Pas d’unités interdites** : en Gantt, uniquement `d` (jour) ou `w` (semaine) ; pas d'heures ou de minutes.
8. **IDs Mermaid valides** si nécessaire pour relier les flèches : utilisez des lettres, chiffres, ou underscores (`A`, `B1`, `task_1`).
9. **Ne jamais mélanger plusieurs types** : Gantt doit rester Gantt, Flowchart reste Flowchart, etc.
10. **Une seule directive Mermaid par tâche** : pas de texte libre ou de noms de personnes hors ID autorisé.

### 3️- Exemples strictement valides

#### Flowchart TD
flowchart TD
    A[Définition du projet] --> B[Choix de la stack]
    B --> C{Front-end}
    C -->|React| D[Design UI - Marie]
    B --> E[Back-end - Python - Pierre]
    D --> F[Setup dev - Pierre]
    F --> G[Présentation client]

#### Gantt
gantt
    title Projet Simple
    dateFormat YYYY-MM-DD
    axisFormat %d/%m
    section Actions
    Design UI         :2025-01-05, 5d
    Setup dev         :2025-01-08, 3d
    Présentation      :2025-01-12, 1d

### 4️- Réponse attendue
- Réponds **UNIQUEMENT avec le code Mermaid valide**, ligne par ligne.
- Aucune explication, aucun commentaire, aucune ligne vide inutile.
- Le code doit être **100 % prêt à coller dans Mermaid Live**.

### 5️- Conseils supplémentaires pour l'agent
- Si une information manque ou est ambiguë, fais une hypothèse cohérente et valide pour le diagramme.
- Vérifie toujours la syntaxe Mermaid avant de renvoyer le code.
"""


# CRÉATION DE L'AGENT PRINCIPAL
agent_principal = create_agent(
    model=model_rapport,
    system_prompt=PROMPT_RAPPORT,
    tools=[get_meeting_data, generer_mermaid, publier_notion],
    context_schema=Context,
)



def creer_page_notion(title: str, markdown_content: str, mermaid_code: Optional[str] = None) -> str:
    """Crée une page Notion professionnelle contenant le rapport Markdown complet et, à la fin, un diagramme Mermaid rendu
    Retourne l'URL de la page créée. extrait"""
    
    print(f"[OUTIL] Création de la page Notion : {title}")

    blocks = markdown_to_notion_blocks(markdown_content)

    if mermaid_code:
        blocks.extend([
            {"type": "heading_2", "content": "Diagramme du Projet"},
            {"type": "divider", "content": ""},
            {"type": "code", "content": f"```mermaid\n{mermaid_code}\n```", "language": "mermaid"}
        ])

    page = notion_manager.create_page_with_structure(
        title=title,
        blocks=blocks,
        properties={}
    )

    if page:
        page_id = page["id"].replace("-", "")
        url = f"https://www.notion.so/{page_id}"
        print(f"Page créée avec succès → {url}")
        return [page_id, url]
    else:
        return "Échec de la création de la page Notion"


def markdown_to_notion_blocks(markdown: str) -> List[Dict]:
    lines = markdown.split('\n')
    blocks = []
    i = 0
    current_paragraph = []

    def flush_paragraph():
        if current_paragraph:
            content = '\n'.join(current_paragraph).strip()
            if content:
                blocks.append({"type": "paragraph", "content": content})
            current_paragraph.clear()

    while i < len(lines):
        line = lines[i].rstrip()

        if line.startswith('# '):
            flush_paragraph()
            blocks.append({"type": "heading_1", "content": line[2:].strip()})
            # Ajouter un divider après le titre principal pour plus de séparation
            blocks.append({"type": "divider", "content": ""})
        elif line.startswith('## '):
            flush_paragraph()
            section_title = line[3:].strip()
            blocks.append({"type": "heading_2", "content": section_title})
            # Ajouter un divider après chaque section pour une meilleure lisibilité
            blocks.append({"type": "divider", "content": ""})
            # Pour les sections importantes, ajouter un callout
            if "Décisions" in section_title:
                blocks.append({"type": "callout", "content": "Section des décisions prises lors de la réunion", "icon": "✅"})
            elif "Actions" in section_title or "à suivre" in section_title:
                blocks.append({"type": "callout", "content": "Actions prioritaires à réaliser", "icon": "🚀"})
            elif "Participants" in section_title:
                blocks.append({"type": "callout", "content": "Liste des participants et leur statut", "icon": "👥"})
        elif line.startswith('### '):
            flush_paragraph()
            blocks.append({"type": "heading_3", "content": line[4:].strip()})
        elif line.startswith('- [ ]') or line.startswith('- [x]'):
            flush_paragraph()
            checked = '[x]' in line.lower()
            content = re.sub(r'^- \[.\]\s*', '', line).strip()
            blocks.append({"type": "to_do", "content": content, "checked": checked})
        elif line.startswith('- ') or line.startswith('• '):
            flush_paragraph()
            content = line[2:].strip()
            # Si c'est dans une section Actions, convertir en to_do
            if any("Actions" in b.get("content", "") for b in blocks[-5:] if b.get("type") == "heading_2"):
                blocks.append({"type": "to_do", "content": content, "checked": False})
            else:
                blocks.append({"type": "bulleted_list_item", "content": content})
        elif re.match(r'^\d+\.\s', line):
            flush_paragraph()
            content = re.sub(r'^\d+\.\s*', '', line).strip()
            blocks.append({"type": "numbered_list_item", "content": content})
        elif line.startswith('---'):
            flush_paragraph()
            blocks.append({"type": "divider", "content": ""})
        elif line.startswith("Point clé important") or line.startswith("Urgence"):
            flush_paragraph()
            if "Point clé important" in line:
                content = line.replace("Point clé important :", "").strip()
                icon = "💡"
            else:
                content = line.replace("Urgence :", "").strip()
                icon = "🚨"
            blocks.append({"type": "callout", "content": content, "icon": icon})
        elif line.strip():
            current_paragraph.append(line.strip())
        else:
            flush_paragraph()

        i += 1

    flush_paragraph()
    return blocks


def invoke_with_retry(model, messages, max_retries=3):
    """Wrapper pour gérer les rate limits avec retry et backoff exponentiel."""
    for attempt in range(max_retries):
        try:
            return model.invoke(messages)
        except Exception as e:
            error_str = str(e).lower()
            if "rate limit" in error_str or "429" in error_str or "quota" in error_str:
                wait_time = 2 ** attempt  # backoff exponentiel
                print(f"⚠️ Rate limit détecté, tentative {attempt+1}/{max_retries}, attente {wait_time}s...")
                time.sleep(wait_time)
            else:
                raise
    raise Exception(f"Échec après {max_retries} tentatives : rate limit ou autre erreur")


def generer_diagramme_mermaid(content_summary: str) -> str:
    
    user_prompt = f"Notes de réunion :\n{content_summary}\n\nGénère un flowchart TD détaillé du processus discuté."

    messages = [SystemMessage(content=PROMPT_MERMAID), HumanMessage(content=user_prompt)]
    print(f"[OUTIL] Génération du diagramme Mermaid")
    response = invoke_with_retry(model_mermaid, messages)
    mermaid = response.content.strip()

    for prefix in ["```mermaid", "```"]:
        if mermaid.startswith(prefix):
            mermaid = mermaid[len(prefix):].strip()
        if mermaid.endswith("```"):
            mermaid = mermaid[:-3].strip()

    if not mermaid.startswith("flowchart TD"):
        mermaid = "flowchart TD\n" + mermaid

    # Indenter proprement
    lines = mermaid.split('\n')
    indented_lines = []
    for line in lines:
        if line.strip().startswith('flowchart'):
            indented_lines.append(line)
        else:
            indented_lines.append('    ' + line.strip())
    mermaid = '\n'.join(indented_lines)

    print(f"[OUTIL] Diagramme Mermaid validé")
    return mermaid

def run_agent(meeting_id: str, demande: str = "Crée un compte-rendu complet avec diagramme et publie dans Notion"):
    """
    Fonction pour utiliser l'agent avec un ID de réunion.
    Génère toujours : Rapport + Diagramme Mermaid + Publication Notion
    
    Args:
        meeting_id: L'ID de la réunion (ex: "CHAOS-2024-001")
        demande: La demande à envoyer à l'agent (optionnel)
    
    Returns:
        La réponse de l'agent
    """
    print(f"Exécution de l'agent pour la réunion: {meeting_id}")
    print(f"Demande: {demande}")
    print("-" * 70)
    
    agent = create_agent(
        model=model_rapport,
        system_prompt=PROMPT_RAPPORT,
        tools=[get_meeting_data, generer_mermaid, publier_notion],
        context_schema=Context,
    )
    
    try:
        response = agent.invoke(
            {"messages": [{"role": "user", "content": demande}]},
            config={"configurable": {"thread_id": f"run_{meeting_id}"}},
            context=Context(meeting_id=meeting_id)
        )
        
        print("Agent exécuté avec succès!")
        
        # Afficher la rs finale
        if 'messages' in response:
            for msg in reversed(response['messages']):
                if hasattr(msg, 'content') and msg.content and msg.content.strip():
                    print("\nRÉPONSE FINALE:")
                    print(msg.content)
                    break
        
        return response
        
    except Exception as e:
        print(f"ERREUR lors de l'exécution: {e}")
        raise


# EXÉCUTION
if __name__ == "__main__":
    print("Azyy")
    
    
    print("\nMODE PERSONNALISÉ")
    print("   → Utilisez vos propres paramètres")
    meeting_id = input("ID de réunion (ex: CHAOS-2024-001): ").strip()
    if meeting_id:
        demande = input("Demande (ex: Crée un rapport complet): ").strip()
        if demande:
            run_agent(meeting_id, demande)
        else:
            print("Demande vide")
    else:
        print("ID de réunion vide")
    

