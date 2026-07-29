const express = require('express');
const cors = require('cors');

const app = express();
app.use(cors());
app.use(express.json());

// База данных в оперативной памяти сервера
let db = {
    users: {},
    promos: {}
};

// Ваш подтвержденный Telegram ID
const OWNER_ID = 6682822292;

// ГЛАВНЫЙ ЭНДПОИНТ АВТОРИЗАЦИИ
app.post('/api/user', (req, res) => {
    let { id, first_name, username } = req.body;
    
    // Если фронтенд прислал пустой ID (из-за блокировки ТГ) — принудительно ставим ваш ID
    if (!id || Number(id) === OWNER_ID) {
        id = OWNER_ID;
        first_name = "Основатель (WOG)";
        username = "FounderAdmin";
    }

    const assignedRole = (Number(id) === OWNER_ID) ? "admin" : "user";

    if (!db.users[id]) {
        db.users[id] = {
            id: Number(id),
            name: first_name,
            username: username,
            balance: 5000,
            role: assignedRole
        };
    }

    res.json(db.users[id]);
});

// ИЗМЕНЕНИЕ БАЛАНСА
app.post('/api/balance', (req, res) => {
    const { id, amount } = req.body;
    const searchId = id ? Number(id) : OWNER_ID;

    if (!db.users[searchId]) {
        db.users[searchId] = {
            id: searchId,
            name: searchId === OWNER_ID ? "Основатель (WOG)" : "Игрок",
            username: "",
            balance: 5000,
            role: searchId === OWNER_ID ? "admin" : "user"
        };
    }

    db.users[searchId].balance += parseInt(amount);
    if (db.users[searchId].balance < 0) db.users[searchId].balance = 0;

    res.json({ success: true, balance: db.users[searchId].balance });
});

// СОЗДАНИЕ ПРОМОКОДА
app.post('/api/promo/create', (req, res) => {
    const { admin_id, code, reward, uses } = req.body;
    if (Number(admin_id) !== OWNER_ID) return res.status(403).json({ error: "Access denied" });

    const cleanCode = code.trim().toUpperCase();
    db.promos[cleanCode] = {
        reward: parseInt(reward),
        uses: parseInt(uses),
        claimed_by: []
    };
    res.json({ success: true });
});

// АКТИВАЦИЯ ПРОМОКОДА
app.post('/api/promo/activate', (req, res) => {
    const { id, code } = req.body;
    const searchId = id ? Number(id) : OWNER_ID;
    const cleanCode = code.trim().toUpperCase();

    if (!db.users[searchId]) return res.status(404).json({ error: "User not found" });
    if (!db.promos[cleanCode]) return res.status(440).json({ error: "Promo not found" });
    if (db.promos[cleanCode].uses <= 0) return res.status(400).json({ error: "Promo expired" });
    if (db.promos[cleanCode].claimed_by.includes(searchId)) {
        return res.status(400).json({ error: "Already claimed" });
    }

    db.users[searchId].balance += db.promos[cleanCode].reward;
    db.promos[cleanCode].uses -= 1;
    db.promos[cleanCode].claimed_by.push(searchId);

    res.json({ success: true, balance: db.users[searchId].balance, message: `Активирован код на +${db.promos[cleanCode].reward} монет!` });
});

// СПИСОК КОДОВ
app.post('/api/promo/list', (req, res) => {
    res.json(db.promos);
});

app.get('/', (req, res) => {
    res.send("WOG Server Online");
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => console.log(`Server started`));
