from __future__ import annotations

import tkinter as tk
from tkinter import messagebox
import subprocess
import requests

BG = "#080e19"
CARD = "#101a2c"
CARD2 = "#14233a"
TEXT = "#eef5ff"
MUTED = "#97aac5"
ACCENT = "#38cfff"
SUCCESS = "#61e7a0"
WARNING = "#ffd166"


def launch_process(path: str, args: str = ""):
    cmd = [path] + ([x for x in args.split(" ") if x] if args else [])
    return subprocess.Popen(cmd, cwd=str(__import__("pathlib").Path(path).resolve().parent))


class ClientShell(tk.Tk):
    def __init__(self, agent, server_url: str):
        super().__init__()
        self.agent = agent
        self.server_url = server_url.rstrip("/")
        self.session_token = None
        self.customer_name = ""
        self.title("POS Professional V27.5.7 Client")
        self.geometry("1420x900")
        self.minsize(1100, 720)
        self.configure(bg=BG)
        self._build()
        self.show_login()

    def _build(self):
        self.header = tk.Frame(self, bg="#07111f", height=70)
        self.header.pack(fill="x")
        self.brand = tk.Label(self.header, text="POS PRO CLIENT", bg="#07111f", fg=TEXT, font=("Segoe UI", 22, "bold"))
        self.brand.pack(side="right", padx=24, pady=18)
        self.status = tk.Label(self.header, text="● غير متصل", bg="#07111f", fg=WARNING, font=("Segoe UI", 11, "bold"))
        self.status.pack(side="left", padx=24)
        self.body = tk.Frame(self, bg=BG)
        self.body.pack(fill="both", expand=True)

    def clear(self):
        for w in self.body.winfo_children(): w.destroy()

    def show_login(self):
        self.clear()
        card = tk.Frame(self.body, bg=CARD, highlightbackground="#23405f", highlightthickness=1)
        card.place(relx=.5, rely=.5, anchor="center", relwidth=.48, relheight=.62)
        tk.Label(card, text="مرحبًا بك", bg=CARD, fg=TEXT, font=("Segoe UI", 30, "bold")).pack(pady=(45, 8))
        tk.Label(card, text="واجهة العملاء وتشغيل الألعاب", bg=CARD, fg=MUTED, font=("Segoe UI", 13)).pack(pady=(0, 28))
        form = tk.Frame(card, bg=CARD); form.pack(fill="x", padx=50)
        tk.Label(form, text="اسم العميل", bg=CARD, fg=TEXT, anchor="e").pack(fill="x")
        self.name_var = tk.StringVar(); ent = tk.Entry(form, textvariable=self.name_var, justify="right", bg="#091321", fg=TEXT, insertbackground=TEXT, relief="flat", font=("Segoe UI", 12)); ent.pack(fill="x", pady=(6, 18), ipady=8)
        tk.Button(form, text="دخول", command=self.login, bg=ACCENT, fg="#03131c", relief="flat", font=("Segoe UI", 11, "bold"), pady=11).pack(fill="x")
        tk.Label(card, text="Server → Client • V17", bg=CARD, fg=MUTED, font=("Segoe UI", 9)).pack(side="bottom", pady=20)
        ent.focus_set()

    def login(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("تسجيل الدخول", "اكتب اسم العميل.", parent=self); return
        try:
            r = requests.post(self.server_url + "/api/v15/client/login", json={"customer_name": name, "pin": "", "device_id": self.agent.device_id}, timeout=5); r.raise_for_status(); data = r.json()
            self.session_token = data.get("token"); self.customer_name = name; self.agent.cfg["current_customer"] = name; self.agent._save(); self.status.configure(text="● متصل • الجلسة نشطة", fg=SUCCESS); self.show_home()
        except Exception as exc:
            messagebox.showerror("الخادم", f"تعذر الاتصال بالخادم:\n{exc}", parent=self)

    def show_home(self):
        self.clear()
        top = tk.Frame(self.body, bg=BG); top.pack(fill="x", padx=28, pady=(24, 12))
        tk.Label(top, text=f"مرحبًا {self.customer_name}", bg=BG, fg=TEXT, font=("Segoe UI", 26, "bold")).pack(side="right")
        tk.Label(top, text="اختر اللعبة أو التطبيق", bg=BG, fg=MUTED, font=("Segoe UI", 12)).pack(side="right", padx=16, pady=(12,0))
        toolbar = tk.Frame(self.body, bg=BG); toolbar.pack(fill="x", padx=28, pady=(4, 14))
        for title, action in [("الألعاب", self.show_games), ("التطبيقات", self.show_apps), ("المتجر", self.show_store), ("الرصيد", self.show_wallet), ("الإعدادات", self.show_settings), ("تسجيل خروج", self.logout_customer)]:
            tk.Button(toolbar, text=title, command=action, bg=CARD2, fg=TEXT, relief="flat", padx=16, pady=9).pack(side="right", padx=5)
        self.show_games(content_parent=self.body, append=True)

    def _panel(self):
        p = tk.Frame(self.body, bg=BG); return p

    def _cards(self, items, title):
        self.clear(); head = tk.Frame(self.body,bg=BG); head.pack(fill="x", padx=28,pady=24); tk.Label(head,text=title,bg=BG,fg=TEXT,font=("Segoe UI",24,"bold")).pack(side="right"); tk.Button(head,text="الرئيسية",command=self.show_home,bg=CARD2,fg=TEXT,relief="flat",padx=16,pady=8).pack(side="left")
        grid = tk.Frame(self.body,bg=BG); grid.pack(fill="both",expand=True,padx=28,pady=4)
        for i,item in enumerate(items):
            card=tk.Frame(grid,bg=CARD,highlightbackground="#233a59",highlightthickness=1); card.grid(row=i//4,column=i%4,padx=8,pady=8,sticky="nsew")
            grid.grid_columnconfigure(i%4,weight=1); grid.grid_rowconfigure(i//4,weight=1)
            tk.Label(card,text=item.get("name",""),bg=CARD,fg=TEXT,font=("Segoe UI",16,"bold")).pack(pady=(32,8))
            tk.Label(card,text=item.get("category",item.get("desc","")),bg=CARD,fg=MUTED).pack()
            cb=item.get("command")
            tk.Button(card,text="فتح",command=cb,bg=ACCENT,fg="#03131c",relief="flat",font=("Segoe UI",10,"bold"),padx=18,pady=7).pack(pady=22)

    def show_games(self, content_parent=None, append=False):
        try: games = requests.get(self.server_url+"/api/v15/client/catalog",timeout=5).json().get("games",[])
        except Exception as exc: messagebox.showerror("الألعاب",str(exc),parent=self); return
        items=[]
        for g in games:
            game=dict(g); game["command"]=lambda gid=g["id"]: self.request_launch(gid); items.append(game)
        if append:
            self._cards_into_existing(items,"الألعاب")
        else: self._cards(items,"الألعاب")

    def _cards_into_existing(self,items,title):
        box=tk.Frame(self.body,bg=BG); box.pack(fill="both",expand=True,padx=28,pady=8)
        tk.Label(box,text=title,bg=BG,fg=TEXT,font=("Segoe UI",18,"bold")).pack(anchor="e",pady=(0,10))
        grid=tk.Frame(box,bg=BG);grid.pack(fill="both",expand=True)
        for i,item in enumerate(items):
            card=tk.Frame(grid,bg=CARD,highlightbackground="#233a59",highlightthickness=1);card.grid(row=i//4,column=i%4,padx=8,pady=8,sticky="nsew");grid.grid_columnconfigure(i%4,weight=1)
            tk.Label(card,text=item["name"],bg=CARD,fg=TEXT,font=("Segoe UI",15,"bold")).pack(pady=(22,5));tk.Label(card,text=item.get("category",""),bg=CARD,fg=MUTED).pack();tk.Button(card,text="تشغيل",command=item["command"],bg=ACCENT,fg="#03131c",relief="flat",padx=18,pady=7).pack(pady=14)

    def show_apps(self):
        try: apps=requests.get(self.server_url+"/api/v15/client/catalog",timeout=5).json().get("apps",[])
        except Exception as exc: messagebox.showerror("التطبيقات",str(exc),parent=self);return
        for a in apps: a["desc"]="Application"; a["command"]=lambda aid=a["id"]: self.request_launch(aid)
        self._cards(apps,"التطبيقات")

    def show_store(self): self._cards([{"name":"مشروبات","desc":"الطلب من المتجر","command":lambda: messagebox.showinfo("المتجر","سيتم ربط المتجر بالخادم في المرحلة التالية.",parent=self)},{"name":"وجبات","desc":"الطلب من المتجر","command":lambda: messagebox.showinfo("المتجر","سيتم ربط المتجر بالخادم في المرحلة التالية.",parent=self)}],"المتجر")
    def show_wallet(self): self._cards([{"name":"الرصيد","desc":"0.00 جنيه","command":lambda: None},{"name":"الوقت","desc":"جلسة نشطة","command":lambda: None}],"الرصيد والوقت")
    def show_settings(self): self._cards([{"name":"الصوت","desc":"إعدادات الصوت","command":lambda: None},{"name":"ملء الشاشة","desc":"Full Screen","command":lambda: self.attributes("-fullscreen",not bool(self.attributes("-fullscreen")))}],"الإعدادات")

    def logout_customer(self):
        try:
            self.agent.cfg["current_customer"] = ""
            self.agent._save()
        except Exception:
            pass
        self.session_token = None
        self.customer_name = ""
        self.show_login()

    def request_launch(self, game_id):
        try:
            r=requests.post(self.server_url+"/api/v15/client/launch",json={"game_id":game_id,"device_id":self.agent.device_id},timeout=5);r.raise_for_status();data=r.json();self.status.configure(text="● BUSY • يتم تشغيل التطبيق",fg=WARNING);messagebox.showinfo("Launch",f"تم إرسال أمر التشغيل: {data.get('game_id')}",parent=self)
        except Exception as exc: messagebox.showerror("Launch",str(exc),parent=self)
