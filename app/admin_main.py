from __future__ import annotations

from fastapi.responses import HTMLResponse

from app.api.admin import router as admin_router
from app.main import app

app.include_router(admin_router)


@app.get("/admin", response_class=HTMLResponse)
def admin_page() -> str:
    return """<!DOCTYPE html>
<html lang=\"ru\">
<head>
  <meta charset=\"UTF-8\" />
  <meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />
  <meta name=\"theme-color\" content=\"#0b0e17\" />
  <title>WOG Admin</title>
  <script src=\"https://telegram.org/js/telegram-web-app.js\"></script>
  <style>
    :root{--bg:#0b0e17;--card:#151923;--inner:#1c2130;--border:#222938;--blue:#2f6bf2;--gold:#ffca28;--cyan:#00d2d3;--green:#05c46b;--red:#ff3838;--text:#fff;--muted:#64748b;--shadow:0 10px 35px rgba(0,0,0,.35);--r:16px}
    *{box-sizing:border-box;margin:0;padding:0;font-family:-apple-system,BlinkMacSystemFont,\"Segoe UI\",Roboto,sans-serif}
    body{background:var(--bg);color:var(--text);padding:14px;min-height:100vh}
    .wrap{max-width:1100px;margin:0 auto;display:flex;flex-direction:column;gap:14px}
    .top{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
    .card{background:var(--card);border:1px solid var(--border);border-radius:var(--r);box-shadow:var(--shadow);padding:14px}
    .grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}
    .mini{background:var(--inner);border:1px solid var(--border);border-radius:14px;padding:12px}
    .mini .v{font-size:22px;font-weight:900;color:var(--gold)}
    .search-row{display:flex;gap:8px;flex-wrap:wrap}
    input,button{border:1px solid var(--border);border-radius:12px;background:var(--inner);color:var(--text);padding:12px 14px;font:inherit}
    button{cursor:pointer;font-weight:800}
    .primary{background:var(--blue);border:none}
    .danger{background:var(--red);border:none}
    .success{background:var(--green);border:none;color:#081018}
    table{width:100%;border-collapse:collapse;font-size:13px}
    th,td{padding:10px;border-bottom:1px solid rgba(255,255,255,.06);text-align:left;vertical-align:top}
    th{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.6px}
    .pill{display:inline-flex;align-items:center;padding:4px 8px;border-radius:999px;font-size:11px;font-weight:800}
    .pill.admin{background:rgba(255,202,40,.12);color:var(--gold)}
    .pill.blocked{background:rgba(255,56,56,.12);color:var(--red)}
    .pill.user{background:rgba(0,210,211,.08);color:var(--cyan)}
    .muted{color:var(--muted)}
    .cols{display:grid;grid-template-columns:1.2fr .8fr;gap:14px}
    @media (max-width: 900px){.grid,.cols{grid-template-columns:1fr 1fr}.cols{grid-template-columns:1fr}}
    @media (max-width: 560px){.grid{grid-template-columns:1fr}.search-row{flex-direction:column}}
  </style>
</head>
<body>
  <div class=\"wrap\">
    <div class=\"top\">
      <div>
        <div style=\"font-size:22px;font-weight:900\">WOG Admin</div>
        <div class=\"muted\" style=\"font-size:12px;margin-top:4px\">Панель управления игроками, балансом и аудитом</div>
      </div>
      <button class=\"primary\" onclick=\"reloadAll()\">Обновить</button>
    </div>

    <div class=\"card\">
      <div class=\"grid\" id=\"summary-grid\"></div>
    </div>

    <div class=\"cols\">
      <div class=\"card\">
        <div class=\"search-row\">
          <input id=\"search-input\" placeholder=\"Поиск по username, имени или Telegram ID\" style=\"flex:1;min-width:220px\" />
          <button class=\"primary\" onclick=\"searchUsers()\">Найти</button>
        </div>
        <div style=\"overflow:auto;margin-top:12px\">
          <table>
            <thead>
              <tr><th>Игрок</th><th>Баланс</th><th>Статус</th><th>Действия</th></tr>
            </thead>
            <tbody id=\"users-body\"></tbody>
          </table>
        </div>
      </div>

      <div class=\"card\">
        <div style=\"display:flex;justify-content:space-between;align-items:center;gap:10px\">
          <div style=\"font-size:16px;font-weight:900\">Аудит</div>
          <div class=\"muted\" style=\"font-size:12px\">последние действия</div>
        </div>
        <div id=\"audit-list\" style=\"margin-top:12px;display:flex;flex-direction:column;gap:8px\"></div>
      </div>
    </div>
  </div>

  <script>
    const tg = window.Telegram && window.Telegram.WebApp ? window.Telegram.WebApp : null;
    const API_BASE = (window.WOG_CONFIG && window.WOG_CONFIG.API_BASE_URL) ? String(window.WOG_CONFIG.API_BASE_URL).replace(/\/$/, '') : '';
    const initData = tg && tg.initData ? tg.initData : '';

    function apiUrl(path){ return `${API_BASE}${path.startsWith('/') ? path : '/' + path}`; }
    async function post(path, payload){
      const r = await fetch(apiUrl(path), {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.detail || data.message || 'Ошибка');
      return data;
    }

    function money(n){ return new Intl.NumberFormat('ru-RU').format(Number(n || 0)); }
    function esc(v){ return String(v ?? '').replace(/[&<>'\"]/g, s => ({'&':'&amp;','<':'&lt;','>':'&gt;','\'':'&#39;','\"':'&quot;'}[s])); }

    function renderSummary(summary){
      const items = [
        ['Игроки', summary.users_total],
        ['Админы', summary.admins_total],
        ['Баланс WC', summary.wallets_total],
        ['Раунды', summary.rounds_total],
        ['Транзакции', summary.transactions_total],
        ['Звёзды', summary.stars_total],
        ['Блоки', summary.blocked_total],
        ['Топ баланс', summary.top_balance],
      ];
      document.getElementById('summary-grid').innerHTML = items.map(([k,v]) => `<div class=\"mini\"><div class=\"muted\" style=\"font-size:11px;text-transform:uppercase\">${k}</div><div class=\"v\">${money(v)}</div></div>`).join('');
    }

    function pillFor(user){ return `<span class=\"pill ${user.role === 'owner' || user.role === 'admin' ? 'admin' : (user.status === 'blocked' ? 'blocked' : 'user')}\">${esc(user.role)}</span>`; }

    function actionButtons(user){
      return `
        <div style=\"display:flex;flex-wrap:wrap;gap:6px\">
          <button class=\"success\" onclick=\"bonus(${user.telegram_id})\">+WC</button>
          <button class=\"danger\" onclick=\"deduct(${user.telegram_id})\">-WC</button>
          ${user.status === 'blocked' ? `<button onclick=\"unblock(${user.telegram_id})\">Разблок</button>` : `<button class=\"danger\" onclick=\"block(${user.telegram_id})\">Блок</button>`}
          <button onclick=\"setRole(${user.telegram_id})\">Роль</button>
        </div>`;
    }

    function renderUsers(users){
      document.getElementById('users-body').innerHTML = users.map(u => `
        <tr>
          <td>
            <div style=\"font-weight:900\">${esc(u.first_name || u.username || 'noname')}</div>
            <div class=\"muted\" style=\"font-size:12px\">@${esc(u.username || '—')} · ${esc(u.telegram_id)}</div>
            <div style=\"margin-top:6px\">${pillFor(u)}</div>
          </td>
          <td>
            <div><b>${money(u.balance)} WC</b></div>
            <div class=\"muted\">⭐ ${money(u.stars_balance)}</div>
            <div class=\"muted\" style=\"font-size:12px;margin-top:6px\">Игры: ${money(u.games_count)} · Оборот: ${money(u.total_volume)}</div>
          </td>
          <td>${esc(u.status)}</td>
          <td>${actionButtons(u)}</td>
        </tr>
      `).join('');
    }

    function renderAudit(actions){
      const el = document.getElementById('audit-list');
      el.innerHTML = actions.length ? actions.map(a => `
        <div style=\"background:var(--inner);border:1px solid var(--border);border-radius:12px;padding:10px\">
          <div style=\"display:flex;justify-content:space-between;gap:10px\"><b>${esc(a.action)}</b><span class=\"muted\">${new Date(a.created_at).toLocaleString('ru-RU')}</span></div>
          <div class=\"muted\" style=\"font-size:12px;margin-top:4px\">actor: ${esc(a.actor_user_id)} · target: ${esc(a.target_user_id)} · amount: ${money(a.amount)}</div>
        </div>
      `).join('') : '<div class="muted">Пока пусто</div>';
    }

    async function reloadAll(){
      try{
        const data = await post('/api/admin/dashboard', { init_data: initData });
        renderSummary(data.summary || {});
        renderUsers(data.top_players || []);
        renderAudit(data.recent_actions || []);
      }catch(e){
        alert(e.message || 'Не удалось загрузить панель');
      }
    }

    async function searchUsers(){
      try{
        const query = document.getElementById('search-input').value || '';
        const data = await post('/api/admin/users/search', { init_data: initData, query, limit: 20 });
        renderUsers(data.users || []);
      }catch(e){ alert(e.message || 'Поиск не удался'); }
    }

    async function action(action, telegram_id, extra={}){
      const payload = Object.assign({ init_data: initData, telegram_id, action }, extra);
      const data = await post('/api/admin/user/action', payload);
      await reloadAll();
      if (tg && tg.showAlert) tg.showAlert('Готово'); else alert('Готово');
      return data;
    }

    function bonus(id){ const amount = Number(prompt('Сколько WC выдать?', '1000') || 0); if (amount>0) action('bonus', id, {amount}).catch(e => alert(e.message)); }
    function deduct(id){ const amount = Number(prompt('Сколько WC списать?', '1000') || 0); if (amount>0) action('deduct', id, {amount}).catch(e => alert(e.message)); }
    function block(id){ action('block', id).catch(e => alert(e.message)); }
    function unblock(id){ action('unblock', id).catch(e => alert(e.message)); }
    function setRole(id){ const role = prompt('Роль: user / moderator / admin / owner', 'moderator'); if (role) action('role', id, {role}).catch(e => alert(e.message)); }

    window.reloadAll = reloadAll;
    window.searchUsers = searchUsers;
    window.bonus = bonus;
    window.deduct = deduct;
    window.block = block;
    window.unblock = unblock;
    window.setRole = setRole;

    if (tg && tg.ready) tg.ready();
    if (tg && tg.expand) tg.expand();
    reloadAll();
  </script>
</body>
</html>"""
