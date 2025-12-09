# -*- coding: utf-8 -*-
# main.py

import os
import html
import sys
sys.stdout.reconfigure(encoding='utf-8')
import json
import asyncio
import warnings
from datetime import datetime, timedelta
from enum import Enum
import re

import aiohttp
from babel.numbers import format_decimal
import phonenumbers
from phonenumbers import geocoder as ph_geo

from pyrogram import Client, filters
from pyrogram.types import (
    ReplyKeyboardMarkup,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from pyrogram.errors import SessionPasswordNeeded, PhoneCodeInvalid
from pyrogram.enums import ParseMode
from khayyam import JalaliDatetime

warnings.filterwarnings("ignore")

# ---------------- CONFIG ----------------
API_ID = 32723346
API_HASH = "00b5473e6d13906442e223145510676e"
BOT_TOKEN = "8599566996:AAG26MIEvtBGsoEEcr_jMmwhvPnGWR6u0KY0"

CHANNEL_LOG = "@SHAH_SELF"        # لاگ استارت‌ها و لاگ مدیریتی
CHANNEL_SALES_LOG = "@SHAH_SELF"  # لاگ فروش‌ها و شارژها
ADMINS = [8324661572]                  # آیدی عددی ادمین‌ها

USERS_FILE = "users.json"
ACCOUNTS_FILE = "accounts.json"

# >>> کانال جویین اجباری
FORCE_CHANNEL = "@SHAH_SELF"      # کانالی که کاربر باید عضو شود

# ---------------- Client ----------------
app = Client("bot_full", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)


# ========================== FILE STORAGE ==========================

class FileStorage:
    @staticmethod
    def ensure_file(path: str, default: dict):
        if not os.path.exists(path):
            with open(path, "w", encoding="utf-8") as f:
                json.dump(default, f, ensure_ascii=False, indent=4)

    @staticmethod
    def load(path: str) -> dict:
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    @staticmethod
    def save(path: str, data: dict):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=4)


# ========================== USER MANAGER ==========================

class UserManager:
    def __init__(self, path: str):
        self.path = path
        FileStorage.ensure_file(self.path, {})
        self.users = FileStorage.load(self.path)

    def ensure_user(self, uid: int):
        s = str(uid)
        if s not in self.users:
            self.users[s] = {
                "register": datetime.now().isoformat(),
                "last": datetime.now().isoformat(),
                "orders": 0,
                "referrals": 0,
                "balance": 0,
                "blocked": False,
                "spent": 0,
                "username": ""
            }
            self.save()

    def get(self, uid: int) -> dict:
        self.ensure_user(uid)
        return self.users[str(uid)]

    def save(self):
        FileStorage.save(self.path, self.users)

    def is_blocked(self, uid: int) -> bool:
        data = self.users.get(str(uid))
        if not data:
            return False
        return data.get("blocked", False)

    def set_blocked(self, uid: int, value: bool):
        self.ensure_user(uid)
        self.users[str(uid)]["blocked"] = value
        self.users[str(uid)]["last"] = datetime.now().isoformat()
        self.save()

    def update_username(self, uid: int, username):
        self.ensure_user(uid)
        self.users[str(uid)]["username"] = username or self.users[str(uid)].get("username", "")
        self.users[str(uid)]["last"] = datetime.now().isoformat()
        self.save()

    def add_balance(self, uid: int, amount: int):
        self.ensure_user(uid)
        self.users[str(uid)]["balance"] = self.users[str(uid)].get("balance", 0) + amount
        self.users[str(uid)]["last"] = datetime.now().isoformat()
        self.save()
        return self.users[str(uid)]["balance"]

    def dec_balance(self, uid: int, amount: int):
        self.ensure_user(uid)
        self.users[str(uid)]["balance"] = max(0, self.users[str(uid)].get("balance", 0) - amount)
        self.users[str(uid)]["last"] = datetime.now().isoformat()
        self.save()
        return self.users[str(uid)]["balance"]

    def add_order(self, uid: int, price: int):
        self.ensure_user(uid)
        u = self.users[str(uid)]
        u["orders"] = u.get("orders", 0) + 1
        u["spent"] = u.get("spent", 0) + price
        u["last"] = datetime.now().isoformat()
        self.save()

    def all_users(self):
        return self.users


# ========================== ACCOUNTS MANAGER ==========================

sold_sessions: dict[str, str] = {}


class AccountManager:
    """
    accounts[phone] = {
        "price": int,
        "session_string": str,
        "available": bool,
        "owner_id": int | None,
        "created_at": iso,
        "sold_to": int | None,
        "sold_at": iso | None,
        "country": str | None,
        "tag": str | None
    }
    """
    def __init__(self, path: str):
        self.path = path
        FileStorage.ensure_file(self.path, {})
        self.accounts = FileStorage.load(self.path)

    def save(self):
        FileStorage.save(self.path, self.accounts)

    def add_account(self, phone: str, price: int, session: str,
                    owner_id=None, country=None, tag=None):
        self.accounts[phone] = {
            "price": price,
            "session_string": session,
            "available": True,
            "owner_id": owner_id,
            "created_at": datetime.now().isoformat(),
            "sold_to": None,
            "sold_at": None,
            "country": country,
            "tag": tag
        }
        self.save()

    def set_sold(self, phone: str, buyer_id: int):
        if phone not in self.accounts:
            return
        session = self.accounts[phone].get("session_string")
        if session:
            sold_sessions[phone] = session
            self.accounts[phone]["session_string"] = ""
        self.accounts[phone]["available"] = False
        self.accounts[phone]["sold_to"] = buyer_id
        self.accounts[phone]["sold_at"] = datetime.now().isoformat()
        self.save()

    def get_available_accounts(self):
        return {k: v for k, v in self.accounts.items() if v.get("available")}

    def list_all(self):
        return self.accounts

    def exists(self, phone: str) -> bool:
        return phone in self.accounts

    def get(self, phone: str):
        return self.accounts.get(phone)

    def set_price(self, phone: str, price: int):
        if phone not in self.accounts:
            return False
        self.accounts[phone]["price"] = price
        self.save()
        return True

    def delete(self, phone: str):
        if phone in self.accounts:
            self.accounts.pop(phone)
            sold_sessions.pop(phone, None)
            self.save()
            return True
        return False

    def clear_session(self, phone: str):
        if phone in self.accounts:
            self.accounts[phone]["session_string"] = ""
        if phone in sold_sessions:
            sold_sessions.pop(phone, None)
        self.save()

    def stats(self):
        total = len(self.accounts)
        available = sum(1 for a in self.accounts.values() if a.get("available"))
        sold = total - available
        total_income = sum(a.get("price", 0) for a in self.accounts.values() if not a.get("available"))
        return {
            "total": total,
            "available": available,
            "sold": sold,
            "income": total_income
        }


# ========================== STATE MANAGER ==========================

class StateMode(str, Enum):
    NONE = "none"
    ADD_ADMIN = "add_admin"
    REMOVE_ADMIN = "remove_admin"
    INC_BALANCE = "inc"
    DEC_BALANCE = "dec"
    BLOCK = "block"
    UNBLOCK = "unblock"
    SEARCH = "search"
    BROADCAST = "broadcast"
    ADD_ACCOUNT_PHONE = "add_account_phone"
    ADD_ACCOUNT_CODE = "add_account_code"
    ADD_ACCOUNT_PASSWORD = "add_account_password"
    ADD_ACCOUNT_PRICE = "add_account_price"
    EDIT_ACCOUNT_PRICE = "edit_account_price"
    DELETE_ACCOUNT = "delete_account"
    BUY_ACCOUNT = "buy_account"
    DELETE_SCAM_ACCOUNT = "delete_scam_account"   # جدید برای حذف اسکم


class StateManager:
    def __init__(self):
        self.wait = {}             # uid -> StateMode
        self.temp_add_account = {} # uid -> dict

    def set_mode(self, uid: int, mode):
        if mode is None:
            self.wait.pop(uid, None)
        else:
            self.wait[uid] = mode

    def get_mode(self, uid: int):
        return self.wait.get(uid)

    def clear_all_for_user(self, uid: int):
        self.wait.pop(uid, None)
        self.temp_add_account.pop(uid, None)


# ========================== GLOBALS / UTILS ==========================

FileStorage.ensure_file(USERS_FILE, {})
FileStorage.ensure_file(ACCOUNTS_FILE, {})

users = UserManager(USERS_FILE)
accounts = AccountManager(ACCOUNTS_FILE)
state = StateManager()

pending_purchases: dict[int, dict] = {}
user_panels: dict[int, list[tuple[int, int]]] = {}  # برای پاک کردن پنل‌های قبلی

def register_user_panel(uid: int, chat_id: int, msg_id: int):
    lst = user_panels.get(uid, [])
    lst.append((chat_id, msg_id))
    user_panels[uid] = lst

async def delete_user_panels(client: Client, uid: int):
    msgs = user_panels.pop(uid, [])
    for chat_id, msg_id in msgs:
        try:
            await client.delete_messages(chat_id, msg_id)
        except Exception:
            pass


def main_keyboard(uid: int):
    rows = [
        ["🛍 خرید شماره مجازی", "🪪 فروش شماره به ربات"],
        ["📞 پشتیبانی", "ℹ️ اطلاعات حساب"],
        ["📘 راهنما", "🤝 دریافت نمایندگی"],
        ["📊 لیست قیمت‌ها", "💳 افزایش موجودی"],
    ]
    if uid in ADMINS:
        rows.append(["🔐 پنل مدیریت"])
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

back_btn = ReplyKeyboardMarkup([["🔙 بازگشت"]], resize_keyboard=True)

admin_markup = ReplyKeyboardMarkup(
    [
        ["➕ افزودن مدیر", "➖ حذف مدیر"],
        ["💰 افزایش موجودی", "📉 کاهش موجودی"],
        ["🚫 بلاک کاربر", "♻ آنبلاک کاربر"],
        ["🔍 جستجوی کاربر", "📢 ارسال همگانی"],
        ["➕ افزودن اکانت", "📋 لیست اکانت‌ها"],
        ["✏️ ویرایش قیمت اکانت", "🗑 حذف اکانت"],
        ["⚠️ افزودن اکانت اسکم", "🧹 حذف اکانت اسکم"],
        ["📊 آمار فروش", "👥 آمار کاربران"],
        ["🔙 بازگشت"],
    ],
    resize_keyboard=True
)

def is_admin(uid: int) -> bool:
    return uid in ADMINS

def is_blocked(uid: int) -> bool:
    return users.is_blocked(uid)

def mask_phone(phone: str) -> str:
    """
    در صورت نیاز می‌توان از این تابع برای ماسک کردن شماره استفاده کرد.
    فعلاً در لیست‌ها اصلاً شماره نمایش داده نمی‌شود (کاملاً مخفی است).
    """
    if len(phone) <= 4:
        return "****"
    return "****" + phone[-4:]


# >>> جویین اجباری: چک عضویت کاربر در کانال
async def is_user_in_force_channel(client: Client, user_id: int) -> bool:
    try:
        member = await client.get_chat_member(FORCE_CHANNEL, user_id)
        # status: "creator", "administrator", "member", "restricted", "left", "kicked"
        return member.status not in ("left", "kicked")
    except Exception:
        # اگر ربات دسترسی نداشته باشه یا هر اروری، به عنوان عضو نبودن در نظر می‌گیریم
        return False

# >>> متن و کیبورد شیشه‌ای جویین اجباری
def get_force_join_text() -> str:
    return (
        "🔒 دسترسی کامل به ربات فقط برای اعضای کانال فعال است.\n\n"
        "برای استفاده از تمام قابلیت‌های ربات، ابتدا در کانال زیر عضو شو 👇\n\n"
        "بعد از عضویت، روی دکمه «✅ بررسی عضویت» بزن تا درجا منوی اصلی برات باز بشه 🔥"
    )

def force_join_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📢 عضویت در کانال",
                    url=f"https://t.me/{FORCE_CHANNEL.lstrip('@')}",
                )
            ],
            [
                InlineKeyboardButton(
                    "✅ بررسی عضویت",
                    callback_data="checkjoin"
                )
            ],
        ]
    )


# =============== COUNTRY DETECTION (با پرچم کنار اسم کشور) ===============

COUNTRY_MAP = {
    "+98": "ایران 🇮🇷",
    "+1": "آمریکا / کانادا 🇺🇸",
    "+90": "ترکیه 🇹🇷",
    "+44": "انگلستان 🇬🇧",
    "+49": "آلمان 🇩🇪",
    "+33": "فرانسه 🇫🇷",
    "+39": "ایتالیا 🇮🇹",
    "+34": "اسپانیا 🇪🇸",
    "+31": "هلند 🇳🇱",
    "+32": "بلژیک 🇧🇪",
    "+46": "سوئد 🇸🇪",
    "+47": "نروژ 🇳🇴",
    "+45": "دانمارک 🇩🇰",
    "+86": "چین 🇨🇳",
    "+81": "ژاپن 🇯🇵",
    "+91": "هند 🇮🇳",
    "+63": "فیلیپین 🇵🇭",
    "+60": "مالزی 🇲🇾",
    "+61": "استرالیا 🇦🇺",
    "+971": "امارات 🇦🇪",
    "+966": "عربستان 🇸🇦",
}

def region_to_flag(region: str) -> str:
    try:
        return ''.join(chr(ord('🇦') + ord(c) - ord('A')) for c in region)
    except Exception:
        return ""

def detect_country(phone: str) -> str:
    # ابتدا از لیست خودمان
    for prefix in sorted(COUNTRY_MAP.keys(), key=len, reverse=True):
        if phone.startswith(prefix):
            return COUNTRY_MAP[prefix]

    # بعد phonenumbers
    try:
        num = phonenumbers.parse(phone, None)
        region = ph_geo.region_code_for_number(num)  # مثلا 'DE'
        if region:
            flag = region_to_flag(region)
            return f"{region} {flag}"
    except Exception:
        pass

    # اگر هیچ‌کدام، یه چیز کلی
    return "سایر کشورها 🌍"


# ========================== COMMON HELPERS ==========================

def is_scam_tag(tag: str | None) -> bool:
    if not tag:
        return False
    t = tag.lower()
    return "scam" in t or "اسکم" in t

def extract_code_from_text(text: str) -> str | None:
    if not text:
        return None
    m = re.search(r"\b(\d{4,8})\b", text)
    return m.group(1) if m else None

def dot_code(code: str) -> str:
    return ".".join(list(code))

def get_session_for_phone(phone: str) -> str | None:
    acc = accounts.get(phone)
    if not acc:
        return None
    session = acc.get("session_string") or sold_sessions.get(phone)
    return session or None


# ---- گروه‌بندی اکانت‌های موجود بر اساس کشور (برای لیست قیمت ساده) ----
def group_available_by_country():
    available_accounts = accounts.get_available_accounts()
    grouped = {}
    for phone, data in available_accounts.items():
        country = data.get("country") or detect_country(phone)
        price = data.get("price", 0)
        scam = is_scam_tag(data.get("tag"))
        if country not in grouped:
            grouped[country] = {
                "count": 0,
                "min_price": price,
                "scam": False,
            }
        grouped[country]["count"] += 1
        if price < grouped[country]["min_price"]:
            grouped[country]["min_price"] = price
        if scam:
            grouped[country]["scam"] = True
    return grouped

def build_price_keyboard(grouped: dict) -> InlineKeyboardMarkup:
    """
    لیست کشورها برای «📊 لیست قیمت‌ها»
    روی هر ردیف کلیک شود، لیست اکانت‌های همان کشور (بدون نمایش شماره) باز می‌شود.
    """
    rows = [
        [
            InlineKeyboardButton("🌍 Country", callback_data="noop:hdr1"),
            InlineKeyboardButton("Status 📊", callback_data="noop:hdr2"),
            InlineKeyboardButton("Price 💰", callback_data="noop:hdr3"),
            InlineKeyboardButton("Qty 📦", callback_data="noop:hdr4"),
            InlineKeyboardButton("Scam ⚠️", callback_data="noop:hdr5"),
        ]
    ]
    for country, info in sorted(grouped.items(), key=lambda x: x[0]):
        price_str = f"{info['min_price']:,}"
        status_text = "Available ✅"
        qty_text = f"{info['count']} عدد"
        scam_text = "Yes" if info["scam"] else "No"
        cb = f"prlist:{country}"
        rows.append(
            [
                InlineKeyboardButton(country, callback_data=cb),
                InlineKeyboardButton(status_text, callback_data=cb),
                InlineKeyboardButton(price_str, callback_data=cb),
                InlineKeyboardButton(qty_text, callback_data=cb),
                InlineKeyboardButton(scam_text, callback_data=cb),
            ]
        )
    return InlineKeyboardMarkup(rows)

# ---------------- کشورها برای خرید (مرحله اول) ----------------
def build_buy_keyboard(grouped: dict) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton("🌍 Country", callback_data="noop:bhdr1"),
            InlineKeyboardButton("Status 📊", callback_data="noop:bhdr2"),
            InlineKeyboardButton("Price 💰", callback_data="noop:bhdr3"),
            InlineKeyboardButton("Qty 📦", callback_data="noop:bhdr4"),
            InlineKeyboardButton("Scam ⚠️", callback_data="noop:bhdr5"),
        ]
    ]
    for country, info in sorted(grouped.items(), key=lambda x: x[0]):
        price_str = f"{info['min_price']:,}"
        status_text = "Available ✅"
        qty_text = f"{info['count']} عدد"
        scam_text = "Yes" if info["scam"] else "No"
        cb = f"buylist:{country}"
        rows.append(
            [
                InlineKeyboardButton(country, callback_data=cb),
                InlineKeyboardButton(status_text, callback_data=cb),
                InlineKeyboardButton(price_str, callback_data=cb),
                InlineKeyboardButton(qty_text, callback_data=cb),
                InlineKeyboardButton(scam_text, callback_data=cb),
            ]
        )

    rows.append(
        [InlineKeyboardButton("🔙 بازگشت به منوی اصلی", callback_data="buyback:main")]
    )
    return InlineKeyboardMarkup(rows)

# ---------------- لیست شماره‌های یک کشور برای خرید (با صفحه‌بندی) ----------------
def build_country_accounts_keyboard(country: str, page: int = 0, per_page: int = 100) -> InlineKeyboardMarkup:
    """
    این تابع *همه* اکانت‌های یک کشور را نشان می‌دهد، ولی شماره‌ها را
    قبل از خرید به صورت کامل مخفی می‌کند.
    per_page = 100 یعنی حتی اگر ۱۰۰ تا شماره هم باشد، همه در همان صفحه نمایش داده می‌شوند.
    """
    available_accounts = accounts.get_available_accounts()
    same_country = [
        (phone, data)
        for phone, data in available_accounts.items()
        if (data.get("country") or detect_country(phone)) == country
    ]

    same_country.sort(key=lambda x: (x[1].get("price", 0), x[0]))

    total = len(same_country)
    start = page * per_page
    end = start + per_page
    page_items = same_country[start:end]

    rows = [
        [InlineKeyboardButton(f"📋 لیست اکانت‌های {country} | تعداد: {total}", callback_data="noop:head")]
    ]

    for idx, (phone, data) in enumerate(page_items, start=start + 1):
        price = data.get("price", 0)
        scam = is_scam_tag(data.get("tag"))
        scam_text = "⚠️ اسکم" if scam else "✅ نرمال"
        btn_text = f"اکانت شماره {idx} | {price:,} تومان | {scam_text}"
        rows.append(
            [InlineKeyboardButton(btn_text, callback_data=f"buyselect:{phone}")]
        )

    nav_row = []
    if start > 0:
        nav_row.append(InlineKeyboardButton("⬅️ صفحه قبل", callback_data=f"page:{country}|{page-1}"))
    if end < total:
        nav_row.append(InlineKeyboardButton("صفحه بعد ➡️", callback_data=f"page:{country}|{page+1}"))
    if nav_row:
        rows.append(nav_row)

    rows.append(
        [InlineKeyboardButton("🔙 بازگشت به لیست کشورها", callback_data="buyback:main")]
    )

    return InlineKeyboardMarkup(rows)

# ---------------- لیست شماره‌های یک کشور برای «📊 لیست قیمت‌ها» ----------------
def build_country_price_list_keyboard(country: str, page: int = 0, per_page: int = 10) -> InlineKeyboardMarkup:
    """
    این لیست فقط برای نمایش قیمت‌ها در بخش «📊 لیست قیمت‌ها» است.
    شماره‌ها کاملاً مخفی هستند و فقط قیمت و وضعیت نمایش داده می‌شود.
    """
    available_accounts = accounts.get_available_accounts()
    same_country = [
        (phone, data)
        for phone, data in available_accounts.items()
        if (data.get("country") or detect_country(phone)) == country
    ]

    same_country.sort(key=lambda x: (x[1].get("price", 0), x[0]))

    total = len(same_country)
    start = page * per_page
    end = start + per_page
    page_items = same_country[start:end]

    rows = [
        [InlineKeyboardButton(f"📋 لیست قیمت اکانت‌های {country} | تعداد: {total}", callback_data="noop:prhead")]
    ]

    for idx, (phone, data) in enumerate(page_items, start=start + 1):
        price = data.get("price", 0)
        scam = is_scam_tag(data.get("tag"))
        scam_text = "⚠️ اسکم" if scam else "✅ نرمال"
        btn_text = f"اکانت شماره {idx} | {price:,} تومان | {scam_text}"
        rows.append(
            [InlineKeyboardButton(btn_text, callback_data="noop:pracc")]
        )

    nav_row = []
    if start > 0:
        nav_row.append(InlineKeyboardButton("⬅️ صفحه قبل", callback_data=f"prpage:{country}|{page-1}"))
    if end < total:
        nav_row.append(InlineKeyboardButton("صفحه بعد ➡️", callback_data=f"prpage:{country}|{page+1}"))
    if nav_row:
        rows.append(nav_row)

    rows.append(
        [InlineKeyboardButton("🔙 بازگشت به لیست کشورها", callback_data="prback:main")]
    )

    return InlineKeyboardMarkup(rows)


# ========================== لاگ‌های مدیریتی پیشرفته ==========================

async def send_admin_log_text(text: str,
                              target_id: int | None = None,
                              target_username: str | None = None):
    """
    ارسال لاگ مدیریتی به کانال با دکمه‌های 🆔 و 🌐
    target_id : کسی که دکمه‌ها به سمت او برود (مثلا کاربری که براش موجودی زدی)
    """
    reply_markup = None
    if target_id is not None:
        btns = [
            [
                InlineKeyboardButton("🆔 عددی", url=f"tg://user?id={target_id}"),
                InlineKeyboardButton(
                    f"🌐 @{target_username}" if target_username else "🌐 بدون یوزرنیم",
                    url=f"https://t.me/{target_username}" if target_username else "https://t.me/"
                ),
            ]
        ]
        reply_markup = InlineKeyboardMarkup(btns)

    try:
        await app.send_message(
            CHANNEL_LOG,
            text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=reply_markup
        )
    except Exception:
        pass


# ========================== TRON TOPUP (شارژ خودکار + دکمه برسی) ==========================

TRX_WALLET = "TYZPhi2PpBYLfMSQuoDAGvCvdy4G9WB1mS"  # آدرس ترون خودت
ADMIN_USERNAMES_TOPUP = [
    "@TG_PARSA",  # پشتیبانی
]

# وضعیت‌های شارژ ترون
topup_stage: dict[int, str] = {}        # uid -> "wallet" / "txid"
topup_wallets: dict[int, str] = {}      # uid -> tron address
topup_used_txids: dict[str, dict] = {}  # txid -> {"user_id":..., "datetime":...}

def fa_number(n) -> str:
    try:
        return format_decimal(n, locale="fa")
    except Exception:
        return str(n)

def reset_topup(uid: int):
    topup_stage.pop(uid, None)
    topup_wallets.pop(uid, None)

def get_increase_balance_text(uid: int) -> str:
    """
    فقط متن راهنما + آدرس ترون.
    محدودیت زمانی حذف شده است.
    """
    admins = "\n".join([f"👉 {a.strip()}" for a in ADMIN_USERNAMES_TOPUP if a.strip()])

    txt = (
        "✨ جهت افزایش موجودی با ترون (TRX):\n\n"
        "1️⃣ مبلغ دلخواه را به آدرس زیر واریز کن 👇\n\n"
        f"<code>{TRX_WALLET}</code>\n\n"
        "2️⃣ بعد از واریز، روی دکمه «✅ برسی و شارژ خودکار ترون» بزن تا:\n\n"
        "   • اول آدرس کیف‌پول ترونت رو بگیریم\n\n"
        "   • بعدش TxID تراکنش رو بگیریم\n\n"
        "   • تراکنش روی بلاک‌چین چک بشه و اگر اوکی بود، موجودی‌ات به‌صورت خودکار شارژ میشه ✅\n\n"
        "⚠️ هر تراکنش فقط یک‌بار قابل استفاده است.\n\n"
    )
    if admins:
        txt += f"\n\n👨‍💻 ادمین‌ها:\n{admins}"
    return txt

def topup_inline_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ برسی و شارژ خودکار ترون",
                    callback_data="trx:check"
                )
            ]
        ]
    )

async def check_trx_on_chain(txid: str):
    async with aiohttp.ClientSession() as session:
        url = f"https://apilist.tronscanapi.com/api/transaction-info?hash={txid}"
        async with session.get(url, ssl=False) as resp:
            if resp.status != 200:
                raise Exception("خطا در ارتباط با سرور Tronscan")

            data = await resp.json()

        if "toAddress" not in data:
            raise Exception("تراکنش نامعتبر است یا هنوز در بلاک‌چین ثبت نشده.")

        to_address = data.get("toAddress", "")
        from_address = data.get("ownerAddress", "")
        success = data.get("contractRet", "") == "SUCCESS"
        timestamp = data.get("timestamp", 0)
        hash_id = data.get("hash", "")

        if not success:
            raise Exception("تراکنش هنوز توسط شبکه تأیید نشده است.")

        trx_date = datetime.fromtimestamp(timestamp / 1000)
        today = datetime.now().date()
        if trx_date.date() != today:
            raise Exception(
                f"این تراکنش برای تاریخ {trx_date.strftime('%Y/%m/%d %H:%M:%S')} است.\n"
                "فقط تراکنش‌های امروز پذیرفته می‌شوند."
            )

        token_info = data.get("tokenTransferInfo")
        if token_info and "amount_str" in token_info:
            amount_raw = token_info.get("amount_str", "0")
        else:
            contract_data = data.get("contractData", {})
            amount_raw = str(contract_data.get("amount", contract_data.get("value", "0")))

        tron_amount = float(amount_raw) / 1_000_000  # SUN → TRX

        irr_rate = None
        try:
            async with session.get("https://arzdigital.com/coins/tron/", ssl=False) as r:
                if r.status == 200:
                    html_page = await r.text()
                    match = re.search(r'<span class="pulser-toman-tron">([\d,]+) ت</span>', html_page)
                    if match:
                        price_str = match.group(1).replace(',', '')
                        irr_rate = float(price_str)
        except Exception as e:
            print("⚠️ خطا در دریافت نرخ تومان:", e)

        value_toman = int(tron_amount * irr_rate) if irr_rate else None

    return tron_amount, value_toman, trx_date, to_address, from_address, hash_id

async def send_topup_log(uid: int, trx_date: datetime,
                         tron_amount: float, added_toman: int, hash_id: str):
    try:
        tg_user = await app.get_users(uid)
        username = tg_user.username
        name = (tg_user.first_name or "") + " " + (tg_user.last_name or "")

        time_str = trx_date.strftime("%Y/%m/%d %H:%M:%S")

        log_text = (
            "💰 شارژ جدید از طریق ترون\n\n"
            f"👤 کاربر: <a href=\"tg://user?id={uid}\">{(name.strip() or str(uid))}</a>\n\n"
            f"🆔 آیدی عددی: <code>{uid}</code>\n\n"
            f"🌐 یوزرنیم: @{username if username else 'ندارد'}\n\n"
            f"📆 زمان تراکنش: {time_str}\n\n"
            f"🔗 Hash: <code>{hash_id}</code>\n\n"
            f"💎 مقدار: {fa_number(tron_amount)} TRX\n\n"
            f"≈ {fa_number(added_toman)} تومان شارژ شده"
        )

        buttons = [
            [
                InlineKeyboardButton("🆔 عددی", url=f"tg://user?id={uid}"),
                InlineKeyboardButton(
                    f"🌐 @{username}" if username else "🌐 بدون یوزرنیم",
                    url=f"https://t.me/{username}" if username else "https://t.me/"
                ),
            ]
        ]
        kb = InlineKeyboardMarkup(buttons)

        await app.send_message(
            CHANNEL_SALES_LOG,
            log_text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            reply_markup=kb
        )

    except Exception as e:
        print("⚠️ خطا در ارسال لاگ شارژ:", e)

async def handle_topup_message(m):
    uid = m.from_user.id
    text = (m.text or "").strip()
    stage = topup_stage.get(uid)
    if not stage:
        return

    if stage == "wallet":
        if not text.startswith("T") or len(text) < 25:
            await m.reply(
                "⚠️ آدرس ترون معتبر نیست. لطفاً آدرس درست وارد کنید.\n"
                "مثال: <code>TPsL.........................</code>",
                parse_mode=ParseMode.HTML
            )
            return

        topup_wallets[uid] = text
        topup_stage[uid] = "txid"

        await m.reply(
            "✅ آدرس شما ثبت شد.\n\n"
            "حالا شناسه تراکنش (TxID) را ارسال کنید:\n\n"
            "📄 نمونه:\n\n"
            "<code>3ec6889346d0a8a84cfa2e9fee02d162ef45b7cb99923bbdd41801df41621549</code>",
            parse_mode=ParseMode.HTML
        )
        return

    if stage == "txid":
        txid = text

        if txid in topup_used_txids:
            info = topup_used_txids[txid]
            old_user = info["user_id"]
            old_time = info["datetime"].strftime("%Y/%m/%d %H:%M:%S")
            if old_user == uid:
                await m.reply(
                    f"⚠️ این تراکنش قبلاً توسط خود شما در تاریخ {old_time} ثبت شده است."
                )
            else:
                await m.reply(
                    f"⚠️ این تراکنش قبلاً توسط کاربر دیگری (ID: {old_user}) "
                    f"در تاریخ {old_time} استفاده شده است."
                )
            return

        await m.reply("⏳ در حال بررسی تراکنش شما در بلاک‌چین ترون ...")

        try:
            tron_amount, value_toman, trx_date, to_address, from_address, hash_id = \
                await check_trx_on_chain(txid)

            if TRX_WALLET.lower() not in to_address.lower():
                await m.reply("⚠️ تراکنش به آدرس کیف‌پول ما ارسال نشده.")
                return

            user_wallet = topup_wallets.get(uid, "")
            if user_wallet.lower() not in from_address.lower():
                await m.reply("⚠️ آدرس فرستنده با آدرسی که ثبت کرده‌اید مطابقت ندارد.")
                return

            if value_toman is None:
                await m.reply(
                    "⚠️ تراکنش تأیید شد اما نتوانستیم نرخ تومان را دریافت کنیم.\n"
                    "لطفاً با پشتیبانی در ارتباط باشید."
                )
                return

            added = int(value_toman)
            new_balance = users.add_balance(uid, added)

            topup_used_txids[txid] = {"user_id": uid, "datetime": trx_date}
            reset_topup(uid)

            msg_text = (
                "✅ تراکنش شما با موفقیت تأیید شد و موجودی‌تان شارژ گردید.\n\n"
                f"💰 مقدار روی بلاک‌چین: {fa_number(tron_amount)} TRX\n"
                f"≈ {fa_number(added)} تومان به موجودی‌تان اضافه شد.\n"
                f"💳 موجودی فعلی: {fa_number(new_balance)} تومان"
            )
            await m.reply(msg_text)

            await send_topup_log(uid, trx_date, tron_amount, added, hash_id)

        except Exception as e:
            await m.reply(
                f"⚠️ خطا در بررسی تراکنش:\n\n<code>{e}</code>",
                parse_mode=ParseMode.HTML
            )


# ========================== HANDLERS ==========================

@app.on_message(filters.private & filters.command("start"))
async def start_handler(c, m):
    uid = m.from_user.id
    if is_blocked(uid):
        return

    # >>> جویین اجباری: اگر عضو کانال نیست، فقط پیام عضویت را بفرست
    if not await is_user_in_force_channel(c, uid):
        await m.reply(
            get_force_join_text(),
            reply_markup=force_join_keyboard()
        )
        return

    users.ensure_user(uid)
    users.update_username(uid, m.from_user.username)

    try:
        if m.text and "start=" in m.text:
            inviter_id = m.text.split("start=")[1]
            inviter = f"👥 دعوت شده توسط: {inviter_id}"
        else:
            inviter = "⭕️ بدون دعوت"

        link_html = f'<a href="tg://openmessage?user_id={uid}">{uid}</a>'
        log_msg = (
            f"#کاربر_{uid}\n"
            f"🔑 #استارت\n"
            f"🆔کاربر: {link_html} - {link_html}\n"
            f"{inviter}"
        )
        await c.send_message(
            CHANNEL_LOG,
            log_msg,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
    except Exception:
        pass

    await m.reply(
        "به ربات فروش شماره تلگرام خوش اومدی 🌹\n\n"
        "از منوی زیر یکی از گزینه‌ها رو انتخاب کن 👇",
        reply_markup=main_keyboard(uid)
    )

@app.on_message(filters.private & filters.regex("^ℹ️ اطلاعات حساب$"))
async def info_handler(c, m):
    uid = m.from_user.id
    if is_blocked(uid):
        return

    u = users.get(uid)

    start_j = JalaliDatetime(datetime.fromisoformat(u["register"]))
    today = JalaliDatetime.now()
    days_active = (today - start_j).days

    msg = (
        f"🇮🇷 {today.strftime('%A')} : {today.strftime('%Y/%m/%d')}\n\n"
        f"⏰ ساعت: {today.strftime('%H:%M:%S')}\n\n"
        f"➖➖➖➖ـ➖➖➖➖\n\n"
        f"🔰 اطلاعات حساب کاربری:\n\n"
        f"🆔 شماره کاربری: {uid}\n\n"
        f"📆 آغاز فعالیت: {start_j.strftime('%Y/%m/%d')}\n\n"
        f"🔮 فعالیت در ربات: {days_active} روز\n\n"
        f"🔭 تعداد کل سفارشات: {u.get('orders', 0)}\n\n"
        f"👥 تعداد زیرمجموعه ها: {u.get('referrals', 0)}\n\n"
        f"➖➖➖➖ـ🔻ـ➖➖➖➖\n\n"
        f"💰 موجودی فعلی: {u.get('balance', 0)} تومان"
    )
    await m.reply(msg, reply_markup=back_btn)


# ---------- لیست قیمت‌ها ----------
@app.on_message(filters.private & filters.regex("^📊 لیست قیمت‌ها$"))
async def prices_handler(c, m):
    uid = m.from_user.id
    if is_blocked(uid):
        return

    grouped = group_available_by_country()
    if not grouped:
        await m.reply(
            "❌ در حال حاضر هیچ شماره‌ای برای فروش موجود نیست.\n"
            "به زودی کشورها و شماره‌های جدید اضافه خواهند شد ✨",
            reply_markup=back_btn
        )
        return

    text = (
        "📊 لیست قیمت کشورهایی که در حال حاضر شماره‌ی آن‌ها موجود است:\n\n"
        "هر ردیف: کشور (با پرچم)، وضعیت، کمترین قیمت، تعداد موجود و وضعیت Scam 👇\n\n"
        "با کلیک روی هر کشور، لیست اکانت‌ها و قیمت‌های آن کشور نمایش داده می‌شود (بدون نمایش شماره‌ها)."
    )
    kb = build_price_keyboard(grouped)
    await m.reply(text, reply_markup=kb)


# ---------- خرید شماره مجازی ----------
@app.on_message(filters.private & filters.regex("^🛍 خرید شماره مجازی$"))
async def buy_handler(c, m):
    uid = m.from_user.id
    if is_blocked(uid):
        return

    await delete_user_panels(c, uid)

    grouped = group_available_by_country()
    if not grouped:
        await m.reply(
            "❌ هیچ اکانتی برای خرید موجود نیست.\n"
            "منتظر بمون تا اکانت‌های جدید اضافه بشه ✨",
            reply_markup=back_btn
        )
        return

    helper_msg = await m.reply(
        "برای بازگشت از دکمه زیر استفاده کن 👇",
        reply_markup=back_btn
    )
    register_user_panel(uid, helper_msg.chat.id, helper_msg.id)

    text = (
        "🛍 لطفاً کشور موردنظر برای خرید شماره مجازی را انتخاب کنید:\n\n"
        "بعد از انتخاب کشور، لیست کامل اکانت‌های موجود آن کشور با قیمت، تعداد و وضعیت نمایش داده می‌شود.\n"
        "توجه: شماره‌ها قبل از پرداخت کاملاً مخفی هستند و بعد از خرید نمایش داده می‌شوند."
    )
    kb = build_buy_keyboard(grouped)
    panel_msg = await m.reply(text, reply_markup=kb)
    register_user_panel(uid, panel_msg.chat.id, panel_msg.id)


# ---------- افزایش موجودی ----------
@app.on_message(filters.private & filters.regex("^💳 افزایش موجودی$"))
async def increase_balance_handler(c, m):
    uid = m.from_user.id
    if is_blocked(uid):
        return

    await delete_user_panels(c, uid)

    text = get_increase_balance_text(uid)

    helper_msg = await m.reply("برای بازگشت از دکمه زیر استفاده کن 👇", reply_markup=back_btn)
    register_user_panel(uid, helper_msg.chat.id, helper_msg.id)

    msg = await m.reply(text, reply_markup=topup_inline_keyboard(), parse_mode=ParseMode.HTML)
    register_user_panel(uid, msg.chat.id, msg.id)


# ========================== BACK BUTTON (GLOBAL) ==========================

@app.on_message(filters.private & filters.regex("^🔙 بازگشت$"))
async def back_btn_handler(c, m):
    uid = m.from_user.id
    state.clear_all_for_user(uid)
    pending_purchases.pop(uid, None)
    reset_topup(uid)
    await delete_user_panels(c, uid)
    await m.reply("🏠 به منوی اصلی برگشتی", reply_markup=main_keyboard(uid))


# ========================== INLINE CALLBACKS ==========================

@app.on_callback_query()
async def callbacks_handler(c, q):
    uid = q.from_user.id
    data = q.data or ""
    parts = data.split(":", 1)
    action = parts[0]
    arg = parts[1] if len(parts) == 2 else ""

    # >>> جویین اجباری: بررسی عضویت
    if action == "checkjoin":
        if await is_user_in_force_channel(c, uid):
            await q.answer("✅ عضویت شما تأیید شد.", show_alert=False)
            try:
                await q.message.delete()
            except Exception:
                pass

            # ثبت کاربر و یوزرنیم بعد از تأیید عضویت
            users.ensure_user(uid)
            from_user = q.from_user
            users.update_username(uid, from_user.username if from_user else None)

            await c.send_message(
                uid,
                "به ربات فروش شماره تلگرام خوش اومدی 🌹\n\n"
                "از منوی زیر یکی از گزینه‌ها رو انتخاب کن 👇",
                reply_markup=main_keyboard(uid)
            )
        else:
            await q.answer("❌ هنوز در کانال عضو نشدی.", show_alert=True)
            try:
                await q.message.delete()
            except Exception:
                pass
            await c.send_message(
                uid,
                get_force_join_text(),
                reply_markup=force_join_keyboard()
            )
        return

    # ------------ TRX TOPUP CALLBACKS (برسی) ------------
    if action == "trx":
        if arg == "back":
            reset_topup(uid)
            await q.answer("به منوی اصلی برگشتی ✅", show_alert=False)
            try:
                await q.message.edit_text("🏠 به منوی اصلی برگشتی", reply_markup=None)
            except Exception:
                pass
            await delete_user_panels(c, uid)
            await c.send_message(
                uid,
                "از منوی زیر یکی از گزینه‌ها رو انتخاب کن 👇",
                reply_markup=main_keyboard(uid)
            )
            return

        if arg == "check":
            topup_stage[uid] = "wallet"
            txt = (
                "📩 لطفاً آدرس کیف‌پول ترون (TRX) خود را ارسال کنید:\n\n"
                "بعد از ثبت آدرس، ازت TxID تراکنش رو می‌گیرم و به صورت خودکار روی بلاک‌چین چک می‌کنم ✅"
            )
            try:
                await q.message.edit_text(
                    txt,
                    reply_markup=None
                )
            except Exception:
                await c.send_message(
                    uid,
                    txt,
                    reply_markup=back_btn
                )
            await q.answer("لطفاً آدرس کیف‌پولت رو بفرست ✅", show_alert=False)
            return

    if action == "noop":
        await q.answer("", show_alert=False)
        return

    # ---------- لیست قیمت‌ها: برگشت به لیست کشورها ----------
    if action == "prback":
        grouped = group_available_by_country()
        if not grouped:
            try:
                await q.message.edit_text(
                    "❌ در حال حاضر هیچ شماره‌ای برای نمایش قیمت وجود ندارد.",
                    reply_markup=None
                )
            except Exception:
                pass
            await q.answer("اکانتی موجود نیست.", show_alert=True)
            return

        text = (
            "📊 لیست قیمت کشورهایی که در حال حاضر شماره‌ی آن‌ها موجود است:\n\n"
            "هر ردیف: کشور (با پرچم), وضعیت، کمترین قیمت، تعداد موجود و وضعیت Scam 👇\n\n"
            "با کلیک روی هر کشور، لیست اکانت‌ها و قیمت‌های آن کشور نمایش داده می‌شود (بدون نمایش شماره‌ها)."
        )
        kb = build_price_keyboard(grouped)
        try:
            await q.message.edit_text(text, reply_markup=kb)
        except Exception:
            pass
        await q.answer("به لیست کشورها برگشتی ✅", show_alert=False)
        return

    # ---------- لیست قیمت‌ها: انتخاب کشور ----------
    if action == "prlist":
        country = arg
        available_accounts = accounts.get_available_accounts()
        same_country = [
            (phone, data)
            for phone, data in available_accounts.items()
            if (data.get("country") or detect_country(phone)) == country
        ]

        if not same_country:
            await q.answer("برای این کشور فعلاً اکانتی موجود نیست.", show_alert=True)
            return

        kb = build_country_price_list_keyboard(country, page=0)
        text = (
            f"📋 لیست قیمت اکانت‌های کشور:\n\n"
            f"🌍 {country}\n\n"
            f"📦 تعداد اکانت‌های موجود: {len(same_country)}\n\n"
            "در این بخش فقط قیمت و وضعیت اکانت‌ها نمایش داده می‌شود.\n"
            "شماره‌ها قبل از خرید کاملاً مخفی هستند."
        )
        try:
            await q.message.edit_text(text, reply_markup=kb)
        except Exception:
            await c.send_message(uid, text, reply_markup=kb)
        await q.answer("لیست قیمت‌ها نمایش داده شد ✅", show_alert=False)
        return

    # ---------- لیست قیمت‌ها: صفحه‌بندی ----------
    if action == "prpage":
        try:
            country, page_str = arg.rsplit("|", 1)
            page = int(page_str)
        except Exception:
            await q.answer("خطا در صفحه‌بندی.", show_alert=True)
            return

        available_accounts = accounts.get_available_accounts()
        same_country = [
            (phone, data)
            for phone, data in available_accounts.items()
            if (data.get("country") or detect_country(phone)) == country
        ]

        kb = build_country_price_list_keyboard(country, page=page)
        text = (
            f"📋 لیست قیمت اکانت‌های کشور:\n\n"
            f"🌍 {country}\n\n"
            f"📦 تعداد اکانت‌های موجود: {len(same_country)}\n\n"
            "در این بخش فقط قیمت و وضعیت اکانت‌ها نمایش داده می‌شود.\n"
            "شماره‌ها قبل از خرید کاملاً مخفی هستند."
        )
        try:
            await q.message.edit_text(text, reply_markup=kb)
        except Exception:
            pass
        await q.answer("صفحه تغییر کرد ✅", show_alert=False)
        return

    # ---------- خرید: برگشت به لیست کشورها ----------
    if action == "buyback":
        pending_purchases.pop(uid, None)
        grouped = group_available_by_country()
        if not grouped:
            try:
                await q.message.edit_text(
                    "❌ در حال حاضر هیچ اکانتی برای خرید موجود نیست.",
                    reply_markup=None
                )
            except Exception:
                pass
            await q.answer("اکانتی موجود نیست.", show_alert=True)
            return

        text = (
            "🛍 لطفاً کشور موردنظر برای خرید شماره مجازی را انتخاب کنید:\n"
            "بعد از انتخاب کشور، لیست اکانت‌های آن کشور نمایش داده می‌شود.\n"
            "توجه: شماره‌ها قبل از پرداخت مخفی هستند."
        )
        kb = build_buy_keyboard(grouped)
        try:
            await q.message.edit_text(text, reply_markup=kb)
        except Exception:
            pass
        await q.answer("به لیست کشورها برگشتی ✅", show_alert=False)
        return

    # ---------- خرید: انتخاب کشور ----------
    if action == "buylist":
        country = arg
        if is_blocked(uid):
            await q.answer("شما بلاک هستید.", show_alert=True)
            return

        available_accounts = accounts.get_available_accounts()
        same_country = [
            (phone, data)
            for phone, data in available_accounts.items()
            if (data.get("country") or detect_country(phone)) == country
        ]

        if not same_country:
            await q.answer("برای این کشور فعلاً شماره‌ای موجود نیست.", show_alert=True)
            return

        kb = build_country_accounts_keyboard(country, page=0)
        text = (
            f"📋 لیست اکانت‌های کشور:\n\n"
            f"🌍 {country}\n\n"
            f"📦 تعداد اکانت‌های موجود: {len(same_country)}\n\n"
            "روی هر ردیف برای دیدن پیش‌فاکتور همان اکانت کلیک کن 👇\n"
            "شماره‌ها تا قبل از خرید مخفی می‌مانند."
        )
        try:
            await q.message.edit_text(text, reply_markup=kb)
        except Exception:
            await c.send_message(uid, text, reply_markup=kb)
        await q.answer("لیست اکانت‌ها نمایش داده شد ✅", show_alert=False)
        return

    # ---------- خرید: صفحه‌بندی اکانت‌ها ----------
    if action == "page":
        try:
            country, page_str = arg.rsplit("|", 1)
            page = int(page_str)
        except Exception:
            await q.answer("خطا در صفحه‌بندی.", show_alert=True)
            return

        available_accounts = accounts.get_available_accounts()
        same_country = [
            (phone, data)
            for phone, data in available_accounts.items()
            if (data.get("country") or detect_country(phone)) == country
        ]

        kb = build_country_accounts_keyboard(country, page=page)
        text = (
            f"📋 لیست اکانت‌های کشور:\n\n"
            f"🌍 {country}\n\n"
            f"📦 تعداد اکانت‌های موجود: {len(same_country)}\n\n"
            "روی هر ردیف برای دیدن پیش‌فاکتور همان اکانت کلیک کن 👇\n"
            "شماره‌ها تا قبل از خرید مخفی می‌مانند."
        )
        try:
            await q.message.edit_text(text, reply_markup=kb)
        except Exception:
            pass
        await q.answer("صفحه تغییر کرد ✅", show_alert=False)
        return

    phone = arg

    # خروج ربات از اکانت
    if action == "logout":
        acc_data = accounts.get(phone)
        if not acc_data or acc_data.get("sold_to") != uid:
            await q.answer("این اکانت به شما تعلق ندارد.", show_alert=True)
            return

        session = get_session_for_phone(phone)
        if not session:
            await q.answer("برای این اکانت Session ذخیره نشده است.", show_alert=True)
            return

        from pyrogram import Client as UserClient

        try:
            async with UserClient(
                name=f"logout_{uid}_{phone}",
                api_id=API_ID,
                api_hash=API_HASH,
                session_string=session,
                in_memory=True,
            ) as user_client:
                try:
                    await user_client.log_out()
                except Exception:
                    pass

            accounts.clear_session(phone)

            try:
                await q.message.delete()
            except Exception:
                pass

            await c.send_message(
                uid,
                "✅ ربات به طور کامل از این اکانت خارج شد و دیگر به آن دسترسی ندارد.",
                reply_markup=main_keyboard(uid)
            )
            await q.answer("خروج از اکانت انجام شد.", show_alert=False)
        except Exception:
            await q.answer("خروج ربات انجام شد.", show_alert=False)

        return

    pending = pending_purchases.get(uid)

    if action == "cancel":
        if pending and pending.get("phone") == phone and not pending.get("billed", False):
            pending_purchases.pop(uid, None)
            try:
                await q.message.edit_text(
                    "❌ خرید لغو شد.\n"
                    "موجودی و وضعیت شما بدون تغییر باقی ماند.",
                    reply_markup=None
                )
            except Exception:
                pass
            await q.answer("خرید لغو شد.", show_alert=False)
        else:
            await q.answer("خریدی برای لغو یافت نشد یا قبلاً نهایی شده است.", show_alert=True)
        return

    acc = accounts.get(phone)
    if not acc:
        await q.answer("اکانت در سیستم یافت نشد!", show_alert=True)
        if pending and pending.get("phone") == phone:
            pending_purchases.pop(uid, None)
        return

    # انتخاب یک اکانت (قبل از نمایش شماره)
    if action == "buyselect":
        if is_blocked(uid):
            await q.answer("شما بلاک هستید.", show_alert=True)
            return

        acc_data = acc
        if not acc_data.get("available", False):
            await q.answer("این اکانت دیگر در دسترس نیست.", show_alert=True)
            return

        price = acc_data.get("price", 0)
        country = acc_data.get("country") or detect_country(phone)
        u = users.get(uid)
        balance = u.get("balance", 0)

        if balance < price:
            await q.answer(
                f"❌ موجودی شما برای این اکانت کافی نیست.\n"
                f"Price: {price} | Balance: {balance}",
                show_alert=True
            )
            return

        pending_purchases[uid] = {
            "phone": phone,
            "price": price,
            "billed": False
        }

        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("📨 دریافت کد", callback_data=f"getcode:{phone}"),
                    InlineKeyboardButton("✅ چکر", callback_data=f"chk:{phone}"),
                ],
                [
                    InlineKeyboardButton("❌ لغو", callback_data=f"cancel:{phone}"),
                    InlineKeyboardButton("🔙 بازگشت", callback_data="buyback:main"),
                ],
            ]
        )

        text = (
            "🧾 پیش‌فاکتور خرید شما:\n\n"
            f"🌍 کشور: {country}\n\n"
            f"📱 شماره انتخاب شده: {phone}\n\n"
            f"💰 قیمت: {price} تومان\n\n"
            "از دکمه‌های زیر برای چکر یا نهایی کردن خرید استفاده کنید 👇"
        )
        try:
            await q.message.edit_text(text, reply_markup=kb)
        except Exception:
            new_msg = await c.send_message(uid, text, reply_markup=kb)
            register_user_panel(uid, new_msg.chat.id, new_msg.id)
        await q.answer("پیش‌فاکتور نمایش داده شد ✅", show_alert=False)
        return

    if action == "chk":
        if pending and pending.get("phone") == phone:
            allowed = True
        elif acc.get("sold_to") == uid:
            allowed = True
        else:
            allowed = False

        if not allowed:
            await q.answer("این چکر مربوط به خرید شما نیست یا منقضی شده است.", show_alert=True)
            return

        session = get_session_for_phone(phone)
        if not session:
            await q.answer("برای این شماره Session ثبت نشده است.", show_alert=True)
            return

        from pyrogram import Client as UserClient

        ok = False
        try:
            async with UserClient(
                name=f"chk_{uid}_{phone}",
                api_id=API_ID,
                api_hash=API_HASH,
                session_string=session,
                in_memory=True,
            ) as temp:
                try:
                    await temp.get_me()
                    ok = True
                except Exception:
                    ok = False
        except Exception:
            ok = False

        if ok:
            await q.answer("✅ اکانت سالم است و Session فعال است.", show_alert=True)
        else:
            await q.answer("❌ اکانت در دسترس نیست یا Session باطل شده.", show_alert=True)
        return

    if action == "getcode":
        price = None
        do_bill = False

        if pending and pending.get("phone") == phone:
            price = pending.get("price", 0)
            if not pending.get("billed", False):
                do_bill = True
        else:
            if acc.get("sold_to") != uid:
                await q.answer("این خرید دیگر فعال نیست یا متعلق به شما نیست.", show_alert=True)
                return

        if do_bill:
            u = users.get(uid)
            balance = u.get("balance", 0)
            if balance < price:
                pending_purchases.pop(uid, None)
                await q.answer("❌ موجودی شما دیگر برای این خرید کافی نیست.", show_alert=True)
                try:
                    await q.message.edit_text(
                        "❌ به دلیل کاهش موجودی، خرید نهایی نشد.",
                        reply_markup=None
                    )
                except Exception:
                    pass
                return

            users.dec_balance(uid, price)
            users.add_order(uid, price)
            accounts.set_sold(phone, uid)

            if pending:
                pending["billed"] = True

            users_data = users.get(uid)
            try:
                country = acc.get("country") or detect_country(phone)
                tag = acc.get("tag") or "-"

                try:
                    tg_user = await c.get_users(uid)
                    username = tg_user.username
                except Exception:
                    username = None

                log_msg = (
                    f"✅ فروش جدید شماره\n\n"
                    f"👤 خریدار: <a href=\"tg://openmessage?user_id={uid}\">{uid}</a>\n\n"
                    f"📱 شماره: {html.escape(phone)}\n\n"
                    f"🌍 کشور: {html.escape(country)}\n\n"
                    f"🏷 برچسب: {html.escape(tag)}\n\n"
                    f"💰 قیمت: {price} تومان\n\n"
                    f"🧾 مجموع خرید خریدار: {users_data.get('spent', 0)} تومان\n\n"
                    f"⏰ تاریخ: {JalaliDatetime.now().strftime('%Y/%m/%d %H:%M:%S')}"
                )

                btns = [InlineKeyboardButton(f"🆔 {uid}", url=f"tg://user?id={uid}")]
                if username:
                    btns.append(
                        InlineKeyboardButton(f"🌐 @{username}", url=f"https://t.me/{username}")
                    )
                else:
                    btns.append(
                        InlineKeyboardButton("🌐 یوزرنیم: ندارد", url="https://t.me/")
                    )

                await c.send_message(
                    CHANNEL_SALES_LOG,
                    log_msg,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                    reply_markup=InlineKeyboardMarkup([btns])
                )
            except Exception:
                pass

            try:
                await q.message.edit_reply_markup(reply_markup=None)
            except Exception:
                pass

            # اینجا شماره بعد از نهایی شدن خرید برای کاربر نمایش داده می‌شود
            await c.send_message(
                uid,
                "🎉 خرید شما با موفقیت نهایی شد!\n\n"
                f"📱 شماره: {phone}\n"
                f"💰 مبلغ پرداختی: {price} تومان\n\n"
                "حالا با دکمه «📨 دریافت کد» کد ورود از تلگرام برایت خوانده می‌شود.",
                reply_markup=main_keyboard(uid)
            )

        session = get_session_for_phone(phone)
        if not session:
            await q.answer("Session برای این اکانت ذخیره نشده است.", show_alert=True)
            return

        from pyrogram import Client as UserClient

        code_found = None
        try:
            async with UserClient(
                name=f"code_{uid}_{phone}",
                api_id=API_ID,
                api_hash=API_HASH,
                session_string=session,
                in_memory=True,
            ) as user_client:

                peer_ids = set()
                try:
                    u777 = await user_client.get_users(777000)
                    peer_ids.add(u777.id)
                except Exception:
                    pass

                try:
                    u_tel = await user_client.get_users("Telegram")
                    peer_ids.add(u_tel.id)
                except Exception:
                    pass

                try:
                    u_42777 = await user_client.get_users("42777")
                    peer_ids.add(u_42777.id)
                except Exception:
                    pass

                for peer_id in peer_ids:
                    async for msg in user_client.get_chat_history(peer_id, limit=50):
                        if msg.text:
                            code = extract_code_from_text(msg.text)
                            if code:
                                code_found = code
                                break
                    if code_found:
                        break

                if not code_found:
                    async for dialog in user_client.get_dialogs():
                        chat = dialog.chat
                        name_parts = [
                            (getattr(chat, "first_name", "") or ""),
                            (getattr(chat, "last_name", "") or ""),
                            (getattr(chat, "title", "") or ""),
                            (getattr(chat, "username", "") or ""),
                        ]
                        name = " ".join(name_parts).lower()
                        if "telegram" in name or chat.id == 777000:
                            async for msg in user_client.get_chat_history(chat.id, limit=50):
                                if msg.text:
                                    code = extract_code_from_text(msg.text)
                                    if code:
                                        code_found = code
                                        break
                            if code_found:
                                break
        except Exception:
            pass

        if code_found:
            dotted = dot_code(code_found)
            kb_actions = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("📨 دریافت کد مجدد", callback_data=f"getcode:{phone}"),
                        InlineKeyboardButton("🚪 خروج ربات از اکانت", callback_data=f"logout:{phone}"),
                    ]
                ]
            )
            await c.send_message(
                uid,
                f"🔑 کد ورود شما:\n\n<code>{dotted}</code>\n\n"
                "کد را در تلگرام وارد کن. هر وقت کارت تمام شد، می‌توانی از دکمه زیر برای خروج ربات از اکانت استفاده کنی:",
                parse_mode=ParseMode.HTML,
                reply_markup=kb_actions
            )
            pending_purchases.pop(uid, None)
            await q.answer("کد برای شما ارسال شد ✅", show_alert=False)
        else:
            await c.send_message(
                uid,
                "ℹ️ هنوز هیچ کدی از 42777 / 777000 / Telegram در این اکانت پیدا نشد.\n"
                "اگر تازه درخواست دادی، چند دقیقه دیگر دوباره روی «📨 دریافت کد مجدد» بزن.",
            )
            await q.answer("فعلاً کدی پیدا نشد.", show_alert=False)

        return


# ========================== سایر دستورات کاربر ==========================

@app.on_message(filters.private & filters.regex("^🪪 فروش شماره به ربات$"))
async def sell_handler(c, m):
    if is_blocked(m.from_user.id):
        return

    await m.reply(
        "📤 جهت فروش شماره خودتان به آیدی ادمین ها پیام دهید .\n\n"
        "در حال حاضر برای فروش شماره با پشتیبانی در ارتباط باشید.\n\n"
        "پشتیبانی: TG_PARSA@",
        reply_markup=back_btn
    )

@app.on_message(filters.private & filters.regex("^📞 پشتیبانی$"))
async def support_handler(c, m):
    if is_blocked(m.from_user.id):
        return
    await m.reply(
        "🔧 برای ارتباط با پشتیبانی، به آیدی زیر پیام بده:\n\n"
        "@TG_PARSA",
        reply_markup=back_btn
    )

@app.on_message(filters.private & filters.regex("^📘 راهنما$"))
async def help_handler(c, m):
    if is_blocked(m.from_user.id):
        return
    try:
        with open("help.txt", "r", encoding="utf-8") as f:
            text = f.read().strip()
    except Exception:
        text = "❌ فایل راهنما پیدا نشد."
    await m.reply(text, reply_markup=back_btn)

@app.on_message(filters.private & filters.regex("^🤝 دریافت نمایندگی$"))
async def agent_handler(c, m):
    if is_blocked(m.from_user.id):
        return
    try:
        with open("agency.txt", "r", encoding="utf-8") as f:
            text = f.read().strip()
    except Exception:
        text = "❌ فایل نمایندگی پیدا نشد."
    await m.reply(text, reply_markup=back_btn)


# ========================== ADMIN PANEL ==========================

@app.on_message(filters.private & filters.regex("^🔐 پنل مدیریت$"))
async def admin_panel(c, m):
    if not is_admin(m.from_user.id):
        return
    state.set_mode(m.from_user.id, None)
    await m.reply("به پنل مدیریتی حرفه‌ای خوش آمدید 👑", reply_markup=admin_markup)

@app.on_message(filters.private & filters.regex("^➕ افزودن مدیر$"))
async def cmd_add_admin(c, m):
    if not is_admin(m.from_user.id):
        return
    state.set_mode(m.from_user.id, StateMode.ADD_ADMIN)
    await m.reply("📌 آیدی عددی کاربر را ارسال کنید:", reply_markup=back_btn)

@app.on_message(filters.private & filters.regex("^➖ حذف مدیر$"))
async def cmd_remove_admin(c, m):
    if not is_admin(m.from_user.id):
        return
    state.set_mode(m.from_user.id, StateMode.REMOVE_ADMIN)
    await m.reply("📌 آیدی عددی مدیر را ارسال کنید:", reply_markup=back_btn)

@app.on_message(filters.private & filters.regex("^💰 افزایش موجودی$"))
async def cmd_inc(c, m):
    if not is_admin(m.from_user.id):
        return
    state.set_mode(m.from_user.id, StateMode.INC_BALANCE)
    await m.reply("📌 فرمت: آیدی مقدار  (مثال: 123456 20000)", reply_markup=back_btn)

@app.on_message(filters.private & filters.regex("^📉 کاهش موجودی$"))
async def cmd_dec(c, m):
    if not is_admin(m.from_user.id):
        return
    state.set_mode(m.from_user.id, StateMode.DEC_BALANCE)
    await m.reply("📌 فرمت: آیدی مقدار  (مثال: 123456 5000)", reply_markup=back_btn)

@app.on_message(filters.private & filters.regex("^🚫 بلاک کاربر$"))
async def cmd_block(c, m):
    if not is_admin(m.from_user.id):
        return
    state.set_mode(m.from_user.id, StateMode.BLOCK)
    await m.reply("📌 آیدی عددی کاربر را برای بلاک ارسال کنید:", reply_markup=back_btn)

@app.on_message(filters.private & filters.regex("^♻ آنبلاک کاربر$"))
async def cmd_unblock(c, m):
    if not is_admin(m.from_user.id):
        return
    state.set_mode(m.from_user.id, StateMode.UNBLOCK)
    await m.reply("📌 آیدی عددی کاربر را برای آنبلاک ارسال کنید:", reply_markup=back_btn)

@app.on_message(filters.private & filters.regex("^🔍 جستجوی کاربر$"))
async def cmd_search(c, m):
    if not is_admin(m.from_user.id):
        return
    state.set_mode(m.from_user.id, StateMode.SEARCH)
    await m.reply("📌 آیدی عددی کاربر را ارسال کنید:", reply_markup=back_btn)

@app.on_message(filters.private & filters.regex("^📢 ارسال همگانی$"))
async def cmd_broadcast(c, m):
    if not is_admin(m.from_user.id):
        return
    state.set_mode(m.from_user.id, StateMode.BROADCAST)
    await m.reply("📌 متن مورد نظر برای ارسال همگانی را ارسال کنید:", reply_markup=back_btn)

@app.on_message(filters.private & filters.regex("^➕ افزودن اکانت$"))
async def cmd_add_account(c, m):
    if not is_admin(m.from_user.id):
        return
    state.set_mode(m.from_user.id, StateMode.ADD_ACCOUNT_PHONE)
    state.temp_add_account.pop(m.from_user.id, None)
    await m.reply(
        "📱 لطفا شماره تلگرام را وارد کنید (با + شروع شود، مثال: +989123456789):",
        reply_markup=back_btn
    )

@app.on_message(filters.private & filters.regex("^⚠️ افزودن اکانت اسکم$"))
async def cmd_add_scam_account(c, m):
    if not is_admin(m.from_user.id):
        return
    uid = m.from_user.id
    state.set_mode(uid, StateMode.ADD_ACCOUNT_PHONE)
    state.temp_add_account[uid] = {"is_scam": True}
    await m.reply(
        "⚠️ لطفا شماره تلگرام اسکم را وارد کنید (با + شروع شود، مثال: +989123456789):",
        reply_markup=back_btn
    )

@app.on_message(filters.private & filters.regex("^📋 لیست اکانت‌ها$"))
async def cmd_list_accounts(c, m):
    if not is_admin(m.from_user.id):
        return

    all_accounts = accounts.list_all()
    if not all_accounts:
        await m.reply("❌ هیچ اکانتی ثبت نشده است.", reply_markup=admin_markup)
        return

    msg_lines = ["📋 لیست تمام اکانت‌ها:\n\n"]
    for phone, data in all_accounts.items():
        status = "موجود ✅" if data.get("available") else "فروخته شده ❌"
        price = data.get("price", 0)
        country = data.get("country") or detect_country(phone)
        tag = data.get("tag") or "-"
        scam_status = "اسکم ✅" if is_scam_tag(tag) else "نرمال ✅"

        display_phone = phone
        msg_lines.append(
            f"📱 {display_phone}\n\n"
            f"🌍 کشور: {country} | 🏷 برچسب: {tag}\n\n"
            f"⚠️ وضعیت اسکم: {scam_status}\n\n"
            f"💰 قیمت: {price} تومان | وضعیت: {status}\n\n"
            f"➖➖➖"
        )

    await m.reply("\n".join(msg_lines), reply_markup=admin_markup)

@app.on_message(filters.private & filters.regex("^✏️ ویرایش قیمت اکانت$"))
async def cmd_edit_price(c, m):
    if not is_admin(m.from_user.id):
        return
    state.set_mode(m.from_user.id, StateMode.EDIT_ACCOUNT_PRICE)
    await m.reply("📌 فرمت: شماره قیمت  (مثال: +989123456789 150000)", reply_markup=back_btn)

@app.on_message(filters.private & filters.regex("^🗑 حذف اکانت$"))
async def cmd_delete_account(c, m):
    if not is_admin(m.from_user.id):
        return
    state.set_mode(m.from_user.id, StateMode.DELETE_ACCOUNT)
    await m.reply("📌 شماره اکانت را برای حذف ارسال کنید (مثال: +989123456789):", reply_markup=back_btn)

@app.on_message(filters.private & filters.regex("^🧹 حذف اکانت اسکم$"))
async def cmd_delete_scam_account(c, m):
    if not is_admin(m.from_user.id):
        return
    state.set_mode(m.from_user.id, StateMode.DELETE_SCAM_ACCOUNT)
    await m.reply("📌 شماره اکانت اسکم را برای حذف ارسال کنید (مثال: +989123456789):", reply_markup=back_btn)

@app.on_message(filters.private & filters.regex("^📊 آمار فروش$"))
async def cmd_stats_sales(c, m):
    if not is_admin(m.from_user.id):
        return
    s = accounts.stats()
    msg = (
        "📊 آمار فروش اکانت‌ها:\n\n"
        f"📦 کل اکانت‌های ثبت شده: {s['total']}\n\n"
        f"✅ اکانت‌های موجود: {s['available']}\n\n"
        f"❌ اکانت‌های فروخته‌شده: {s['sold']}\n\n"
        f"💰 مجموع درآمد (بر اساس قیمت ثبت‌شده): {s['income']} تومان"
    )
    await m.reply(msg, reply_markup=admin_markup)

@app.on_message(filters.private & filters.regex("^👥 آمار کاربران$"))
async def cmd_stats_users(c, m):
    if not is_admin(m.from_user.id):
        return
    all_users = users.all_users()
    total = len(all_users)
    blocked_count = sum(1 for u in all_users.values() if u.get("blocked", False))
    total_orders = sum(u.get("orders", 0) for u in all_users.values())
    total_spent = sum(u.get("spent", 0) for u in all_users.values())
    msg = (
        "👥 آمار کاربران ربات:\n\n"
        f"👤 تعداد کل کاربران: {total}\n\n"
        f"⛔ کاربران بلاک شده: {blocked_count}\n\n"
        f"🛍 مجموع سفارشات ثبت شده: {total_orders}\n\n"
        f"💳 مجموع خرید کاربران: {total_spent} تومان"
    )
    await m.reply(msg, reply_markup=admin_markup)


# ========================== INPUT HANDLER (ADMIN MODES + TOPUP) ==========================

@app.on_message(filters.private & filters.text)
async def input_handler(c, m):
    uid = m.from_user.id
    text = (m.text or "").strip()

    if topup_stage.get(uid):
        await handle_topup_message(m)
        return

    mode = state.get_mode(uid)
    if not mode:
        return

    if not is_admin(uid):
        return

    # ---------- ADD ACCOUNT PROCESS ----------
    if mode == StateMode.ADD_ACCOUNT_PHONE:
        if not text.startswith("+") or not text[1:].isdigit():
            await m.reply("❌ شماره نامعتبر است. باید با + شروع شود و فقط عدد باشد.", reply_markup=back_btn)
            return

        phone = text
        if accounts.exists(phone):
            await m.reply("⚠️ این شماره از قبل در سیستم ثبت شده است.", reply_markup=admin_markup)
            state.set_mode(uid, None)
            return

        from pyrogram import Client as UserClient

        client = UserClient(
            name=f"acc_{phone[1:]}",
            api_id=API_ID,
            api_hash=API_HASH,
            in_memory=True
        )
        try:
            await client.connect()
            sent = await client.send_code(phone)
        except Exception as e:
            try:
                await client.disconnect()
            except Exception:
                pass
            await m.reply(f"❌ خطا در ارسال کد: {e}", reply_markup=admin_markup)
            state.set_mode(uid, None)
            return

        temp = state.temp_add_account.get(uid, {})
        temp.update({
            "phone": phone,
            "client": client,
            "code_hash": sent.phone_code_hash
        })
        state.temp_add_account[uid] = temp

        await m.reply("📩 کد ارسال شده به تلگرام را وارد کنید:", reply_markup=back_btn)
        state.set_mode(uid, StateMode.ADD_ACCOUNT_CODE)
        return

    if mode == StateMode.ADD_ACCOUNT_CODE:
        if uid not in state.temp_add_account:
            state.set_mode(uid, None)
            return

        data = state.temp_add_account[uid]
        client = data["client"]
        phone = data["phone"]
        code_hash = data["code_hash"]
        code = text

        try:
            await client.sign_in(phone, code_hash, code)
            session = await client.export_session_string()
            await client.disconnect()
            state.temp_add_account[uid]["session"] = session

            await m.reply(
                "✔ لاگین موفق!\n"
                "قيمت را وارد کنيد :",
                reply_markup=back_btn,
                parse_mode=ParseMode.HTML
            )
            state.set_mode(uid, StateMode.ADD_ACCOUNT_PRICE)
            return

        except PhoneCodeInvalid:
            await m.reply("❌ کد وارد شده اشتباه است — دوباره وارد کنید:", reply_markup=back_btn)
            return
        except SessionPasswordNeeded:
            await m.reply("🔐 این اکانت رمز دو مرحله‌ای دارد. لطفاً رمز را ارسال کنید:", reply_markup=back_btn)
            state.set_mode(uid, StateMode.ADD_ACCOUNT_PASSWORD)
            return
        except Exception as e:
            try:
                await client.disconnect()
            except Exception:
                pass
            await m.reply(f"❌ خطا در ورود: {e}", reply_markup=admin_markup)
            state.clear_all_for_user(uid)
            return

    if mode == StateMode.ADD_ACCOUNT_PASSWORD:
        if uid not in state.temp_add_account:
            state.set_mode(uid, None)
            return

        data = state.temp_add_account[uid]
        client = data["client"]
        password = text

        try:
            await client.check_password(password)
            session = await client.export_session_string()
            await client.disconnect()
            state.temp_add_account[uid]["session"] = session

            await m.reply(
                "✔ لاگین موفق!\n\n"
                "اگر می‌خواهی کشور یا برچسب دلخواه بدهی، به این فرمت بفرست:\n"
                "<code>country=USA, tag=scam</code>\n\n"
                "یا فقط قیمت را (عدد) ارسال کن:",
                reply_markup=back_btn,
                parse_mode=ParseMode.HTML
            )
            state.set_mode(uid, StateMode.ADD_ACCOUNT_PRICE)
            return

        except Exception:
            try:
                await client.disconnect()
            except Exception:
                pass
            await m.reply("❌ رمز دو مرحله‌ای اشتباه است.", reply_markup=admin_markup)
            state.clear_all_for_user(uid)
            return

    if mode == StateMode.ADD_ACCOUNT_PRICE:
        if uid not in state.temp_add_account:
            state.set_mode(uid, None)
            return

        phone = state.temp_add_account[uid]["phone"]
        session = state.temp_add_account[uid].get("session", "")

        country = state.temp_add_account[uid].get("country")
        tag = state.temp_add_account[uid].get("tag")
        is_scam_flag = state.temp_add_account[uid].get("is_scam", False)

        price_str = text

        if ("country=" in text or "tag=" in text) and not price_str.isdigit():
            parts = text.split(",")
            extras = {}
            for part in parts:
                if "=" in part:
                    k, v = part.split("=", 1)
                    extras[k.strip().lower()] = v.strip()
            country = extras.get("country") or country
            tag = extras.get("tag") or tag
            state.temp_add_account[uid]["country"] = country
            state.temp_add_account[uid]["tag"] = tag
            await m.reply("💰 حالا قیمت اکانت را (فقط عدد) ارسال کن:", reply_markup=back_btn)
            return

        if not price_str.isdigit():
            await m.reply("❌ قیمت باید فقط عدد باشد.", reply_markup=back_btn)
            return

        price = int(price_str)

        if is_scam_flag and not tag:
            tag = "scam"

        auto_country = country or detect_country(phone)

        accounts.add_account(phone, price, session, owner_id=uid, country=auto_country, tag=tag)

        scam_status = "اسکم ✅" if is_scam_tag(tag) else "نرمال ✅"

        await m.reply(
            f"✔ اکانت {phone} با قیمت {price} تومان اضافه شد.\n"
            f"🌍 کشور: {auto_country} | 🏷 برچسب: {tag or '-'} | ⚠️ {scam_status}",
            reply_markup=admin_markup
        )

        # لاگ در کانال برای افزودن اکانت
        try:
            admin_user = await app.get_users(uid)
            admin_username = admin_user.username
        except Exception:
            admin_username = None

        log_text = (
            "➕ اکانت جدید به سیستم اضافه شد\n\n"
            f"👤 ادمین ثبت‌کننده: <a href=\"tg://user?id={uid}\">{uid}</a>\n\n"
            f"📱 شماره: <code>{html.escape(phone)}</code>\n\n"
            f"🌍 کشور: {html.escape(auto_country)}\n\n"
            f"🏷 برچسب: {html.escape(tag or '-')}\n\n"
            f"⚠️ وضعیت: {scam_status}\n\n"
            f"💰 قیمت ثبت‌شده: {price} تومان\n\n"
            f"⏰ زمان: {JalaliDatetime.now().strftime('%Y/%m/%d %H:%M:%S')}"
        )
        await send_admin_log_text(log_text, target_id=uid, target_username=admin_username)

        state.clear_all_for_user(uid)
        return

    # ---------- SEARCH USER ----------
    if mode == StateMode.SEARCH:
        state.set_mode(uid, None)
        if not text.isdigit():
            await m.reply("❌ لطفاً فقط آیدی عددی ارسال کنید.", reply_markup=admin_markup)
            return

        target = int(text)
        u_all = users.all_users()
        if str(target) not in u_all:
            await m.reply("❌ کاربر پیدا نشد.", reply_markup=admin_markup)
            return

        u = u_all[str(target)]
        try:
            usr = await app.get_users(target)
            username = usr.username or "ثبت نشده"
        except Exception:
            username = "ثبت نشده"

        reg_dt = datetime.fromisoformat(u["register"])
        last_dt = datetime.fromisoformat(u["last"])
        start_j = JalaliDatetime(reg_dt)
        last_j = JalaliDatetime(last_dt)
        days_active = (JalaliDatetime.now() - start_j).days

        blocked_status = "مسدود ❌" if u.get("blocked", False) else "مسدود نیست ✅"

        msg = (
            f"🆔کاربری: <a href=\"tg://openmessage?user_id={target}\">{target}</a>\n\n"
            f"👤اوپن چت: <a href=\"tg://openmessage?user_id={target}\">{target}</a>\n\n"
            f"🌈تگ کاربری: @{html.escape(username)}\n\n"
            f"🌐زبان انتخاب شده: FA\n\n"
            f"🔑آغاز فعالیت: {start_j.strftime('%H:%M:%S-%Y/%m/%d')}\n\n"
            f"💤آخرین استفاده: {last_j.strftime('%H:%M:%S-%Y/%m/%d')}\n\n"
            f"🔮تعداد روز های فعال: {days_active}\n\n"
            f"➖➖➖➖ـ➖➖➖➖\n\n"
            f"⛔️وضعیت مسدودی: {blocked_status}\n\n"
            f"⭕️وضعیت بلاکی: کاربر ربات را بلاک نکرده ✅\n\n"
            f"➖➖➖➖ـ➖➖➖➖\n\n"
            f"👥تعداد زیرمجموعه ها: {u.get('referrals', 0)}\n\n"
            f"🏧آخرین انتقال به: ✖️\n\n"
            f"🔭تعداد سفارشات کاربر: {u.get('orders', 0)}\n\n"
            f"🛒مجموع خرید از فروشگاه: {u.get('spent', 0)} تومان\n\n"
            f"💰موجودی فعلی: {u.get('balance', 0)} تومان"
        )
        await m.reply(
            msg,
            reply_markup=admin_markup,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True
        )
        return

    # ---------- ADD ADMIN ----------
    if mode == StateMode.ADD_ADMIN:
        state.set_mode(uid, None)
        if not text.isdigit():
            await m.reply("❌ آیدی نامعتبر است.", reply_markup=admin_markup)
            return
        new_id = int(text)
        if new_id in ADMINS:
            await m.reply("⚠️ این فرد در حال حاضر ادمین است.", reply_markup=admin_markup)
            return
        ADMINS.append(new_id)
        await m.reply("✔ ادمین جدید با موفقیت اضافه شد.", reply_markup=admin_markup)
        try:
            await app.send_message(new_id, "🎉 شما به عنوان ادمین ربات اضافه شدید.")
        except Exception:
            pass

        # لاگ کانال
        try:
            new_user = await app.get_users(new_id)
            new_un = new_user.username
        except Exception:
            new_un = None
        try:
            admin_user = await app.get_users(uid)
            admin_un = admin_user.username
        except Exception:
            admin_un = None

        log_text = (
            "👑 ادمین جدید اضافه شد\n\n"
            f"👤 ادمین اضافه‌کننده: <a href=\"tg://user?id={uid}\">{uid}</a>\n\n"
            f"👤 ادمین جدید: <a href=\"tg://user?id={new_id}\">{new_id}</a>\n\n"
            f"⏰ زمان: {JalaliDatetime.now().strftime('%Y/%m/%d %H:%M:%S')}"
        )
        await send_admin_log_text(log_text, target_id=new_id, target_username=new_un)
        return

    # ---------- REMOVE ADMIN ----------
    if mode == StateMode.REMOVE_ADMIN:
        state.set_mode(uid, None)
        if not text.isdigit():
            await m.reply("❌ آیدی نامعتبر است.", reply_markup=admin_markup)
            return
        rem = int(text)
        if rem not in ADMINS:
            await m.reply("⚠️ این فرد ادمین نیست.", reply_markup=admin_markup)
            return
        if rem == uid:
            await m.reply("🚫 نمی‌توانید خودتان را حذف کنید.", reply_markup=admin_markup)
            return
        ADMINS.remove(rem)
        await m.reply("✔ ادمین حذف شد.", reply_markup=admin_markup)
        try:
            await app.send_message(rem, "❗ شما از لیست ادمین‌ها حذف شده‌اید.")
        except Exception:
            pass

        # لاگ
        try:
            rem_user = await app.get_users(rem)
            rem_un = rem_user.username
        except Exception:
            rem_un = None

        log_text = (
            "❗ ادمین حذف شد\n\n"
            f"👤 ادمین حذف‌کننده: <a href=\"tg://user?id={uid}\">{uid}</a>\n\n"
            f"👤 ادمین حذف‌شده: <a href=\"tg://user?id={rem}\">{rem}</a>\n\n"
            f"⏰ زمان: {JalaliDatetime.now().strftime('%Y/%m/%d %H:%M:%S')}"
        )
        await send_admin_log_text(log_text, target_id=rem, target_username=rem_un)
        return

    # ---------- INC BALANCE ----------
    if mode == StateMode.INC_BALANCE:
        state.set_mode(uid, None)
        parts = text.split()
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
            await m.reply("❌ فرمت اشتباه. مثال: 123456 20000", reply_markup=admin_markup)
            return
        target = int(parts[0])
        amount = int(parts[1])
        users.ensure_user(target)
        new_balance = users.add_balance(target, amount)
        await m.reply(
            f"✔ موجودی {target} به اندازه {amount} تومان افزایش یافت.\n"
            f"💰 موجودی جدید: {new_balance} تومان",
            reply_markup=admin_markup
        )
        try:
            await app.send_message(
                target,
                f"💰 موجودی شما {amount} تومان افزایش یافت. موجودی فعلی: {new_balance} تومان"
            )
        except Exception:
            pass

        try:
            t_user = await app.get_users(target)
            t_un = t_user.username
        except Exception:
            t_un = None

        log_text = (
            "💹 افزایش موجودی کاربر\n\n"
            f"👤 ادمین انجام‌دهنده: <a href=\"tg://user?id={uid}\">{uid}</a>\n\n"
            f"👤 کاربر: <a href=\"tg://user?id={target}\">{target}</a>\n\n"
            f"💰 مبلغ اضافه شده: {amount} تومان\n\n"
            f"💳 موجودی جدید: {new_balance} تومان\n\n"
            f"⏰ زمان: {JalaliDatetime.now().strftime('%Y/%m/%d %H:%M:%S')}"
        )
        await send_admin_log_text(log_text, target_id=target, target_username=t_un)
        return

    # ---------- DEC BALANCE ----------
    if mode == StateMode.DEC_BALANCE:
        state.set_mode(uid, None)
        parts = text.split()
        if len(parts) != 2 or not parts[0].isdigit() or not parts[1].isdigit():
            await m.reply("❌ فرمت اشتباه. مثال: 123456 5000", reply_markup=admin_markup)
            return
        target = int(parts[0])
        amount = int(parts[1])
        users.ensure_user(target)
        new_balance = users.dec_balance(target, amount)
        await m.reply(
            f"✔ از موجودی {target} به اندازه {amount} تومان کسر شد.\n"
            f"💰 موجودی جدید: {new_balance} تومان",
            reply_markup=admin_markup
        )
        try:
            await app.send_message(
                target,
                f"🔻 از موجودی شما {amount} تومان کسر شد. موجودی فعلی: {new_balance} تومان"
            )
        except Exception:
            pass

        try:
            t_user = await app.get_users(target)
            t_un = t_user.username
        except Exception:
            t_un = None

        log_text = (
            "📉 کاهش موجودی کاربر\n\n"
            f"👤 ادمین انجام‌دهنده: <a href=\"tg://user?id={uid}\">{uid}</a>\n\n"
            f"👤 کاربر: <a href=\"tg://user?id={target}\">{target}</a>\n\n"
            f"💸 مبلغ کم شده: {amount} تومان\n\n"
            f"💳 موجودی جدید: {new_balance} تومان\n\n"
            f"⏰ زمان: {JalaliDatetime.now().strftime('%Y/%m/%d %H:%M:%S')}"
        )
        await send_admin_log_text(log_text, target_id=target, target_username=t_un)
        return

    # ---------- BLOCK ----------
    if mode == StateMode.BLOCK:
        state.set_mode(uid, None)
        if not text.isdigit():
            await m.reply("❌ آیدی نامعتبر است.", reply_markup=admin_markup)
            return
        target = int(text)
        if target in ADMINS:
            await m.reply("❌ نمی‌توانید مدیر را بلاک کنید.", reply_markup=admin_markup)
            return
        users.set_blocked(target, True)
        await m.reply(f"🚫 کاربر {target} بلاک شد.", reply_markup=admin_markup)
        try:
            await app.send_message(target, "🚫 شما توسط ادمین بلاک شدید.")
        except Exception:
            pass

        try:
            t_user = await app.get_users(target)
            t_un = t_user.username
        except Exception:
            t_un = None

        log_text = (
            "🚫 بلاک کاربر\n\n"
            f"👤 ادمین: <a href=\"tg://user?id={uid}\">{uid}</a>\n\n"
            f"👤 کاربر بلاک شده: <a href=\"tg://user?id={target}\">{target}</a>\n\n"
            f"⏰ زمان: {JalaliDatetime.now().strftime('%Y/%m/%d %H:%M:%S')}"
        )
        await send_admin_log_text(log_text, target_id=target, target_username=t_un)
        return

    # ---------- UNBLOCK ----------
    if mode == StateMode.UNBLOCK:
        state.set_mode(uid, None)
        if not text.isdigit():
            await m.reply("❌ آیدی نامعتبر است.", reply_markup=admin_markup)
            return
        target = int(text)
        users_all = users.all_users()
        if str(target) not in users_all or not users_all[str(target)].get("blocked", False):
            await m.reply("⚠️ این کاربر بلاک نیست.", reply_markup=admin_markup)
            return
        users.set_blocked(target, False)
        await m.reply(f"♻ کاربر {target} آنبلاک شد.", reply_markup=admin_markup)
        try:
            await app.send_message(target, "♻ دسترسی شما به ربات باز شد.")
        except Exception:
            pass

        try:
            t_user = await app.get_users(target)
            t_un = t_user.username
        except Exception:
            t_un = None

        log_text = (
            "♻ آنبلاک کاربر\n\n"
            f"👤 ادمین: <a href=\"tg://user?id={uid}\">{uid}</a>\n\n"
            f"👤 کاربر آنبلاک شده: <a href=\"tg://user?id={target}\">{target}</a>\n\n"
            f"⏰ زمان: {JalaliDatetime.now().strftime('%Y/%m/%d %H:%M:%S')}"
        )
        await send_admin_log_text(log_text, target_id=target, target_username=t_un)
        return

    # ---------- BROADCAST ----------
    if mode == StateMode.BROADCAST:
        state.set_mode(uid, None)
        text_to_send = text
        all_users = users.all_users()
        sent = 0
        failed = 0
        for uid_str in list(all_users.keys()):
            try:
                uid_i = int(uid_str)
                if all_users[uid_str].get("blocked", False):
                    continue
                await app.send_message(uid_i, text_to_send)
                sent += 1
                await asyncio.sleep(0.05)
            except Exception:
                failed += 1
                await asyncio.sleep(0.05)
        await m.reply(
            f"📢 ارسال همگانی انجام شد.\n\n✅ ارسال شده: {sent}\n\n❌ ناموفق: {failed}",
            reply_markup=admin_markup
        )
        return

    # ---------- EDIT ACCOUNT PRICE ----------
    if mode == StateMode.EDIT_ACCOUNT_PRICE:
        parts = text.split()
        if len(parts) != 2:
            await m.reply("❌ فرمت اشتباه. مثال: +989123456789 150000", reply_markup=admin_markup)
            state.set_mode(uid, None)
            return
        phone, price_str = parts
        if not price_str.isdigit():
            await m.reply("❌ قیمت باید عدد باشد.", reply_markup=admin_markup)
            state.set_mode(uid, None)
            return
        price = int(price_str)
        ok = accounts.set_price(phone, price)
        if not ok:
            await m.reply("❌ این شماره در سیستم ثبت نشده است.", reply_markup=admin_markup)
        else:
            await m.reply(f"✔ قیمت اکانت {phone} به {price} تومان تغییر یافت.", reply_markup=admin_markup)
        state.set_mode(uid, None)
        return

    # ---------- DELETE ACCOUNT ----------
    if mode == StateMode.DELETE_ACCOUNT:
        phone = text
        acc = accounts.get(phone)
        ok = accounts.delete(phone)
        if ok:
            await m.reply(f"🗑 اکانت {phone} حذف شد.", reply_markup=admin_markup)
        else:
            await m.reply("❌ این شماره در سیستم یافت نشد.", reply_markup=admin_markup)
        state.set_mode(uid, None)

        if ok and acc:
            tag = acc.get("tag") or "-"
            scam_status = "اسکم ✅" if is_scam_tag(tag) else "نرمال ✅"
            log_text = (
                "🗑 حذف اکانت از سیستم\n\n"
                f"👤 ادمین: <a href=\"tg://user?id={uid}\">{uid}</a>\n\n"
                f"📱 شماره: <code>{html.escape(phone)}</code>\n\n"
                f"🏷 برچسب: {html.escape(tag)} | ⚠️ {scam_status}\n\n"
                f"⏰ زمان: {JalaliDatetime.now().strftime('%Y/%m/%d %H:%M:%S')}"
            )
            await send_admin_log_text(log_text, target_id=uid, target_username=None)
        return

    # ---------- DELETE SCAM ACCOUNT ----------
    if mode == StateMode.DELETE_SCAM_ACCOUNT:
        phone = text
        acc = accounts.get(phone)
        if not acc:
            await m.reply("❌ این شماره در سیستم یافت نشد.", reply_markup=admin_markup)
            state.set_mode(uid, None)
            return

        tag = acc.get("tag") or "-"
        if not is_scam_tag(tag):
            await m.reply("⚠️ این اکانت به عنوان اسکم ثبت نشده است.", reply_markup=admin_markup)
            state.set_mode(uid, None)
            return

        ok = accounts.delete(phone)
        if ok:
            await m.reply(f"🧹 اکانت اسکم {phone} حذف شد.", reply_markup=admin_markup)

            log_text = (
                "🧹 حذف اکانت اسکم\n\n"
                f"👤 ادمین: <a href=\"tg://user?id={uid}\">{uid}</a>\n\n"
                f"📱 شماره: <code>{html.escape(phone)}</code>\n\n"
                f"🏷 برچسب: {html.escape(tag)} | ⚠️ اسکم ✅\n\n"
                f"⏰ زمان: {JalaliDatetime.now().strftime('%Y/%m/%d %H:%M:%S')}"
            )
            await send_admin_log_text(log_text, target_id=uid, target_username=None)
        else:
            await m.reply("❌ خطا در حذف اکانت.", reply_markup=admin_markup)

        state.set_mode(uid, None)
        return


# ---------------- Run ----------------
if __name__ == "__main__":
    print("🚀 ربات فروش شماره + شارژ خودکار ترون (نسخه پیشرفته) در حال اجراست...")
    app.run()
