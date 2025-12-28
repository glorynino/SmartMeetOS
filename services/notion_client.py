import requests
import json
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("NOTION_API_KEY")  

if not TOKEN:
    raise ValueError("NOTION_API_KEY manquante dans les variables d'environnement (.env)")


@property
def headers(self):
    return self.headers

class NotionManager:
    def __init__(self, token: str = None):
        self.token = token or TOKEN
        if not self.token:
            raise ValueError("Token Notion manquant")

        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28"
        }

        self.buildit_id = None
        self.config_file = "buildit_simple_config.json"
        self.load_config()

    def load_config(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    self.buildit_id = config.get("buildit_id")
            except Exception as e:
                print(f"Erreur lecture config: {e}")

    def save_config(self):
        config = {"buildit_id": self.buildit_id}
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Erreur sauvegarde config: {e}")

    def setup(self) -> bool:
        print("Configuration de BuildIT...")
        if not self.test_token():
            print("Token Notion invalide ou expiré")
            return False
        return self.create_or_find_buildit()

    def test_token(self) -> bool:
        try:
            response = requests.get("https://api.notion.com/v1/users/me", headers=self.headers, timeout=10)
            return response.status_code == 200
        except Exception:
            return False

    def create_or_find_buildit(self) -> bool:
        if self.buildit_id and self.check_page(self.buildit_id):
            print("BuildIT déjà configuré")
            return True

        print("Recherche d'une page BuildIT existante...")
        try:
            response = requests.post(
                "https://api.notion.com/v1/search",
                headers=self.headers,
                json={"query": "BuildIT", "filter": {"property": "object", "value": "page"}}
            )
            if response.status_code == 200:
                for page in response.json().get("results", []):
                    title = self.get_page_title(page)
                    if "buildit" in title.lower():
                        self.buildit_id = page["id"]
                        self.save_config()
                        print(f"BuildIT trouvé : {title}")
                        return True
        except Exception as e:
            print(f"Erreur recherche: {e}")

        print("Création d'une nouvelle page BuildIT...")
        return self.create_buildit()

    def get_page_title(self, page) -> str:
        title_prop = page.get("properties", {}).get("title", {})
        titles = title_prop.get("title", [])
        return titles[0]["text"]["content"] if titles else "Sans titre"

    def check_page(self, page_id: str) -> bool:
        try:
            response = requests.get(f"https://api.notion.com/v1/pages/{page_id}", headers=self.headers)
            return response.status_code == 200
        except:
            return False

    def create_buildit(self) -> bool:
        # Essai en racine
        try:
            page_data = {
                "parent": {"type": "workspace", "workspace": True},
                "properties": {"title": [{"text": {"content": "🏗️ BuildIT - Documentation"}}]}
            }
            response = requests.post("https://api.notion.com/v1/pages", headers=self.headers, json=page_data)
            if response.status_code == 200:
                self.buildit_id = response.json()["id"]
                self.save_config()
                print("BuildIT créé à la racine")
                return True
        except:
            pass

        # Alt : sous une page existante
        return self.create_buildit_alternative()

    def create_buildit_alternative(self) -> bool:
        try:
            response = requests.post("https://api.notion.com/v1/search", headers=self.headers, json={"page_size": 1})
            if response.status_code != 200 or not response.json().get("results"):
                return False
            parent_id = response.json()["results"][0]["id"]
            page_data = {
                "parent": {"page_id": parent_id},
                "properties": {"title": [{"text": {"content": "🏗️ BuildIT - Documentation"}}]}
            }
            resp = requests.post("https://api.notion.com/v1/pages", headers=self.headers, json=page_data)
            if resp.status_code == 200:
                self.buildit_id = resp.json()["id"]
                self.save_config()
                print("BuildIT créé sous une page existante")
                return True
        except Exception as e:
            print(f"Erreur création alternative: {e}")
        return False

    def get_buildit_url(self) -> str:
        if self.buildit_id:
            clean_id = self.buildit_id.replace("-", "")
            return f"https://www.notion.so/{clean_id}"
        return "Non configuré"

    def reset(self):
        self.buildit_id = None
        if os.path.exists(self.config_file):
            os.remove(self.config_file)
        print("Configuration réinitialisée")

    
    def create_page_with_structure(
        self,
        title: str,
        blocks: list,
        properties: dict = None,
        parent_page_id: str = None
       ) ->dict | None:
        if not parent_page_id and self.buildit_id:
            parent_page_id = self.buildit_id
    
        if not parent_page_id:
            print("Page parent manquante")
            return None
    
        notion_properties = {
            "title": {
                "title": [{"text": {"content": title or "Réunion sans titre"}}]
            }
        }
    
        # Mapper TOUS les blocs
        all_notion_blocks = self._map_blocks(blocks)
    
        print(f"{len(all_notion_blocks)} blocs générés par Groq")
    
        # Créer la page avec les 100 premiers blocs seulement
        initial_blocks = all_notion_blocks[:100]
        page_data = {
            "parent": {"page_id": parent_page_id},
            "properties": notion_properties,
            "children": initial_blocks
        }
    
        try:
            response = requests.post(
                "https://api.notion.com/v1/pages",
                headers=self.headers,
                json=page_data,
                timeout=30
            )
    
            if response.status_code != 200:
                print(f"Erreur création page : {response.status_code} - {response.text}")
                return None
    
            page = response.json()
            page_id = page["id"]
            url = page.get("url")
            print(f"Page créée : {url}")
    
            self.add_link_to_buildit(title, url)
    
            # === AJOUT DES BLOCS RESTANTS PAR BATCHS DE 100 ===
            remaining_blocks = all_notion_blocks[100:]
            if remaining_blocks:
                print(f"Ajout de {len(remaining_blocks)} blocs supplémentaires...")
    
                for i in range(0, len(remaining_blocks), 100):
                    batch = remaining_blocks[i:i+100]
                    append_data = {"children": batch}
    
                    append_response = requests.patch(
                        f"https://api.notion.com/v1/blocks/{page_id}/children",
                        headers=self.headers,
                        json=append_data,
                        timeout=30
                    )
    
                    if append_response.status_code == 200:
                        print(f"+ {len(batch)} blocs ajoutés")
                    else:
                        print(f"Erreur ajout batch : {append_response.text[:200]}")
    
            print("Page complète avec tout le contenu structuré !")
            return page
    
        except Exception as e:
            print(f"Exception : {e}")
            return None
        
        
    def _map_blocks(self, blocks: list) -> list:
        """Convertit les blocs simples en format API Notion - version ultra-fiable"""
        notion_blocks = []
    
        for block in blocks:
            block_type = block.get("type", "paragraph")
            content = str(block.get("content", "")).strip()
    
            # Ignorer les blocs vides
            if block_type != "divider" and not content:
                continue
    
            base_block = {
                "object": "block",
                "type": block_type,
            }
    
            if block_type in ["heading_1", "heading_2", "heading_3"]:
                base_block[block_type] = {
                    "rich_text": [{"type": "text", "text": {"content": content}}]
                }
    
            elif block_type == "paragraph":
                base_block["paragraph"] = {
                    "rich_text": [{"type": "text", "text": {"content": content}}]
                }
    
            elif block_type == "bulleted_list_item":
                item = {
                    "rich_text": [{"type": "text", "text": {"content": content}}]
                }
                children = block.get("children", [])
                if children:
                    item["children"] = self._map_blocks(children)
                base_block["bulleted_list_item"] = item
    
            elif block_type == "numbered_list_item":
                item = {
                    "rich_text": [{"type": "text", "text": {"content": content}}]
                }
                children = block.get("children", [])
                if children:
                    item["children"] = self._map_blocks(children)
                base_block["numbered_list_item"] = item
    
            elif block_type == "to_do":
                base_block["to_do"] = {
                    "rich_text": [{"type": "text", "text": {"content": content}}],
                    "checked": bool(block.get("checked", False))
                }
    
            elif block_type == "callout":
                emoji = block.get("icon", "💡")
                base_block["callout"] = {
                    "rich_text": [{"type": "text", "text": {"content": content}}],
                    "icon": {"type": "emoji", "emoji": emoji}
                }
    
            elif block_type == "quote":
                base_block["quote"] = {
                    "rich_text": [{"type": "text", "text": {"content": content}}]
                }
    
            elif block_type == "divider":
                base_block["divider"] = {}
    
            else:
                # Fallback : paragraphe simple
                base_block["type"] = "paragraph"
                base_block["paragraph"] = {
                    "rich_text": [{"type": "text", "text": {"content": content}}]
                }
    
            notion_blocks.append(base_block)
    
        return notion_blocks

    def create_meeting(self, title: str, summary: str) -> dict | None:
        """Méthode simple conservée (utilise seulement un paragraphe)"""
        blocks = [{"type": "paragraph", "content": summary}]
        return self.create_page_with_structure(title=title, blocks=blocks)

    def add_link_to_buildit(self, title: str, url: str):
        if not self.buildit_id:
            return

        try:
            block_data = {
                "children": [{
                    "object": "block",
                    "type": "bulleted_list_item",
                    "bulleted_list_item": {
                        "rich_text": [
                            {"type": "text", "text": {"content": "• "}},
                            {"type": "text", "text": {"content": title, "link": {"url": url}}},
                            {"type": "text", "text": {"content": f" [{datetime.now().strftime('%H:%M')}]"}, "annotations": {"color": "gray"}}
                        ]
                    }
                }]
            }
            requests.patch(
                f"https://api.notion.com/v1/blocks/{self.buildit_id}/children",
                headers=self.headers,
                json=block_data
            )
        except Exception as e:
            print(f"⚠️ Lien non ajouté à BuildIT: {e}")
            
def main():
    print("🏗️ BUILDIT AVANCÉ - Test")
    manager = NotionManager()

    if not manager.setup():
        print("❌ Configuration échouée")
        return

    print(f"🔗 BuildIT : {manager.get_buildit_url()}")

    # Exemple avec structure riche
    test_structure = {
        "title": "Réunion Test Avancée",
        "blocks": [
            {"type": "heading_1", "content": "Réunion Stratégique"},
            {"type": "callout", "content": "Projet critique - Urgence haute"},
            {"type": "heading_2", "content": "Décisions"},
            {"type": "bulleted_list_item", "content": "Python choisi pour le backend"},
            {"type": "heading_2", "content": "Actions"},
            {"type": "to_do", "content": "Designer les APIs", "checked": False},
            {"type": "to_do", "content": "Setup cluster EKS", "checked": True},
            {"type": "divider"},
            {"type": "paragraph", "content": "Prochaine réunion jeudi 10h"}
        ],
        "properties": {
            "Date": datetime.now().strftime("%Y-%m-%d"),
            "Participants": ["Alice", "Pierre", "Marie"],
            "Statut": "En cours",
            "Urgence": "Haute"
        }
    }

    page = manager.create_page_with_structure(**test_structure)
    if page:
        print("Tout fonctionne parfaitement !")

if __name__ == "__main__":
    main()