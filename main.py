from fastapi import FastAPI, HTTPException, Form, Request, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import sqlite3
from datetime import datetime
import re
import matplotlib.pyplot as plt
import os
from fastapi.security import OAuth2PasswordBearer
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.authentication import requires, AuthCredentials, AuthenticationBackend, SimpleUser
from starlette.requests import HTTPConnection

# Authentication Backend
class BasicAuthBackend(AuthenticationBackend):
    async def authenticate(self, conn: HTTPConnection):
        token = conn.cookies.get("auth_token")
        if not token:
            return None
        try:
            username, password = token.split(':')
            cursor = sqlite3.connect('ombor.db', check_same_thread=False).cursor()
            cursor.execute("SELECT username, rol FROM foydalanuvchilar WHERE username = ? AND parol = ?", (username, password))
            user = cursor.fetchone()
            if user:
                return AuthCredentials(["authenticated"]), SimpleUser(username)
        except:
            return None

# FastAPI ilovasi
app = FastAPI()
app.add_middleware(AuthenticationMiddleware, backend=BasicAuthBackend())
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
db = sqlite3.connect('ombor.db', check_same_thread=False)
cursor = db.cursor()

# Ma'lumotlar bazasi jadvallarini yaratish
def create_tables():
    cursor.execute('''CREATE TABLE IF NOT EXISTS mahsulotlar
                      (nomi TEXT PRIMARY KEY, miqdori INTEGER, sana TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS ovqatlar
                      (nomi TEXT PRIMARY KEY)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS retseptlar
                      (ovqat_nomi TEXT, ingredient_nomi TEXT, miqdori INTEGER)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS ovqat_berish
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, ovqat_nomi TEXT, sana TEXT, foydalanuvchi TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS foydalanuvchilar
                      (username TEXT PRIMARY KEY, parol TEXT, rol TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS ombor_tarixi
                      (id INTEGER PRIMARY KEY AUTOINCREMENT, mahsulot_nomi TEXT, miqdori INTEGER, 
                       operatsiya TEXT, sana TEXT, foydalanuvchi TEXT)''')
    db.commit()

create_tables()

# Foydalanuvchilarni avtomatik qo'shish
def initialize_default_users():
    default_users = [
        ('admin1', 'admin123', 'admin'),
        ('oshpaz1', 'oshpaz123', 'oshpaz'),
        ('menejer1', 'menejer123', 'menejer')
    ]
    for user in default_users:
        cursor.execute("INSERT OR IGNORE INTO foydalanuvchilar VALUES (?, ?, ?)", user)
    db.commit()

initialize_default_users()

# Validatsiya funksiyasi
def validate_input(nomi, miqdori, sana):
    if not nomi or not miqdori or not sana:
        raise ValueError("Barcha maydonlar to‘ldirilishi shart")
    if not re.match(r"^[a-zA-Z0-9\s]+$", nomi):
        raise ValueError("Nomi faqat harflar va raqamlardan iborat bo‘lishi kerak")
    miqdori = int(miqdori)
    if miqdori < 0:
        raise ValueError("Miqdor manfiy bo‘lishi mumkin emas")
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", sana):
        raise ValueError("Sana YYYY-MM-DD formatida bo‘lishi kerak")
    return nomi, miqdori, sana

# Foydalanuvchi autentifikatsiyasi
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

def get_current_user(request: Request):
    if not hasattr(request, 'user') or not request.user.is_authenticated:
        return RedirectResponse(url="/login", status_code=303)
    cursor = sqlite3.connect('ombor.db', check_same_thread=False).cursor()
    cursor.execute("SELECT rol FROM foydalanuvchilar WHERE username = ?", (request.user.display_name,))
    rol = cursor.fetchone()
    return {"username": request.user.display_name, "rol": rol[0] if rol else "guest"}

# Login sahifasi
@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return templates.TemplateResponse("login.html", {"request": request, "messages": []})

@app.post("/login", response_class=HTMLResponse)
async def login(request: Request, username: str = Form(...), password: str = Form(...)):
    cursor = sqlite3.connect('ombor.db', check_same_thread=False).cursor()
    cursor.execute("SELECT rol FROM foydalanuvchilar WHERE username = ? AND parol = ?", (username, password))
    result = cursor.fetchone()
    if result:
        token = f"{username}:{password}"
        response = templates.TemplateResponse("index.html", {"request": request, "username": username, "rol": result[0]})
        response.set_cookie(key="auth_token", value=token, httponly=True)
        return response
    return templates.TemplateResponse("login.html", {"request": request, "messages": ["Noto‘g‘ri username yoki parol"]})

# Bosh sahifa
@app.get("/", response_class=HTMLResponse)
async def root(request: Request, user: dict = Depends(get_current_user)):
    return templates.TemplateResponse("index.html", {"request": request, "username": user["username"], "rol": user["rol"]})

# Mahsulot qo'shish formasi uchun GET (slash bilan va slashsiz)
@app.get("/mahsulot_qoshish", response_class=HTMLResponse)
@app.get("/mahsulot_qoshish/", response_class=HTMLResponse)
async def mahsulot_qoshish_form(request: Request, user: dict = Depends(get_current_user)):
    if user["rol"] not in ["admin", "menejer"]:
        raise HTTPException(status_code=403, detail="Ruxsat yo‘q")
    return templates.TemplateResponse("mahsulot_qoshish.html", {"request": request, "messages": []})

# Mahsulot qo'shish uchun POST (slash bilan va slashsiz)
@app.post("/mahsulot_qoshish/", response_class=HTMLResponse)
@app.post("/mahsulot_qoshish", response_class=HTMLResponse)
async def mahsulot_qoshish(request: Request, nomi: str = Form(...), miqdori: str = Form(...), sana: str = Form(...), user: dict = Depends(get_current_user)):
    if user["rol"] not in ["admin", "menejer"]:
        raise HTTPException(status_code=403, detail="Ruxsat yo‘q")
    try:
        nomi, miqdori, sana = validate_input(nomi, miqdori, sana)
        cursor.execute("INSERT OR REPLACE INTO mahsulotlar VALUES (?, ?, ?)", (nomi, miqdori, sana))
        cursor.execute("INSERT INTO ombor_tarixi (mahsulot_nomi, miqdori, operatsiya, sana, foydalanuvchi) "
                       "VALUES (?, ?, ?, ?, ?)", (nomi, miqdori, "qo'shish", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user["username"]))
        db.commit()
        print(f"Qo‘shildi: {nomi}, {miqdori}, {sana}")  # Debugging uchun
        return templates.TemplateResponse("mahsulot_qoshish.html", {"request": request, "message": f"{nomi} omborga qo‘shildi", "messages": []})
    except ValueError as e:
        print(f"Xatolik: {str(e)}")  # Debugging uchun
        return templates.TemplateResponse("mahsulot_qoshish.html", {"request": request, "messages": [str(e)]})

# Ovqat qo'shish
@app.get("/ovqat_qoshish", response_class=HTMLResponse)
async def ovqat_qoshish_form(request: Request, user: dict = Depends(get_current_user)):
    if user["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Ruxsat yo‘q")
    return templates.TemplateResponse("ovqat_qoshish.html", {"request": request, "messages": []})

@app.post("/ovqat_qoshish/", response_class=HTMLResponse)
async def ovqat_qoshish(request: Request, ovqat_nomi: str = Form(...), retsept: str = Form(...), user: dict = Depends(get_current_user)):
    if user["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Ruxsat yo‘q")
    try:
        if not ovqat_nomi.strip():
            raise ValueError("Ovqat nomi kiritilishi shart")
        if not re.match(r"^[a-zA-Z0-9\s]+$", ovqat_nomi):
            raise ValueError("Ovqat nomi faqat harflar va raqamlardan iborat bo‘lishi kerak")
        
        retsept_dict = {}
        for line in retsept.splitlines():
            line = line.strip()
            if not line:
                continue
            if ":" not in line:
                raise ValueError(f"Noto‘g‘ri format: '{line}'. To‘g‘ri format: nomi:miqdori")
            parts = line.split(":")
            if len(parts) != 2:
                raise ValueError(f"Noto‘g‘ri format: '{line}'. To‘g‘ri format: nomi:miqdori")
            nomi, miqdori = parts
            nomi = nomi.strip()
            miqdori = miqdori.strip()
            if not nomi or not miqdori:
                raise ValueError(f"Ingredient nomi va miqdori bo‘sh bo‘lmasligi kerak: '{line}'")
            if not re.match(r"^[a-zA-Z0-9\s]+$", nomi):
                raise ValueError(f"Ingredient nomi faqat harflar va raqamlardan iborat bo‘lishi kerak: '{nomi}'")
            miqdori = int(miqdori)
            if miqdori <= 0:
                raise ValueError(f"{nomi} miqdori musbat bo‘lishi kerak")
            retsept_dict[nomi] = miqdori
        
        if not retsept_dict:
            raise ValueError("Kamida bitta ingredient kiritilishi kerak")
        
        cursor.execute("INSERT OR REPLACE INTO ovqatlar VALUES (?)", (ovqat_nomi,))
        for ingredient, miqdori in retsept_dict.items():
            cursor.execute("INSERT OR REPLACE INTO retseptlar VALUES (?, ?, ?)", (ovqat_nomi, ingredient, miqdori))
        db.commit()
        return templates.TemplateResponse("ovqat_qoshish.html", {"request": request, "message": f"{ovqat_nomi} ovqat ro‘yxatiga qo‘shildi", "messages": []})
    except ValueError as e:
        return templates.TemplateResponse("ovqat_qoshish.html", {"request": request, "messages": [str(e)]})

# Ovqat berish
@app.get("/ovqat_berish", response_class=HTMLResponse)
async def ovqat_berish_form(request: Request, user: dict = Depends(get_current_user)):
    if user["rol"] not in ["admin", "oshpaz"]:
        raise HTTPException(status_code=403, detail="Ruxsat yo‘q")
    cursor.execute("SELECT nomi FROM ovqatlar")
    ovqatlar = [row[0] for row in cursor.fetchall()]
    return templates.TemplateResponse("ovqat_berish.html", {"request": request, "messages": [], "ovqatlar": ovqatlar})

@app.post("/ovqat_berish/", response_class=HTMLResponse)
async def ovqat_berish(request: Request, ovqat_nomi: str = Form(...), user: dict = Depends(get_current_user)):
    if user["rol"] not in ["admin", "oshpaz"]:
        raise HTTPException(status_code=403, detail="Ruxsat yo‘q")
    cursor.execute("SELECT nomi FROM ovqatlar")
    ovqatlar = [row[0] for row in cursor.fetchall()]
    try:
        cursor.execute("SELECT ingredient_nomi, miqdori FROM retseptlar WHERE ovqat_nomi = ?", (ovqat_nomi,))
        retsept = {row[0]: row[1] for row in cursor.fetchall()}
        if not retsept:
            raise ValueError(f"{ovqat_nomi} uchun retsept topilmadi")
        cursor.execute("SELECT nomi, miqdori FROM mahsulotlar")
        ombor = {row[0]: row[1] for row in cursor.fetchall()}
        min_porsiya = float('inf')
        yetishmaydiganlar = []
        for ingredient, kerakli_miqdor in retsept.items():
            if ingredient not in ombor:
                yetishmaydiganlar.append(f"'{ingredient}' omborda yo‘q")
                continue
            porsiya = ombor[ingredient] // kerakli_miqdor
            if ombor[ingredient] < kerakli_miqdor:
                yetishmaydiganlar.append(f"'{ingredient}' yetarli emas: {ombor[ingredient]} gramm bor, {kerakli_miqdor} gramm kerak")
            min_porsiya = min(min_porsiya, porsiya)
        if yetishmaydiganlar:
            return templates.TemplateResponse("ovqat_berish.html", {"request": request, "messages": yetishmaydiganlar, "ovqatlar": ovqatlar})
        if min_porsiya == 0:
            return templates.TemplateResponse("ovqat_berish.html", {"request": request, "messages": ["Ingredientlar yetarli emas!"], "ovqatlar": ovqatlar})
        for ingredient, miqdori in retsept.items():
            cursor.execute("UPDATE mahsulotlar SET miqdori = miqdori - ? WHERE nomi = ?", (miqdori, ingredient))
            cursor.execute("INSERT INTO ombor_tarixi (mahsulot_nomi, miqdori, operatsiya, sana, foydalanuvchi) "
                          "VALUES (?, ?, ?, ?, ?)", (ingredient, miqdori, "ayirish", datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user["username"]))
        cursor.execute("INSERT INTO ovqat_berish (ovqat_nomi, sana, foydalanuvchi) VALUES (?, ?, ?)",
                      (ovqat_nomi, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user["username"]))
        db.commit()
        return templates.TemplateResponse("ovqat_berish.html", {"request": request, "message": f"{ovqat_nomi} uchun 1 porsiya berildi", "messages": [], "ovqatlar": ovqatlar})
    except sqlite3.Error as e:
        return templates.TemplateResponse("ovqat_berish.html", {"request": request, "messages": [f"Ma'lumotlar bazasi xatosi: {str(e)}"], "ovqatlar": ovqatlar})

# Hisobot tayyorlash
@app.get("/hisobot", response_class=HTMLResponse)
async def hisobot_form(request: Request, user: dict = Depends(get_current_user)):
    if user["rol"] not in ["admin", "menejer"]:
        raise HTTPException(status_code=403, detail="Ruxsat yo‘q")
    try:
        cursor.execute("SELECT ovqat_nomi, COUNT(*) FROM ovqat_berish GROUP BY ovqat_nomi")
        hisobot = {row[0]: row[1] for row in cursor.fetchall()}
        if not hisobot:
            raise ValueError("Hisobot uchun ma'lumotlar yo‘q")
        plt.figure(figsize=(10, 6))
        plt.bar(hisobot.keys(), hisobot.values(), color='skyblue')
        plt.title("Oylik Ovqat Berish Hisoboti", fontsize=14)
        plt.xlabel("Ovqat Nomi", fontsize=12)
        plt.ylabel("Porsiyalar Soni", fontsize=12)
        plt.xticks(rotation=45)
        plt.tight_layout()
        plt.savefig("static/hisobot.png")
        plt.close()
        return templates.TemplateResponse("hisobot.html", {"request": request, "image": "/static/hisobot.png"})
    except ValueError as e:
        return templates.TemplateResponse("hisobot.html", {"request": request, "messages": [str(e)]})

# Ogohlantirishlar
@app.get("/ogohlantirishlar", response_class=HTMLResponse)
async def ogohlantirishlar_form(request: Request, user: dict = Depends(get_current_user)):
    if user["rol"] not in ["admin", "menejer"]:
        raise HTTPException(status_code=403, detail="Ruxsat yo‘q")
    try:
        cursor.execute("SELECT nomi, miqdori FROM mahsulotlar")
        ogohlantirishlar = [f"{row[0]} zaxirasi kam: {row[1]} gramm" for row in cursor.fetchall() if row[1] < 100]
        return templates.TemplateResponse("ogohlantirishlar.html", {"request": request, "ogohlantirishlar": ogohlantirishlar})
    except sqlite3.Error as e:
        return templates.TemplateResponse("ogohlantirishlar.html", {"request": request, "messages": [f"Ma'lumotlar bazasi xatosi: {str(e)}"]})

# Ombor tarixi
@app.get("/ombor_tarixi", response_class=HTMLResponse)
async def ombor_tarixi_form(request: Request, user: dict = Depends(get_current_user)):
    if user["rol"] not in ["admin", "menejer"]:
        raise HTTPException(status_code=403, detail="Ruxsat yo‘q")
    try:
        cursor.execute("SELECT id, mahsulot_nomi, miqdori, operatsiya, sana, foydalanuvchi FROM ombor_tarixi")
        tarix = cursor.fetchall()
        return templates.TemplateResponse("ombor_tarixi.html", {"request": request, "tarix": tarix})
    except sqlite3.Error as e:
        return templates.TemplateResponse("ombor_tarixi.html", {"request": request, "messages": [f"Ma'lumotlar bazasi xatosi: {str(e)}"]})

# Foydalanuvchi qo'shish
@app.get("/foydalanuvchi_qoshish", response_class=HTMLResponse)
async def foydalanuvchi_qoshish_form(request: Request, user: dict = Depends(get_current_user)):
    if user["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Ruxsat yo‘q")
    return templates.TemplateResponse("foydalanuvchi_qoshish.html", {"request": request, "messages": []})

@app.post("/foydalanuvchi_qoshish/", response_class=HTMLResponse)
async def foydalanuvchi_qoshish(request: Request, username: str = Form(...), parol: str = Form(...), rol: str = Form(...), user: dict = Depends(get_current_user)):
    if user["rol"] != "admin":
        raise HTTPException(status_code=403, detail="Ruxsat yo‘q")
    try:
        if not re.match(r"^[a-zA-Z0-9]+$", username):
            raise ValueError("Username faqat harflar va raqamlardan iborat bo‘lishi kerak")
        if len(parol) < 6:
            raise ValueError("Parol kamida 6 belgi bo‘lishi kerak")
        if rol not in ["admin", "oshpaz", "menejer"]:
            raise ValueError("Noto‘g‘ri rol")
        cursor.execute("INSERT OR REPLACE INTO foydalanuvchilar VALUES (?, ?, ?)", (username, parol, rol))
        db.commit()
        return templates.TemplateResponse("foydalanuvchi_qoshish.html", {"request": request, "message": f"{username} foydalanuvchi qo‘shildi", "messages": []})
    except ValueError as e:
        return templates.TemplateResponse("foydalanuvchi_qoshish.html", {"request": request, "messages": [str(e)]})