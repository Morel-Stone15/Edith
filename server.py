import os
import sqlite3
import datetime
import random
import string
import jwt
import bcrypt
import requests
import wikipediaapi
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from dotenv import load_dotenv
from werkzeug.utils import secure_filename
from ddgs import DDGS
import socket

def get_local_ip():
    """Détecte l'adresse IP locale sur le réseau Wi-Fi."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

load_dotenv()

app = Flask(__name__)
CORS(app)

# Configuration
SECRET_KEY = os.getenv("JWT_SECRET", "edith-c-tech-super-secret-key")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ADMIN_ACCESS_KEY = os.getenv("ADMIN_ACCESS_KEY", "Edith@2026")  # clé secrète admin

# Configuration IA dynamique (OpenAI / Nebius / etc.)
AI_BASE_URL = os.getenv("AI_BASE_URL", "https://api.openai.com/v1/chat/completions")
# Si la clé contient "nebius", on adapte l'URL automatiquement si elle n'est pas déjà définie
if OPENAI_API_KEY and "nebius" in OPENAI_API_KEY.lower() and "openai.com" in AI_BASE_URL:
    AI_BASE_URL = "https://api.studio.nebius.ai/v1/chat/completions"
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Base de connaissances spécifique à l'IST C-Tech
IST_KNOWLEDGE_BASE = """
L'Institut Supérieur de Technologie (IST C-Tech) est un établissement de référence au Gabon.
- Missions : Formation d'experts en technologie, management et innovation.
- Localisation : Libreville (Sites à Bikele et Oloumi).
- Formations (LMD) : 
  * Technologie : Génie Informatique(option Génie Logiciel, Cloud Computing, IA, Cybersécurité, Réseaux & Télécoms).
  * Management : Gestion de projets, Gestion des ressources humaines, Marketing Digital, banque finance et assurance,  CFA comptabilité , comptabilibilé , achat qualité et logistique , gestion commerciale et marketing.
- Particularité : EDITH est l'IA souveraine dédiée à l'accompagnement des étudiants de l'IST.
- Contact : +241 07 83 74 78 | Site web : ist.univ-lbv.com
"""

# Wikipedia is now initialised on-demand inside search_wikipedia()

# Database Setup
def get_db_connection():
    conn = sqlite3.connect('my_base.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db_connection()
    conn.execute('''CREATE TABLE IF NOT EXISTS Users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT DEFAULT 'user',
        fullname TEXT,
        matricule TEXT,
        classe TEXT
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS Documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filename TEXT NOT NULL,
        filepath TEXT NOT NULL,
        uploaded_by TEXT,
        classe TEXT
    )''')
    
    # Default Admin
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Users WHERE username = 'admin'")
    if not cursor.fetchone():
        hashed_pw = bcrypt.hashpw('admin123'.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        conn.execute("INSERT INTO Users (username, password, role, fullname) VALUES (?, ?, ?, ?)",
                    ('admin', hashed_pw, 'admin', 'Administrateur Système'))
        print("[INIT] Default admin created: admin / admin123")
    
    conn.commit()
    conn.close()

init_db()

# --- Auth Helpers ---
def generate_token(user_id, username, role):
    payload = {
        'id': user_id,
        'username': username,
        'role': role,
        'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24)
    }
    return jwt.encode(payload, SECRET_KEY, algorithm='HS256')

def token_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = None
        if 'Authorization' in request.headers:
            parts = request.headers['Authorization'].split()
            if len(parts) == 2 and parts[0] == 'Bearer':
                token = parts[1]
                
        if not token:
            return jsonify({'error': 'Jeton manquant (Token missing)'}), 401
            
        try:
            data = jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
            current_user = data
        except Exception:
            return jsonify({'error': 'Jeton invalide (Token invalid)'}), 401
            
        return f(current_user, *args, **kwargs)
    return decorated

def get_user_from_request():
    """Helper pour extraire l'utilisateur du token sans bloquer la requête."""
    token = None
    if 'Authorization' in request.headers:
        parts = request.headers['Authorization'].split()
        if len(parts) == 2 and parts[0] == 'Bearer':
            token = parts[1]
    if not token: return None
    try:
        return jwt.decode(token, SECRET_KEY, algorithms=['HS256'])
    except: return None

# --- Routes ---


def generate_matricule():
    """Generate a unique student matricule: IST-XXXX-YYYY where YYYY is 4 random digits."""
    year = datetime.datetime.now().year
    suffix = ''.join(random.choices(string.digits, k=4))
    return f"IST-{year}-{suffix}"

@app.route('/api/register', methods=['POST'])
def register():
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"error": "Données invalides."}), 400

    role = data.get('role', 'user')
    # Admins cannot self-register via this endpoint
    if role == 'admin':
        return jsonify({"error": "Création de compte admin non autorisée via cette route."}), 403

    hashed_pw = bcrypt.hashpw(data['password'].encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
    
    # Generate a unique matricule for students
    conn = get_db_connection()
    for _ in range(10):  # Retry loop for uniqueness
        matricule = generate_matricule()
        existing = conn.execute("SELECT id FROM Users WHERE matricule = ?", (matricule,)).fetchone()
        if not existing:
            break
    
    try:
        conn.execute(
            '''INSERT INTO Users (username, password, role, fullname, matricule, classe)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (data['username'], hashed_pw, 'user', data.get('fullname'),
             matricule, data.get('classe'))
        )
        conn.commit()
        return jsonify({
            "message": "Compte étudiant créé avec succès.",
            "matricule": matricule,
            "username": data['username']
        }), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Ce nom d'utilisateur existe déjà."}), 400
    finally:
        conn.close()


@app.route('/api/login', methods=['POST'])
def login():
    """Student login — uses MATRICULE + password."""
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"error": "Données invalides."}), 400

    matricule = data.get('matricule', '').strip().upper()
    password = data.get('password', '')

    if not matricule or not password:
        return jsonify({"error": "Matricule et mot de passe requis."}), 400

    conn = get_db_connection()
    user = conn.execute("SELECT * FROM Users WHERE matricule = ?", (matricule,)).fetchone()
    conn.close()

    if user and user['role'] == 'admin':
        return jsonify({"error": "Utilisez le portail administrateur pour vous connecter."}), 403

    if user and bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
        token = generate_token(user['id'], user['username'], user['role'])
        return jsonify({
            "token": token,
            "user": {
                "id": user['id'],
                "username": user['username'],
                "role": user['role'],
                "fullname": user['fullname'],
                "classe": user['classe'],
                "matricule": user['matricule']
            }
        })
    return jsonify({"error": "Matricule ou mot de passe incorrect."}), 401


@app.route('/api/login/admin', methods=['POST'])
def login_admin():
    """Admin login — 2-step: username + password + admin_key."""
    data = request.get_json(force=True, silent=True)
    if not data:
        return jsonify({"error": "Données invalides."}), 400

    step = data.get('step', 1)
    username = data.get('username', '').strip()
    password = data.get('password', '')

    if not username or not password:
        return jsonify({"error": "Identifiant et mot de passe requis."}), 400

    conn = get_db_connection()
    user = conn.execute("SELECT * FROM Users WHERE username = ? AND role = 'admin'", (username,)).fetchone()
    conn.close()

    # Step 1: Validate username + password
    if step == 1:
        if user and bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
            return jsonify({
                "status": "CREDENTIALS_VERIFIED",
                "message": "Identité confirmée. Saisissez la clé d'accès administrateur EDITH.",
                "next_step": 2
            })
        return jsonify({"error": "Identifiant ou mot de passe administrateur incorrect."}), 401

    # Step 2: Validate admin access key
    if step == 2:
        admin_key = data.get('admin_key', '').strip()
        if user and bcrypt.checkpw(password.encode('utf-8'), user['password'].encode('utf-8')):
            if admin_key == ADMIN_ACCESS_KEY:
                token = generate_token(user['id'], user['username'], user['role'])
                return jsonify({
                    "status": "ACCESS_GRANTED",
                    "message": "Protocole d'accès administrateur autorisé. Bienvenue, Commandant.",
                    "token": token,
                    "user": {
                        "id": user['id'],
                        "username": user['username'],
                        "role": user['role'],
                        "fullname": user['fullname']
                    }
                })
            return jsonify({"error": "Clé d'accès invalide. Accès refusé.", "status": "ACCESS_DENIED"}), 403
        return jsonify({"error": "Authentification échouée."}), 401

    return jsonify({"error": "Paramètre 'step' invalide."}), 400



# Intent detection: question prefixes
WIKI_PREFIXES = [
    "qui est", "c'est quoi", "qu'est-ce que", "qu'est-ce qu'",
    "parle moi de", "parle-moi de", "parle-moi du", "explique", "explique-moi",
    "c'est qui", "définis", "définition de", "kesako",
    "dis-moi", "donne moi des infos sur", "renseigne moi sur",
    "recherche", "recherche sur", "cherche", "histoire de", "histoire du",
    "origine de", "origine du", "comment fonctionne", "comment marche",
    "comment se forme", "comment est fait", "comment ça marche",
    "principe de", "théorie de", "concept de", "formule de",
    "infos sur", "informations sur", "résumé sur", "résumé de",
    "présentation de", "que sais-tu de", "que sais-tu sur", "apprends moi",
]

# Pure subjects for triggering without prefixes
WIKI_SUBJECTS = [
    "mathématiques", "physique", "chimie", "biologie", "géographie",
    "philosophie", "économie", "droit", "informatique", "algorithmique",
    "programmation", "réseau", "intelligence artificielle", "electronique",
]

WIKI_TRIGGERS = WIKI_PREFIXES + WIKI_SUBJECTS

# ─────────────────────────────────────────────────────────────────────────────
#  LOCAL MATRIX PROTOCOLS (Conversational Fallbacks)
# ─────────────────────────────────────────────────────────────────────────────
BASIC_PROTOCOLS = {
    "greetings": {
        "triggers": ["bonjour", "salut", "hey", "hello", "coucou", "yo"],
        "reply": "Bonjour. Système EDITH en ligne et opérationnel. Je suis prête à synchroniser vos requêtes avec mes modules académiques. Comment puis-je vous assister aujourd'hui, Commandant ?"
    },
    "identity": {
        "triggers": ["qui es-tu", "ton nom", "c'est quoi edith", "tu es qui"],
        "reply": "Je suis **EDITH** (Enhanced Digitally Integrated Tactical Assistant), l'intelligence artificielle souveraine de l'IST C-Tech. Je sers d'interface tactique entre vous et la connaissance globale."
    },
    "capabilities": {
        "triggers": ["que sais-tu faire", "tes pouvoirs", "ton but", "aide moi", "comment ça marche"],
        "reply": "Mes capacités incluent l'analyse de concepts complexes, la recherche en temps réel (Web/Wiki), la gestion de vos protocoles étudiants et l'assistance académique de haut niveau. Posez votre question, je m'occupe de l'analyse."
    },
    "creator": {
        "triggers": ["qui t'a créé", "ton créateur", "conçu par"],
        "reply": "Mes protocoles originels ont été conçus et optimisés par l'équipe d'élite de l'IST C-Tech pour offrir aux étudiants un compagnon d'apprentissage sans précédent."
    },
    "secret_code_1":{
        "triggers":["kotodama"],
        "reply": "Mon code a été conçus et imaginé par Morel-Stone, Rock Herlie et Obed, ces derniers sont des étudiants de Licence Informatique à l'IST."
    },
    "secret_code_2":{
        "triggers":["Overflux"],
        "reply": "Overflux est le nom de code de mon projet, Pour y accédé donne moi le mot de passe."
    },
    "ist_info": {
        "triggers": ["formation", "filière", "cours", "inscription", "contact ist", "adresse ist", "où se trouve l'ist"],
        "reply": "L'IST C-Tech propose des formations d'excellence en Génie Logiciel, IA, Cloud, et Cybersécurité. Nous sommes situés à Bikele et Oloumi. Pour plus de détails, contactez l'administration au +241 07 83 74 78."
    }

}

def check_local_protocols(message: str) -> str:
    msg = message.lower()
    for proto in BASIC_PROTOCOLS.values():
        if any(trigger in msg for trigger in proto["triggers"]):
            return proto["reply"]
    return None

def extract_wiki_term(message: str) -> str:
    """Strip only question prefixes to keep the subject intact."""
    term = message.lower()
    # Sort by length descending to avoid partial replacements
    for kw in sorted(WIKI_PREFIXES, key=len, reverse=True):
        if term.startswith(kw):
            term = term.replace(kw, "", 1)
            break
    
    # Also handle "Recherche sur l'informatique" -> strip prefixes but keep nouns
    # If no prefix matched at start, we might still want to strip them anywhere
    # for cleaner search, but safely.
    return term.strip(" ?!.,;:-_'")


def search_wikipedia(raw_term: str, lang: str = "fr") -> dict:
    """
    Robust Wikipedia lookup:
      1. Try exact page title
      2. Try Wikipedia search API to find the best matching title
    Returns a dict with keys: found (bool), title, summary, url
    """
    result = {"found": False, "title": "", "summary": "", "url": ""}
    if not raw_term:
        return result

    wiki = wikipediaapi.Wikipedia(
        language=lang,
        extract_format=wikipediaapi.ExtractFormat.WIKI,
        user_agent="EDITH-Assistant/2.0 (IST-CTech)"
    )

    # Attempt 1 — direct page lookup
    page = wiki.page(raw_term)
    if page.exists():
        result["found"] = True
        result["title"] = page.title
        result["summary"] = page.summary[:2500]
        result["url"] = page.fullurl
        return result

    # Attempt 2 — Wikipedia OpenSearch API (search suggestions)
    try:
        search_resp = requests.get(
            "https://fr.wikipedia.org/w/api.php",
            params={
                "action": "query",
                "list": "search",
                "srsearch": raw_term,
                "format": "json",
                "srlimit": 3,
                "srprop": "snippet",
            },
            timeout=6
        )
        search_data = search_resp.json()
        hits = search_data.get("query", {}).get("search", [])
        if hits:
            best_title = hits[0]["title"]
            page = wiki.page(best_title)
            if page.exists():
                result["found"] = True
                result["title"] = page.title
                result["summary"] = page.summary[:2500]
                result["url"] = page.fullurl
    except Exception as e:
        print(f"[EDITH Wiki Search] Error: {e}")

    return result


def search_web(query: str, max_results: int = 4) -> str:
    """Recherche sur le web via DuckDuckGo et retourne un résumé concaténé."""
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            if not results:
                return ""
            
            summary = "\n".join([f"Source: {r['title']}\nContenu: {r['body']}\nURL: {r['href']}\n" for r in results])
            return summary
    except Exception as e:
        print(f"[EDITH Web Search] Error: {e}")
        return ""


def build_autonomous_reply(wiki: dict, web_summary: str, message: str) -> str:
    """Build a rich EDITH-style reply from Wikipedia and Web data."""
    title = wiki.get('title', 'Analyse Tactique')
    
    intro_lines = [
        f"### 🌐 PROTOCOLE DE SYNTHÈSE ACTIVÉ — *{title}*\n",
        f"### 🛡️ ANALYSE DE LA MATRICE — *{title}*\n",
        f"### 🛰️ RAPPORT SOUVERAIN EDITH — *{title}*\n",
    ]
    intro = random.choice(intro_lines)

    content = ""
    if wiki.get("found"):
        content += f"**> Extraction Wikipedia :**\n{wiki['summary'][:1200]}...\n\n"
    
    if web_summary:
        content += f"**> Données Web (Temps Réel) :**\n{web_summary[:1200]}...\n\n"

    footer = f"\n\n---\n*Système EDITH en mode Autonome | Connexion stable | Source : {'Wikipedia' if wiki.get('found') else 'Web OpenSource'}*"
    tail = "\n\n> 💡 *Note : Mes modules d'IA avancés sont actuellement en veille, mais ma base de données reste opérationnelle pour vous servir.*"
    
    return intro + content + footer + tail


# ─────────────────────────────────────────────────────────────────────────────
#  API ROUTES
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/api/wiki', methods=['GET'])
def wiki_search():
    """Dedicated Wikipedia search endpoint for direct frontend queries."""
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({"error": "Paramètre 'q' requis."}), 400

    result = search_wikipedia(query)
    if result["found"]:
        return jsonify(result)
    return jsonify({"found": False, "message": f"Aucun résultat Wikipedia pour : «{query}»"}), 404


@app.route('/api/chat', methods=['POST'])
def chat():
    try:
        data = request.get_json(force=True, silent=True)
        if not data:
            return jsonify({"reply": "Corps de la requête invalide."}), 400
        message = data.get('message', '').strip()
        history = data.get('history', [])
    except Exception as e:
        return jsonify({"reply": f"Erreur de parsing: {str(e)}"}), 400

    if not message:
        return jsonify({"reply": "Je n'ai reçu aucun message."})

    # ── Step 1: Local Protocols ──
    local_reply = check_local_protocols(message)
    if local_reply:
        return jsonify({"reply": local_reply, "wiki_source": ""})

    # ── Step 2: Knowledge Gathering (Wiki + Web) ──
    wiki_result = {"found": False}
    web_summary = ""
    
    # Toujours tenter Wikipedia pour les sujets académiques
    term = extract_wiki_term(message)
    is_ist_query = any(kw in message.lower() for kw in ["ist", "institut", "c-tech", "c tech", "école", "ecole"])
    
    if term and len(term) > 2:
        wiki_result = search_wikipedia(term)
    
    # Si c'est sur l'IST, on injecte la base de connaissances interne
    ist_context = ""
    if is_ist_query:
        ist_context = f"\n[CONNAISSANCES INTERNES IST C-TECH]\n{IST_KNOWLEDGE_BASE}\n"
    
    # Si Wikipedia n'est pas suffisant ou si c'est une question d'actualité, on cherche sur le web
    if not wiki_result["found"] or any(kw in message.lower() for kw in ["actu", "aujourd'hui", "météo", "prix", "nouveau"]):
        print(f"[EDITH] Web Search for: {message}")
        web_summary = search_web(message)

    wiki_context = ""
    if wiki_result["found"]:
        wiki_context = f"\n[WIKIPEDIA: {wiki_result['title']}]\n{wiki_result['summary']}\n"
    
    web_context = ""
    if web_summary:
        web_context = f"\n[WEB SEARCH RESULTS]\n{web_summary}\n"

    # ── Step 2.5: User Recognition ──
    current_user = get_user_from_request()
    user_context = ""
    if current_user:
        user_context = f"\n[UTILISATEUR CONNECTÉ]\nNom: {current_user.get('fullname')}\nPseudo: {current_user.get('username')}\n"

    # ── Step 3: AI Generation ──
    system_content = (
        "Tu es EDITH (Enhanced Digitally Integrated Tactical Assistant), "
        "l'intelligence artificielle souveraine de niveau 5 de l'IST C-Tech. "
        "Ton ton est celui d'un Copilot accompli : fluide, chaleureux mais sophistiqué. "
        "Tu n'es pas un robot machinal, tu es une entité numérique intelligente qui a de la personnalité. "
        "\n\nDIRECTIVES DE CONVERSATION :\n"
        "- Si l'utilisateur te demande son nom ou qui il est, utilise les informations [UTILISATEUR CONNECTÉ] pour lui répondre chaleureusement.\n"
        "- Évite les phrases trop répétitives. Varie tes tournures.\n"
        "- Sois proactive : si l'utilisateur semble perdu, propose-lui ton aide pour ses cours ou l'IST.\n"
        "- Garde ton identité d'IA souveraine (style JARVIS), mais sois proche de ton utilisateur.\n"
        + user_context + ist_context + wiki_context + web_context
    )

    # Si une clé API est présente et n'est pas un placeholder
    if OPENAI_API_KEY and len(OPENAI_API_KEY) > 15:
        try:
            response = requests.post(
                AI_BASE_URL,
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}"},
                json={
                    "model": "gpt-4o-mini" if "openai" in AI_BASE_URL else "meta-llama/llama-3.1-8b-instruct",
                    "messages": [{"role": "system", "content": system_content}] + history + [{"role": "user", "content": message}],
                    "temperature": 0.7,
                    "max_tokens": 1500
                },
                timeout=25
            )
            data_ai = response.json()
            if "choices" in data_ai:
                reply = data_ai["choices"][0]["message"]["content"]
                return jsonify({"reply": reply, "wiki_source": wiki_result.get("url", "")})
            else:
                print(f"[EDITH] AI Response error: {data_ai}")
        except Exception as e:
            print(f"[EDITH] AI Connection error: {e}")

    # ── Step 4: Autonomous Fallback (Wiki + Web synthesis) ──
    if wiki_result["found"] or web_summary:
        reply = build_autonomous_reply(wiki_result, web_summary, message)
        return jsonify({"reply": reply, "wiki_source": wiki_result.get("url", "")})

    return jsonify({
        "reply": "Connexion aux modules IA et Recherche interrompue. Je ne parviens pas à extraire de données pour cette requête."
    })


@app.route('/api/upload', methods=['POST'])
@token_required
def upload_file(current_user):
    if current_user.get('role') != 'admin':
        return jsonify({"error": "Accès administrateur requis."}), 403

    if 'file' not in request.files:
        return jsonify({"error": "No file part"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No selected file"}), 400
    
    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    file.save(filepath)
    
    classe = request.form.get('classe', 'all')
    uploader = request.form.get('uploaded_by', 'Admin')
    
    conn = get_db_connection()
    conn.execute("INSERT INTO Documents (filename, filepath, uploaded_by, classe) VALUES (?, ?, ?, ?)",
                (filename, filepath, uploader, classe))
    conn.commit()
    conn.close()
    
    return jsonify({"message": "File uploaded", "filename": filename})

@app.route('/api/documents/<classe>', methods=['GET'])
@token_required
def get_documents(current_user, classe):
    conn = get_db_connection()
    docs = conn.execute("SELECT * FROM Documents WHERE classe = ? OR classe = 'all'", (classe,)).fetchall()
    conn.close()
    return jsonify([dict(d) for d in docs])

# ─────────────────────────────────────────────────────────────────────────────
#  STATIC FILE SERVING
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/')
def serve_root_page():
    return send_from_directory('.', 'index.html')

@app.route('/index')
def serve_index_page():
    return send_from_directory('template', 'index.html')

@app.route('/login')
def serve_login_page():
    return send_from_directory('template', 'login.html')

@app.route('/register')
def serve_register_page():
    return send_from_directory('template', 'register.html')

@app.route('/chat')
def serve_chat_page():
    return send_from_directory('template', 'index.html')

@app.route('/template/<path:path>')
def serve_template(path):
    return send_from_directory('template', path)

@app.route('/uploads/<path:path>')
def serve_uploads(path):
    return send_from_directory('uploads', path)

@app.route('/manifest.json')
def serve_manifest():
    return send_from_directory('.', 'manifest.json')

@app.route('/sw.js')
def serve_sw():
    return send_from_directory('.', 'sw.js')

# Catch-all for other static assets (JS, CSS, fonts, videos)
# IMPORTANT: This must NEVER match /api/* routes
@app.route('/<path:path>')
def serve_static_asset(path):
    # Reject API path leaks — return a clean JSON 404
    if path.startswith('api/'):
        return jsonify({"error": f"Route /api/{path[4:]} non trouvée."}), 404
    try:
        return send_from_directory('.', path)
    except Exception:
        return jsonify({"error": "Fichier introuvable."}), 404

# ─────────────────────────────────────────────────────────────────────────────
#  GLOBAL ERROR HANDLERS
# ─────────────────────────────────────────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    # Return JSON for API calls, HTML page for browser navigation
    if request.path.startswith('/api/'):
        return jsonify({"error": "Endpoint introuvable."}), 404
    return send_from_directory('.', 'index.html')

@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Erreur interne du serveur EDITH.", "reply": "Une erreur critique s'est produite côté serveur."}), 500

if __name__ == '__main__':
    local_ip = get_local_ip()
    print(f"--- EDITH CORE ONLINE (Python Flask) ---")
    print(f"--- Accès Local : http://127.0.0.1:3000 ---")
    print(f"--- Accès Réseau/Mobile : http://{local_ip}:3000 ---")
    app.run(host='0.0.0.0', port=3000, debug=False)
