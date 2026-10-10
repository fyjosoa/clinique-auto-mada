# -*- coding: utf-8 -*-
"""
CliniqueAutoMada v8.1 - Devis -> Facture (Windows + Android)
- Rétrocompatible avec la base de données V7 et V7.x
- Interface adaptative : téléphones (petits/grands), tablettes, portrait et paysage
- Gestion complète pièces, fournisseurs, articles, stock, acomptes et statistiques
"""

import functools
import os
import re
import smtplib
import sqlite3
import threading
import urllib.parse
import webbrowser
from contextlib import contextmanager
from datetime import datetime
from email.message import EmailMessage

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp, sp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.filechooser import FileChooserIconView
from kivy.uix.gridlayout import GridLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.utils import platform

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import simpleSplit
    from reportlab.pdfgen import canvas
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False

try:
    from pypdf import PdfReader
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False

Window.softinput_mode = "below_target"

# ============================================================
# CHEMINS
# ============================================================

DOSSIER_APP = DOSSIER_PDF = DB_PATH = ""


def init_chemins(app):
    global DOSSIER_APP, DOSSIER_PDF, DB_PATH
    if platform == "android":
        DOSSIER_APP = app.user_data_dir
    else:
        DOSSIER_APP = os.path.join(os.path.expanduser("~"), "CliniqueAutoMada")
    DOSSIER_PDF = os.path.join(DOSSIER_APP, "PDF_Export")
    os.makedirs(DOSSIER_PDF, exist_ok=True)
    DB_PATH = os.path.join(DOSSIER_APP, "clinique_auto_mada.db")


# ============================================================
# COULEURS & CHARTE GRAPHIQUE AMÉLIORÉE
# ============================================================

BLEU = (0.15, 0.45, 0.75, 1)
BLEU_FONCE = (0.05, 0.20, 0.40, 1)
GRIS_TEXTE = (0.25, 0.25, 0.25, 1)
GRIS = (0.6, 0.6, 0.6, 1)
VERT = (0.12, 0.55, 0.28, 1)
ROUGE = (0.68, 0.15, 0.15, 1)
ORANGE = (0.88, 0.48, 0.12, 1)


# ============================================================
# BASE DE DONNÉES & MIGRATION AUTOMATIQUE V7 -> V8
# ============================================================

@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _ajouter_colonnes(cur, table, colonnes):
    existantes = {r[1] for r in cur.execute(f"PRAGMA table_info({table})")}
    for nom, definition in colonnes:
        if nom not in existantes:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {nom} {definition}")


def init_database():
    with db() as c:
        # Tables de base (compatibilité V7)
        c.execute("""CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT, nom TEXT DEFAULT '',
            telephone TEXT DEFAULT '', adresse TEXT DEFAULT '', email TEXT DEFAULT '')""")
        c.execute("""CREATE TABLE IF NOT EXISTS vehicules (
            id INTEGER PRIMARY KEY AUTOINCREMENT, client_id INTEGER,
            marque TEXT DEFAULT '', modele TEXT DEFAULT '',
            immatriculation TEXT DEFAULT '', kilometrage TEXT DEFAULT '',
            moteur TEXT DEFAULT '', vin TEXT DEFAULT '')""")
        c.execute("""CREATE TABLE IF NOT EXISTS devis (
            id INTEGER PRIMARY KEY AUTOINCREMENT, client TEXT DEFAULT '',
            vehicule TEXT DEFAULT '', immatriculation TEXT DEFAULT '',
            date_devis TEXT DEFAULT '', kilometrage TEXT DEFAULT '',
            total REAL DEFAULT 0, statut TEXT DEFAULT 'En attente',
            version INTEGER DEFAULT 1, tva_taux REAL DEFAULT 0)""")
        c.execute("""CREATE TABLE IF NOT EXISTS lignes_devis (
            id INTEGER PRIMARY KEY AUTOINCREMENT, devis_id INTEGER, numero INTEGER,
            type_ligne TEXT DEFAULT 'Pièce', designation TEXT DEFAULT '',
            quantite REAL DEFAULT 1, prix_unitaire REAL DEFAULT 0, total REAL DEFAULT 0)""")
        c.execute("""CREATE TABLE IF NOT EXISTS factures (
            id INTEGER PRIMARY KEY AUTOINCREMENT, devis_id INTEGER,
            client TEXT DEFAULT '', vehicule TEXT DEFAULT '',
            immatriculation TEXT DEFAULT '', date_facture TEXT DEFAULT '',
            total REAL DEFAULT 0, tva_taux REAL DEFAULT 0, paye INTEGER DEFAULT 0,
            acompte REAL DEFAULT 0)""")
        c.execute("""CREATE TABLE IF NOT EXISTS lignes_facture (
            id INTEGER PRIMARY KEY AUTOINCREMENT, facture_id INTEGER, numero INTEGER,
            type_ligne TEXT DEFAULT 'Pièce', designation TEXT DEFAULT '',
            quantite REAL DEFAULT 1, prix_unitaire REAL DEFAULT 0, total REAL DEFAULT 0)""")
        c.execute("""CREATE TABLE IF NOT EXISTS historique_prix (
            id INTEGER PRIMARY KEY AUTOINCREMENT, marque TEXT DEFAULT '',
            modele TEXT DEFAULT '', designation TEXT DEFAULT '',
            prix REAL DEFAULT 0, date_prix TEXT DEFAULT '')""")
        c.execute("CREATE TABLE IF NOT EXISTS parametres (cle TEXT PRIMARY KEY, valeur TEXT)")

        # Nouvelles tables V8 (Fournisseurs, Articles/Pièces, Historique achats)
        c.execute("""CREATE TABLE IF NOT EXISTS fournisseurs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, nom TEXT DEFAULT '',
            telephone TEXT DEFAULT '', whatsapp TEXT DEFAULT '', email TEXT DEFAULT '',
            nif TEXT DEFAULT '', stat TEXT DEFAULT '')""")
        c.execute("""CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT, reference TEXT DEFAULT '',
            designation TEXT DEFAULT '', fournisseur TEXT DEFAULT '',
            prix_achat REAL DEFAULT 0, prix_vente REAL DEFAULT 0, stock REAL DEFAULT 0)""")
        c.execute("""CREATE TABLE IF NOT EXISTS historique_achats (
            id INTEGER PRIMARY KEY AUTOINCREMENT, article_id INTEGER,
            fournisseur TEXT DEFAULT '', quantite REAL DEFAULT 0,
            prix_achat REAL DEFAULT 0, date_achat TEXT DEFAULT '')""")

        # Migration automatique des colonnes manquantes si la base V7 existe déjà
        _ajouter_colonnes(c, "clients", [("email", "TEXT DEFAULT ''"), ("adresse", "TEXT DEFAULT ''")])
        _ajouter_colonnes(c, "vehicules", [("modele", "TEXT DEFAULT ''"), ("vin", "TEXT DEFAULT ''")])
        _ajouter_colonnes(c, "devis", [("version", "INTEGER DEFAULT 1"), ("tva_taux", "REAL DEFAULT 0")])
        _ajouter_colonnes(c, "factures", [("tva_taux", "REAL DEFAULT 0"), ("paye", "INTEGER DEFAULT 0"), ("acompte", "REAL DEFAULT 0")])


# ---- Paramètres ---------------------------------------------------------

DEFAUTS = {
    "garage_nom": "CliniqueAutoMada - Entreprise Individuelle",
    "garage_adresse": "Itaosy Ambanilalana 102 Antananarivo",
    "garage_nif": "NIF: 4011891188 – RCS: 108011015111",
    "garage_contact": "Tél: 0346680206 / 0330339135 | Email: Steeph.szon@gmail.com",
    "tva_taux": "0",
    "smtp_hote": "smtp.gmail.com",
    "smtp_port": "465",
    "smtp_user": "",
    "smtp_mdp": "",
}
_CACHE = None


def param(cle):
    global _CACHE
    if _CACHE is None:
        with db() as c:
            _CACHE = {r["cle"]: r["valeur"] for r in c.execute("SELECT cle, valeur FROM parametres")}
    return _CACHE.get(cle, DEFAUTS.get(cle, ""))


def set_param(cle, valeur):
    param(cle)
    with db() as c:
        c.execute("INSERT OR REPLACE INTO parametres (cle, valeur) VALUES (?, ?)", (cle, valeur))
    _CACHE[cle] = valeur


# ============================================================
# OUTILS
# ============================================================

def prix_nombre(texte):
    try:
        val = str(texte).replace(" ", "").replace(",", ".")
        return float(val) if val else 0.0
    except Exception:
        return 0.0


def prix_affiche(nombre):
    try:
        return "{:,.0f} Ar".format(float(nombre)).replace(",", " ")
    except Exception:
        return "0 Ar"


def nombre_txt(x):
    try:
        x = float(x)
        return str(int(x)) if x == int(x) else str(x)
    except Exception:
        return "0"


def nom_fichier_sur(texte):
    return re.sub(r"[^A-Za-z0-9_-]", "", str(texte)) or "SANS"


def numero_doc(prefixe, doc_id, date_txt=""):
    annee = str(date_txt)[-4:] if len(str(date_txt)) >= 4 else str(datetime.now().year)
    return f"{prefixe}-{annee}-{int(doc_id):04d}"


def totaux(lignes, taux=0.0):
    pieces = sum(l["total"] for l in lignes if l.get("type") != "M.O.")
    mo = sum(l["total"] for l in lignes if l.get("type") == "M.O.")
    ht = pieces + mo
    tva = ht * taux / 100.0
    return {"pieces": pieces, "mo": mo, "ht": ht, "tva": tva, "ttc": round(ht + tva)}


def numero_whatsapp(tel):
    n = "".join(ch for ch in str(tel) if ch.isdigit())
    if n.startswith("00"):
        n = n[2:]
    if n.startswith("261"):
        return n
    if n.startswith("0"):
        n = n[1:]
    return "261" + n if n else ""


def ouvrir_whatsapp(telephone, message):
    n = numero_whatsapp(telephone)
    msg = urllib.parse.quote(str(message))
    webbrowser.open(f"https://wa.me/{n}?text={msg}" if n else f"https://wa.me/?text={msg}")


def ouvrir_ou_partager(chemin):
    try:
        if platform == "android":
            from androidstorage4kivy import ShareSheet
            ShareSheet().share_file(chemin)
        elif platform == "win":
            os.startfile(chemin)  # noqa
        else:
            webbrowser.open("file://" + chemin)
    except Exception as e:
        afficher_popup("Ouverture impossible", str(e))


def securise(fn):
    @functools.wraps(fn)
    def wrapper(*a, **k):
        try:
            return fn(*a, **k)
        except Exception as e:
            afficher_popup("Erreur", str(e))
    return wrapper


# ============================================================
# WIDGETS DE BASE ADAPTÉS AU MOBILE
# ============================================================

# --- Échelle adaptative : s'ajuste à la taille réelle de l'écran -----------
S = 1.0           # facteur d'échelle (0.85 petit téléphone -> 1.4 tablette)
COMPACT = False   # True sur les petits écrans (lignes de devis sur 2 rangées)


def init_echelle():
    # Calcule l'échelle à partir du plus petit côté de l'écran (stable en rotation)
    global S, COMPACT
    try:
        court = min(Window.width, Window.height) / dp(1)
    except Exception:
        court = 360.0
    if court <= 0:
        court = 360.0
    S = max(0.85, min(1.4, court / 360.0))
    COMPACT = court < 420


def D(x):
    return dp(x) * S


def F(x):
    return sp(x) * S


def taille_popup(largeur=0.9, hauteur=0.4, minimum=0):
    # Popup flexible : plus étroit sur tablette, plus haut en paysage
    W_, H_ = Window.size
    paysage = W_ > H_
    lrg = min(largeur, 0.7) if paysage else largeur
    hau = min(0.95, hauteur * 1.9) if paysage else hauteur
    w_px = min(W_ * lrg, D(560))
    h_px = min(H_ * 0.95, max(H_ * hau, minimum))
    return {"size_hint": (None, None), "size": (w_px, h_px)}


def bouton(texte, couleur=BLEU, hauteur=45):
    b = Button(text=str(texte), font_size=F(13), bold=True, size_hint_y=None,
               height=D(hauteur), background_normal="", background_color=couleur,
               halign="center", valign="middle")
    b.bind(size=lambda i, s: setattr(i, "text_size", (s[0] - D(6), s[1])))
    return b


def titre(texte):
    lbl = Label(text=str(texte), font_size=F(18), bold=True, color=BLEU_FONCE,
                size_hint_y=None, height=D(40), halign="center", valign="middle",
                shorten=True, shorten_from="right")
    lbl.bind(size=lambda i, s: setattr(i, "text_size", s))
    return lbl


def etiquette(texte, taille=12, couleur=GRIS_TEXTE, gras=False, hauteur=22, multi=False):
    lbl = Label(text=str(texte), font_size=F(taille), color=couleur, bold=gras,
                halign="left", valign="top" if multi else "middle",
                shorten=not multi, shorten_from="right",
                size_hint_y=None, height=D(hauteur))
    lbl.bind(size=lambda i, s: setattr(i, "text_size", s))
    return lbl


def bouton_retour(ecran):
    b = bouton("RETOUR À L'ACCUEIL", BLEU_FONCE, 42)
    b.bind(on_release=lambda x: setattr(ecran.manager, "current", "accueil"))
    return b


def _label_popup(message):
    lbl = Label(text=str(message), font_size=F(13), halign="center", valign="middle")
    lbl.bind(size=lambda i, s: setattr(i, "text_size", (s[0] - D(10), s[1])))
    return lbl


def afficher_popup(titre_txt, message_txt):
    pop = Popup(title=str(titre_txt), content=_label_popup(message_txt),
                **taille_popup(0.88, 0.38, D(170)))
    pop.open()
    return pop


def popup_actions(titre_txt, message, actions):
    box = BoxLayout(orientation="vertical", spacing=D(8), padding=D(10))
    box.add_widget(_label_popup(message))
    minimum = len(actions) * D(50) + D(150)
    pop = Popup(title=str(titre_txt), content=box, **taille_popup(0.9, 0.55, minimum))
    for texte, couleur, fn in actions:
        b = bouton(texte, couleur, 42)

        def cliquer(x, f=fn):
            pop.dismiss()
            if f:
                f()
        b.bind(on_release=cliquer)
        box.add_widget(b)
    pop.open()
    return pop


def carte(titre_txt, sous_txt, actions):
    box = BoxLayout(orientation="vertical", size_hint_y=None, height=D(124),
                    padding=D(8), spacing=D(4))
    box.add_widget(etiquette(titre_txt, 13, BLEU_FONCE, True, 22))
    box.add_widget(etiquette(sous_txt, 11, GRIS_TEXTE, False, 34, multi=True))
    rangee = BoxLayout(spacing=D(4), size_hint_y=None, height=D(36))
    for texte, couleur, fn in actions:
        b = bouton(texte, couleur, 36)
        b.font_size = F(11)
        b.bind(on_release=fn)
        rangee.add_widget(b)
    box.add_widget(rangee)
    return box


def formulaire(champs, hauteur=38):
    # Grille étiquette / champ qui grandit avec son contenu
    grille = GridLayout(cols=2, spacing=D(4), size_hint_y=None)
    grille.bind(minimum_height=grille.setter("height"))
    saisies = {}
    for cle, hint in champs:
        lbl = etiquette(hint, 11, BLEU_FONCE, True, hauteur)
        lbl.size_hint_x = 0.4
        ti = TextInput(multiline=False, font_size=F(12), size_hint_y=None,
                       height=D(hauteur), size_hint_x=0.6)
        saisies[cle] = ti
        grille.add_widget(lbl)
        grille.add_widget(ti)
    return grille, saisies


class TexteDefilant(ScrollView):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.lbl = Label(color=BLEU_FONCE, font_size=F(13), halign="left", valign="top",
                         size_hint_y=None)
        self.lbl.bind(width=lambda i, w: setattr(i, "text_size", (w, None)),
                      texture_size=lambda i, ts: setattr(i, "height", ts[1]))
        self.add_widget(self.lbl)

    def set(self, texte):
        self.lbl.text = texte


class TexteAuto(Label):
    # Texte qui s'agrandit selon son contenu (à placer dans un ScrollView)

    def __init__(self, **kwargs):
        super().__init__(color=BLEU_FONCE, font_size=F(13), halign="left",
                         valign="top", size_hint_y=None, **kwargs)
        self.bind(width=lambda i, w: setattr(i, "text_size", (w, None)),
                  texture_size=lambda i, ts: setattr(i, "height", max(ts[1], D(30))))

    def set(self, texte):
        self.text = texte


class EcranFlex(Screen):
    # Écran dont le contenu est centré et limité en largeur sur tablette / PC
    LARGEUR_MAX = 760

    def monter(self, contenu):
        ancre = AnchorLayout(anchor_x="center", anchor_y="center")
        contenu.size_hint = (None, 1)

        def ajuster(*args):
            contenu.width = min(ancre.width, D(self.LARGEUR_MAX))

        ancre.bind(width=ajuster)
        ancre.add_widget(contenu)
        self.add_widget(ancre)
        ajuster()


# ============================================================
# GESTION PDF & IMPORTATION V7 RÉTROCOMPATIBLE
# ============================================================

def analyser_pdf_clinique_auto(chemin_pdf):
    if not HAS_PYPDF:
        raise ValueError("La bibliothèque 'pypdf' n'est pas installée.")
    reader = PdfReader(chemin_pdf)
    texte_complet = ""
    for page in reader.pages:
        texte_complet += page.extract_text() + "\n"

    donnees = {"client": "", "telephone": "", "email": "", "vehicule": "", "immatriculation": "", "kilometrage": "", "moteur": "", "lignes": []}
    m_client = re.search(r"Doit\s+à\s*:\s*(.+)", texte_complet, re.IGNORECASE)
    if m_client:
        donnees["client"] = m_client.group(1).strip()
    m_immat = re.search(r"Immatriculation\s*(?:du\s*véhicule)?\s*:\s*([A-Za-z0-9]+)", texte_complet, re.IGNORECASE)
    if m_immat:
        donnees["immatriculation"] = m_immat.group(1).strip()
    m_km = re.search(r"Kilométrage\s*:\s*(\d+)", texte_complet, re.IGNORECASE)
    if m_km:
        donnees["kilometrage"] = m_km.group(1).strip()
    m_veh = re.search(r"Véhicule\s*:\s*(.+)", texte_complet, re.IGNORECASE)
    if m_veh:
        donnees["vehicule"] = m_veh.group(1).strip()

    lignes_raw = texte_complet.split("\n")
    pattern_ligne = re.compile(r"^\s*(\d+)\s+(.+?)\s+(\d+(?:\.\d+)?)\s+([\d\s]+)\s+([\d\s]+)\s*$")
    for l in lignes_raw:
        m = pattern_ligne.match(l.strip())
        if m:
            num, des, qte, pu, tot = m.groups()
            pu_num = float(pu.replace(" ", ""))
            tot_num = float(tot.replace(" ", ""))
            qte_num = float(qte)
            type_l = "M.O." if "m.o" in des.lower() or "main" in des.lower() else "Pièce"
            donnees["lignes"].append({"type": type_l, "designation": des.strip(), "quantite": qte_num, "prix": pu_num, "total": tot_num})
    return donnees


def importer_devis_depuis_pdf(chemin_pdf):
    donnees = analyser_pdf_clinique_auto(chemin_pdf)
    if not donnees["client"] and not donnees["immatriculation"]:
        raise ValueError("Impossible de lire les informations clés de ce PDF.")
    d = {
        "client": donnees["client"] or "CLIENT INCONNU",
        "telephone": donnees["telephone"],
        "email": donnees["email"],
        "vehicule": donnees["vehicule"] or "VÉHICULE INCONNU",
        "immat": donnees["immatriculation"] or "SANS_IMMAT",
        "moteur": donnees["moteur"],
        "km": donnees["kilometrage"] or "0"
    }
    devis_id, version = sauver_devis(d, donnees["lignes"])
    return devis_id, d["client"], len(donnees["lignes"])


def charger_document(type_doc, doc_id):
    if type_doc == "Devis":
        tab, lig, fk, col_date = "devis", "lignes_devis", "devis_id", "date_devis"
    else:
        tab, lig, fk, col_date = "factures", "lignes_facture", "facture_id", "date_facture"
    with db() as c:
        h = c.execute(f"SELECT * FROM {tab} WHERE id=?", (doc_id,)).fetchone()
        if not h:
            raise ValueError(f"{type_doc} introuvable.")
        ls = c.execute(f"SELECT * FROM {lig} WHERE {fk}=? ORDER BY numero", (doc_id,)).fetchall()
        doc = dict(h)
        if type_doc == "Devis":
            doc["km"] = h["kilometrage"]
        else:
            r = c.execute("SELECT kilometrage FROM devis WHERE id=?", (h["devis_id"],)).fetchone()
            doc["km"] = r["kilometrage"] if r else ""
        cl = c.execute("SELECT telephone, email FROM clients WHERE nom=? COLLATE NOCASE LIMIT 1", (h["client"],)).fetchone()
        v = c.execute("SELECT moteur FROM vehicules WHERE immatriculation=? COLLATE NOCASE ORDER BY id DESC LIMIT 1", (h["immatriculation"],)).fetchone()
    doc["tel"] = cl["telephone"] if cl else ""
    doc["email"] = (cl["email"] if cl else "") or ""
    doc["moteur"] = v["moteur"] if v else ""
    doc["date"] = h[col_date]
    doc["version"] = int(doc.get("version") or 1)
    doc["tva_taux"] = float(doc.get("tva_taux") or 0)
    doc["acompte"] = float(doc.get("acompte") or 0) if type_doc == "Facture" else 0.0
    doc["lignes"] = [{"type": l["type_ligne"], "designation": l["designation"], "quantite": l["quantite"], "prix": l["prix_unitaire"], "total": l["total"]} for l in ls]
    return doc


def sauver_devis(d, lignes, devis_id=None, taux=0.0):
    aujourdhui = datetime.now().strftime("%d/%m/%Y")
    ttc = totaux(lignes, taux)["ttc"]
    with db() as c:
        r = c.execute("SELECT id FROM clients WHERE nom=? COLLATE NOCASE LIMIT 1", (d["client"],)).fetchone()
        if r:
            client_id = r["id"]
            c.execute("UPDATE clients SET telephone=COALESCE(NULLIF(?, ''), telephone), email=COALESCE(NULLIF(?, ''), email) WHERE id=?", (d["telephone"], d["email"], client_id))
        else:
            client_id = c.execute("INSERT INTO clients (nom, telephone, email) VALUES (?,?,?)", (d["client"], d["telephone"], d["email"])).lastrowid

        r = c.execute("SELECT id FROM vehicules WHERE client_id=? AND immatriculation=? COLLATE NOCASE", (client_id, d["immat"])).fetchone()
        if r:
            c.execute("UPDATE vehicules SET marque=?, kilometrage=?, moteur=? WHERE id=?", (d["vehicule"], d["km"], d["moteur"], r["id"]))
        else:
            c.execute("INSERT INTO vehicules (client_id, marque, immatriculation, kilometrage, moteur) VALUES (?,?,?,?,?)", (client_id, d["vehicule"], d["immat"], d["km"], d["moteur"]))

        if devis_id is None:
            devis_id = c.execute("INSERT INTO devis (client, vehicule, immatriculation, date_devis, kilometrage, total, statut, version, tva_taux) VALUES (?,?,?,?,?,?,?,?,?)",
                                 (d["client"], d["vehicule"], d["immat"], aujourdhui, d["km"], ttc, "En attente", 1, taux)).lastrowid
            version = 1
        else:
            row = c.execute("SELECT version, statut FROM devis WHERE id=?", (devis_id,)).fetchone()
            if not row:
                raise ValueError("Devis introuvable.")
            if row["statut"] == "Facturé":
                raise ValueError("Ce devis est déjà facturé.")
            version = int(row["version"] or 1) + 1
            c.execute("UPDATE devis SET client=?, vehicule=?, immatriculation=?, kilometrage=?, total=?, version=?, tva_taux=? WHERE id=?",
                      (d["client"], d["vehicule"], d["immat"], d["km"], ttc, version, taux, devis_id))
            c.execute("DELETE FROM lignes_devis WHERE devis_id=?", (devis_id,))

        for idx, l in enumerate(lignes, 1):
            c.execute("INSERT INTO lignes_devis (devis_id, numero, type_ligne, designation, quantite, prix_unitaire, total) VALUES (?,?,?,?,?,?,?)",
                      (devis_id, idx, l["type"], l["designation"], l["quantite"], l["prix"], l["total"]))
            # Historique des prix intelligent
            c.execute("INSERT INTO historique_prix (marque, designation, prix, date_prix) VALUES (?,?,?,?)",
                      (d["vehicule"], l["designation"], l["prix"], aujourdhui))
    return devis_id, version


def facturer_devis(devis_id, acompte=0.0):
    with db() as c:
        d = c.execute("SELECT * FROM devis WHERE id=?", (devis_id,)).fetchone()
        if not d:
            raise ValueError("Devis introuvable.")
        if c.execute("SELECT 1 FROM factures WHERE devis_id=?", (devis_id,)).fetchone():
            raise ValueError("Ce devis est déjà facturé.")
        fid = c.execute("INSERT INTO factures (devis_id, client, vehicule, immatriculation, date_facture, total, tva_taux, paye, acompte) VALUES (?,?,?,?,?,?,?,0,?)",
                        (devis_id, d["client"], d["vehicule"], d["immatriculation"], datetime.now().strftime("%d/%m/%Y"), d["total"], d["tva_taux"] or 0, acompte)).lastrowid
        c.execute("INSERT INTO lignes_facture (facture_id, numero, type_ligne, designation, quantite, prix_unitaire, total) SELECT ?, numero, type_ligne, designation, quantite, prix_unitaire, total FROM lignes_devis WHERE devis_id=?", (fid, devis_id))
        c.execute("UPDATE devis SET statut='Facturé' WHERE id=?", (devis_id,))
    return fid


def stats():
    mois = datetime.now().strftime("%m/%Y")
    with db() as c:
        ca = c.execute("SELECT COALESCE(SUM(total),0) FROM factures WHERE date_facture LIKE ?", ("%/" + mois,)).fetchone()[0]
        imp = c.execute("SELECT COALESCE(SUM(total - COALESCE(acompte,0)),0), COUNT(*) FROM factures WHERE COALESCE(paye,0)=0").fetchone()
        att = c.execute("SELECT COUNT(*) FROM devis WHERE statut != 'Facturé'").fetchone()[0]
    return ca, imp[0], imp[1], att


# ============================================================
# GÉNÉRATION PDF PROFESSIONNEL
# ============================================================

def generer_pdf(type_doc, doc_id, doc):
    if not HAS_REPORTLAB:
        return None
    lignes, taux = doc["lignes"], doc["tva_taux"]
    t = totaux(lignes, taux)
    numero = numero_doc("DEV" if type_doc == "Devis" else "FAC", doc_id, doc["date"])
    rev = f"_rev{doc['version']}" if type_doc == "Devis" and doc["version"] > 1 else ""
    chemin = os.path.join(DOSSIER_PDF, f"{numero}_{nom_fichier_sur(doc['immatriculation'])}{rev}.pdf")

    c = canvas.Canvas(chemin, pagesize=A4)
    L, R = 40, 555
    page = [1]

    def entete():
        c.setFont("Helvetica-Bold", 13)
        c.drawString(L, 800, param("garage_nom"))
        c.setFont("Helvetica", 9)
        for i, cle in enumerate(("garage_adresse", "garage_nif", "garage_contact")):
            c.drawString(L, 786 - 13 * i, param(cle))
        c.setFont("Helvetica-Bold", 12)
        suffixe = f" - révision {doc['version']}" if type_doc == "Devis" and doc["version"] > 1 else ""
        c.drawString(L, 730, f"{type_doc.upper()} N° {numero}{suffixe}")
        c.setFont("Helvetica", 10)
        c.drawString(L, 715, f"Date : {doc['date']}")
        c.drawString(L, 700, f"Immatriculation : {doc['immatriculation']}")
        c.drawString(L, 685, f"Kilométrage : {doc['km']}")
        c.drawString(L, 670, f"Véhicule : {doc['vehicule']}")
        c.setFont("Helvetica-Bold", 11)
        c.drawString(350, 730, f"Client : {str(doc['client'])[:32]}")

    def entete_tableau(y):
        c.setFont("Helvetica-Bold", 9)
        c.drawString(L, y, "N°")
        c.drawString(70, y, "Désignation des travaux ou pièces")
        c.drawRightString(380, y, "Qté")
        c.drawRightString(460, y, "PU (Ar)")
        c.drawRightString(R, y, "Total (Ar)")
        c.setLineWidth(0.5)
        c.line(L, y - 5, R, y - 5)
        return y - 20

    def pied():
        c.setFont("Helvetica", 8)
        c.drawCentredString(297, 25, f"{param('garage_nom')} - Page {page[0]}")

    def nouvelle_page():
        pied()
        c.showPage()
        page[0] += 1
        entete()
        return entete_tableau(640)

    entete()
    y = entete_tableau(640)
    for i, l in enumerate(lignes, 1):
        morceaux = simpleSplit(str(l["designation"]), "Helvetica", 8, 270) or [""]
        if y - 11 * len(morceaux) < 60:
            y = nouvelle_page()
        c.setFont("Helvetica", 8)
        c.drawString(L, y, str(i))
        for k, m in enumerate(morceaux):
            c.drawString(70, y - 11 * k, m)
        c.drawRightString(380, y, nombre_txt(l["quantite"]))
        c.drawRightString(460, y, prix_affiche(l["prix"]))
        c.drawRightString(R, y, prix_affiche(l["total"]))
        y -= 11 * len(morceaux) + 4

    if y < 190:
        y = nouvelle_page()
    c.line(L, y, R, y)
    y -= 16
    c.setFont("Helvetica", 9)
    detail = [("Pièces", t["pieces"]), ("Main-d'œuvre", t["mo"])]
    if taux:
        detail += [("Total HT", t["ht"]), (f"TVA {taux:g} %", t["tva"])]
    for lib, val in detail:
        c.drawString(380, y, lib)
        c.drawRightString(R, y, prix_affiche(val))
        y -= 13
    c.setFont("Helvetica-Bold", 11)
    c.drawString(380, y - 4, "TOTAL TTC" if taux else "TOTAL")
    c.drawRightString(R, y - 4, prix_affiche(t["ttc"]))
    y -= 18

    if type_doc == "Facture" and doc.get("acompte", 0) > 0:
        c.setFont("Helvetica", 9)
        c.drawString(380, y, "Acompte versé")
        c.drawRightString(R, y, prix_affiche(doc["acompte"]))
        y -= 15
        c.setFont("Helvetica-Bold", 10)
        c.drawString(380, y, "RESTE À PAYER")
        c.drawRightString(R, y, prix_affiche(max(0, t["ttc"] - doc["acompte"])))
        y -= 25

    c.setFont("Helvetica", 9)
    if type_doc == "Devis":
        c.drawString(L, y, "Devis valable 30 jours. Bon pour accord :")
        c.line(L, y - 40, 240, y - 40)
    else:
        c.drawString(L, y, "Merci de votre confiance.")
    pied()
    c.save()
    return chemin


def regenerer_pdf(type_doc, doc_id):
    doc = charger_document(type_doc, doc_id)
    return generer_pdf(type_doc, doc_id, doc), doc


# ============================================================
# EMAILING ET PARTAGE WHATSAPP
# ============================================================

def envoyer_email(destinataire, sujet, corps, piece_jointe, callback):
    hote = param("smtp_hote").strip()
    port = int(prix_nombre(param("smtp_port")) or 465)
    user, mdp, nom = param("smtp_user").strip(), param("smtp_mdp"), param("garage_nom")
    if not (hote and user and mdp):
        callback(False, "Configurez d'abord l'e-mail dans Paramètres.")
        return

    def tache():
        try:
            msg = EmailMessage()
            msg["From"] = f"{nom} <{user}>"
            msg["To"] = destinataire
            msg["Subject"] = sujet
            msg.set_content(corps)
            if piece_jointe:
                with open(piece_jointe, "rb") as f:
                    msg.add_attachment(f.read(), maintype="application", subtype="pdf", filename=os.path.basename(piece_jointe))
            if port == 465:
                srv = smtplib.SMTP_SSL(hote, port, timeout=30)
            else:
                srv = smtplib.SMTP(hote, port, timeout=30)
                srv.starttls()
            with srv:
                srv.login(user, mdp)
                srv.send_message(msg)
            ok, info = True, ""
        except Exception as e:
            ok, info = False, str(e)
        Clock.schedule_once(lambda dt: callback(ok, info))

    threading.Thread(target=tache, daemon=True).start()


def _message_client(type_doc, doc, numero):
    corrige = type_doc == "Devis" and doc["version"] > 1
    intro = "Voici la version corrigée de votre devis" if corrige else f"Veuillez trouver votre {type_doc.lower()}"
    return f"Bonjour {doc['client']},\n\n{intro} N° {numero} pour {doc['vehicule']} ({doc['immatriculation']}).\nMontant total : {prix_affiche(doc['total'])}.\n\nCordialement,\n{param('garage_nom')}"


@securise
def envoyer_document(type_doc, doc_id):
    chemin, doc = regenerer_pdf(type_doc, doc_id)
    if not chemin or not doc["email"]:
        afficher_popup("Info", "E-mail manquant ou PDF indisponible.")
        return
    numero = numero_doc("DEV" if type_doc == "Devis" else "FAC", doc_id, doc["date"])
    sujet = f"{type_doc} N° {numero} - {doc['vehicule']} ({doc['immatriculation']})"
    attente = afficher_popup("Envoi", f"Envoi à {doc['email']}...")

    def fin(ok, info):
        attente.dismiss()
        afficher_popup("Succès" if ok else "Échec", f"{type_doc} envoyé !" if ok else info)

    envoyer_email(doc["email"], sujet, _message_client(type_doc, doc, numero), chemin, fin)


@securise
def partager_whatsapp(type_doc, doc_id):
    chemin, doc = regenerer_pdf(type_doc, doc_id)
    numero = numero_doc("DEV" if type_doc == "Devis" else "FAC", doc_id, doc["date"])
    if platform == "android" and chemin:
        ouvrir_ou_partager(chemin)
    else:
        ouvrir_whatsapp(doc["tel"], _message_client(type_doc, doc, numero))
        if chemin:
            ouvrir_ou_partager(chemin)


@securise
def voir_pdf(type_doc, doc_id):
    chemin, _ = regenerer_pdf(type_doc, doc_id)
    if chemin:
        ouvrir_ou_partager(chemin)


# ============================================================
# ÉCRAN DEVIS (Lignes, Suggestions, Calculs)
# ============================================================

class LigneDevis(BoxLayout):

    def __init__(self, parent_devis, valeurs=None, **kwargs):
        compact = COMPACT
        super().__init__(orientation="vertical" if compact else "horizontal",
                         spacing=D(4), size_hint_y=None,
                         height=D(88) if compact else D(42), **kwargs)
        v = valeurs or {}
        self.parent_devis = parent_devis
        prix_txt = nombre_txt(v["prix"]) if v.get("prix") else ""
        self.type_ligne = Spinner(text=v.get("type", "Pièce"), values=("Pièce", "M.O."), font_size=F(12))
        self.designation = TextInput(text=v.get("designation", ""), hint_text="Désignation", multiline=False, font_size=F(12))
        self.quantite = TextInput(text=nombre_txt(v.get("quantite", 1)), hint_text="Qté", multiline=False, input_filter="float", font_size=F(12))
        self.prix = TextInput(text=prix_txt, hint_text="Prix unitaire", multiline=False, input_filter="float", font_size=F(12))
        self.total = Label(text="0 Ar", font_size=F(11), bold=True, color=BLEU_FONCE)
        btn = Button(text="X", font_size=F(12), bold=True, size_hint_x=None, width=D(34), background_normal="", background_color=ROUGE)

        if compact:
            # Petit écran : 2 rangées (type + désignation + X) puis (qté + prix + total)
            r1 = BoxLayout(spacing=D(4))
            r2 = BoxLayout(spacing=D(4))
            self.type_ligne.size_hint_x = 0.28
            self.designation.size_hint_x = 0.72
            self.quantite.size_hint_x = 0.22
            self.prix.size_hint_x = 0.42
            self.total.size_hint_x = 0.36
            for w in (self.type_ligne, self.designation, btn):
                r1.add_widget(w)
            for w in (self.quantite, self.prix, self.total):
                r2.add_widget(w)
            self.add_widget(r1)
            self.add_widget(r2)
        else:
            self.type_ligne.size_hint_x = 0.18
            self.designation.size_hint_x = 0.36
            self.quantite.size_hint_x = 0.10
            self.prix.size_hint_x = 0.18
            self.total.size_hint_x = 0.18
            for w in (self.type_ligne, self.designation, self.quantite, self.prix, self.total, btn):
                self.add_widget(w)

        self.quantite.bind(text=self.changement)
        self.prix.bind(text=self.changement)
        self.type_ligne.bind(text=self.changement)
        btn.bind(on_release=lambda x: self.parent_devis.supprimer_ligne(self))
        self.changement()

    def changement(self, *args):
        self.total.text = prix_affiche(prix_nombre(self.quantite.text) * prix_nombre(self.prix.text))
        self.parent_devis.calculer_totaux()


class DevisScreen(EcranFlex):

    CHAMPS = [("client", "Nom du client", "text"),
              ("telephone", "Téléphone", "tel"),
              ("email", "E-mail", "mail"),
              ("marque", "Marque / Modèle véhicule", "text"),
              ("immat", "Immatriculation", "text"),
              ("moteur", "Moteur / VIN", "text"),
              ("km", "Kilométrage", "number")]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        principal = BoxLayout(orientation="vertical", padding=D(10), spacing=D(6))
        self.titre_lbl = titre("NOUVEAU DEVIS")
        principal.add_widget(self.titre_lbl)

        # Zone défilante : informations + lignes (rien n'est coupé en paysage)
        scroll = ScrollView(do_scroll_x=False)
        contenu = BoxLayout(orientation="vertical", spacing=D(6), size_hint_y=None)
        contenu.bind(minimum_height=contenu.setter("height"))

        infos = GridLayout(cols=2, spacing=D(4), size_hint_y=None)
        infos.bind(minimum_height=infos.setter("height"))
        infos.bind(width=lambda i, w: setattr(i, "cols", 2 if w < D(560) else 3))
        self.champs = {}
        for cle, hint, typ in self.CHAMPS:
            ti = TextInput(hint_text=hint, multiline=False, font_size=F(12), input_type=typ,
                           size_hint_y=None, height=D(38))
            self.champs[cle] = ti
            infos.add_widget(ti)
        self.date_lbl = Label(text="", color=BLEU_FONCE, font_size=F(13), bold=True,
                              size_hint_y=None, height=D(38))
        infos.add_widget(self.date_lbl)
        contenu.add_widget(infos)

        if not COMPACT:
            barre = BoxLayout(size_hint_y=None, height=D(28), spacing=D(4))
            for t, w in [("TYPE", 0.18), ("DÉSIGNATION", 0.36), ("QTÉ", 0.10), ("P.U.", 0.18), ("TOTAL", 0.18)]:
                barre.add_widget(Label(text=t, bold=True, font_size=F(10), color=BLEU_FONCE, size_hint_x=w))
            barre.add_widget(Label(text="", size_hint_x=None, width=D(34)))
            contenu.add_widget(barre)

        self.zone_lignes = GridLayout(cols=1, spacing=D(6) if COMPACT else D(3), size_hint_y=None)
        self.zone_lignes.bind(minimum_height=self.zone_lignes.setter("height"))
        contenu.add_widget(self.zone_lignes)

        btn_ajout = bouton("+ AJOUTER UNE LIGNE", BLEU, 40)
        btn_ajout.bind(on_release=lambda x: self.ajouter_ligne())
        contenu.add_widget(btn_ajout)

        scroll.add_widget(contenu)
        principal.add_widget(scroll)

        self.total_general = Label(text="", font_size=F(15), bold=True, color=VERT,
                                   size_hint_y=None, height=D(30), halign="center", valign="middle")
        self.total_general.bind(size=lambda i, s: setattr(i, "text_size", s))
        principal.add_widget(self.total_general)

        actions = BoxLayout(size_hint_y=None, height=D(44), spacing=D(6))
        b1 = bouton("ENREGISTRER", VERT, 44)
        b1.bind(on_release=lambda x: self.enregistrer())
        b2 = bouton("RETOUR", BLEU_FONCE, 44)
        b2.bind(on_release=lambda x: setattr(self.manager, "current", "accueil"))
        actions.add_widget(b1)
        actions.add_widget(b2)
        principal.add_widget(actions)

        self.monter(principal)
        self.reinitialiser()

    def reinitialiser(self):
        self.devis_id = None
        self.taux = prix_nombre(param("tva_taux"))
        for w in self.champs.values():
            w.text = ""
        self.zone_lignes.clear_widgets()
        self.lignes = []
        self.titre_lbl.text = "NOUVEAU DEVIS"
        self.date_lbl.text = "Date : " + datetime.now().strftime("%d/%m/%Y")
        self.ajouter_ligne()

    def charger(self, devis_id):
        doc = charger_document("Devis", devis_id)
        self.reinitialiser()
        self.zone_lignes.clear_widgets()
        self.lignes = []
        self.devis_id = devis_id
        self.taux = doc["tva_taux"]
        valeurs = {"client": doc["client"], "telephone": doc["tel"], "email": doc["email"],
                   "marque": doc["vehicule"], "immat": doc["immatriculation"],
                   "moteur": doc["moteur"], "km": doc["km"]}
        for k, v in valeurs.items():
            self.champs[k].text = str(v or "")
        for l in doc["lignes"]:
            self.ajouter_ligne(l)
        if not self.lignes:
            self.ajouter_ligne()
        self.titre_lbl.text = f"MODIFIER DEVIS {numero_doc('DEV', devis_id, doc['date'])}"
        self.date_lbl.text = f"Date : {doc['date']} (rév. {doc['version']})"
        self.calculer_totaux()

    def ajouter_ligne(self, valeurs=None):
        ligne = LigneDevis(self, valeurs)
        self.lignes.append(ligne)
        self.zone_lignes.add_widget(ligne)
        self.calculer_totaux()

    def supprimer_ligne(self, ligne):
        if ligne in self.lignes:
            self.lignes.remove(ligne)
            self.zone_lignes.remove_widget(ligne)
            self.calculer_totaux()

    def lire_lignes(self):
        res = []
        for l in self.lignes:
            q, p = prix_nombre(l.quantite.text), prix_nombre(l.prix.text)
            res.append({"type": l.type_ligne.text, "designation": l.designation.text.strip(), "quantite": q, "prix": p, "total": q * p})
        return res

    def calculer_totaux(self):
        t = totaux(self.lire_lignes(), self.taux)
        if self.taux:
            self.total_general.text = f"TOTAL TTC : {prix_affiche(t['ttc'])} (HT {prix_affiche(t['ht'])})"
        else:
            self.total_general.text = f"TOTAL DEVIS : {prix_affiche(t['ttc'])}"
        return t

    @securise
    def enregistrer(self, *args):
        d = {k: w.text.strip() for k, w in self.champs.items()}
        d["vehicule"] = d["marque"]
        if not d["client"] or not d["immat"]:
            afficher_popup("Validation", "Renseignez au moins le Client et l'Immatriculation.")
            return
        lignes = [l for l in self.lire_lignes() if l["designation"]]
        if not lignes:
            afficher_popup("Devis vide", "Ajoutez au moins une ligne.")
            return

        devis_id, _ = sauver_devis(d, lignes, self.devis_id, self.taux)
        chemin, doc = regenerer_pdf("Devis", devis_id)
        self.reinitialiser()
        popup_actions("Enregistré avec succès", f"Devis {numero_doc('DEV', devis_id, doc['date'])} sauvegardé.\nTotal : {prix_affiche(doc['total'])}", [
            ("Envoyer par e-mail", VERT, lambda: envoyer_document("Devis", devis_id)),
            ("WhatsApp / Partager", ORANGE, lambda: partager_whatsapp("Devis", devis_id)),
            ("Voir le PDF", BLEU, (lambda: ouvrir_ou_partager(chemin)) if chemin else None),
            ("Fermer", GRIS, None)])


# ============================================================
# GESTION DES FACTURES, ACOMPTES ET PAIEMENTS
# ============================================================

class FacturesScreen(EcranFlex):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        racine = BoxLayout(orientation="vertical", padding=D(10), spacing=D(6))
        racine.add_widget(titre("DEVIS & FACTURES"))
        self.zone = GridLayout(cols=1, spacing=D(6), size_hint_y=None)
        self.zone.bind(minimum_height=self.zone.setter("height"))
        sv = ScrollView(do_scroll_x=False)
        sv.add_widget(self.zone)
        racine.add_widget(sv)
        racine.add_widget(bouton_retour(self))
        self.monter(racine)

    def on_enter(self):
        self.charger()

    @securise
    def charger(self, *args):
        self.zone.clear_widgets()
        with db() as c:
            devis = c.execute("SELECT * FROM devis WHERE statut != 'Facturé' ORDER BY id DESC LIMIT 50").fetchall()
            factures = c.execute("SELECT * FROM factures ORDER BY id DESC LIMIT 50").fetchall()

        self.zone.add_widget(etiquette("DEVIS EN COURS", 13, ORANGE, True, 26))
        if not devis:
            self.zone.add_widget(etiquette("Aucun devis en attente.", 11, GRIS, False, 20))
        for d in devis:
            i = d["id"]
            rev = f" (rév. {d['version']})" if (d["version"] or 1) > 1 else ""
            self.zone.add_widget(carte(
                f"{numero_doc('DEV', i, d['date_devis'])}{rev} - {d['client']}",
                f"{d['vehicule']} ({d['immatriculation']}) | {prix_affiche(d['total'])}",
                [("Modifier", BLEU, lambda x, i=i: self.modifier_devis(i)),
                 ("PDF", BLEU_FONCE, lambda x, i=i: voir_pdf("Devis", i)),
                 ("Facturer", VERT, lambda x, i=i: self.demander_facturation(i))]))

        self.zone.add_widget(etiquette("FACTURES", 13, ORANGE, True, 26))
        if not factures:
            self.zone.add_widget(etiquette("Aucune facture.", 11, GRIS, False, 20))
        for f in factures:
            i = f["id"]
            paye = bool(f["paye"])
            acompte = float(f["acompte"] or 0)
            etat = "PAYÉE" if paye else (f"Acompte {prix_affiche(acompte)}" if acompte > 0 else "IMPAYÉE")
            self.zone.add_widget(carte(
                f"{numero_doc('FAC', i, f['date_facture'])} - {f['client']}",
                f"{f['vehicule']} ({f['immatriculation']}) | {prix_affiche(f['total'])} | {etat}",
                [("PDF", BLEU_FONCE, lambda x, i=i: voir_pdf("Facture", i)),
                 ("E-mail", ORANGE, lambda x, i=i: envoyer_document("Facture", i)),
                 # t=f["total"] : fixe la valeur pour CHAQUE facture (bug de la V8 : toutes
                 # les factures utilisaient le total de la dernière de la liste)
                 ("Paiement", VERT, lambda x, i=i, t=f["total"]: self.gerer_paiement(i, t))]))

    @securise
    def modifier_devis(self, devis_id):
        ecran = self.manager.get_screen("devis")
        ecran.charger(devis_id)
        self.manager.current = "devis"

    def demander_facturation(self, devis_id):
        box = BoxLayout(orientation="vertical", spacing=D(8), padding=D(10))
        box.add_widget(_label_popup("Entrez le montant de l'acompte reçu (0 si aucun) :"))
        ti_acompte = TextInput(text="0", multiline=False, input_filter="float", font_size=F(14), size_hint_y=None, height=D(42))
        box.add_widget(ti_acompte)
        pop = Popup(title="Facturation et Acompte", content=box, **taille_popup(0.85, 0.42, D(230)))

        @securise
        def valider(x):
            acompte_val = prix_nombre(ti_acompte.text)
            pop.dismiss()
            fid = facturer_devis(devis_id, acompte_val)
            _, doc = regenerer_pdf("Facture", fid)
            self.charger()
            afficher_popup("Facture créée", f"Facture {numero_doc('FAC', fid, doc['date'])} générée avec succès.")

        btn = bouton("VALIDER LA FACTURE", VERT, 44)
        btn.bind(on_release=valider)
        box.add_widget(btn)
        pop.open()

    def gerer_paiement(self, facture_id, total_ttc):
        box = BoxLayout(orientation="vertical", spacing=D(8), padding=D(10))
        box.add_widget(_label_popup(f"Total Facture : {prix_affiche(total_ttc)}"))
        ti_acompte = TextInput(hint_text="Montant total déjà versé", multiline=False, input_filter="float", font_size=F(14), size_hint_y=None, height=D(42))
        box.add_widget(ti_acompte)
        pop = Popup(title="Gestion du Paiement", content=box, **taille_popup(0.85, 0.5, D(280)))

        @securise
        def marquer_tout(x):
            with db() as c:
                c.execute("UPDATE factures SET paye=1, acompte=? WHERE id=?", (total_ttc, facture_id))
            pop.dismiss()
            self.charger()

        @securise
        def ajouter_acompte(x):
            val = prix_nombre(ti_acompte.text)
            paye_val = 1 if val >= total_ttc else 0
            with db() as c:
                c.execute("UPDATE factures SET acompte=?, paye=? WHERE id=?", (val, paye_val, facture_id))
            pop.dismiss()
            self.charger()

        b1 = bouton("MARQUER ENTIÈREMENT PAYÉE", VERT, 42)
        b1.bind(on_release=marquer_tout)
        b2 = bouton("ENREGISTRER L'ACOMPTE", ORANGE, 42)
        b2.bind(on_release=ajouter_acompte)
        box.add_widget(b1)
        box.add_widget(b2)
        pop.open()


# ============================================================
# MODULES V8 (Fournisseurs, Articles/Pièces, Stock)
# ============================================================

class FournisseursScreen(EcranFlex):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        racine = BoxLayout(orientation="vertical", padding=D(10), spacing=D(6))
        racine.add_widget(titre("GESTION DES FOURNISSEURS"))

        sv = ScrollView(do_scroll_x=False)
        contenu = BoxLayout(orientation="vertical", spacing=D(8), size_hint_y=None)
        contenu.bind(minimum_height=contenu.setter("height"))

        form, self.inputs = formulaire([("nom", "Nom Fournisseur"), ("tel", "Téléphone"),
                                        ("whatsapp", "WhatsApp"), ("email", "E-mail")])
        contenu.add_widget(form)
        b = bouton("AJOUTER LE FOURNISSEUR", VERT, 44)
        b.bind(on_release=lambda x: self.ajouter())
        contenu.add_widget(b)
        contenu.add_widget(etiquette("FOURNISSEURS ENREGISTRÉS", 12, ORANGE, True, 26))
        self.zone = TexteAuto()
        contenu.add_widget(self.zone)

        sv.add_widget(contenu)
        racine.add_widget(sv)
        racine.add_widget(bouton_retour(self))
        self.monter(racine)

    def on_enter(self):
        self.rafraichir()

    @securise
    def rafraichir(self):
        with db() as c:
            rows = c.execute("SELECT * FROM fournisseurs ORDER BY nom").fetchall()
        # Correction : la colonne s'appelle "telephone" (et non "tel")
        txt = "\n\n".join(f"• {r['nom']} | Tél : {r['telephone'] or '-'} | WhatsApp : {r['whatsapp'] or '-'}"
                          + (f" | {r['email']}" if r['email'] else "") for r in rows)
        self.zone.set(txt or "Aucun fournisseur enregistré.")

    @securise
    def ajouter(self):
        vals = {k: ti.text.strip() for k, ti in self.inputs.items()}
        if not vals["nom"]:
            afficher_popup("Erreur", "Le nom du fournisseur est obligatoire.")
            return
        with db() as c:
            c.execute("INSERT INTO fournisseurs (nom, telephone, whatsapp, email) VALUES (?,?,?,?)",
                      (vals["nom"], vals["tel"], vals["whatsapp"], vals["email"]))
        for ti in self.inputs.values():
            ti.text = ""
        self.rafraichir()
        afficher_popup("Succès", "Fournisseur ajouté.")


class ArticlesScreen(EcranFlex):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        racine = BoxLayout(orientation="vertical", padding=D(10), spacing=D(6))
        racine.add_widget(titre("CATALOGUE ARTICLES & PIÈCES"))

        sv = ScrollView(do_scroll_x=False)
        contenu = BoxLayout(orientation="vertical", spacing=D(8), size_hint_y=None)
        contenu.bind(minimum_height=contenu.setter("height"))

        form, self.inputs = formulaire([("ref", "Référence Pièce"), ("des", "Désignation"),
                                        ("p_achat", "Prix d'achat"), ("p_vente", "Prix de vente"),
                                        ("stock", "Stock initial")])
        contenu.add_widget(form)
        b = bouton("ENREGISTRER L'ARTICLE", VERT, 44)
        b.bind(on_release=lambda x: self.ajouter())
        contenu.add_widget(b)
        contenu.add_widget(etiquette("ARTICLES EN STOCK", 12, ORANGE, True, 26))
        self.zone = TexteAuto()
        contenu.add_widget(self.zone)

        sv.add_widget(contenu)
        racine.add_widget(sv)
        racine.add_widget(bouton_retour(self))
        self.monter(racine)

    def on_enter(self):
        self.rafraichir()

    @securise
    def rafraichir(self):
        with db() as c:
            rows = c.execute("SELECT * FROM articles ORDER BY designation").fetchall()
        txt = "\n\n".join(f"[{r['reference']}] {r['designation']}\n  Achat: {prix_affiche(r['prix_achat'])} | Vente: {prix_affiche(r['prix_vente'])} | Stock: {nombre_txt(r['stock'])}" for r in rows)
        self.zone.set(txt or "Aucun article en stock.")

    @securise
    def ajouter(self):
        vals = {k: ti.text.strip() for k, ti in self.inputs.items()}
        if not vals["des"]:
            afficher_popup("Erreur", "La désignation est obligatoire.")
            return
        with db() as c:
            c.execute("INSERT INTO articles (reference, designation, prix_achat, prix_vente, stock) VALUES (?,?,?,?,?)",
                      (vals["ref"], vals["des"], prix_nombre(vals["p_achat"]), prix_nombre(vals["p_vente"]), prix_nombre(vals["stock"])))
        for ti in self.inputs.values():
            ti.text = ""
        self.rafraichir()
        afficher_popup("Succès", "Article enregistré.")


# ============================================================
# LISTES, RECHERCHE & TABLEAU DE BORD ACCUEIL
# ============================================================

def donnees_clients(f):
    q = f"%{f}%"
    with db() as c:
        rows = c.execute("SELECT nom, telephone, email FROM clients WHERE nom LIKE ? OR telephone LIKE ? ORDER BY nom", (q, q)).fetchall()
    return "\n\n".join(f"• {r['nom']}\n    Tél : {r['telephone'] or '-'} | E-mail : {r['email'] or '-'}" for r in rows)


def donnees_vehicules(f):
    q = f"%{f}%"
    with db() as c:
        rows = c.execute("SELECT v.marque, v.immatriculation, v.kilometrage, c.nom FROM vehicules v LEFT JOIN clients c ON c.id=v.client_id WHERE v.marque LIKE ? OR v.immatriculation LIKE ? ORDER BY v.id DESC", (q, q)).fetchall()
    return "\n\n".join(f"• {r['marque']} ({r['immatriculation']}) - {r['kilometrage']} km\n    Propriétaire : {r['nom'] or '-'}" for r in rows)


def donnees_historique(f):
    q = f"%{f}%"
    with db() as c:
        rows = c.execute("SELECT designation, prix, date_prix FROM historique_prix WHERE designation LIKE ? ORDER BY id DESC LIMIT 100", (q,)).fetchall()
    return "\n\n".join(f"• {r['designation']} : {prix_affiche(r['prix'])} ({r['date_prix']})" for r in rows)


def donnees_recherche(f):
    if not f:
        return "Saisissez un terme pour rechercher..."
    q = f"%{f}%"
    sortie = []
    with db() as c:
        for r in c.execute("SELECT id, client, vehicule, immatriculation, total, statut FROM devis WHERE client LIKE ? OR immatriculation LIKE ? ORDER BY id DESC LIMIT 30", (q, q)):
            sortie.append(f"DEV-{r['id']} | {r['client']} | {r['vehicule']} ({r['immatriculation']}) | {prix_affiche(r['total'])} | {r['statut']}")
    return "\n\n".join(sortie) or "Aucun résultat trouvé."


class ListeScreen(EcranFlex):

    def __init__(self, titre_txt, fonction, recherche=False, **kwargs):
        super().__init__(**kwargs)
        self.fonction = fonction
        racine = BoxLayout(orientation="vertical", padding=D(10), spacing=D(6))
        racine.add_widget(titre(titre_txt))
        self.champ = None
        if recherche:
            self.champ = TextInput(hint_text="Rechercher...", multiline=False, font_size=F(13), size_hint_y=None, height=D(42))
            self.champ.bind(text=lambda *a: self.rafraichir())
            racine.add_widget(self.champ)
        self.texte = TexteDefilant()
        racine.add_widget(self.texte)
        racine.add_widget(bouton_retour(self))
        self.monter(racine)

    def on_enter(self):
        self.rafraichir()

    def rafraichir(self):
        filtre = self.champ.text.strip() if self.champ else ""
        try:
            self.texte.set(self.fonction(filtre) or "Aucun résultat.")
        except Exception as e:
            self.texte.set(f"Erreur : {e}")


class ParametresScreen(EcranFlex):
    CHAMPS = [("garage_nom", "Nom du garage"), ("garage_adresse", "Adresse"),
              ("garage_nif", "NIF / RCS"), ("garage_contact", "Contacts"),
              ("tva_taux", "TVA %"), ("smtp_hote", "SMTP"),
              ("smtp_port", "Port"), ("smtp_user", "E-mail"), ("smtp_mdp", "Mot de passe")]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        racine = BoxLayout(orientation="vertical", padding=D(10), spacing=D(6))
        racine.add_widget(titre("PARAMÈTRES"))
        grille = GridLayout(cols=2, spacing=D(4), size_hint_y=None)
        grille.bind(minimum_height=grille.setter("height"))
        self.saisies = {}
        for cle, lib in self.CHAMPS:
            lbl = etiquette(lib, 11, BLEU_FONCE, True, 40)
            lbl.size_hint_x = 0.38
            grille.add_widget(lbl)
            ti = TextInput(multiline=False, font_size=F(12), size_hint_y=None, height=D(40),
                           size_hint_x=0.62, password=(cle == "smtp_mdp"))
            self.saisies[cle] = ti
            grille.add_widget(ti)
        sv = ScrollView(do_scroll_x=False)
        sv.add_widget(grille)
        racine.add_widget(sv)
        b1 = bouton("ENREGISTRER", VERT, 44)
        b1.bind(on_release=lambda x: self.enregistrer())
        racine.add_widget(b1)
        racine.add_widget(bouton_retour(self))
        self.monter(racine)

    def on_pre_enter(self):
        for cle, ti in self.saisies.items():
            ti.text = param(cle)

    @securise
    def enregistrer(self):
        for cle, ti in self.saisies.items():
            set_param(cle, ti.text.strip())
        afficher_popup("Paramètres", "Paramètres enregistrés.")


class AccueilScreen(EcranFlex):
    LARGEUR_MAX = 900

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        layout = BoxLayout(orientation="vertical", padding=D(12), spacing=D(8))
        layout.add_widget(titre("CLINIQUE AUTO MADA"))
        self.stats = Label(text="", font_size=F(12), color=GRIS_TEXTE, halign="center",
                           valign="middle", size_hint_y=None, height=D(66))
        self.stats.bind(size=lambda i, s: setattr(i, "text_size", s))
        layout.add_widget(self.stats)

        scroll = ScrollView(do_scroll_x=False)
        menu = GridLayout(cols=2, spacing=D(8), padding=D(4), size_hint_y=None)
        menu.bind(minimum_height=menu.setter("height"))
        # Nombre de colonnes selon la largeur : 2 (téléphone) -> 3 ou 4 (tablette / paysage)
        menu.bind(width=lambda i, w: setattr(i, "cols", max(2, min(4, int(w / D(200))))))

        boutons = [
            ("NOUVEAU DEVIS", "devis"),
            ("DEVIS & FACTURES", "factures"),
            ("IMPORTER PDF", "import_pdf"),
            ("CLIENTS", "clients"),
            ("VÉHICULES", "vehicules"),
            ("FOURNISSEURS", "fournisseurs"),
            ("ARTICLES / STOCK", "articles"),
            ("RECHERCHE", "recherche"),
            ("PRIX HABITUELS", "historique"),
            ("PARAMÈTRES", "parametres")
        ]

        for texte, ecran in boutons:
            b = bouton(texte, BLEU, 54)
            if ecran == "import_pdf":
                b.bind(on_release=lambda x: self.ouvrir_importateur_pdf())
            else:
                b.bind(on_release=lambda x, e=ecran: self.aller(e))
            menu.add_widget(b)

        quitter = bouton("QUITTER", ROUGE, 54)
        quitter.bind(on_release=lambda x: App.get_running_app().stop())
        menu.add_widget(quitter)
        scroll.add_widget(menu)
        layout.add_widget(scroll)
        self.monter(layout)

    def aller(self, ecran):
        if ecran == "devis":
            self.manager.get_screen("devis").reinitialiser()
        self.manager.current = ecran

    def ouvrir_importateur_pdf(self):
        content = BoxLayout(orientation='vertical', spacing=D(8), padding=D(8))
        filechooser = FileChooserIconView(filters=['*.pdf'], path=DOSSIER_PDF, multiselect=True)
        content.add_widget(filechooser)
        pop = Popup(title="Sélectionner les PDF", content=content, size_hint=(0.95, 0.92))

        def valider_selection(instance):
            if not filechooser.selection:
                afficher_popup("Importation", "Sélectionnez au moins un fichier PDF.")
                return
            fichiers = filechooser.selection
            pop.dismiss()
            succes = erreurs = 0
            for fichier in fichiers:
                try:
                    importer_devis_depuis_pdf(fichier)
                    succes += 1
                except Exception:
                    erreurs += 1
            afficher_popup("Importation", f"{succes} fichier(s) importé(s).\n{erreurs} échec(s).")

        btn = bouton("IMPORTER LA SÉLECTION", VERT, 44)
        btn.bind(on_release=valider_selection)
        content.add_widget(btn)
        pop.open()

    def on_enter(self):
        try:
            ca, impaye, nb_imp, attente = stats()
            self.stats.text = f"CA du mois : {prix_affiche(ca)} | Impayés : {nb_imp} ({prix_affiche(impaye)})\nDevis en attente : {attente}"
        except Exception as e:
            self.stats.text = f"Erreur statistiques : {e}"


class CliniqueAutoMadaApp(App):
    title = "Clinique Auto Mada"

    def build(self):
        init_chemins(self)
        init_echelle()
        init_database()
        sm = ScreenManager()
        sm.add_widget(AccueilScreen(name="accueil"))
        sm.add_widget(DevisScreen(name="devis"))
        sm.add_widget(FacturesScreen(name="factures"))
        sm.add_widget(FournisseursScreen(name="fournisseurs"))
        sm.add_widget(ArticlesScreen(name="articles"))
        sm.add_widget(ListeScreen("CLIENTS", donnees_clients, True, name="clients"))
        sm.add_widget(ListeScreen("VÉHICULES", donnees_vehicules, True, name="vehicules"))
        sm.add_widget(ListeScreen("PRIX HABITUELS", donnees_historique, True, name="historique"))
        sm.add_widget(ListeScreen("RECHERCHE", donnees_recherche, True, name="recherche"))
        sm.add_widget(ParametresScreen(name="parametres"))
        Window.bind(on_keyboard=self.touche)
        return sm

    def touche(self, window, key, *args):
        if key == 27 and self.root.current != "accueil":
            self.root.current = "accueil"
            return True
        return False


if __name__ == "__main__":
    CliniqueAutoMadaApp().run()
