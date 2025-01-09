#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import curses
import os
import json
import threading
import subprocess
import time
from datetime import datetime
import uuid

# Pour afficher CPU, RAM, Disque et Réseau
try:
    import psutil
except ImportError:
    psutil = None

CONFIG_FILE = "config.json"

###############################################################################
# 1) Chargement / Sauvegarde du fichier config.json
###############################################################################

def load_config():
    """Charge config.json ou renvoie une structure par défaut."""
    if not os.path.exists(CONFIG_FILE):
        return {
            "projects": [],
            "network_interface": ""  # Interface réseau à surveiller
        }
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            print(f"Erreur JSON dans {CONFIG_FILE}: {e}")
            print("Réinitialisation de la configuration avec une structure par défaut.")
            return {
                "projects": [],
                "network_interface": ""
            }
        except Exception as e:
            print(f"Erreur inattendue lors du chargement de {CONFIG_FILE}: {e}")
            print("Réinitialisation de la configuration avec une structure par défaut.")
            return {
                "projects": [],
                "network_interface": ""
            }

def save_config(data):
    """Sauvegarde la configuration dans config.json."""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=4)

###############################################################################
# 2) Application TUI
###############################################################################

class ImapSyncTUI:
    """
    Application TUI pour gérer les projets et comptes IMAPSync.
    """

    def __init__(self):
        self.config = load_config()
        self.sync_tasks = {}  # Clé: task_id, Valeur: dict des détails de la tâche
        self.lock = threading.Lock()

        self.main_menu = [
            "Accueil",
            "Projet",
            "Synchronisation",
            "Paramètres",
            "Logs",
            "Quitter"
        ]
        self.selected_main_idx = 0
        self.menu_state = "main"  
        self.status_message = "Bienvenue dans IMAPSync UI!"

        # Pour le défilement des logs
        self.log_scroll_offsets = {}

        # Filtrage des logs
        self.current_log_filter = "all"

        # Interface et stats réseau
        self.network_interface = self.config.get("network_interface", "")
        self.upload_rate = 0
        self.download_rate = 0

    ###########################################################################
    # A) Lancement curses
    ###########################################################################

    def run(self):
        curses.wrapper(self._main_loop)

    def _main_loop(self, stdscr):
        self.stdscr = stdscr
        curses.curs_set(0)
        curses.start_color()
        curses.use_default_colors()

        # Couleurs
        curses.init_pair(1, curses.COLOR_CYAN, -1)   # Titre
        curses.init_pair(2, curses.COLOR_WHITE, curses.COLOR_BLUE)  
        curses.init_pair(3, curses.COLOR_YELLOW, -1)  # Highlight menu
        curses.init_pair(4, curses.COLOR_GREEN, -1)   # Success
        curses.init_pair(5, curses.COLOR_RED, -1)     # Erreur
        curses.init_pair(6, curses.COLOR_MAGENTA, -1) # Sélection
        curses.init_pair(7, curses.COLOR_WHITE, curses.COLOR_BLACK) 
        curses.init_pair(8, curses.COLOR_BLUE, -1)    # Stats Dashboard
        curses.init_pair(9, curses.COLOR_WHITE, curses.COLOR_GREEN) 

        # Dimensions fixes
        max_y, max_x = stdscr.getmaxyx()
        title_height = 3
        menu_width = 35
        status_height = 1
        main_width = max_x - menu_width
        main_height = max_y - title_height - status_height

        # Fenêtres
        self.title_win  = curses.newwin(title_height, max_x, 0, 0)
        self.menu_win   = curses.newwin(main_height, menu_width, title_height, 0)
        self.main_win   = curses.newwin(main_height, main_width, title_height, menu_width)
        self.status_win = curses.newwin(status_height, max_x, title_height + main_height, 0)

        self.title_win.bkgd(' ', curses.color_pair(1) | curses.A_BOLD)
        self.status_win.bkgd(' ', curses.color_pair(2))

        # Thread pour le débit réseau
        if psutil:
            if not self.network_interface:
                ifaces = list(psutil.net_if_stats().keys())
                if ifaces:
                    self.network_interface = ifaces[0]
                    self.config["network_interface"] = self.network_interface
                    save_config(self.config)
            net_thread = threading.Thread(target=self._update_network_stats, daemon=True)
            net_thread.start()

        # Boucle principale
        while True:
            self._draw_all()
            key = stdscr.getch()

            if self.menu_state == "main":
                self._on_main_menu_select(key)
            elif self.menu_state == "projet":
                self._on_projet_menu_select(key)
            elif self.menu_state == "synchro":
                self._on_synchro_menu_select(key)
            elif self.menu_state == "parametre":
                self._on_parametre_menu_select(key)
            elif self.menu_state == "logs":
                self._on_logs_menu_select(key)

            # Mise à jour logs
            self._update_logs_display()
            save_config(self.config)

    ###########################################################################
    # B) Dessin des fenêtres
    ###########################################################################

    def _draw_all(self):
        # Titre
        self.title_win.erase()
        title_text = " IMAPSync UI - Gestion des Projets et Comptes "
        tw = self.title_win.getmaxyx()[1]
        self.title_win.addstr(1, max(0, (tw - len(title_text)) // 2), title_text)
        self.title_win.refresh()

        # Menu
        self.menu_win.erase()
        if self.menu_state == "main":
            self._draw_menu(self.main_menu, self.selected_main_idx)
        elif self.menu_state == "projet":
            self._draw_projet_menu()
        elif self.menu_state == "synchro":
            self._draw_synchro_menu()
        elif self.menu_state == "parametre":
            self._draw_parametre_menu()
        elif self.menu_state == "logs":
            self._draw_logs_menu()
        self.menu_win.box()
        self.menu_win.refresh()

        # Main
        if self.menu_state == "main":
            self._draw_home_content()
        elif self.menu_state == "logs":
            self._draw_logs_content()
        else:
            self.main_win.erase()
            self.main_win.box()
            self.main_win.refresh()

        # Barre de statut
        self._draw_status_bar()

    def _draw_status_bar(self):
        self.status_win.erase()
        if psutil:
            cpu_usage = psutil.cpu_percent(interval=0.0)
            mem_usage = psutil.virtual_memory().percent
            disk_usage = psutil.disk_usage('/').percent
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            up_str = self._format_rate(self.upload_rate)
            down_str = self._format_rate(self.download_rate)

            status_str = (f"[CPU: {cpu_usage:.0f}% | RAM: {mem_usage:.0f}% | DISK: {disk_usage:.0f}% "
                          f"| UP: {up_str} | DOWN: {down_str}] {now_str}")
        else:
            status_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        max_x = self.status_win.getmaxyx()[1]
        combined_str = f"{status_str} - {self.status_message}"
        truncated_str = combined_str[:max_x - 1]
        self.status_win.addstr(0, 0, truncated_str)
        self.status_win.refresh()

    def _draw_home_content(self):
        self.main_win.erase()
        self.main_win.box()
        h, w = self.main_win.getmaxyx()
        self.main_win.addstr(1, 2, "=== Accueil / Tableau de bord ===", curses.A_BOLD)
        y = 3

        with self.lock:
            total = len(self.sync_tasks)
            running = sum(1 for t in self.sync_tasks.values() if t["status"] == "En cours")
            succeeded = sum(1 for t in self.sync_tasks.values() if t["status"] == "Terminée")
            failed = sum(1 for t in self.sync_tasks.values() if "Erreur" in t["status"])
            stopped = sum(1 for t in self.sync_tasks.values() if t["status"] == "Arrêtée")

            lines = [
                f"Total Tâches : {total}",
                f"Tâches en Cours : {running}",
                f"Tâches Terminées : {succeeded}",
                f"Tâches Échouées : {failed}",
                f"Tâches Arrêtées : {stopped}"
            ]
            for line in lines:
                if y < h - 2:
                    self.main_win.addstr(y, 2, line, curses.color_pair(8))
                    y += 1
            y += 1

            # Stats projets
            for project in self.config["projects"]:
                proj_name = project["project_name"]
                proj_tasks = [t for t in self.sync_tasks.values() if t["project_name"] == proj_name]
                proj_total = len(proj_tasks)
                proj_running = sum(1 for t in proj_tasks if t["status"] == "En cours")
                proj_succeeded = sum(1 for t in proj_tasks if t["status"] == "Terminée")
                proj_failed = sum(1 for t in proj_tasks if "Erreur" in t["status"])
                proj_stopped = sum(1 for t in proj_tasks if t["status"] == "Arrêtée")

                lines_proj = [
                    f"Projet: {proj_name}",
                    f"   Total: {proj_total}",
                    f"   En Cours: {proj_running}",
                    f"   Terminées: {proj_succeeded}",
                    f"   Échouées: {proj_failed}",
                    f"   Arrêtées: {proj_stopped}"
                ]
                for lp in lines_proj:
                    if y < h - 2:
                        self.main_win.addstr(y, 2, lp, curses.color_pair(8))
                        y += 1
                y += 1

        self.main_win.refresh()

    def _draw_menu(self, menu_items, selected_idx):
        for i, item in enumerate(menu_items):
            y = i + 1
            if i == selected_idx:
                self.menu_win.attron(curses.color_pair(3) | curses.A_BOLD)
                self.menu_win.addstr(y, 1, item)
                self.menu_win.attroff(curses.color_pair(3) | curses.A_BOLD)
            else:
                self.menu_win.addstr(y, 1, item)

    def _draw_projet_menu(self):
        lines = [
            "=== Menu Projet ===",
            "a) Ajouter un projet",
            "m) Modifier un projet",
            "d) Supprimer un projet",
            "c) Gérer les comptes",
            "q) Retour"
        ]
        for i, line in enumerate(lines):
            self.menu_win.addstr(i+1, 1, line)

    def _draw_synchro_menu(self):
        lines = [
            "=== Menu Synchronisation ===",
            "l) Lancer une synchronisation",
            "a) Ajouter une tâche de synchronisation",
            "v) Vue Globale des Synchronisations",
            "q) Retour"
        ]
        for i, line in enumerate(lines):
            self.menu_win.addstr(i+1, 1, line)

    def _draw_parametre_menu(self):
        lines = [
            "=== Menu Paramètres ===",
            "o) Options IMAPSync",
            "n) Sélectionner Interface Réseau",
            "q) Retour"
        ]
        for i, line in enumerate(lines):
            self.menu_win.addstr(i+1, 1, line)

    def _draw_logs_menu(self):
        lines = [
            "=== Menu Logs ===",
            "v) Vue Globale des Synchronisations",
            "s) Rechercher un terme",
            "f) Filtrer l'affichage",
            "t) Déployer/Replier une tâche",
            "e) Exporter logs",
            "q) Retour"
        ]
        for i, line in enumerate(lines):
            self.menu_win.addstr(i+1, 1, line)

    def _draw_logs_content(self):
        self.main_win.erase()
        self.main_win.box()
        h, w = self.main_win.getmaxyx()

        title = "=== Logs des Synchronisations === (↑/↓/PageUp/PageDown pour défiler)"
        if len(title) > w - 2:
            title = title[:w-2]
        self.main_win.addstr(1, 1, title, curses.A_BOLD)

        y = 3
        with self.lock:
            filtered_tasks = [tid for tid, t in self.sync_tasks.items() if self._match_log_filter(t)]
            if not filtered_tasks:
                self.main_win.addstr(y, 1, "Aucune synchronisation correspondante au filtre.", curses.color_pair(7))
            else:
                for tid in filtered_tasks:
                    task = self.sync_tasks[tid]
                    proj_name = task["project_name"]
                    status = task["status"]
                    expand_marker = "+" if not task.get("expanded", False) else "-"
                    header = f"{expand_marker} Tâche: [{tid}] Projet: {proj_name} | Status: {status}"
                    if len(header) > w - 2:
                        header = header[:w-2]
                    self.main_win.addstr(y, 1, header, curses.color_pair(7) | curses.A_BOLD)
                    y += 1

                    if task.get("expanded", False):
                        offset = self.log_scroll_offsets.get(tid, 0)
                        logs_to_display = task["logs"][offset : offset + (h - y - 2)]
                        for line in logs_to_display:
                            if y >= h - 2:
                                break
                            display_line = f"    {line}"
                            if len(display_line) > w - 2:
                                display_line = display_line[: w - 2]
                            self.main_win.addstr(y, 3, display_line, curses.color_pair(7))
                            y += 1

        self.main_win.refresh()

    def _update_logs_display(self):
        if self.menu_state == "logs":
            self._draw_logs_content()

    ###########################################################################
    # C) Navigation dans les menus
    ###########################################################################

    def _on_main_menu_select(self, key):
        if key == curses.KEY_UP:
            self.selected_main_idx = max(0, self.selected_main_idx - 1)
        elif key == curses.KEY_DOWN:
            self.selected_main_idx = min(len(self.main_menu) - 1, self.selected_main_idx + 1)
        elif key == ord('\n'):
            item = self.main_menu[self.selected_main_idx].lower()
            if "accueil" in item:
                self.menu_state = "main"
            elif "projet" in item:
                self.menu_state = "projet"
            elif "synchronisation" in item:
                self.menu_state = "synchro"
            elif "paramètre" in item:
                self.menu_state = "parametre"
            elif "logs" in item:
                self.menu_state = "logs"
            elif "quitter" in item:
                raise SystemExit

    def _on_projet_menu_select(self, key):
        if key in (ord('q'), ord('Q')):
            self.menu_state = "main"
        elif key in (ord('a'), ord('A')):
            self._add_project()
        elif key in (ord('m'), ord('M')):
            self._modify_project()
        elif key in (ord('d'), ord('D')):
            self._delete_project()
        elif key in (ord('c'), ord('C')):
            self._manage_accounts()

    def _on_synchro_menu_select(self, key):
        if key in (ord('q'), ord('Q')):
            self.menu_state = "main"
        elif key in (ord('l'), ord('L')):
            self.action_launch_sync()       # <--- Important
        elif key in (ord('a'), ord('A')):
            self.action_add_sync_task()     # <--- Important
        elif key in (ord('v'), ord('V')):
            self.menu_state = "logs"

    def _on_parametre_menu_select(self, key):
        if key in (ord('q'), ord('Q')):
            self.menu_state = "main"
        elif key in (ord('o'), ord('O')):
            self._imapsync_options_menu()
        elif key in (ord('n'), ord('N')):
            self._select_network_interface()

    def _on_logs_menu_select(self, key):
        if key in (ord('q'), ord('Q')):
            self.menu_state = "main"
        elif key in (ord('v'), ord('V')):
            self.menu_state = "logs"
        elif key in (ord('s'), ord('S')):
            self._search_logs()
        elif key in (ord('f'), ord('F')):
            self._filter_logs()
        elif key in (ord('t'), ord('T')):
            self._toggle_task_expansion()
        elif key in (ord('e'), ord('E')):
            self._export_logs()
        elif key == curses.KEY_UP:
            self._scroll_logs(-1)
        elif key == curses.KEY_DOWN:
            self._scroll_logs(1)
        elif key == curses.KEY_PPAGE:
            self._scroll_logs(-self._page_size())
        elif key == curses.KEY_NPAGE:
            self._scroll_logs(self._page_size())

    ###########################################################################
    # D) Scroll des logs
    ###########################################################################

    def _scroll_logs(self, delta):
        with self.lock:
            for tid, task in self.sync_tasks.items():
                if task.get("expanded", False):
                    current_offset = self.log_scroll_offsets.get(tid, 0)
                    new_offset = max(0, current_offset + delta)
                    max_logs = len(task["logs"])
                    window_size = self.main_win.getmaxyx()[0] - 5
                    if new_offset > max_logs - window_size:
                        new_offset = max(0, max_logs - window_size)
                    self.log_scroll_offsets[tid] = new_offset

    def _page_size(self):
        h, _ = self.main_win.getmaxyx()
        return max(1, h // 2)

    ###########################################################################
    # E) Gestion des Projets (Add, Modify, Delete, Manage Accounts)
    ###########################################################################
    # ... identique à la version précédente ...

    ###########################################################################
    # F) Gestion des Comptes
    ###########################################################################
    # ... identique ...

    ###########################################################################
    # G) Lancer la Synchronisation
    ###########################################################################

    def action_launch_sync(self):
        """Lance la synchronisation IMAP pour un projet sélectionné."""
        projs = self.config["projects"]
        if not projs:
            self.popup_message("Aucun projet disponible.", msg_type="error")
            return

        current_idx = 0
        while True:
            self.main_win.erase()
            self.main_win.box()
            h, w = self.main_win.getmaxyx()
            self.main_win.addstr(1, 1, "=== Lancer Synchronisation ===", curses.A_BOLD)
            self.main_win.addstr(2, 1, "Sélectionnez un projet :")
            for i, p in enumerate(projs):
                if i == current_idx:
                    self.main_win.attron(curses.color_pair(6) | curses.A_BOLD)
                    self.main_win.addstr(4 + i, 1, p["project_name"])
                    self.main_win.attroff(curses.color_pair(6) | curses.A_BOLD)
                else:
                    self.main_win.addstr(4 + i, 1, p["project_name"])
            self.main_win.refresh()

            key = self.stdscr.getch()
            if key == curses.KEY_UP:
                current_idx = (current_idx - 1) % len(projs)
            elif key == curses.KEY_DOWN:
                current_idx = (current_idx + 1) % len(projs)
            elif key == ord('\n'):
                project = projs[current_idx]
                accounts = project.get("accounts", [])
                if not accounts:
                    self.popup_message("Aucun compte à synchroniser dans ce projet.", msg_type="error")
                    return

                # Sélection des comptes
                selected_accounts = self._select_accounts_to_sync(project)
                if not selected_accounts:
                    self.popup_message("Aucun compte sélectionné.", msg_type="info")
                    return

                interval_str = self.curses_input("Relancer toutes les X minutes (0 = pas de relance) :", default=str(project.get("sync_interval", 60)))
                try:
                    interval = int(interval_str)
                except:
                    interval = 60
                project["sync_interval"] = interval
                save_config(self.config)

                # Lancer la synchro pour chaque compte
                for acc in selected_accounts:
                    self._start_sync(project, [acc], interval)

                self.popup_message("Synchronisation démarrée.", msg_type="success")
                break
            elif key in (27, ord('q')):
                break

    def action_add_sync_task(self):
        """Ajoute une tâche de synchronisation (intervalle) pour un projet."""
        projs = self.config["projects"]
        if not projs:
            self.popup_message("Aucun projet disponible.", msg_type="error")
            return

        current_idx = 0
        while True:
            self.main_win.erase()
            self.main_win.box()
            h, w = self.main_win.getmaxyx()
            self.main_win.addstr(1, 1, "=== Ajouter une Tâche de Synchronisation ===", curses.A_BOLD)
            self.main_win.addstr(2, 1, "Sélectionnez un projet :")
            for i, p in enumerate(projs):
                if i == current_idx:
                    self.main_win.attron(curses.color_pair(6) | curses.A_BOLD)
                    self.main_win.addstr(4 + i, 1, p["project_name"])
                    self.main_win.attroff(curses.color_pair(6) | curses.A_BOLD)
                else:
                    self.main_win.addstr(4 + i, 1, p["project_name"])
            self.main_win.refresh()

            key = self.stdscr.getch()
            if key == curses.KEY_UP:
                current_idx = (current_idx - 1) % len(projs)
            elif key == curses.KEY_DOWN:
                current_idx = (current_idx + 1) % len(projs)
            elif key == ord('\n'):
                project = projs[current_idx]
                accounts = project.get("accounts", [])
                if not accounts:
                    self.popup_message("Aucun compte à synchroniser.", msg_type="error")
                    return

                selected_accounts = self._select_accounts_to_sync(project)
                if not selected_accounts:
                    self.popup_message("Aucun compte sélectionné.", msg_type="info")
                    return

                interval_str = self.curses_input("Relancer toutes les X minutes (0 = pas de relance) :", default=str(project.get("sync_interval", 60)))
                try:
                    interval = int(interval_str)
                except:
                    interval = 60
                project["sync_interval"] = interval
                save_config(self.config)

                for acc in selected_accounts:
                    self._start_sync(project, [acc], interval)

                self.popup_message("Tâche de synchronisation ajoutée.", msg_type="success")
                break
            elif key in (27, ord('q')):
                break

    ###########################################################################
    # H) Historique
    ###########################################################################
    # (optionnel, selon vos besoins)

    ###########################################################################
    # I) Fonctions de Synchronisation
    ###########################################################################

    def _start_sync(self, project, selected_accounts, interval):
        with self.lock:
            task_id = f"{project['project_name']}_{uuid.uuid4().hex[:8]}"
            self.sync_tasks[task_id] = {
                "project_name": project["project_name"],
                "status": "En cours",
                "logs": [],
                "thread": None,
                "process": None,
                "selected_accounts": selected_accounts,
                "interval": interval,
                "timer": None,
                "expanded": False
            }
            self.log_scroll_offsets[task_id] = 0

        thread = threading.Thread(target=self._run_imapsync_for_task, args=(task_id,))
        thread.daemon = True
        with self.lock:
            self.sync_tasks[task_id]["thread"] = thread
        thread.start()

        if interval > 0:
            timer = threading.Timer(interval * 60, self._scheduled_sync, args=(task_id,))
            timer.daemon = True
            with self.lock:
                self.sync_tasks[task_id]["timer"] = timer
            timer.start()

    def _scheduled_sync(self, task_id):
        with self.lock:
            task = self.sync_tasks.get(task_id)
            if not task or task["status"] not in ["En cours", "Terminée", "Erreur: échecs sur un ou plusieurs comptes"]:
                return
            thread = threading.Thread(target=self._run_imapsync_for_task, args=(task_id,))
            thread.daemon = True
            self.sync_tasks[task_id]["thread"] = thread
            thread.start()

    def _run_imapsync_for_task(self, task_id):
        with self.lock:
            task = self.sync_tasks.get(task_id)
            if not task:
                return
            project = next((p for p in self.config["projects"] if p["project_name"] == task["project_name"]), None)
            if not project:
                task["status"] = "Erreur: Projet introuvable"
                return
            accounts = task["selected_accounts"]
            imapsync_bin = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin", "imapsync")

            if not os.path.exists(imapsync_bin):
                task["logs"].append(f"Binaire imapsync introuvable à {imapsync_bin}")
                task["status"] = "Erreur: imapsync introuvable"
                return

        old_server = project.get("old_server_url", "")
        new_server = project.get("new_server_url", "")
        imapsync_options = project.get("imapsync_options", {})

        for acc in accounts:
            src_email = acc.get("source_email", "")
            tgt_email = acc.get("target_email", src_email)
            password = acc.get("password", "")
            subfolder = acc.get("subfolder", "")

            cmd = [
                imapsync_bin,
                "--host1", old_server,
                "--user1", src_email,
                "--password1", password,
                "--host2", new_server,
                "--user2", tgt_email,
                "--password2", password
            ]

            # Options IMAPSync
            if imapsync_options.get("ssl1"):
                cmd.append("--ssl1")
            if imapsync_options.get("ssl2"):
                cmd.append("--ssl2")
            if imapsync_options.get("tls1"):
                cmd.append("--tls1")
            if imapsync_options.get("tls2"):
                cmd.append("--tls2")
            if imapsync_options.get("logfile"):
                cmd += ["--logfile", imapsync_options["logfile"]]
            if imapsync_options.get("authmech1"):
                cmd += ["--authmech1", imapsync_options["authmech1"]]
            if imapsync_options.get("authmech2"):
                cmd += ["--authmech2", imapsync_options["authmech2"]]
            if imapsync_options.get("automap"):
                cmd.append("--automap")
            if imapsync_options.get("regextrans2"):
                cmd += ["--regextrans2", imapsync_options["regextrans2"]]
            if imapsync_options.get("delete2"):
                cmd.append("--delete2")
            if imapsync_options.get("maxsize"):
                cmd += ["--maxsize", str(imapsync_options["maxsize"])]
            if imapsync_options.get("minsize"):
                cmd += ["--minsize", str(imapsync_options["minsize"])]

            # Sous-dossier
            if subfolder:
                cmd += ["--regextrans2", f"s/^(.*)/{subfolder}/$1"]

            cmd_str = " ".join(cmd)
            with self.lock:
                task["logs"].append(f"Commande : {cmd_str}")

            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True
                )
                with self.lock:
                    task["process"] = proc

                while True:
                    output = proc.stdout.readline()
                    if output:
                        with self.lock:
                            task["logs"].append(output.strip())
                            self.status_message = f"Synchronisation en cours pour '{project['project_name']}'..."
                    elif proc.poll() is not None:
                        break

                err_output = proc.stderr.read()
                if err_output:
                    with self.lock:
                        task["logs"].append(f"ERREUR: {err_output.strip()}")
                        self.status_message = f"Erreur lors de la synchronisation."

                rc = proc.returncode
                with self.lock:
                    if rc == 0:
                        task["logs"].append(f"Synchronisation OK pour {src_email} -> {tgt_email}")
                    else:
                        task["logs"].append(f"Synchronisation échouée pour {src_email} -> {tgt_email} (Code {rc})")
            except Exception as e:
                with self.lock:
                    task["logs"].append(f"Exception lors de la synchro: {str(e)}")

        # Statut final
        with self.lock:
            # Vérifier s'il y a une erreur
            if any("échouée" in log.lower() or "erreur" in log.lower() for log in task["logs"]):
                task["status"] = "Erreur: échecs sur un ou plusieurs comptes"
            else:
                task["status"] = "Terminée"

    ###########################################################################
    # J) Sélection de l'Interface Réseau et Options IMAPSync
    ###########################################################################

    def _imapsync_options_menu(self):
        opts = [
            "1) Activer/Désactiver SSL sur host1",
            "2) Activer/Désactiver SSL sur host2",
            "3) Activer/Désactiver TLS sur host1",
            "4) Activer/Désactiver TLS sur host2",
            "5) Définir fichier de log",
            "6) Définir mécanisme d'authentification host1",
            "7) Définir mécanisme d'authentification host2",
            "8) Activer/Désactiver Automap",
            "9) Définir RegexTrans2",
            "10) Activer/Désactiver delete2",
            "11) Définir maxsize",
            "12) Définir minsize",
            "q) Retour"
        ]
        idx = 0
        while True:
            self.main_win.erase()
            self.main_win.box()
            h, w = self.main_win.getmaxyx()
            self.main_win.addstr(1, 1, "=== Options IMAPSync ===", curses.A_BOLD)
            for i, opt in enumerate(opts):
                if i == idx:
                    self.main_win.attron(curses.color_pair(3) | curses.A_BOLD)
                    self.main_win.addstr(3 + i, 1, opt)
                    self.main_win.attroff(curses.color_pair(3) | curses.A_BOLD)
                else:
                    self.main_win.addstr(3 + i, 1, opt)
            self.main_win.refresh()

            key = self.stdscr.getch()
            if key == curses.KEY_UP:
                idx = (idx - 1) % len(opts)
            elif key == curses.KEY_DOWN:
                idx = (idx + 1) % len(opts)
            elif key == ord('\n'):
                if idx == 0:
                    self._toggle_imapsync_option("ssl1")
                elif idx == 1:
                    self._toggle_imapsync_option("ssl2")
                elif idx == 2:
                    self._toggle_imapsync_option("tls1")
                elif idx == 3:
                    self._toggle_imapsync_option("tls2")
                elif idx == 4:
                    self._set_imapsync_logfile()
                elif idx == 5:
                    self._set_imapsync_authmech1()
                elif idx == 6:
                    self._set_imapsync_authmech2()
                elif idx == 7:
                    self._toggle_imapsync_option("automap")
                elif idx == 8:
                    self._set_imapsync_regextrans2()
                elif idx == 9:
                    self._toggle_imapsync_option("delete2")
                elif idx == 10:
                    self._set_imapsync_maxsize()
                elif idx == 11:
                    self._set_imapsync_minsize()
                elif idx == 12:
                    break
            elif key in (27, ord('q'), ord('Q')):
                break

    def _toggle_imapsync_option(self, opt):
        # Choisir un projet
        project = self._select_project_for_options()
        if not project:
            return
        current = project["imapsync_options"].get(opt, False)
        project["imapsync_options"][opt] = not current
        save_config(self.config)
        self.popup_message(f"Option '{opt}' basculée ({not current}).", msg_type="success")

    def _select_project_for_options(self):
        projs = self.config["projects"]
        if not projs:
            self.popup_message("Aucun projet disponible.", msg_type="error")
            return None
        idx = 0
        while True:
            self.main_win.erase()
            self.main_win.box()
            h, w = self.main_win.getmaxyx()
            self.main_win.addstr(1, 1, "=== Sélectionner un Projet ===", curses.A_BOLD)
            for i, p in enumerate(projs):
                if i == idx:
                    self.main_win.attron(curses.color_pair(6) | curses.A_BOLD)
                    self.main_win.addstr(3 + i, 1, p["project_name"])
                    self.main_win.attroff(curses.color_pair(6) | curses.A_BOLD)
                else:
                    self.main_win.addstr(3 + i, 1, p["project_name"])
            self.main_win.refresh()

            key = self.stdscr.getch()
            if key == curses.KEY_UP:
                idx = (idx - 1) % len(projs)
            elif key == curses.KEY_DOWN:
                idx = (idx + 1) % len(projs)
            elif key == ord('\n'):
                return projs[idx]
            elif key in (27, ord('q')):
                return None

    def _set_imapsync_logfile(self):
        proj = self._select_project_for_options()
        if not proj:
            return
        logfile = self.curses_input("Nom du fichier log :", default=proj["imapsync_options"].get("logfile", "imapsync.log"))
        proj["imapsync_options"]["logfile"] = logfile
        save_config(self.config)
        self.popup_message(f"Fichier de log défini : {logfile}", msg_type="success")

    def _set_imapsync_authmech1(self):
        proj = self._select_project_for_options()
        if not proj:
            return
        val = self.curses_input("Authmech1 :", default=proj["imapsync_options"].get("authmech1", "PLAIN"))
        proj["imapsync_options"]["authmech1"] = val.upper()
        save_config(self.config)
        self.popup_message(f"authmech1 défini : {val.upper()}", msg_type="success")

    def _set_imapsync_authmech2(self):
        proj = self._select_project_for_options()
        if not proj:
            return
        val = self.curses_input("Authmech2 :", default=proj["imapsync_options"].get("authmech2", "PLAIN"))
        proj["imapsync_options"]["authmech2"] = val.upper()
        save_config(self.config)
        self.popup_message(f"authmech2 défini : {val.upper()}", msg_type="success")

    def _set_imapsync_regextrans2(self):
        proj = self._select_project_for_options()
        if not proj:
            return
        val = self.curses_input("RegexTrans2 :", default=proj["imapsync_options"].get("regextrans2", ""))
        proj["imapsync_options"]["regextrans2"] = val
        save_config(self.config)
        self.popup_message(f"regextrans2 défini : {val}", msg_type="success")

    def _set_imapsync_maxsize(self):
        proj = self._select_project_for_options()
        if not proj:
            return
        val = self.curses_input("maxsize (bytes) :", default=str(proj["imapsync_options"].get("maxsize", 10485760)))
        try:
            num = int(val)
            proj["imapsync_options"]["maxsize"] = num
            save_config(self.config)
            self.popup_message(f"maxsize défini : {num}", msg_type="success")
        except:
            self.popup_message("Valeur invalide.", msg_type="error")

    def _set_imapsync_minsize(self):
        proj = self._select_project_for_options()
        if not proj:
            return
        val = self.curses_input("minsize (bytes) :", default=str(proj["imapsync_options"].get("minsize", 1024)))
        try:
            num = int(val)
            proj["imapsync_options"]["minsize"] = num
            save_config(self.config)
            self.popup_message(f"minsize défini : {num}", msg_type="success")
        except:
            self.popup_message("Valeur invalide.", msg_type="error")

    def _select_network_interface(self):
        if not psutil:
            self.popup_message("psutil non installé, fonctionnalité réseau indisponible.", msg_type="error")
            return

        ifaces = list(psutil.net_if_stats().keys())
        if not ifaces:
            self.popup_message("Aucune interface réseau détectée.", msg_type="error")
            return

        idx = 0
        while True:
            self.main_win.erase()
            self.main_win.box()
            h, w = self.main_win.getmaxyx()
            self.main_win.addstr(1, 1, "=== Sélectionner Interface Réseau ===", curses.A_BOLD)
            for i, iface in enumerate(ifaces):
                if i == idx:
                    self.main_win.attron(curses.color_pair(6) | curses.A_BOLD)
                    self.main_win.addstr(3 + i, 1, iface)
                    self.main_win.attroff(curses.color_pair(6) | curses.A_BOLD)
                else:
                    self.main_win.addstr(3 + i, 1, iface)
            self.main_win.refresh()

            key = self.stdscr.getch()
            if key == curses.KEY_UP:
                idx = (idx - 1) % len(ifaces)
            elif key == curses.KEY_DOWN:
                idx = (idx + 1) % len(ifaces)
            elif key == ord('\n'):
                self.network_interface = ifaces[idx]
                self.config["network_interface"] = self.network_interface
                save_config(self.config)
                self.popup_message(f"Interface réseau : {self.network_interface}", msg_type="success")
                break
            elif key in (27, ord('q')):
                break

    ###########################################################################
    # L) Affichage & Saisie
    ###########################################################################

    def _print_in_main(self, lines):
        self.main_win.erase()
        self.main_win.box()
        h, w = self.main_win.getmaxyx()
        max_x = w - 2
        y = 1
        for line in lines:
            if y < h - 1:
                if len(line) > max_x:
                    line = line[:max_x-3] + "..."
                self.main_win.addstr(y, 1, line, curses.color_pair(7))
                y += 1
        self.main_win.refresh()

    def popup_message(self, message, wait_key=True, msg_type="info"):
        lines = message.split("\n")
        self._print_in_main(lines)
        if msg_type == "success":
            self.status_win.attron(curses.color_pair(4))
        elif msg_type == "error":
            self.status_win.attron(curses.color_pair(5))
        elif msg_type == "notification":
            self.status_win.attron(curses.color_pair(9))
        else:
            self.status_win.attron(curses.color_pair(2))

        if wait_key:
            h, w = self.main_win.getmaxyx()
            self.main_win.addstr(h - 2, 1, "Appuyez sur une touche pour continuer...")
            self.main_win.refresh()
            self.main_win.getch()

        if msg_type == "success":
            self.status_win.attroff(curses.color_pair(4))
        elif msg_type == "error":
            self.status_win.attroff(curses.color_pair(5))
        elif msg_type == "notification":
            self.status_win.attroff(curses.color_pair(9))
        else:
            self.status_win.attroff(curses.color_pair(2))

        self.status_message = message[:60]
        self._draw_status_bar()

    def curses_input(self, prompt, default="", hidden=False):
        curses.curs_set(1)
        self.main_win.erase()
        self.main_win.box()
        h, w = self.main_win.getmaxyx()
        max_x = w - 4

        if default:
            prompt_full = f"{prompt} (actuel: {default})"
        else:
            prompt_full = prompt

        if len(prompt_full) > max_x:
            prompt_full = prompt_full[:max_x - 3] + "..."
        self.main_win.addstr(1, 1, prompt_full, curses.color_pair(7))
        self.main_win.refresh()

        buf = list(default)
        pos = len(buf)
        input_y = 3

        while True:
            try:
                key = self.main_win.getch(input_y, 1 + pos)
            except curses.error:
                key = -1

            if key in (curses.KEY_ENTER, 10, 13):
                break
            elif key in (curses.KEY_BACKSPACE, 127, 8):
                if pos > 0:
                    pos -= 1
                    buf.pop()
            elif key == 27:  # ESC
                buf = list(default)
                break
            elif 32 <= key <= 126:
                ch = chr(key)
                buf.insert(pos, ch)
                pos += 1

            disp = "".join("*" if hidden else c for c in buf)
            if len(disp) > max_x:
                disp = disp[:max_x - 3] + "..."
            self.main_win.addstr(input_y, 1, " " * max_x, curses.color_pair(7))
            self.main_win.addstr(input_y, 1, disp, curses.color_pair(7))
            self.main_win.refresh()

        curses.curs_set(0)
        return "".join(buf).strip()

    def wait_key(self):
        h, w = self.main_win.getmaxyx()
        self.main_win.addstr(h - 2, 1, "Appuyez sur une touche pour continuer...")
        self.main_win.refresh()
        self.main_win.getch()

    ###########################################################################
    # M) Sélection des Comptes
    ###########################################################################

    def _select_accounts_to_sync(self, project):
        accounts = project.get("accounts", [])
        selected = [False] * len(accounts)
        current_idx = 0

        while True:
            self.main_win.erase()
            self.main_win.box()
            h, w = self.main_win.getmaxyx()
            self.main_win.addstr(1, 1, f"=== Sélectionner les Comptes pour '{project['project_name']}' ===", curses.A_BOLD)
            self.main_win.addstr(2, 1, "Flèches haut/bas pour naviguer, espace pour sélectionner, Entrée pour valider.")

            for i, acc in enumerate(accounts):
                checkbox = "[X]" if selected[i] else "[ ]"
                line = f"{checkbox} {acc['source_email']}"
                if i == current_idx:
                    self.main_win.attron(curses.color_pair(3) | curses.A_BOLD)
                    self.main_win.addstr(4 + i, 1, line)
                    self.main_win.attroff(curses.color_pair(3) | curses.A_BOLD)
                else:
                    self.main_win.addstr(4 + i, 1, line)

            self.main_win.refresh()

            key = self.stdscr.getch()
            if key == curses.KEY_UP:
                current_idx = (current_idx - 1) % len(accounts)
            elif key == curses.KEY_DOWN:
                current_idx = (current_idx + 1) % len(accounts)
            elif key == ord(' '):
                selected[current_idx] = not selected[current_idx]
            elif key == ord('\n'):
                return [acc for acc, sel in zip(accounts, selected) if sel]
            elif key == 27:
                return []

    ###########################################################################
    # N) Toggle Expansion
    ###########################################################################

    def _toggle_task_expansion(self):
        tasks = list(self.sync_tasks.keys())
        if not tasks:
            self.popup_message("Aucune tâche disponible.", msg_type="error")
            return

        idx = 0
        while True:
            self.main_win.erase()
            self.main_win.box()
            h, w = self.main_win.getmaxyx()
            self.main_win.addstr(1, 1, "=== Toggle Expansion Tâches ===", curses.A_BOLD)
            for i, tid in enumerate(tasks):
                task = self.sync_tasks[tid]
                expand_marker = "+" if not task.get("expanded", False) else "-"
                line = f"{expand_marker} [{tid}] {task['project_name']} | {task['status']}"
                if i == idx:
                    self.main_win.attron(curses.color_pair(6) | curses.A_BOLD)
                    self.main_win.addstr(3 + i, 1, line)
                    self.main_win.attroff(curses.color_pair(6) | curses.A_BOLD)
                else:
                    self.main_win.addstr(3 + i, 1, line)
            self.main_win.refresh()

            key = self.stdscr.getch()
            if key == curses.KEY_UP:
                idx = (idx - 1) % len(tasks)
            elif key == curses.KEY_DOWN:
                idx = (idx + 1) % len(tasks)
            elif key == ord('\n'):
                sel_tid = tasks[idx]
                with self.lock:
                    self.sync_tasks[sel_tid]["expanded"] = not self.sync_tasks[sel_tid].get("expanded", False)
                break
            elif key in (27, ord('q')):
                break

    ###########################################################################
    # O) Arrêter une Synchronisation
    ###########################################################################

    def _stop_sync(self, task_id):
        with self.lock:
            task = self.sync_tasks.get(task_id)
            if not task:
                self.popup_message(f"Aucune synchro pour '{task_id}'.", msg_type="error")
                return
            proc = task.get("process")
            if proc and proc.poll() is None:
                proc.terminate()
                task["status"] = "Arrêtée"
                task["logs"].append("Synchronisation arrêtée manuellement.")
                self.popup_message(f"Sync '{task_id}' arrêtée.", msg_type="notification")
            else:
                self.popup_message(f"Sync '{task_id}' n'est pas en cours.", msg_type="error")

    ###########################################################################
    # P) Méthodes Utilitaires (Filtrage Logs, Recherche, Export)
    ###########################################################################

    def _match_log_filter(self, task):
        status = task["status"]
        if self.current_log_filter == "all":
            return True
        elif self.current_log_filter == "succeeded":
            return status == "Terminée"
        elif self.current_log_filter == "failed":
            return ("Erreur" in status) or ("échouée" in status.lower())
        elif self.current_log_filter == "running":
            return status == "En cours"
        return True

    def _filter_logs(self):
        options = [
            "1) Toutes",
            "2) Réussies (Terminées)",
            "3) Échouées",
            "4) En cours",
            "q) Retour"
        ]
        idx = 0
        while True:
            self.main_win.erase()
            self.main_win.box()
            h, w = self.main_win.getmaxyx()
            self.main_win.addstr(1, 1, "=== Filtrer Logs ===", curses.A_BOLD)
            for i, opt in enumerate(options):
                if i == idx:
                    self.main_win.attron(curses.color_pair(3) | curses.A_BOLD)
                    self.main_win.addstr(3 + i, 1, opt)
                    self.main_win.attroff(curses.color_pair(3) | curses.A_BOLD)
                else:
                    self.main_win.addstr(3 + i, 1, opt)
            self.main_win.refresh()

            key = self.stdscr.getch()
            if key == curses.KEY_UP:
                idx = (idx - 1) % len(options)
            elif key == curses.KEY_DOWN:
                idx = (idx + 1) % len(options)
            elif key == ord('\n'):
                if idx == 0:
                    self.current_log_filter = "all"
                elif idx == 1:
                    self.current_log_filter = "succeeded"
                elif idx == 2:
                    self.current_log_filter = "failed"
                elif idx == 3:
                    self.current_log_filter = "running"
                elif idx == 4:
                    break
                self.popup_message(f"Filtre : {options[idx]}", msg_type="success")
                break
            elif key in (27, ord('q')):
                break

    def _search_logs(self):
        term = self.curses_input("Terme de recherche :", default="")
        if not term:
            self.popup_message("Recherche annulée.", msg_type="info")
            return
        matched = []
        with self.lock:
            for tid, t in self.sync_tasks.items():
                for line in t["logs"]:
                    if term.lower() in line.lower():
                        matched.append(f"[{tid}] {line}")
        if not matched:
            self.popup_message("Aucun log correspondant.", msg_type="info")
        else:
            lines = [f"=== Résultats: '{term}' ===", ""]
            lines.extend(matched)
            self._print_in_main(lines)
            self.wait_key()

    def _export_logs(self):
        filename = self.curses_input("Fichier d'export :", default="logs_export.txt")
        if not filename:
            self.popup_message("Export annulé.", msg_type="info")
            return
        with self.lock:
            try:
                with open(filename, "w", encoding="utf-8") as f:
                    for tid, t in self.sync_tasks.items():
                        f.write(f"=== Tâche: {tid} ===\n")
                        f.write(f"Projet: {t['project_name']}\n")
                        f.write(f"Status: {t['status']}\nLogs:\n")
                        for line in t["logs"]:
                            f.write(line + "\n")
                        f.write("\n")
                self.popup_message(f"Logs exportés: '{filename}'.", msg_type="success")
            except Exception as e:
                self.popup_message(f"Erreur export: {str(e)}", msg_type="error")

    ###########################################################################
    # Q) Thread pour mettre à jour le débit réseau
    ###########################################################################

    def _update_network_stats(self):
        if not psutil:
            return

        prev_sent = 0
        prev_recv = 0

        while True:
            if not self.network_interface:
                time.sleep(1)
                continue

            net_io = psutil.net_io_counters(pernic=True).get(self.network_interface)
            if net_io:
                sent = net_io.bytes_sent
                recv = net_io.bytes_recv
                self.upload_rate = max(0, sent - prev_sent)
                self.download_rate = max(0, recv - prev_recv)
                prev_sent = sent
                prev_recv = recv
            time.sleep(1)

    def _format_rate(self, bytes_per_second):
        if bytes_per_second < 1024:
            return f"{bytes_per_second} B/s"
        elif bytes_per_second < 1024**2:
            return f"{bytes_per_second / 1024:.1f} KB/s"
        else:
            return f"{bytes_per_second / 1024**2:.1f} MB/s"

###############################################################################
# Main
###############################################################################

def main():
    app = ImapSyncTUI()
    app.run()

if __name__ == "__main__":
    main()
