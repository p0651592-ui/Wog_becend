from __future__ import annotations

import json
import logging
import secrets
from typing import Any

import requests
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.api.schemas import (
    AdminActionPayload,
    AdminSearchPayload,
    BalancePayload,
    GameRoundPayload,
    InitDataPayload,
    PayoutPayload,
    WheelClassicSpinPayload,
)
from app.api.wheel_plus import router as wheel_plus_router
from app.core.config import settings
from app.db.base import Base
from app.db.models import AdminAuditLog, GameRound, PlayerStats, User, Wallet
from app.db.session import engine, get_db
from app.services.stats_service import StatsService
from app.services.telegram_auth import verify_telegram_init_data
from app.services.wallet_service import WalletService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("wog.backend")

app = FastAPI(title=settings.project_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.cors_origins == ["*"] else settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(wheel_plus_router)

AMERICAN_WHEEL_SEQUENCE = [
    "0", "28", "9", "26", "30", "11", "7", "20", "32", "17", "5", "22",
    "34", "15", "3", "24", "36", "13", "1", "00", "27", "10", "25", "29",
    "12", "8", "19", "31", "18", "6", "21", "33", "16", "4", "23", "35",
    "14", "2",
]

RED_NUMBERS = {"1", "3", "5", "7", "9", "12", "14", "16", "18", "19", "21", "23", "25", "27", "30", "32", "34", "36"}
BLACK_NUMBERS = {"2", "4", "6", "8", "10", "11", "13", "15", "17", "20", "22", "24", "26", "28", "29", "31", "33", "35"}

ADMIN_PANEL_HTML = """<!DOCTYPE html>
<html lang=\"ru\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0, viewport-fit=cover\" />
  <meta name=\"theme-color\" content=\"#0b0e17\" />
  <title>WOG Admin</title>
  <script src=\"https://telegram.org/js/telegram-web-app.js\"></script>
  <style>
    :root{--bg:#0b0e17;--card:#151923;--inner:#1c2130;--border:#222938;--blue:#2f6bf2;--gold:#ffca28;--green:#05c46b;--red:#ff3838;--text:#fff;--muted:#64748b;--shadow:0 10px 35px rgba(0,0,0,.35);--r:16px}
    *{box-sizing:border-box;margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,\"Segoe UI\",Roboto,sans-serif}
    body{background:var(--bg);color:var(--text);padding:16px;min-height:100vh;display:flex;justify-content:center}
    .app{width:100%;max-width:980px;display:flex;flex-direction:column;gap:14px}
    .topbar,.card,.grid-card,.panel{background:var(--card);border:1px solid var(--border);border-radius:var(--r);box-shadow:var(--shadow)}
    .topbar{padding:16px;display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap}
    .pill{display:inline-flex;align-items:center;gap:6px;padding:6px 10px;border-radius:999px;background:#101523;border:1px solid var(--border);font-size:12px;font-weight:800;color:var(--muted)}
    .btn{border:none;border-radius:12px;padding:11px 14px;font-weight:900;cursor:pointer;color:var(--text);background:var(--blue)}
    .btn.secondary{background:#171a26;border:1px solid var(--border)}
    .btn.danger{background:var(--red)}
    .grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}
    .grid-card{padding:14px;display:flex;flex-direction:column;gap:6px;min-height:92px}
    .grid-card .label{font-size:11px;color:var(--muted);font-weight:800;text-transform:uppercase;letter-spacing:.6px}
    .grid-card .value{font-size:22px;font-weight:900}
    .layout{display:grid;grid-template-columns:1.2fr .8fr;gap:12px}
    .panel{padding:14px;display:flex;flex-direction:column;gap:10px}
    .panel h3{font-size:15px;margin-bottom:2px}
    .panel p,.muted{color:var(--muted);font-size:12px;line-height:1.45}
    .form-row{display:grid;grid-template-columns:repeat(2,1fr);gap:10px}
    input,select{width:100%;background:var(--inner);border:1px solid var(--border);border-radius:12px;color:var(--text);padding:11px 12px;font-size:14px;outline:none}
    .table-wrap{overflow:auto;border-radius:12px;border:1px solid var(--border)}
    table{width:100%;border-collapse:collapse;min-width:760px;background:#101523}
    th,td{padding:10px 12px;border-bottom:1px solid var(--border);text-align:left;font-size:12px;vertical-align:top}
    th{position:sticky;top:0;background:#0f1320;z-index:1;font-size:11px;text-transform:uppercase;letter-spacing:.4px;color:var(--muted)}
    tr:hover td{background:#121727}
    .tag{padding:3px 8px;border-radius:999px;font-size:11px;font-weight:900;display:inline-block}
    .tag.active{background:rgba(5,196,107,.12);color:var(--green)}
    .tag.blocked{background:rgba(255,56,56,.12);color:var(--red)}
    .tag.user{background:rgba(47,107,242,.12);color:#9dc0ff}
    .tag.admin{background:rgba(255,202,40,.12);color:var(--gold)}
    .actions{display:flex;gap:8px;flex-wrap:wrap}
    @media (max-width: 900px){.grid,.layout,.form-row{grid-template-columns:1fr 1fr}.layout{grid-template-columns:1fr}}
    @media (max-width: 640px){.grid,.layout,.form-row{grid-template-columns:1fr}.topbar{align-items:flex-start}}
  </style>
</head>
<body>
  <div class=\"app\">
    <div class=\"topbar\">
      <div>
        <div style=\"font-size:18px;font-weight:900\">WOG Admin Panel</div>
        <div class=\"muted\" id=\"admin-subtitle\">Подключение к backend...</div>
      </div>
      <div class=\"actions\">
        <span class=\"pill\" id=\"admin-status\">loading</span>
        <button class=\"btn secondary\" id=\"refresh-btn\" type=\"button\">Обновить</button>
        <button class=\"btn\" id=\"sync-btn\" type=\"button\">Синхронизировать</button>
      </div>
    </div>

    <div class=\"grid\">
      <div class=\"grid-card\"><div class=\"label\">Пользователи</div><div class=\"value\" id=\"metric-users\">0</div><div class=\"muted\">Всего аккаунтов</div></div>
      <div class=\"grid-card\"><div class=\"label\">Активные</div><div class=\"value\" id=\"metric-active\">0</div><div class=\"muted\">Статус active</div></div>
      <div class=\"grid-card\"><div class=\"label\">Игры</div><div class=\"value\" id=\"metric-rounds\">0</div><div class=\"muted\">Всего раундов</div></div>
      <div class=\"grid-card\"><div class=\"label\">Баланс в системе</div><div class=\"value\" id=\"metric-balance\">0</div><div class=\"muted\">Сумма WC по кошелькам</div></div>
    </div>

    <div class=\"layout\">
      <div class=\"panel\">
        <div class=\"actions\" style=\"justify-content:space-between;align-items:center\">
          <div>
            <h3>Игроки</h3>
            <p>Баланс, статус и роль. Действия работают только для администраторов из `ADMIN_TELEGRAM_IDS`.</p>
          </div>
          <input id=\"user-search\" type=\"text\" placeholder=\"Поиск по имени или Telegram ID\" style=\"max-width:280px\" />
        </div>
        <div class=\"table-wrap\">
          <table>
            <thead>
              <tr><th>Telegram</th><th>Профиль</th><th>Баланс</th><th>Статус</th><th>Роль</th><th>Действия</th></tr>
            </thead>
            <tbody id=\"users-body\"></tbody>
          </table>
        </div>
      </div>

      <div class=\"panel\">
        <div>
          <h3>Быстрые действия</h3>
          <p>Начисление, списание, смена статуса и роли.</p>
        </div>
        <div class=\"form-row\">
          <input id=\"action-telegram-id\" type=\"number\" min=\"1\" placeholder=\"Telegram ID\" />
          <select id=\"action-type\">
            <option value=\"grant_balance\">Начислить WC</option>
            <option value=\"withdraw_balance\">Списать WC</option>
            <option value=\"set_status\">Изменить статус</option>
            <option value=\"set_role\">Изменить роль</option>
          </select>
        </div>
        <div class=\"form-row\">
          <input id=\"action-amount\" type=\"number\" min=\"0\" placeholder=\"Сумма WC\" value=\"0\" />
          <select id=\"action-status\"><option value=\"active\">active</option><option value=\"blocked\">blocked</option></select>
        </div>
        <div class=\"form-row\">
          <select id=\"action-role\"><option value=\"user\">user</option><option value=\"moderator\">moderator</option><option value=\"admin\">admin</option><option value=\"owner\">owner</option></select>
          <input id=\"action-note\" type=\"text\" placeholder=\"Комментарий\" />
        </div>
        <button class=\"btn\" id=\"apply-action-btn\" type=\"button\">Выполнить</button>
        <div class=\"panel\" style=\"padding:12px;background:#101523\">
          <div style=\"font-size:13px;font-weight:900\">Последние раунды</div>
          <div class=\"table-wrap\"><table style=\"min-width:520px\"><thead><tr><th>ID</th><th>Игра</th><th>Ставка</th><th>Выплата</th><th>Результат</th></tr></thead><tbody id=\"rounds-body\"></tbody></table></div>
        </div>
        <div class=\"panel\" style=\"padding:12px;background:#101523\">
          <div style=\"font-size:13px;font-weight:900\">Аудит</div>
          <div class=\"table-wrap\"><table style=\"min-width:520px\"><thead><tr><th>Время</th><th>Действие</th><th>Цель</th><th>Сумма</th></tr></thead><tbody id=\"audit-body\"></tbody></table></div>
        </div>
      </div>
    </div>
  </div>

  <script>
    const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
    const API_BASE = (window.WOG_CONFIG && window.WOG_CONFIG.API_BASE_URL) ? String(window.WOG_CONFIG.API_BASE_URL).replace(/\/$/, '') : '';
    const state = { initData: tg && tg.initData ? tg.initData : '', summary: null, users: [], rounds: [], audit: [] };
    const $ = (id) => document.getElementById(id);
    const apiUrl = (path) => `${API_BASE}${path.startsWith('/') ? path : `/${path}`}`;

    function notify(message) { if (tg && typeof tg.showAlert === 'function') tg.showAlert(String(message)); else alert(String(message)); }

    async function requestJson(path, payload) {
      const response = await fetch(apiUrl(path), { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
      let data = null; try { data = await response.json(); } catch (_) {}
      if (!response.ok) throw new Error((data && (data.detail || data.message)) ? (data.detail || data.message) : `Ошибка сервера (${response.status})`);
      return data;
    }

    const fmt = (n) => Number(n || 0).toLocaleString('ru-RU');
    const safeText = (v) => String(v ?? '');
    const badge = (status, role) => {
      const s = safeText(status).toLowerCase();
      const r = safeText(role).toLowerCase();
      const statusClass = s === 'blocked' ? 'blocked' : 'active';
      const roleClass = r === 'admin' || r === 'owner' ? 'admin' : r === 'moderator' ? 'user' : 'user';
      return `<span class=\"tag ${statusClass}\">${s || 'active'}</span> <span class=\"tag ${roleClass}\">${r || 'user'}</span>`;
    };

    function renderSummary() {
      const s = state.summary || {};
      $('metric-users').textContent = fmt(s.users_count);
      $('metric-active').textContent = fmt(s.active_users_count);
      $('metric-rounds').textContent = fmt(s.rounds_count);
      $('metric-balance').textContent = fmt(s.total_balance);
      $('admin-status').textContent = s.admin_access ? 'ADMIN' : 'DENIED';
      $('admin-subtitle').textContent = s.admin_access ? 'Доступ подтверждён' : 'Доступ запрещён';
    }

    function renderUsers() {
      $('users-body').innerHTML = state.users.map((u) => `
        <tr>
          <td>${safeText(u.telegram_id)}</td>
          <td><div style=\"font-weight:900\">${safeText(u.name)}</div><div class=\"muted\">${safeText(u.created_at)}</div></td>
          <td><b>${fmt(u.balance)}</b> WC<br><span class=\"muted\">звёзды: ${fmt(u.stars_balance)}</span></td>
          <td>${badge(u.status, u.role)}</td>
          <td><b>${safeText(u.role)}</b></td>
          <td><div class=\"actions\"><button class=\"btn secondary\" type=\"button\" onclick=\"prefillUser(${u.telegram_id}, '${safeText(u.role)}', '${safeText(u.status)}')\">Выбрать</button><button class=\"btn danger\" type=\"button\" onclick=\"quickStatus(${u.telegram_id}, '${safeText(u.status) === 'blocked' ? 'active' : 'blocked'}')\">${safeText(u.status) === 'blocked' ? 'Разблок' : 'Блок'}</button></div></td>
        </tr>
      `).join('');
    }

    function renderRounds() {
      $('rounds-body').innerHTML = state.rounds.map((r) => `<tr><td>#${r.id}</td><td>${safeText(r.game_type)}</td><td>${fmt(r.bet)}</td><td>${fmt(r.payout)}</td><td>${safeText(r.result)}</td></tr>`).join('');
    }

    function renderAudit() {
      $('audit-body').innerHTML = state.audit.map((a) => `<tr><td>${safeText(a.created_at)}</td><td>${safeText(a.action)}</td><td>${safeText(a.target)}</td><td>${fmt(a.amount)}</td></tr>`).join('');
    }

    async function loadSummary() {
      const data = await requestJson('/api/admin/summary', { init_data: state.initData });
      state.summary = data.summary;
      state.users = data.users || [];
      state.rounds = data.rounds || [];
      state.audit = data.audit || [];
      renderSummary(); renderUsers(); renderRounds(); renderAudit();
    }

    async function refreshPanel() { await loadSummary(); notify('Панель обновлена'); }

    window.prefillUser = function prefillUser(telegramId, role, status) {
      $('action-telegram-id').value = telegramId;
      $('action-role').value = role || 'user';
      $('action-status').value = status || 'active';
    };

    window.quickStatus = async function quickStatus(telegramId, status) {
      $('action-telegram-id').value = telegramId;
      $('action-type').value = 'set_status';
      $('action-status').value = status;
      await applyAction();
    };

    async function applyAction() {
      const telegramId = Number($('action-telegram-id').value || 0);
      const action = $('action-type').value;
      const amount = Number($('action-amount').value || 0);
      const role = $('action-role').value;
      const status = $('action-status').value;
      const note = $('action-note').value || '';
      if (!telegramId) { notify('Укажи Telegram ID'); return; }
      const payload = { init_data: state.initData, telegram_id: telegramId, action, amount, role, status, note };
      const data = await requestJson('/api/admin/action', payload);
      state.summary = data.summary; state.users = data.users || state.users; state.rounds = data.rounds || state.rounds; state.audit = data.audit || state.audit;
      renderSummary(); renderUsers(); renderRounds(); renderAudit();
      notify('Действие выполнено');
    }

    $('refresh-btn').addEventListener('click', refreshPanel);
    $('sync-btn').addEventListener('click', applyAction);
    $('apply-action-btn').addEventListener('click', applyAction);
    $('user-search').addEventListener('input', async (e) => {
      const query = String(e.target.value || '');
      const data = await requestJson('/api/admin/users', { init_data: state.initData, query, limit: 50 });
      state.users = data.users || [];
      renderUsers();
    });

    async function boot() {
      if (tg && typeof tg.ready === 'function') tg.ready();
      if (tg && typeof tg.expand === 'function') tg.expand();
      try { await loadSummary(); } catch (error) { console.error(error); notify(error.message || 'Нет доступа к админке'); }
    }

    boot();
  </script>
</body>
</html>"""


@app.on_event("startup")
def on_startup() -> None:
    Base.metadata.create_all(bind=engine)


def _ensure_user(session: Session, init_data: str) -> tuple[User, dict[str, Any]]:
    if not settings.telegram_bot_token:
        raise HTTPException(status_code=500, detail="TELEGRAM_BOT_TOKEN is not configured")

    telegram_user = verify_telegram_init_data(init_data, settings.telegram_bot_token)
    if not telegram_user:
        raise HTTPException(status_code=403, detail="Telegram authentication failed")

    telegram_id = int(telegram_user["id"])
    username = str(telegram_user.get("username") or "")
    first_name = str(telegram_user.get("first_name") or telegram_user.get("last_name") or "noname")

    user = WalletService.get_or_create_user(session, telegram_id, username=username, first_name=first_name)
    session.flush()
    return user, telegram_user


def _require_admin(session: Session, init_data: str) -> tuple[User, dict[str, Any]]:
    user, telegram_user = _ensure_user(session, init_data)
    if settings.admin_telegram_ids and user.telegram_id not in settings.admin_telegram_ids:
        raise HTTPException(status_code=403, detail="Admin access denied")
    if not settings.admin_telegram_ids:
        raise HTTPException(status_code=403, detail="Admin list is not configured")
    if user.status == "blocked":
        raise HTTPException(status_code=403, detail="Admin account is blocked")
    return user, telegram_user


def _admin_log(
    session: Session,
    actor_user_id: int | None,
    action: str,
    target_user_id: int | None = None,
    amount: int = 0,
    meta: dict[str, Any] | None = None,
) -> None:
    session.add(
        AdminAuditLog(
            actor_user_id=actor_user_id,
            target_user_id=target_user_id,
            action=action,
            amount=amount,
            meta_json=json.dumps(meta or {}, ensure_ascii=False),
        )
    )


def _roulette_result_for_spin() -> str:
    return secrets.choice(AMERICAN_WHEEL_SEQUENCE)


def _roulette_color(value: str) -> str:
    if value in {"0", "00"}:
        return "green"
    if value in RED_NUMBERS:
        return "red"
    if value in BLACK_NUMBERS:
        return "black"
    return "green"


def _roulette_win_multiplier(bet_type: str, chosen_number: str, result: str) -> int:
    if bet_type == "number":
        return 35 if chosen_number == result else 0
    if bet_type in {"red", "black", "even", "odd", "low", "high"}:
        if result in {"0", "00"}:
            return 0
        number = int(result)
        if bet_type == "red" and result in RED_NUMBERS:
            return 1
        if bet_type == "black" and result in BLACK_NUMBERS:
            return 1
        if bet_type == "even" and number % 2 == 0:
            return 1
        if bet_type == "odd" and number % 2 == 1:
            return 1
        if bet_type == "low" and 1 <= number <= 18:
            return 1
        if bet_type == "high" and 19 <= number <= 36:
            return 1
    if bet_type in {"dozen1", "dozen2", "dozen3"}:
        if result in {"0", "00"}:
            return 0
        number = int(result)
        if bet_type == "dozen1" and 1 <= number <= 12:
            return 2
        if bet_type == "dozen2" and 13 <= number <= 24:
            return 2
        if bet_type == "dozen3" and 25 <= number <= 36:
            return 2
    if bet_type in {"column1", "column2", "column3"}:
        if result in {"0", "00"}:
            return 0
        number = int(result)
        column = ((number - 1) % 3) + 1
        if (bet_type == "column1" and column == 1) or (bet_type == "column2" and column == 2) or (bet_type == "column3" and column == 3):
            return 2
    return 0


@app.get("/")
def root() -> dict[str, Any]:
    return {"status": "ok", "service": settings.project_name}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "healthy"}


@app.get("/admin", response_class=HTMLResponse)
def admin_panel() -> HTMLResponse:
    return HTMLResponse(ADMIN_PANEL_HTML)


@app.post("/api/auth/telegram")
def auth_telegram(payload: InitDataPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    user, _ = _ensure_user(db, payload.init_data)
    db.commit()
    profile = StatsService.build_profile_payload(db, user)
    profile["text"] = StatsService.format_profile_text(profile)
    return profile


@app.get("/api/profile/{telegram_id}")
def get_profile_by_telegram_id(telegram_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    user = db.scalar(select(User).where(User.telegram_id == telegram_id))
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    profile = StatsService.build_profile_payload(db, user)
    profile["text"] = StatsService.format_profile_text(profile)
    return profile


@app.post("/api/profile/me")
def get_my_profile(payload: InitDataPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    user, _ = _ensure_user(db, payload.init_data)
    profile = StatsService.build_profile_payload(db, user)
    profile["text"] = StatsService.format_profile_text(profile)
    return profile


@app.post("/api/user/balance")
def get_user_balance(payload: BalancePayload, db: Session = Depends(get_db)) -> dict[str, int]:
    user, _ = _ensure_user(db, payload.init_data)
    db.commit()
    snapshot = WalletService.get_snapshot(db, user.id)
    return {"balance": snapshot.balance}


@app.post("/api/admin/summary")
def admin_summary(payload: AdminSearchPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    actor, _ = _require_admin(db, payload.init_data)
    users_count = db.scalar(select(func.count(User.id))) or 0
    active_users_count = db.scalar(select(func.count(User.id)).where(User.status == "active")) or 0
    rounds_count = db.scalar(select(func.count(GameRound.id))) or 0
    total_balance = db.scalar(select(func.coalesce(func.sum(Wallet.balance), 0))) or 0
    total_stars = db.scalar(select(func.coalesce(func.sum(Wallet.stars_balance), 0))) or 0
    top_users = (
        db.execute(
            select(User, Wallet, PlayerStats)
            .join(Wallet, Wallet.user_id == User.id)
            .join(PlayerStats, PlayerStats.user_id == User.id, isouter=True)
            .order_by(desc(Wallet.balance))
            .limit(8)
        )
        .all()
    )
    recent_rounds = db.execute(select(GameRound).order_by(desc(GameRound.created_at)).limit(10)).scalars().all()
    audit_rows = db.execute(select(AdminAuditLog).order_by(desc(AdminAuditLog.created_at)).limit(10)).scalars().all()
    return {
        "summary": {
            "admin_access": True,
            "actor_telegram_id": actor.telegram_id,
            "users_count": users_count,
            "active_users_count": active_users_count,
            "rounds_count": rounds_count,
            "total_balance": total_balance,
            "total_stars": total_stars,
        },
        "users": [
            {
                "telegram_id": user.telegram_id,
                "name": user.username or user.first_name or "noname",
                "balance": wallet.balance,
                "stars_balance": wallet.stars_balance,
                "status": user.status,
                "role": user.role,
                "created_at": user.created_at.isoformat(),
                "games_count": stats.games_count if stats else 0,
                "max_balance": stats.max_balance if stats else wallet.balance,
                "max_multiplier": stats.max_multiplier if stats else 0,
            }
            for user, wallet, stats in top_users
        ],
        "rounds": [
            {
                "id": round_row.id,
                "game_type": round_row.game_type,
                "bet": round_row.bet,
                "payout": round_row.payout,
                "result": json.loads(round_row.result_json).get("result", ""),
                "created_at": round_row.created_at.isoformat(),
            }
            for round_row in recent_rounds
        ],
        "audit": [
            {
                "created_at": row.created_at.isoformat(),
                "action": row.action,
                "target": row.target_user_id,
                "amount": row.amount,
            }
            for row in audit_rows
        ],
    }


@app.post("/api/admin/users")
def admin_users(payload: AdminSearchPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    _require_admin(db, payload.init_data)
    search_text = payload.query.strip().lower()
    query = (
        select(User, Wallet, PlayerStats)
        .join(Wallet, Wallet.user_id == User.id)
        .join(PlayerStats, PlayerStats.user_id == User.id, isouter=True)
        .order_by(desc(User.updated_at))
    )
    rows = db.execute(query).all()
    users = []
    for user, wallet, stats in rows:
        name = f"{user.username} {user.first_name}".strip().lower()
        if search_text and search_text not in name and search_text not in str(user.telegram_id):
            continue
        users.append(
            {
                "telegram_id": user.telegram_id,
                "name": user.username or user.first_name or "noname",
                "balance": wallet.balance,
                "stars_balance": wallet.stars_balance,
                "status": user.status,
                "role": user.role,
                "created_at": user.created_at.isoformat(),
                "games_count": stats.games_count if stats else 0,
                "max_balance": stats.max_balance if stats else wallet.balance,
                "max_multiplier": stats.max_multiplier if stats else 0,
            }
        )
        if len(users) >= payload.limit:
            break
    return {"users": users}


@app.post("/api/admin/rounds")
def admin_rounds(payload: AdminSearchPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    _require_admin(db, payload.init_data)
    rounds = db.execute(select(GameRound).order_by(desc(GameRound.created_at)).limit(payload.limit)).scalars().all()
    return {
        "rounds": [
            {
                "id": row.id,
                "user_id": row.user_id,
                "game_type": row.game_type,
                "bet": row.bet,
                "payout": row.payout,
                "multiplier": row.multiplier,
                "result": json.loads(row.result_json).get("result", ""),
                "created_at": row.created_at.isoformat(),
            }
            for row in rounds
        ]
    }


@app.post("/api/admin/audit")
def admin_audit(payload: AdminSearchPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    _require_admin(db, payload.init_data)
    logs = db.execute(select(AdminAuditLog).order_by(desc(AdminAuditLog.created_at)).limit(payload.limit)).scalars().all()
    return {
        "audit": [
            {
                "created_at": row.created_at.isoformat(),
                "action": row.action,
                "target": row.target_user_id,
                "amount": row.amount,
            }
            for row in logs
        ]
    }


@app.post("/api/admin/action")
def admin_action(payload: AdminActionPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    actor, _ = _require_admin(db, payload.init_data)
    target = db.scalar(select(User).where(User.telegram_id == payload.telegram_id))
    if target is None:
        raise HTTPException(status_code=404, detail="Target user not found")

    wallet = db.scalar(select(Wallet).where(Wallet.user_id == target.id).with_for_update())
    if wallet is None:
        raise HTTPException(status_code=404, detail="Wallet not found")

    action = payload.action.strip().lower()
    meta: dict[str, Any] = {"note": payload.status if action == "set_status" else payload.role}

    if action == "grant_balance":
        if payload.amount <= 0:
            raise HTTPException(status_code=400, detail="Amount must be positive")
        WalletService.deposit(db, target.id, payload.amount, tx_type="admin_grant", meta={"actor": actor.telegram_id, **meta})
        _admin_log(db, actor.id, "grant_balance", target.id, payload.amount, meta)
    elif action == "withdraw_balance":
        if payload.amount <= 0:
            raise HTTPException(status_code=400, detail="Amount must be positive")
        WalletService.withdraw(db, target.id, payload.amount, tx_type="admin_withdraw", meta={"actor": actor.telegram_id, **meta})
        _admin_log(db, actor.id, "withdraw_balance", target.id, -payload.amount, meta)
    elif action == "set_status":
        if payload.status.strip() not in {"active", "blocked"}:
            raise HTTPException(status_code=400, detail="Invalid status")
        target.status = payload.status.strip()
        _admin_log(db, actor.id, "set_status", target.id, 0, {"status": target.status})
    elif action == "set_role":
        if payload.role.strip() not in {"user", "moderator", "admin", "owner"}:
            raise HTTPException(status_code=400, detail="Invalid role")
        target.role = payload.role.strip()
        _admin_log(db, actor.id, "set_role", target.id, 0, {"role": target.role})
    else:
        raise HTTPException(status_code=400, detail="Unknown admin action")

    db.commit()
    return {
        "status": "success",
        "summary": admin_summary(AdminSearchPayload(init_data=payload.init_data, limit=20), db)["summary"],
        "users": admin_users(AdminSearchPayload(init_data=payload.init_data, query="", limit=20), db)["users"],
        "rounds": admin_rounds(AdminSearchPayload(init_data=payload.init_data, query="", limit=10), db)["rounds"],
        "audit": admin_audit(AdminSearchPayload(init_data=payload.init_data, query="", limit=10), db)["audit"],
    }


@app.post("/api/wheel-classic/spin")
def spin_wheel_classic(payload: WheelClassicSpinPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    user, _ = _ensure_user(db, payload.init_data)
    if payload.bet > 0:
        WalletService.place_bet(db, user.id, payload.bet, meta={"game": "wheel_classic", "bet_type": payload.bet_type, "number": payload.number})

    result = _roulette_result_for_spin()
    multiplier = _roulette_win_multiplier(payload.bet_type, payload.number.strip(), result)
    payout = payload.bet * multiplier if multiplier > 0 else 0

    if payout > 0:
        WalletService.payout(db, user.id, payout, meta={"game": "wheel_classic", "result": result})

    round_row = GameRound(
        user_id=user.id,
        game_type="wheel_classic",
        bet=payload.bet,
        payout=payout,
        multiplier=multiplier,
        client_seed=payload.client_seed,
        server_seed_hash=secrets.token_hex(16),
        server_seed=secrets.token_hex(32),
        nonce=secrets.randbelow(1_000_000),
        result_json=json.dumps(
            {
                "result": result,
                "color": _roulette_color(result),
                "bet_type": payload.bet_type,
                "chosen_number": payload.number,
                "payout": payout,
                "multiplier": multiplier,
            },
            ensure_ascii=False,
        ),
    )
    db.add(round_row)
    StatsService.update_after_round(db, user.id, bet=payload.bet, payout=payout, multiplier=multiplier)
    db.commit()

    profile = StatsService.build_profile_payload(db, user)
    profile["text"] = StatsService.format_profile_text(profile)
    snapshot = WalletService.get_snapshot(db, user.id)
    return {
        "status": "success",
        "game": "wheel_classic",
        "result": result,
        "color": _roulette_color(result),
        "balance": snapshot.balance,
        "payout": payout,
        "multiplier": multiplier,
        "profile": profile,
        "round": {
            "id": round_row.id,
            "bet": payload.bet,
            "bet_type": payload.bet_type,
            "chosen_number": payload.number,
            "client_seed": payload.client_seed,
            "server_seed_hash": round_row.server_seed_hash,
            "nonce": round_row.nonce,
        },
    }


@app.post("/api/wheel/payout")
def process_payout(payload: PayoutPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    user, _ = _ensure_user(db, payload.init_data)
    snapshot = WalletService.payout(db, user.id, payload.amount_won, meta={"source": "wheel"})
    StatsService.update_after_round(db, user.id, bet=0, payout=payload.amount_won, multiplier=0)
    db.commit()
    profile = StatsService.build_profile_payload(db, user)
    profile["balance"] = snapshot.balance
    profile["text"] = StatsService.format_profile_text(profile)
    return {"status": "success", "balance": snapshot.balance, "profile": profile}


@app.post("/api/games/round/finish")
def finish_game_round(payload: GameRoundPayload, db: Session = Depends(get_db)) -> dict[str, Any]:
    user, _ = _ensure_user(db, payload.init_data)

    if payload.bet > 0:
        WalletService.place_bet(db, user.id, payload.bet, meta={"game": payload.game_type})
    if payload.payout > 0:
        WalletService.payout(db, user.id, payload.payout, meta={"game": payload.game_type})

    round_row = GameRound(
        user_id=user.id,
        game_type=payload.game_type,
        bet=payload.bet,
        payout=payload.payout,
        multiplier=payload.multiplier,
        client_seed=payload.client_seed,
        server_seed_hash=payload.server_seed_hash,
        server_seed=payload.server_seed,
        nonce=payload.nonce,
        result_json=json.dumps(payload.result_json, ensure_ascii=False),
    )
    db.add(round_row)
    StatsService.update_after_round(db, user.id, bet=payload.bet, payout=payload.payout, multiplier=payload.multiplier)
    db.commit()

    profile = StatsService.build_profile_payload(db, user)
    profile["text"] = StatsService.format_profile_text(profile)
    return {
        "status": "success",
        "game_id": round_row.id,
        "profile": profile,
        "round": {
            "bet": payload.bet,
            "payout": payload.payout,
            "multiplier": payload.multiplier,
            "client_seed": payload.client_seed,
            "server_seed_hash": payload.server_seed_hash,
            "nonce": payload.nonce,
        },
    }


@app.post("/github-webhook")
async def github_webhook(request: Request) -> dict[str, str]:
    try:
        payload = await request.json()
        repo_name = payload.get("repository", {}).get("full_name") or payload.get("repository", {}).get("name", "Wog_Project")
        commits = payload.get("commits", [])
        lines = []
        for commit in commits[:5]:
            lines.append(f"• {commit.get('message')} (автор: {commit.get('author', {}).get('name')})")

        if settings.telegram_bot_token and settings.telegram_chat_id:
            message_text = f"🚀 Новый пуш в {repo_name}\n\n" + "\n".join(lines)
            requests.post(
                f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage",
                json={
                    "chat_id": settings.telegram_chat_id,
                    "text": message_text,
                    "parse_mode": "Markdown",
                    "disable_web_page_preview": True,
                },
                timeout=10,
            )
    except Exception as exc:  # pragma: no cover - webhook should never break app
        logger.exception("GitHub webhook failed: %s", exc)
    return {"status": "success"}
