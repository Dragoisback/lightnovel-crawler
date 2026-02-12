import tkinter as tk
from tkinter import ttk, simpledialog, messagebox
import json
import os
import logging
import base64
from threading import Thread
from lncrawl.core.app import App
from lncrawl.core.sources import prepare_crawler
from lncrawl.models import OutputFormat

logger = logging.getLogger(__name__)


class LibraryApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Lightnovel Crawler Library")
        self.root.geometry("800x600")

        self.library_file = "library.json"
        self.library = []

        self.create_widgets()
        self.load_library()

    def create_widgets(self):
        # Frame for listbox and scrollbar
        list_frame = ttk.Frame(self.root, padding="10")
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.novel_listbox = tk.Listbox(list_frame, font=("Arial", 12))
        self.novel_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.novel_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.novel_listbox.config(yscrollcommand=scrollbar.set)

        # Frame for buttons
        button_frame = ttk.Frame(self.root, padding="10")
        button_frame.pack(fill=tk.X)

        self.add_btn = ttk.Button(button_frame, text="Add Novel", command=self.add_novel)
        self.add_btn.pack(side=tk.LEFT, padx=5)

        self.login_btn = ttk.Button(button_frame, text="Login", command=self.login_novel)
        self.login_btn.pack(side=tk.LEFT, padx=5)

        self.refresh_btn = ttk.Button(button_frame, text="Refresh", command=self.refresh_novel)
        self.refresh_btn.pack(side=tk.LEFT, padx=5)

        self.exit_btn = ttk.Button(button_frame, text="Exit", command=self.root.quit)
        self.exit_btn.pack(side=tk.RIGHT, padx=5)

    def load_library(self):
        if os.path.exists(self.library_file):
            try:
                with open(self.library_file, 'r', encoding='utf-8') as f:
                    self.library = json.load(f)
            except Exception as e:
                logger.error("Failed to load library: %s", e)

        self.update_listbox()

    def save_library(self):
        try:
            with open(self.library_file, 'w', encoding='utf-8') as f:
                json.dump(self.library, f, indent=4)
        except Exception as e:
            logger.error("Failed to save library: %s", e)
            messagebox.showerror("Error", "Failed to save library")

    def update_listbox(self):
        # Preserve selection
        selection = self.novel_listbox.curselection()

        self.novel_listbox.delete(0, tk.END)
        for novel in self.library:
            title = novel.get('title', novel.get('url'))
            last_chap = novel.get('last_chapter', 0)
            self.novel_listbox.insert(tk.END, f"{title} (Last Chapter: {last_chap})")

        if selection and selection[0] < self.novel_listbox.size():
            self.novel_listbox.select_set(selection[0])

    def add_novel(self):
        url = simpledialog.askstring("Add Novel", "Enter Novel URL:")
        if not url:
            return

        if not url.startswith('http'):
            messagebox.showerror("Error", "Invalid URL")
            return

        for novel in self.library:
            if novel['url'] == url:
                messagebox.showinfo("Info", "Novel already in library")
                return

        novel_data = {
            'url': url,
            'title': url,  # Placeholder until refresh
            'last_chapter': 0,
            'login': None
        }
        self.library.append(novel_data)
        self.save_library()
        self.update_listbox()

        # Select the new item
        self.novel_listbox.select_clear(0, tk.END)
        self.novel_listbox.select_set(tk.END)

        if messagebox.askyesno("Login", "Do you want to log in to this novel?"):
            self.prompt_login(novel_data)

    def login_novel(self):
        selection = self.novel_listbox.curselection()
        if not selection:
            messagebox.showwarning("Warning", "Select a novel first")
            return

        index = selection[0]
        novel = self.library[index]
        self.prompt_login(novel)

    def prompt_login(self, novel_data):
        username = simpledialog.askstring("Login", f"Enter Username for {novel_data.get('title')}:")
        if not username:
            return

        password = simpledialog.askstring("Login", f"Enter Password for {novel_data.get('title')}:", show='*')
        if not password:
            return

        # Simple encoding to avoid cleartext in JSON
        encoded_pass = base64.b64encode(password.encode()).decode()
        novel_data['login'] = {'username': username, 'password': encoded_pass}
        self.save_library()
        messagebox.showinfo("Success", "Login credentials saved")

    def refresh_novel(self):
        selection = self.novel_listbox.curselection()
        if not selection:
            messagebox.showwarning("Warning", "Select a novel first")
            return

        index = selection[0]
        novel_data = self.library[index]

        t = Thread(target=self._crawl_novel, args=(novel_data,))
        t.start()

    def _crawl_novel(self, novel_data):
        app = App()
        try:
            app.initialize()
            url = novel_data['url']
            app.crawler = prepare_crawler(url)

            # Pre-configure app to avoid interactive prompts
            app.pack_by_volume = False
            # Default format EPUB. Can be expanded to user preference.
            app.output_formats = {OutputFormat.epub.value: True}

            # Login if credentials exist
            login = novel_data.get('login')
            if login and app.can_do('login'):
                try:
                    password = base64.b64decode(login['password']).decode()
                except Exception:
                    password = login['password']  # Fallback for old/cleartext
                app.login_data = (login['username'], password)

            app.get_novel_info()

            # Update title in library if it's the first run
            if novel_data.get('title') == novel_data.get('url'):
                novel_data['title'] = app.crawler.novel_title
                self.save_library_safe()
                self.update_listbox_safe()

            last_chap_id = novel_data.get('last_chapter', 0)

            # Filter chapters
            new_chapters = [
                x for x in app.crawler.chapters
                if x['id'] > last_chap_id
            ]

            if not new_chapters:
                self.root.after(0, lambda: messagebox.showinfo("Info", f"No new chapters for {novel_data['title']}"))
                return

            app.chapters = new_chapters
            app.start_download()
            app.bind_books()
            app.compress_books()

            # Update last chapter
            if new_chapters:
                max_id = max([x['id'] for x in new_chapters])
                novel_data['last_chapter'] = max_id
                self.save_library_safe()
                self.update_listbox_safe()

            self.root.after(0, lambda: messagebox.showinfo(
                "Success", f"Downloaded {len(new_chapters)} chapters for {novel_data['title']}"
            ))

        except Exception as e:
            logger.exception("Crawling failed")
            err_msg = str(e)
            self.root.after(0, lambda: messagebox.showerror("Error", f"Crawling failed: {err_msg}"))
        finally:
            app.destroy()

    def save_library_safe(self):
        self.root.after(0, self.save_library)

    def update_listbox_safe(self):
        self.root.after(0, self.update_listbox)


def start_gui():
    root = tk.Tk()
    _ = LibraryApp(root)
    root.mainloop()
