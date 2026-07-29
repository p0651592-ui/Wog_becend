const express = require('express');
const cors = require('cors');
const app = express();

app.use(cors());
app.use(express.json());

// Виртуальная база данных в памяти сервера
// Сюда будут записываться все игроки, их балансы и созданные промокоды
let db = {
    users: {},
    promos: {}
};

// Ваш Telegram ID для автоматической выдачи админки на бэкенде
const ADMIN_ID = 6682822292;

// 1. ПОЛУЧЕНИЕ ИЛИ РЕГИСТРАЦИЯ ИГРОКА
app.post('/api/user', (req, res) => {
    const { id, first_name, username } = req.body;
    if (!id) return res.status(400).json({ error: "Missing user ID" });

    // Если игрока еще нет в базе — регистрируем его и даем 5000 монет
    if (!db.users[id]) {
        db.users[id] = {
            id: Number(id),
            name: first_name || "Игрок",
            username: username || "",
            balance: 5000,
            role: Number(id) === ADMIN_ID ? "admin" : "user"
        };
    }
    res.json(db.users[id]);
});

// 2. ИЗМЕНЕНИЕ БАЛАНСА (Выигрыш / Проигрыш / Админка)
app.post('/api/balance', (req, res) => {
    const { id, amount } = req.body;
    if (!id || isNaN(amount)) return res.status(400).json({ error: "Invalid data" });

    if (db.users[id]) {
        db.users[id].balance += parseInt(amount);
        // Защита от ухода баланса в минус
        if (db.users[id].balance < 0) db.users[id].balance = 0; 
        
        return res.json({ success: true, balance: db.users[id].balance });
    }
    res.status(404).json({ error: "User not found" });
});

// 3. СОЗДАНИЕ ПРОМОКОДА (Доступно только через админку)
app.post('/api/promo/create', (req, res) => {
    const { admin_id, code, reward, uses } = req.body;
    if (Number(admin_id) !== ADMIN_ID) return res.status(403).json({ error: "Access denied" });

    const cleanCode = code.trim().toUpperCase();
    db.promos[cleanCode] = {
        reward: parseInt(reward),
        uses: parseInt(uses)
    };
    res.json({ success: true, promos: db.promos });
});

// 4. АКТИВАЦИЯ ПРОМОКОДА ИГРОКОМ
app.post('/api/promo/activate', (req, res) => {
    const { id, code } = req.body;
    const cleanCode = code.trim().toUpperCase();

    if (!db.users[id]) return res.status(404).json({ error: "User not found" });
    if (!db.promos[cleanCode]) return res.status(440).json({ error: "Promo not found" });
    if (db.promos[cleanCode].uses <= 0) return res.status(400).json({ error: "Promo expired" });

    // Начисляем награду
    db.users[id].balance += db.promos[cleanCode].reward;
    db.promos[cleanCode].uses -= 1; // Минусуем активацию

    res.json({ 
        success: true, 
        balance: db.users[id].balance, 
        message: `Активирован промокод на ${db.promos[cleanCode].reward} монет!` 
    });
});

// 5. ПРОСМОТР ВСЕХ КОДОВ ДЛЯ АДМИНА
app.post('/api/promo/list', (req, res) => {
    const { admin_id } = req.body;
    if (Number(admin_id) !== ADMIN_ID) return res.status(403).json({ error: "Access denied" });
    res.json(db.promos);
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Server running on port ${PORT}`));
